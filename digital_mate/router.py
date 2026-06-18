"""Intent router for classifying user messages into pillars and actions.

Uses the LLM to classify user intent and route to the appropriate pillar handler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from digital_mate.llm.client import LLMClient, LLMError
from digital_mate.llm.prompts import build_router_messages

logger = logging.getLogger(__name__)

# Valid pillar names
VALID_PILLARS = {"content", "strategy", "research", "analytics", "general"}

# Valid actions per pillar
VALID_ACTIONS: dict[str, set[str]] = {
    "content": {"caption", "hooks", "hashtags", "cta", "rewrite", "ideas", "calendar", "other"},
    "strategy": {"plan", "funnel", "budget", "timeline", "launch", "audit", "other"},
    "research": {"trends", "competitors", "audience", "keywords", "benchmarks", "other"},
    "analytics": {"report", "kpis", "interpret", "roi", "improve", "other"},
    "general": {"chitchat", "help", "brand", "unclear"},
}


@dataclass
class RouterResult:
    """Result of intent classification.

    Attributes:
        pillar: The identified pillar (content/strategy/research/analytics/general).
        action: The specific action within the pillar.
        confidence: Classification confidence (0.0 to 1.0).
        language_detected: Detected language of the message.
    """
    pillar: str
    action: str
    confidence: float = 0.8
    language_detected: str = "en"

    @property
    def is_general(self) -> bool:
        """Check if the result is for the general (non-pillar) category.

        Returns:
            True if pillar is 'general'.
        """
        return self.pillar == "general"


class IntentRouter:
    """LLM-based intent classifier that routes messages to pillars.

    Uses a lightweight LLM call with JSON output to classify
    user messages into marketing pillars and specific actions.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        language: str = "bilingual",
        bot_name: str = "Digital Mate",
    ) -> None:
        """Initialize the intent router.

        Args:
            llm_client: LLM client for classification.
            language: Language setting.
            bot_name: Bot display name.
        """
        self.llm_client = llm_client
        self.language = language
        self.bot_name = bot_name

    async def classify(
        self,
        message: str,
        context: list[dict[str, str]] | None = None,
    ) -> RouterResult:
        """Classify a user message into pillar and action.

        Args:
            message: The user's message text.
            context: Optional recent conversation context.

        Returns:
            RouterResult with pillar, action, confidence, and language.
        """
        context = context or []
        messages = build_router_messages(
            user_message=message,
            context=context,
            language=self.language,
            bot_name=self.bot_name,
        )

        try:
            result = await self.llm_client.chat_json(messages)
            return self._parse_result(result)
        except LLMError as exc:
            logger.error("Router LLM error: %s", exc)
            # Fallback: try keyword-based classification
            return self._keyword_fallback(message)
        except Exception as exc:
            logger.error("Unexpected router error: %s", exc)
            return RouterResult(pillar="general", action="unclear", confidence=0.3)

    def _parse_result(self, data: dict[str, Any]) -> RouterResult:
        """Parse and validate the LLM JSON response.

        Args:
            data: Parsed JSON response from LLM.

        Returns:
            Validated RouterResult.
        """
        pillar = str(data.get("pillar", "general")).lower().strip()
        action = str(data.get("action", "other")).lower().strip()
        confidence = float(data.get("confidence", 0.7))
        language = str(data.get("language_detected", "en")).lower().strip()

        # Validate pillar
        if pillar not in VALID_PILLARS:
            logger.warning("Invalid pillar '%s', defaulting to general", pillar)
            pillar = "general"

        # Validate action
        valid_actions = VALID_ACTIONS.get(pillar, VALID_ACTIONS["general"])
        if action not in valid_actions:
            logger.warning("Invalid action '%s' for pillar '%s', defaulting to 'other'", action, pillar)
            action = "other"

        # Clamp confidence
        confidence = max(0.0, min(1.0, confidence))

        # Validate language
        if language not in ("en", "id", "mixed"):
            language = "en"

        return RouterResult(
            pillar=pillar,
            action=action,
            confidence=confidence,
            language_detected=language,
        )

    def _keyword_fallback(self, message: str) -> RouterResult:
        """Fallback classification using keyword matching.

        Used when the LLM router call fails.

        Args:
            message: User message text.

        Returns:
            RouterResult based on keyword matching.
        """
        msg_lower = message.lower()

        # Greetings and chitchat
        greetings = {"hi", "hello", "hey", "thanks", "thank you", "bye", "good morning",
                     "halo", "hai", "selamat", "terima kasih", "makasih"}
        if any(g in msg_lower for g in greetings):
            return RouterResult(pillar="general", action="chitchat", confidence=0.6)

        # Help
        help_words = {"help", "what can you", "how do you", "bantuan", "apa yang bisa"}
        if any(h in msg_lower for h in help_words):
            return RouterResult(pillar="general", action="help", confidence=0.6)

        # Content keywords
        content_words = {"caption", "post", "copy", "hashtag", "hook", "rewrite", "content idea",
                         "konten", "caption", "tulisan"}
        if any(c in msg_lower for c in content_words):
            return RouterResult(pillar="content", action="other", confidence=0.5)

        # Strategy keywords
        strategy_words = {"plan", "strategy", "funnel", "budget", "launch", "campaign",
                          "rencana", "strategi", "anggaran", "kampanye"}
        if any(s in msg_lower for s in strategy_words):
            return RouterResult(pillar="strategy", action="other", confidence=0.5)

        # Research keywords
        research_words = {"trend", "research", "competitor", "analysis", "market", "keyword",
                          "tren", "riset", "kompetitor", "analisis", "pasar"}
        if any(r in msg_lower for r in research_words):
            return RouterResult(pillar="research", action="other", confidence=0.5)

        # Analytics keywords
        analytics_words = {"report", "analytics", "metrics", "kpi", "roi", "data", "performance",
                           "laporan", "analitik", "metrik", "kinerja"}
        if any(a in msg_lower for a in analytics_words):
            return RouterResult(pillar="analytics", action="other", confidence=0.5)

        return RouterResult(pillar="general", action="unclear", confidence=0.3)
