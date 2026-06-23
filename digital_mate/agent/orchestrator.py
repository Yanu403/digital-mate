"""Orchestrator for coordinating multi-step workflow execution.

Sits between the intent router and pillar dispatch. Decides whether a
message needs a multi-step workflow or a single pillar response.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from digital_mate.agent.workflow import WorkflowEngine
from digital_mate.pillars.base import BasePillar
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)


class Orchestrator:
    """Coordinates between the router and pillar dispatch.

    Checks if a classified intent should trigger a multi-step workflow
    (e.g. Research → Content) or fall through to single-pillar execution.

    Args:
        pillars: Mapping of pillar name to BasePillar instance.
    """

    def __init__(self, pillars: dict[str, BasePillar]) -> None:
        self.pillars = pillars
        self.workflow_engine = WorkflowEngine(pillars)

    async def execute(
        self,
        user_message: str,
        pillar: str,
        action: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, bool]:
        """Execute a request — either as a multi-step workflow or single pillar.

        If a workflow is detected, orchestrates the full chain and returns
        the combined result. Otherwise returns empty string to signal that
        normal single-pillar dispatch should handle the request.

        Args:
            user_message: Original user message text.
            pillar: Router-classified pillar name.
            action: Router-classified action name.
            context: Recent conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional async callback for progress updates
                (e.g. editing a Telegram placeholder message).

        Returns:
            Tuple of (response_text, was_workflow).
            If was_workflow is False, caller should use normal dispatch.
        """
        workflow = self.workflow_engine.detect_workflow(user_message, pillar, action)

        if workflow is None:
            return "", False

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
            # Fall through to single-pillar dispatch on failure
            return "", False
