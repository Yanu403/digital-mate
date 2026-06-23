"""Refiner that improves output based on critique feedback.

Takes the original request, a draft response, and specific critique
suggestions, then regenerates an improved version.
"""

from __future__ import annotations

import logging

from digital_mate.llm.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

REFINER_SYSTEM_PROMPT = """You are a marketing content refiner. You receive:
1. The original user request
2. A draft response that needs improvement
3. Specific critique feedback with suggestions

Rewrite the response addressing ALL critique points. Keep the same format and structure, but improve quality.
Output ONLY the refined text — no explanations, no meta-commentary."""


class Refiner:
    """Refines pillar output based on critique feedback.

    Takes a draft response and critic suggestions, then regenerates
    an improved version addressing all identified issues.

    Args:
        llm_client: LLM client for generating refined output.
    """

    MAX_ITERATIONS = 2  # Max refinement rounds

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def refine(
        self,
        pillar: str,
        user_message: str,
        draft: str,
        suggestions: str,
    ) -> str:
        """Refine output based on critique feedback.

        Args:
            pillar: Pillar name (for logging context).
            user_message: The original user request.
            draft: The draft response to improve.
            suggestions: Specific improvement suggestions from the critic.

        Returns:
            Refined output text. Returns the original draft on LLM failure.
        """
        user_content = (
            f"## Original User Request\n{user_message}\n\n"
            f"## Draft Response\n{draft}\n\n"
            f"## Critique Feedback & Suggestions\n{suggestions}"
        )

        messages = [
            {"role": "system", "content": REFINER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        try:
            refined = await self.llm_client.chat(messages, temperature=0.7, max_tokens=2048)
            if refined and refined.strip():
                return refined.strip()
            logger.warning("Refiner returned empty response for %s pillar", pillar)
            return draft
        except (LLMError, Exception) as exc:
            logger.warning("Refinement failed for %s pillar: %s", pillar, exc)
            return draft
