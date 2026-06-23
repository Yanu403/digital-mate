"""Orchestrator for coordinating multi-step workflow and plan execution.

Sits between the intent router and pillar dispatch. Decides whether a
message needs a multi-step workflow (Phase 1), a decomposed plan (Phase 2),
or a single pillar response.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from digital_mate.agent.planner import Planner
from digital_mate.agent.plan_store import PlanStore
from digital_mate.agent.executor import PlanExecutor
from digital_mate.agent.workflow import WorkflowEngine
from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)

# Keywords that suggest a complex, multi-step request
_COMPLEX_KEYWORDS = frozenset({
    "launching", "launch", "bantu", "help me with", "help me",
    "buat semua", "buatkan semua", "lengkap", "full campaign",
    "from scratch", "mulai dari nol", "kampanye lengkap",
    "end-to-end", "comprehensive", "all-in-one",
    "setup everything", "siapkan semua", "full marketing",
})


def _is_complex_request(message: str, confidence: float) -> bool:
    """Check if a message is complex enough to warrant planning.

    Heuristics:
    - Message length > 100 chars
    - OR contains goal-like keywords
    - OR router confidence < 0.7

    Args:
        message: User message text.
        confidence: Router classification confidence.

    Returns:
        True if the message should be decomposed into a plan.
    """
    if len(message) > 100:
        return True

    msg_lower = message.lower()
    if any(kw in msg_lower for kw in _COMPLEX_KEYWORDS):
        return True

    if confidence < 0.7:
        return True

    return False


class Orchestrator:
    """Coordinates between the router and pillar dispatch.

    Checks if a classified intent should trigger a multi-step workflow,
    a decomposed plan, or fall through to single-pillar execution.

    Args:
        pillars: Mapping of pillar name to BasePillar instance.
        planner: Optional Planner for goal decomposition.
        plan_store: Optional PlanStore for plan persistence.
    """

    def __init__(
        self,
        pillars: dict[str, BasePillar],
        planner: Planner | None = None,
        plan_store: PlanStore | None = None,
    ) -> None:
        self.pillars = pillars
        self.workflow_engine = WorkflowEngine(pillars)
        self.planner = planner
        self.plan_store = plan_store
        self._executor: PlanExecutor | None = None
        if plan_store is not None:
            self._executor = PlanExecutor(pillars, plan_store)

    async def execute(
        self,
        user_message: str,
        pillar: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        confidence: float = 0.8,
        chat_id: int | None = None,
    ) -> tuple[str, bool]:
        """Execute a request — workflow, plan, or single pillar.

        Flow:
        1. Try workflow detection (Phase 1)
        2. If no workflow: check if complex enough for planning
        3. If complex → create plan via LLM, execute via executor
        4. If not complex or planner fails → return ("", False)

        Args:
            user_message: Original user message text.
            pillar: Router-classified pillar name.
            action: Router-classified action name.
            context: Recent conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional async callback for progress updates.
            confidence: Router classification confidence.
            chat_id: Optional chat ID for plan persistence.

        Returns:
            Tuple of (response_text, was_handled).
            If was_handled is False, caller should use normal dispatch.
        """
        # Phase 1: Try workflow detection
        workflow = self.workflow_engine.detect_workflow(user_message, pillar, action)

        if workflow is not None:
            logger.info("Orchestrator: workflow '%s' detected", workflow.name)
            try:
                result = await self.workflow_engine.execute(
                    workflow=workflow,
                    user_message=user_message,
                    context=context,
                    brand_profile=brand_profile,
                    key_facts=key_facts,
                    on_progress=on_progress,
                )
                return result.text, True
            except Exception as exc:
                logger.error("Orchestrator workflow '%s' failed: %s", workflow.name, exc)
                # Fall through to planning or single-pillar

        # Phase 2: Try planning for complex requests
        if (
            self.planner is not None
            and self.plan_store is not None
            and self._executor is not None
            and chat_id is not None
            and pillar != "general"
            and _is_complex_request(user_message, confidence)
        ):
            # Check for existing active plan
            existing = await self.plan_store.get_active_plan(chat_id)
            if existing is not None:
                logger.info("Chat %d already has active plan %s", chat_id, existing["plan_id"])
                # Don't create a new plan, fall through to single pillar
            else:
                try:
                    return await self._execute_plan(
                        user_message=user_message,
                        chat_id=chat_id,
                        context=context,
                        brand_profile=brand_profile,
                        key_facts=key_facts,
                        on_progress=on_progress,
                    )
                except Exception as exc:
                    logger.error("Orchestrator planning failed: %s", exc)
                    # Fall through to single-pillar dispatch

        return "", False

    async def _execute_plan(
        self,
        user_message: str,
        chat_id: int,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, bool]:
        """Create and execute a plan for a complex request.

        Args:
            user_message: Original user message.
            chat_id: Telegram chat ID.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional progress callback.

        Returns:
            Tuple of (response_text, was_handled).
        """
        # Build brand context for the planner
        brand_ctx = ""
        if brand_profile:
            from digital_mate.llm.prompts import build_brand_context
            brand_ctx = build_brand_context(
                name=brand_profile.name,
                industry=brand_profile.industry,
                audience=brand_profile.audience,
                tone=brand_profile.tone,
                products=brand_profile.products,
                hashtags=brand_profile.hashtags,
                competitors=brand_profile.competitors,
                platform_preference=brand_profile.platform_preference,
                budget_range=brand_profile.budget_range,
                business_stage=brand_profile.business_stage,
            )

        # Ask planner to decompose the goal
        steps = await self.planner.create_plan(
            user_goal=user_message,
            brand_context=brand_ctx,
            key_facts=key_facts,
        )

        if not steps:
            logger.info("Planner returned no steps, falling through")
            return "", False

        # Create plan in DB
        plan_id = await self.plan_store.create_plan(chat_id, user_message, steps)
        logger.info("Created plan %s with %d steps for chat %d", plan_id, len(steps), chat_id)

        # Execute the plan
        try:
            result_text = await self._executor.execute(
                plan_id=plan_id,
                steps=steps,
                user_message=user_message,
                context=context,
                brand_profile=brand_profile,
                key_facts=key_facts,
                on_progress=on_progress,
            )
            return result_text, True
        except Exception as exc:
            logger.error("Plan execution failed: %s", exc)
            await self.plan_store.fail_plan(plan_id, str(exc))
            return "", False
