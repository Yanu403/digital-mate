"""Workflow definitions and execution engine for multi-step pillar chaining.

Defines workflow steps, built-in workflows, and the engine that executes
them sequentially, passing data between steps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from digital_mate.pillars.base import BasePillar, PillarResult
from digital_mate.memory.brand_profile import BrandProfile

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStep:
    """A single step in a workflow.

    Attributes:
        pillar: Target pillar name (research, content, strategy, analytics).
        action: Action to execute within the pillar.
        input_transform: How to build input from previous results.
            - "user_message": use the original user message
            - "previous_text": use text from the previous step's PillarResult
            - "previous_metadata": extract a specific key from previous metadata
        input_key: Key in metadata to extract (used with input_transform="previous_metadata").
        description: Human-readable description shown as progress indicator.
    """

    pillar: str
    action: str
    input_transform: str = "user_message"
    input_key: str = ""
    description: str = ""


@dataclass
class Workflow:
    """A named sequence of workflow steps.

    Attributes:
        name: Unique workflow identifier.
        trigger_keywords: Keywords in user messages that suggest this workflow.
        steps: Ordered list of WorkflowStep to execute.
        description: Human-readable workflow description.
    """

    name: str
    trigger_keywords: list[str]
    steps: list[WorkflowStep]
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in workflows
# ---------------------------------------------------------------------------

WORKFLOWS: dict[str, Workflow] = {
    "research_to_content": Workflow(
        name="research_to_content",
        trigger_keywords=[
            "based on trends",
            "berdasarkan tren",
            "trending content",
            "konten trending",
            "research then write",
            "riset lalu buat",
            "tren lalu buat",
        ],
        steps=[
            WorkflowStep(
                pillar="research",
                action="trends",
                input_transform="user_message",
                description="🔍 Searching trends...",
            ),
            WorkflowStep(
                pillar="content",
                action="caption",
                input_transform="previous_text",
                description="✍️ Writing caption based on trends...",
            ),
        ],
        description="Research current trends, then create content based on findings",
    ),
    "research_to_strategy": Workflow(
        name="research_to_strategy",
        trigger_keywords=[
            "competitor analysis",
            "analisis kompetitor",
            "research strategy",
            "riset strategi",
            "market research plan",
            "rencana riset pasar",
        ],
        steps=[
            WorkflowStep(
                pillar="research",
                action="competitors",
                input_transform="user_message",
                description="🔍 Analyzing competitors...",
            ),
            WorkflowStep(
                pillar="strategy",
                action="plan",
                input_transform="previous_text",
                description="📋 Creating strategy based on findings...",
            ),
        ],
        description="Analyze competitors, then create a strategy addressing gaps",
    ),
    "analytics_to_strategy": Workflow(
        name="analytics_to_strategy",
        trigger_keywords=[
            "improve performance",
            "tingkatkan performa",
            "optimize campaign",
            "optimasi kampanye",
            "data driven strategy",
            "strategi berbasis data",
            "analytics strategy",
        ],
        steps=[
            WorkflowStep(
                pillar="analytics",
                action="report",
                input_transform="user_message",
                description="📊 Analyzing performance data...",
            ),
            WorkflowStep(
                pillar="strategy",
                action="plan",
                input_transform="previous_text",
                description="📋 Creating improvement strategy...",
            ),
        ],
        description="Analyze performance metrics, then create improvement strategy",
    ),
    "strategy_to_content": Workflow(
        name="strategy_to_content",
        trigger_keywords=[
            "content from strategy",
            "konten dari strategi",
            "plan and write",
            "rencana dan tulis",
            "strategy content calendar",
            "kalender konten strategi",
        ],
        steps=[
            WorkflowStep(
                pillar="strategy",
                action="plan",
                input_transform="user_message",
                description="📋 Creating marketing plan...",
            ),
            WorkflowStep(
                pillar="content",
                action="calendar",
                input_transform="previous_text",
                description="📅 Generating content calendar from plan...",
            ),
        ],
        description="Create a marketing plan, then generate a content calendar from it",
    ),
}


# ---------------------------------------------------------------------------
# Content-hint keywords for heuristic workflow detection
# ---------------------------------------------------------------------------

_CONTENT_HINTS = frozenset({
    "caption", "content", "konten", "post", "buat", "write", "draft",
    "tulis", "kalender", "calendar", "instagram", "tiktok", "ig",
})

_STRATEGY_HINTS = frozenset({
    "strategy", "strategi", "plan", "rencana", "improve", "tingkatkan",
    "optimize", "optimasi", "recommendation", "rekomendasi",
})


class WorkflowEngine:
    """Executes workflow definitions by chaining pillar handlers.

    Args:
        pillars: Mapping of pillar name to BasePillar instance.
    """

    def __init__(self, pillars: dict[str, BasePillar]) -> None:
        self.pillars = pillars

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect_workflow(
        self,
        message: str,
        pillar: str,
        action: str,
    ) -> Workflow | None:
        """Check if a user message should trigger a multi-step workflow.

        Detection uses two strategies:
        1. Keyword matching against workflow trigger_keywords.
        2. Heuristic: pillar+action combination combined with content/strategy
           hints elsewhere in the message.

        Args:
            message: Original user message.
            pillar: Router-classified pillar.
            action: Router-classified action.

        Returns:
            Matching Workflow, or None if single-pillar dispatch is sufficient.
        """
        msg_lower = message.lower()

        # Strategy 1: explicit keyword triggers
        for workflow in WORKFLOWS.values():
            if any(kw in msg_lower for kw in workflow.trigger_keywords):
                return workflow

        # Strategy 2: heuristic — research + content hints → research_to_content
        if pillar == "research" and action in ("trends", "keywords"):
            if any(h in msg_lower for h in _CONTENT_HINTS):
                return WORKFLOWS["research_to_content"]

        # Strategy 2b: research + competitors + strategy hints → research_to_strategy
        if pillar == "research" and action in ("competitors", "audience"):
            if any(h in msg_lower for h in _STRATEGY_HINTS):
                return WORKFLOWS["research_to_strategy"]

        # Strategy 2c: analytics + strategy hints → analytics_to_strategy
        if pillar == "analytics" and action in ("report", "improve", "interpret"):
            if any(h in msg_lower for h in _STRATEGY_HINTS):
                return WORKFLOWS["analytics_to_strategy"]

        # Strategy 2d: strategy + content hints → strategy_to_content
        if pillar == "strategy" and action in ("plan", "launch"):
            if any(h in msg_lower for h in _CONTENT_HINTS):
                return WORKFLOWS["strategy_to_content"]

        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        workflow: Workflow,
        user_message: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> PillarResult:
        """Execute a workflow, running each step sequentially.

        Data flows between steps via WorkflowStep.input_transform.

        Args:
            workflow: The Workflow to execute.
            user_message: Original user message.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional async callback for progress updates.

        Returns:
            Combined PillarResult from all steps.
        """
        results: list[PillarResult] = []

        for i, step in enumerate(workflow.steps):
            # Report progress
            if on_progress and step.description:
                try:
                    await on_progress(step.description)
                except Exception:
                    pass  # Progress is best-effort

            # Build input for this step
            step_input = self._build_step_input(step, user_message, results)

            # Get pillar handler
            pillar_handler = self.pillars.get(step.pillar)
            if pillar_handler is None:
                logger.warning(
                    "Workflow '%s' step %d: pillar '%s' not available, skipping",
                    workflow.name, i, step.pillar,
                )
                continue

            # Execute step
            logger.info(
                "Workflow '%s' step %d/%d: %s.%s",
                workflow.name, i + 1, len(workflow.steps), step.pillar, step.action,
            )
            try:
                result = await pillar_handler.handle_structured(
                    user_message=step_input,
                    action=step.action,
                    context=context,
                    brand_profile=brand_profile,
                    key_facts=key_facts,
                )
                results.append(result)
            except Exception as exc:
                logger.error(
                    "Workflow '%s' step %d failed: %s",
                    workflow.name, i + 1, exc,
                )
                # Continue with remaining steps if possible
                results.append(PillarResult(
                    text=f"⚠️ Step {i + 1} ({step.pillar}) encountered an error: {exc}",
                ))

        return self._combine_results(workflow, results)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_step_input(
        self,
        step: WorkflowStep,
        user_message: str,
        previous_results: list[PillarResult],
    ) -> str:
        """Build the input message for a workflow step.

        Args:
            step: The current WorkflowStep.
            user_message: Original user message.
            previous_results: Results from prior steps.

        Returns:
            Input string for the pillar handler.
        """
        if step.input_transform == "user_message":
            return user_message

        if step.input_transform == "previous_text" and previous_results:
            prev = previous_results[-1]
            # Combine: original request + previous step output as context
            return (
                f"Based on the following research/analysis, "
                f"{user_message}\n\n"
                f"---\nContext from previous step:\n{prev.text}"
            )

        if step.input_transform == "previous_metadata" and previous_results:
            prev = previous_results[-1]
            if step.input_key and step.input_key in prev.metadata:
                return str(prev.metadata[step.input_key])
            # Fallback to previous text if key not found
            return prev.text

        return user_message

    @staticmethod
    def _combine_results(
        workflow: Workflow,
        results: list[PillarResult],
    ) -> PillarResult:
        """Combine results from all workflow steps into a single result.

        Args:
            workflow: The executed workflow.
            results: Results from each step.

        Returns:
            Combined PillarResult with all texts and merged metadata.
        """
        if not results:
            return PillarResult(text="⚠️ Workflow produced no results.")

        if len(results) == 1:
            return results[0]

        # Build combined text with section headers
        sections: list[str] = []
        for i, (step, result) in enumerate(zip(workflow.steps, results)):
            if step.description:
                # Use description as section header (strip emoji for cleaner look)
                header = step.description
                sections.append(f"**{header}**\n\n{result.text}")
            else:
                sections.append(result.text)

        combined_text = "\n\n---\n\n".join(sections)

        # Merge metadata and sources
        combined_metadata: dict[str, Any] = {"workflow": workflow.name, "step_count": len(results)}
        all_sources: list[str] = []
        for result in results:
            combined_metadata.update(result.metadata)
            all_sources.extend(result.sources)

        return PillarResult(
            text=combined_text,
            metadata=combined_metadata,
            sources=all_sources,
        )
