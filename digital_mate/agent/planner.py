"""LLM-powered goal decomposition planner.

Takes a high-level marketing goal and breaks it into 2-7 concrete,
actionable steps using the LLM, validated against the router's
pillar and action definitions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.router import VALID_PILLARS, VALID_ACTIONS

logger = logging.getLogger(__name__)

# System prompt for the planner LLM
PLANNER_SYSTEM_PROMPT = """You are a marketing plan decomposer. Given a user's high-level marketing goal, break it into 2-7 concrete, actionable steps.

Each step must specify:
- pillar: one of "research", "content", "strategy", "analytics"
- action: specific action (e.g., "trends", "caption", "plan", "report")
- description: what this step accomplishes (short, 5-10 words)
- input_from: "user_request" for the first step, or "step_N" to reference a previous step's output (e.g., "step_1", "step_2")

Output ONLY a JSON array, no other text. Example:
[
  {"pillar": "research", "action": "trends", "description": "Research current market trends", "input_from": "user_request"},
  {"pillar": "research", "action": "competitors", "description": "Analyze top 3 competitors", "input_from": "user_request"},
  {"pillar": "strategy", "action": "plan", "description": "Create positioning strategy", "input_from": "step_1"},
  {"pillar": "content", "action": "caption", "description": "Draft social media captions", "input_from": "step_3"}
]"""

# Valid non-general pillars for planning
_PLANNABLE_PILLARS = {"research", "content", "strategy", "analytics"}


class Planner:
    """LLM-powered goal decomposition planner.

    Args:
        llm_client: LLM client for generating the plan.
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm_client = llm_client

    async def create_plan(
        self,
        user_goal: str,
        brand_context: str = "",
        key_facts: str = "",
    ) -> list[dict]:
        """Decompose a user goal into ordered steps.

        Args:
            user_goal: The user's high-level marketing goal.
            brand_context: Optional brand profile context.
            key_facts: Optional key facts for personalization.

        Returns:
            List of step dicts with pillar, action, description, input_from.
            Returns empty list if planning fails.
        """
        # Build user message with optional context
        parts = [user_goal]
        if brand_context:
            parts.append(f"\nBrand context:\n{brand_context}")
        if key_facts:
            parts.append(f"\nKey facts:\n{key_facts}")
        user_message = "\n".join(parts)

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        # Try twice: first attempt, then retry on validation failure
        for attempt in range(2):
            try:
                raw = await self.llm_client.chat_json(messages)
                steps = self._parse_steps(raw)
                if steps:
                    logger.info(
                        "Planner created %d steps (attempt %d)",
                        len(steps), attempt + 1,
                    )
                    return steps
                logger.warning("Planner validation failed on attempt %d", attempt + 1)
            except (LLMError, json.JSONDecodeError) as exc:
                logger.error("Planner LLM error on attempt %d: %s", attempt + 1, exc)
            except Exception as exc:
                logger.error("Unexpected planner error on attempt %d: %s", attempt + 1, exc)

        logger.warning("Planner failed after 2 attempts, returning empty list")
        return []

    def _parse_steps(self, data: Any) -> list[dict]:
        """Parse and validate the LLM JSON response into step dicts.

        Args:
            data: Parsed JSON from LLM (should be a list).

        Returns:
            Validated list of step dicts, or empty list on failure.
        """
        if not isinstance(data, list):
            # If chat_json wrapped it in an object, try to extract
            if isinstance(data, dict):
                # Try common keys
                for key in ("steps", "plan", "items"):
                    if key in data and isinstance(data[key], list):
                        data = data[key]
                        break
                else:
                    return []
            else:
                return []

        if len(data) < 2 or len(data) > 7:
            logger.warning("Planner returned %d steps (need 2-7)", len(data))
            # Still accept if reasonable
            if len(data) == 0:
                return []

        validated: list[dict] = []
        for i, step in enumerate(data):
            if not isinstance(step, dict):
                return []

            pillar = str(step.get("pillar", "")).lower().strip()
            action = str(step.get("action", "")).lower().strip()
            description = str(step.get("description", "")).strip()
            input_from = str(step.get("input_from", "user_request")).strip()

            # Validate pillar (must be a plannable pillar, not general)
            if pillar not in _PLANNABLE_PILLARS:
                logger.warning("Invalid planner pillar '%s' at step %d", pillar, i + 1)
                return []

            # Validate action against VALID_ACTIONS
            valid_actions = VALID_ACTIONS.get(pillar, set())
            if action not in valid_actions:
                logger.warning("Invalid planner action '%s' for pillar '%s' at step %d", action, pillar, i + 1)
                return []

            # Validate input_from format
            if input_from != "user_request":
                # Must be "step_N" format
                if not input_from.startswith("step_"):
                    input_from = "user_request"
                else:
                    try:
                        ref_step = int(input_from.split("_")[1])
                        if ref_step < 1 or ref_step >= i + 1:
                            # Can't reference a future step or step 0
                            input_from = "user_request"
                    except (ValueError, IndexError):
                        input_from = "user_request"

            if not description:
                description = f"Step {i + 1}: {pillar}.{action}"

            validated.append({
                "pillar": pillar,
                "action": action,
                "description": description,
                "input_from": input_from,
            })

        return validated
