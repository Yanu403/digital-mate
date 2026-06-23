"""Plan executor — runs plan steps sequentially with progress reporting.

Executes each step in a plan by dispatching to the appropriate pillar
handler, updating the plan store with progress, and combining results.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from digital_mate.agent.plan_store import PlanStore
from digital_mate.memory.brand_profile import BrandProfile
from digital_mate.pillars.base import BasePillar, PillarResult

logger = logging.getLogger(__name__)


class PlanExecutor:
    """Executes plan steps sequentially with progress reporting.

    Args:
        pillars: Mapping of pillar name to BasePillar instance.
        plan_store: PlanStore for tracking execution progress.
    """

    def __init__(
        self,
        pillars: dict[str, BasePillar],
        plan_store: PlanStore,
    ) -> None:
        self.pillars = pillars
        self.plan_store = plan_store

    async def execute(
        self,
        plan_id: str,
        steps: list[dict],
        user_message: str,
        context: list[dict[str, str]],
        brand_profile: BrandProfile | None = None,
        key_facts: str = "",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Execute all plan steps, update progress, return combined result.

        Progress messages format:
            🚀 Plan: "{goal}"
            ✅ 1/N: description [done]
            ⏳ 2/N: description [running...]
            ⬜ 3/N: description

        On failure: mark step as failed, continue with remaining steps.
        After all steps: mark plan as completed, return combined summary.

        Args:
            plan_id: The plan UUID.
            steps: List of step dicts (pillar, action, description, input_from).
            user_message: Original user message.
            context: Conversation context.
            brand_profile: Optional brand profile.
            key_facts: Key facts for personalization.
            on_progress: Optional async callback for progress updates.

        Returns:
            Combined result text from all steps.
        """
        total = len(steps)
        results: list[str] = []
        step_outputs: dict[int, str] = {}  # step_order (1-based) -> output text

        # Get plan goal from DB for progress display
        goal_text = user_message[:80]
        cursor = await self.plan_store.db.execute(
            "SELECT goal FROM plans WHERE plan_id = ?", (plan_id,)
        )
        row = await cursor.fetchone()
        if row:
            goal_text = row[0]

        # Send initial progress
        if on_progress:
            await on_progress(self._format_progress_init(goal_text, total))

        for i, step in enumerate(steps):
            step_order = i + 1
            pillar_name = step["pillar"]
            action = step["action"]
            description = step.get("description", f"Step {step_order}")
            input_from = step.get("input_from", "user_request")

            # Update progress: mark this step as running
            if on_progress:
                await on_progress(
                    self._format_progress_step(steps, step_outputs, i, total, goal_text)
                )

            # Mark step as running in DB
            await self.plan_store.update_step_status(plan_id, step_order, "running")

            # Determine input for this step
            step_input = self._resolve_input(
                input_from, user_message, step_outputs
            )

            # Get pillar handler
            pillar = self.pillars.get(pillar_name)
            if pillar is None:
                logger.warning("Plan step %d: pillar '%s' not available", step_order, pillar_name)
                error_msg = f"Pillar '{pillar_name}' not available"
                await self.plan_store.update_step_status(
                    plan_id, step_order, "failed", error_message=error_msg
                )
                results.append(f"⚠️ Step {step_order} ({description}): {error_msg}")
                continue

            # Execute the step
            logger.info("Plan %s step %d/%d: %s.%s", plan_id, step_order, total, pillar_name, action)
            try:
                result = await pillar.handle_structured(
                    user_message=step_input,
                    action=action,
                    context=context,
                    brand_profile=brand_profile,
                    key_facts=key_facts,
                )
                result_text = result.text
                step_outputs[step_order] = result_text
                results.append(result_text)

                # Mark step as completed
                await self.plan_store.update_step_status(
                    plan_id, step_order, "completed", result_text=result_text
                )
            except Exception as exc:
                logger.error("Plan %s step %d failed: %s", plan_id, step_order, exc)
                error_msg = str(exc)
                await self.plan_store.update_step_status(
                    plan_id, step_order, "failed", error_message=error_msg
                )
                results.append(f"⚠️ Step {step_order} ({description}) encountered an error: {exc}")

        # Mark plan as completed
        await self.plan_store.complete_plan(plan_id)

        # Send final progress
        if on_progress:
            await on_progress(self._format_progress_done(steps, step_outputs, total, goal_text))

        # Combine results
        return self._combine_results(steps, results, goal_text)

    @staticmethod
    def _resolve_input(
        input_from: str,
        user_message: str,
        step_outputs: dict[int, str],
    ) -> str:
        """Resolve the input text for a step based on input_from.

        Args:
            input_from: "user_request" or "step_N".
            user_message: Original user message.
            step_outputs: Map of step_order -> output text from completed steps.

        Returns:
            Resolved input text.
        """
        if input_from == "user_request":
            return user_message

        # Parse step_N reference
        if input_from.startswith("step_"):
            try:
                ref = int(input_from.split("_")[1])
                if ref in step_outputs:
                    # Combine original request with referenced step output
                    return (
                        f"Based on the following analysis, {user_message}\n\n"
                        f"---\nContext from step {ref}:\n{step_outputs[ref]}"
                    )
            except (ValueError, IndexError):
                pass

        # Fallback to user message
        return user_message

    @staticmethod
    def _format_progress_init(goal: str, total: int) -> str:
        """Format initial progress message.

        Args:
            goal: Plan goal text.
            total: Total number of steps.

        Returns:
            Formatted progress text.
        """
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal
        lines = [f'🚀 Plan: "{goal_short}"', ""]
        for i in range(1, total + 1):
            lines.append(f"⬜ {i}/{total}: ...")
        return "\n".join(lines)

    @staticmethod
    def _format_progress_step(
        steps: list[dict],
        step_outputs: dict[int, str],
        current: int,
        total: int,
        goal: str,
    ) -> str:
        """Format progress message showing current step as running.

        Args:
            steps: All step dicts.
            step_outputs: Completed step outputs.
            current: Current step index (0-based).
            total: Total steps.
            goal: Plan goal.

        Returns:
            Formatted progress text.
        """
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal
        lines = [f'🚀 Plan: "{goal_short}"', ""]
        for i in range(total):
            desc = steps[i].get("description", f"Step {i + 1}")
            desc_short = desc[:40] + "..." if len(desc) > 40 else desc
            if i < current:
                lines.append(f"✅ {i + 1}/{total}: {desc_short} [done]")
            elif i == current:
                lines.append(f"⏳ {i + 1}/{total}: {desc_short} [running...]")
            else:
                lines.append(f"⬜ {i + 1}/{total}: {desc_short}")
        return "\n".join(lines)

    @staticmethod
    def _format_progress_done(
        steps: list[dict],
        step_outputs: dict[int, str],
        total: int,
        goal: str,
    ) -> str:
        """Format final progress message (all steps done).

        Args:
            steps: All step dicts.
            step_outputs: All step outputs.
            total: Total steps.
            goal: Plan goal.

        Returns:
            Formatted progress text.
        """
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal
        lines = [f'🚀 Plan: "{goal_short}"', ""]
        for i in range(total):
            desc = steps[i].get("description", f"Step {i + 1}")
            desc_short = desc[:40] + "..." if len(desc) > 40 else desc
            order = i + 1
            if order in step_outputs:
                lines.append(f"✅ {order}/{total}: {desc_short} [done]")
            else:
                lines.append(f"❌ {order}/{total}: {desc_short} [failed]")
        return "\n".join(lines)

    @staticmethod
    def _combine_results(
        steps: list[dict],
        results: list[str],
        goal: str,
    ) -> str:
        """Combine results from all steps into a single response.

        Args:
            steps: Step definitions.
            results: Result text from each step.
            goal: Plan goal text.

        Returns:
            Combined response text.
        """
        if not results:
            return "⚠️ Plan produced no results."

        if len(results) == 1:
            return results[0]

        sections: list[str] = []
        for i, (step, result) in enumerate(zip(steps, results)):
            desc = step.get("description", f"Step {i + 1}")
            sections.append(f"**{desc}**\n\n{result}")

        return "\n\n---\n\n".join(sections)
