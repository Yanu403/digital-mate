"""Reflection engine that ties critic and refiner together.

Implements the generate → evaluate → refine loop for self-improving
pillar output quality. Only applies to pillars that benefit from
iterative refinement (content, strategy) and optionally research.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.agent.critic import Critic
from digital_mate.agent.refiner import Refiner

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """Generate → evaluate → refine loop.

    Runs pillar output through a critic-refiner cycle to improve quality
    before delivering to the user. Skips low-value pillars (analytics,
    general) to avoid unnecessary latency.

    Args:
        critic: Critic instance for evaluating output quality.
        refiner: Refiner instance for improving output based on critique.
    """

    # Pillars that always benefit from self-reflection
    REFLECT_PILLARS: set[str] = {"content", "strategy"}
    # Optional reflection for research (if few sources)
    OPTIONAL_PILLARS: set[str] = {"research"}
    # Skip for analytics and general — low subjective quality value
    SKIP_PILLARS: set[str] = {"analytics", "general"}

    def __init__(self, critic: Critic, refiner: Refiner) -> None:
        self.critic = critic
        self.refiner = refiner

    async def reflect_and_refine(
        self,
        pillar: str,
        user_message: str,
        initial_output: str,
        brand_context: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Run the reflection loop.

        Evaluates the initial output against quality rubrics. If it fails,
        refines and re-evaluates up to MAX_ITERATIONS times.

        Args:
            pillar: Pillar name (content/strategy/research/analytics/general).
            user_message: The original user request.
            initial_output: The initial generated output.
            brand_context: Optional brand context for evaluation.
            metadata: Optional metadata dict (e.g. sources for research).

        Returns:
            Tuple of (final_output, reflection_log).
            reflection_log contains: iterations, initial_score, final_score,
            improved, skipped.
        """
        # Determine if this pillar should be reflected
        if pillar in self.SKIP_PILLARS:
            return initial_output, {"iterations": 0, "skipped": True}

        # For research, only reflect if metadata indicates few sources
        if pillar in self.OPTIONAL_PILLARS:
            if metadata and len(metadata.get("sources", [])) >= 3:
                return initial_output, {"iterations": 0, "skipped": True}

        current_output = initial_output
        log: dict[str, Any] = {
            "iterations": 0,
            "initial_score": 0.0,
            "final_score": 0.0,
            "improved": False,
        }

        max_iter = self.refiner.MAX_ITERATIONS
        for i in range(max_iter):
            evaluation = await self.critic.evaluate(
                pillar, user_message, current_output, brand_context
            )
            log["iterations"] = i + 1

            if i == 0:
                log["initial_score"] = evaluation.get("overall", 0.0)

            if evaluation.get("pass", False):
                log["final_score"] = evaluation.get("overall", 0.0)
                logger.info(
                    "Reflection passed for %s pillar at iteration %d (score=%.1f)",
                    pillar, i + 1, log["final_score"],
                )
                break

            # Refine based on critique
            suggestions = evaluation.get("suggestions", "")
            if not suggestions:
                log["final_score"] = evaluation.get("overall", 0.0)
                break

            refined = await self.refiner.refine(
                pillar, user_message, current_output, suggestions
            )
            if refined != current_output:
                current_output = refined
                log["improved"] = True
                logger.info(
                    "Reflection refined %s pillar (iteration %d)",
                    pillar, i + 1,
                )

            log["final_score"] = evaluation.get("overall", 0.0)

        return current_output, log
