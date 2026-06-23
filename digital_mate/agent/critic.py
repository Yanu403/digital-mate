"""LLM-powered critic that evaluates pillar output quality.

Provides quality rubrics per marketing pillar and a Critic class
that scores outputs against defined criteria using structured LLM evaluation.
"""

from __future__ import annotations

import logging
from typing import Any

from digital_mate.llm.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

# Quality rubrics per pillar
RUBRICS: dict[str, dict[str, Any]] = {
    "content": {
        "criteria": [
            "hook_strength",
            "cta_clarity",
            "brand_voice_match",
            "engagement_potential",
        ],
        "threshold": 7,
        "description": "Evaluate social media content quality",
    },
    "strategy": {
        "criteria": [
            "completeness",
            "feasibility",
            "specificity",
            "actionability",
        ],
        "threshold": 7,
        "description": "Evaluate marketing strategy quality",
    },
    "research": {
        "criteria": [
            "source_quality",
            "relevance",
            "depth",
            "actionability",
        ],
        "threshold": 6,
        "description": "Evaluate research analysis quality",
    },
    "analytics": {
        "criteria": [
            "accuracy",
            "insight_depth",
            "recommendation_quality",
        ],
        "threshold": 6,
        "description": "Evaluate analytics report quality",
    },
}

CRITIC_SYSTEM_PROMPT = """You are a strict marketing content critic. Evaluate the given output on these criteria, scoring each 1-10:
{criteria_list}

Return ONLY a JSON object:
{{"scores": {{"criterion_name": score, ...}}, "overall": float, "pass": bool, "suggestions": "specific improvement suggestions"}}

Pass threshold: {threshold}/10 average. If any score < 5, mark as fail regardless of average.
Be specific in suggestions — quote the weak parts and suggest exact improvements."""


class Critic:
    """LLM-powered output quality evaluator.

    Uses structured rubrics to score pillar outputs and provide
    actionable improvement suggestions.

    Args:
        llm_client: LLM client for generating evaluations.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def evaluate(
        self,
        pillar: str,
        user_message: str,
        output: str,
        brand_context: str = "",
    ) -> dict[str, Any]:
        """Evaluate output quality for a given pillar.

        Args:
            pillar: Pillar name (content/strategy/research/analytics).
            user_message: The original user request.
            output: The generated output to evaluate.
            brand_context: Optional brand context for evaluation.

        Returns:
            Evaluation dict with keys: scores, overall, pass, suggestions.
            Returns a default passing evaluation on LLM failure.
        """
        rubric = RUBRICS.get(pillar)
        if rubric is None:
            # No rubric for this pillar (e.g. general) — auto-pass
            return {
                "scores": {},
                "overall": 10.0,
                "pass": True,
                "suggestions": "",
            }

        criteria_list = "\n".join(
            f"- {c} (1-10)" for c in rubric["criteria"]
        )
        system_prompt = CRITIC_SYSTEM_PROMPT.format(
            criteria_list=criteria_list,
            threshold=rubric["threshold"],
        )

        user_content = (
            f"## User Request\n{user_message}\n\n"
            f"## Output to Evaluate\n{output}"
        )
        if brand_context:
            user_content = f"## Brand Context\n{brand_context}\n\n{user_content}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            result = await self.llm_client.chat_json(messages, temperature=0.3, max_tokens=512)
        except (LLMError, Exception) as exc:
            logger.warning("Critic evaluation failed for %s pillar: %s", pillar, exc)
            # Return a default passing evaluation so we don't block delivery
            return {
                "scores": {},
                "overall": 7.0,
                "pass": True,
                "suggestions": "",
            }

        # Validate and normalize the result
        scores = result.get("scores", {})
        if not isinstance(scores, dict):
            scores = {}

        overall = result.get("overall", 0)
        if not isinstance(overall, (int, float)):
            overall = 0.0
        overall = float(overall)

        passed = result.get("pass", False)
        if not isinstance(passed, bool):
            passed = False

        suggestions = result.get("suggestions", "")
        if not isinstance(suggestions, str):
            suggestions = str(suggestions)

        return {
            "scores": scores,
            "overall": overall,
            "pass": passed,
            "suggestions": suggestions,
        }
