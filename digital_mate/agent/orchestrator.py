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
from digital_mate.agent.workflow import WORKFLOWS, WorkflowEngine
from digital_mate.llm.client import LLMClient, LLMError
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


ROUTE_CLASSIFIER_PROMPT = """You are a routing classifier for a marketing assistant bot. Given a user message and its initial classification, decide the best execution strategy.

Return ONLY a JSON object with these fields:
{
  "strategy": "workflow" | "plan" | "single",
  "workflow_name": "research_to_content" | "research_to_strategy" | "analytics_to_strategy" | "strategy_to_content" | null,
  "reasoning": "brief reason"
}

Strategies:
- "workflow": Message explicitly asks for a multi-step marketing workflow (e.g., "research trends then write caption"). Pick the matching workflow_name.
- "plan": Message is a complex marketing goal that should be decomposed into 2-7 steps (e.g., "launching a new product", "create full marketing campaign").
- "single": Message is a straightforward single-request (e.g., "write a caption", "analyze competitors").

Available workflows:
- research_to_content: Research trends, then create content based on findings
- research_to_strategy: Research/analyze competitors, then create strategy
- analytics_to_strategy: Analyze performance data, then create improvement strategy
- strategy_to_content: Create marketing plan, then generate content calendar
"""


class RoutingClassifier:
    """LLM-based classifier that decides routing strategy for a user message.

    Uses a single lightweight ``chat_json()`` call (max_tokens=100) with
    the router model (cheap/fast) to determine whether the message should
    trigger a workflow, a decomposed plan, or a single-pillar response.

    Args:
        llm_client: LLM client for generating the classification.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def classify(
        self,
        user_message: str,
        pillar: str,
        action: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Classify the routing strategy for a user message.

        Args:
            user_message: Original user message text.
            pillar: Router-classified pillar name.
            action: Router-classified action name.
            confidence: Router classification confidence.

        Returns:
            Dict with keys: strategy ("workflow"|"plan"|"single"),
            workflow_name (str|None), reasoning (str).
            Returns a default single-response dict on LLM failure.
        """
        user_content = (
            f"Message: {user_message}\n"
            f"Initial classification: pillar={pillar}, action={action}, confidence={confidence:.2f}"
        )
        messages = [
            {"role": "system", "content": ROUTE_CLASSIFIER_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            result = await self.llm_client.chat_json(
                messages, temperature=0.1, max_tokens=100,
            )
        except (LLMError, Exception) as exc:
            logger.warning("Routing classifier failed: %s — falling back to heuristic", exc)
            return {"strategy": "single", "workflow_name": None, "reasoning": "classifier_error"}

        # Validate and normalize
        strategy = str(result.get("strategy", "single")).lower().strip()
        if strategy not in ("workflow", "plan", "single"):
            strategy = "single"

        workflow_name = result.get("workflow_name")
        if workflow_name is not None:
            workflow_name = str(workflow_name).strip()
            if workflow_name not in WORKFLOWS:
                workflow_name = None

        reasoning = str(result.get("reasoning", ""))

        return {
            "strategy": strategy,
            "workflow_name": workflow_name,
            "reasoning": reasoning,
        }


class Orchestrator:
    """Coordinates between the router and pillar dispatch.

    Checks if a classified intent should trigger a multi-step workflow,
    a decomposed plan, or fall through to single-pillar execution.

    Uses an LLM-based RoutingClassifier for the primary routing decision,
    with keyword-based heuristics as fallback when the LLM call fails.

    Args:
        pillars: Mapping of pillar name to BasePillar instance.
        planner: Optional Planner for goal decomposition.
        plan_store: Optional PlanStore for plan persistence.
        llm_client: Optional LLM client for the routing classifier.
    """

    def __init__(
        self,
        pillars: dict[str, BasePillar],
        planner: Planner | None = None,
        plan_store: PlanStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.pillars = pillars
        self.workflow_engine = WorkflowEngine(pillars)
        self.planner = planner
        self.plan_store = plan_store
        self.llm_client = llm_client
        self._classifier: RoutingClassifier | None = None
        if llm_client is not None:
            self._classifier = RoutingClassifier(llm_client)
        self._executor: PlanExecutor | None = None
        if plan_store is not None:
            self._executor = PlanExecutor(pillars, plan_store)

    async def resume_plan(
        self,
        plan_id: str,
        user_message: str,
        user_id: int,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str | None:
        """Resume an interrupted plan by executing remaining steps.

        Args:
            plan_id: The plan ID to resume.
            user_message: Original user message (plan goal).
            user_id: Chat/user ID for plan persistence.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional progress callback.

        Returns:
            Result text if plan was executed, None if executor is unavailable.
        """
        if self._executor is None:
            return None
        return await self._executor.execute(
            plan_id=plan_id,
            steps=[],  # executor fetches from store
            user_message=user_message,
            context=context,
            brand_profile=brand_profile,
            key_facts=key_facts,
            on_progress=on_progress,
        )

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
        1. Call LLM routing classifier (or use keyword fallback)
        2. If "workflow" → execute matching workflow
        3. If "plan" → create plan via LLM, execute via executor
        4. If "single" or classifier fails → return ("", False)

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
        # --- Primary: LLM-based routing classification ---
        classification = await self._classify_routing(
            user_message, pillar, action, confidence,
        )

        strategy = classification.get("strategy", "single")
        workflow_name = classification.get("workflow_name")

        # --- Workflow strategy ---
        if strategy == "workflow" and workflow_name:
            workflow = WORKFLOWS.get(workflow_name)
            if workflow is not None:
                logger.info(
                    "Orchestrator: LLM classified as workflow '%s' (%s)",
                    workflow_name, classification.get("reasoning", ""),
                )
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
                    logger.error("Orchestrator workflow '%s' failed: %s", workflow_name, exc)
                    # Fall through to planning or single-pillar

            # LLM said workflow but name invalid or execution failed —
            # fall back to keyword detection
            workflow = self.workflow_engine.detect_workflow(user_message, pillar, action)
            if workflow is not None:
                logger.info("Orchestrator: fallback keyword workflow '%s'", workflow.name)
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
                    logger.error("Orchestrator fallback workflow '%s' failed: %s", workflow.name, exc)

        # --- Plan strategy ---
        if strategy == "plan" or (
            strategy == "workflow" and not workflow_name
        ):
            if (
                self.planner is not None
                and self.plan_store is not None
                and self._executor is not None
                and chat_id is not None
                and pillar != "general"
            ):
                # Check for existing active plan
                existing = await self.plan_store.get_active_plan(chat_id)
                if existing is not None:
                    logger.info("Chat %d already has active plan %s", chat_id, existing["plan_id"])
                else:
                    logger.info(
                        "Orchestrator: LLM classified as plan (%s)",
                        classification.get("reasoning", ""),
                    )
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

        # --- Fallback: keyword-based heuristic ---
        # Used when LLM says "single" or when LLM strategies failed above
        workflow = self.workflow_engine.detect_workflow(user_message, pillar, action)
        if workflow is not None:
            logger.info("Orchestrator: keyword fallback workflow '%s'", workflow.name)
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
                logger.error("Orchestrator keyword workflow '%s' failed: %s", workflow.name, exc)

        # Fallback: keyword-based complex request check for planning
        if (
            self.planner is not None
            and self.plan_store is not None
            and self._executor is not None
            and chat_id is not None
            and pillar != "general"
            and _is_complex_request(user_message, confidence)
        ):
            existing = await self.plan_store.get_active_plan(chat_id)
            if existing is not None:
                logger.info("Chat %d already has active plan %s", chat_id, existing["plan_id"])
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
                    logger.error("Orchestrator keyword planning failed: %s", exc)

        return "", False

    async def _classify_routing(
        self,
        user_message: str,
        pillar: str,
        action: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Run the LLM routing classifier, falling back to heuristic on failure.

        Args:
            user_message: Original user message text.
            pillar: Router-classified pillar name.
            action: Router-classified action name.
            confidence: Router classification confidence.

        Returns:
            Classification dict with strategy, workflow_name, reasoning.
        """
        if self._classifier is not None:
            try:
                return await self._classifier.classify(
                    user_message, pillar, action, confidence,
                )
            except Exception as exc:
                logger.warning("Routing classifier failed: %s", exc)

        # Fallback: heuristic classification
        return self._heuristic_classify(user_message, pillar, action, confidence)

    @staticmethod
    def _heuristic_classify(
        user_message: str,
        pillar: str,
        action: str,
        confidence: float,
    ) -> dict[str, Any]:
        """Heuristic fallback when LLM classifier is unavailable.

        Uses the same keyword-based logic as the legacy detect_workflow
        and _is_complex_request functions.

        Args:
            user_message: Original user message text.
            pillar: Router-classified pillar name.
            action: Router-classified action name.
            confidence: Router classification confidence.

        Returns:
            Classification dict with strategy, workflow_name, reasoning.
        """
        # Check for workflow triggers
        engine = WorkflowEngine(pillars={})
        workflow = engine.detect_workflow(user_message, pillar, action)
        if workflow is not None:
            return {
                "strategy": "workflow",
                "workflow_name": workflow.name,
                "reasoning": "keyword_heuristic",
            }

        # Check for complex request → plan
        if _is_complex_request(user_message, confidence):
            return {
                "strategy": "plan",
                "workflow_name": None,
                "reasoning": "complex_heuristic",
            }

        return {
            "strategy": "single",
            "workflow_name": None,
            "reasoning": "simple_request",
        }

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
