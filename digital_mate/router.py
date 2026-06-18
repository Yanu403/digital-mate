"""Intent router for classifying user messages into pillars and actions.

Uses the LLM to classify user intent and route to the appropriate pillar handler.
Includes TTL caching of classification results and per-user rate limiting
to reduce unnecessary LLM calls and prevent token abuse.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from cachetools import TTLCache

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

# Default result returned when cooldown is active and no cache hit
_COOLDOWN_DEFAULT = None  # Sentinel; built lazily as a RouterResult


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

    Features:
    - TTL cache for classification results to avoid redundant LLM calls.
    - Per-user cooldown to rate-limit rapid successive messages.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        language: str = "bilingual",
        bot_name: str = "Digital Mate",
        cache_ttl: int = 300,
        cache_maxsize: int = 256,
        cooldown_seconds: float = 2.0,
    ) -> None:
        """Initialize the intent router.

        Args:
            llm_client: LLM client for classification.
            language: Language setting.
            bot_name: Bot display name.
            cache_ttl: TTL in seconds for cached classification results.
            cache_maxsize: Maximum number of entries in the cache.
            cooldown_seconds: Minimum interval between LLM calls per user.
        """
        self.llm_client = llm_client
        self.language = language
        self.bot_name = bot_name
        self._cache: TTLCache[str, RouterResult] = TTLCache(maxsize=cache_maxsize, ttl=cache_ttl)
        self._last_call: dict[int, float] = {}
        self._cooldown_seconds = cooldown_seconds

    async def classify(
        self,
        message: str,
        context: list[dict[str, str]] | None = None,
        chat_id: int | None = None,
    ) -> RouterResult:
        """Classify a user message into pillar and action.

        Checks the cache first, then enforces per-user cooldown before
        making an LLM call.

        Args:
            message: The user's message text.
            context: Optional recent conversation context.
            chat_id: Optional chat ID for per-user cooldown tracking.

        Returns:
            RouterResult with pillar, action, confidence, and language.
        """
        cache_key = hashlib.sha256(message.encode()).hexdigest()

        # 1. Check cache
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Router cache hit for message hash %s", cache_key[:12])
            return cached

        # 2. Check per-user cooldown
        if chat_id is not None:
            now = time.monotonic()
            last = self._last_call.get(chat_id)
            if last is not None and (now - last) < self._cooldown_seconds:
                logger.debug(
                    "Router cooldown active for chat %d (%.1fs remaining)",
                    chat_id,
                    self._cooldown_seconds - (now - last),
                )
                return RouterResult(pillar="general", action="unclear", confidence=0.3)

        # 3. Call LLM
        context = context or []
        messages = build_router_messages(
            user_message=message,
            context=context,
            language=self.language,
            bot_name=self.bot_name,
        )

        try:
            result_data = await self.llm_client.chat_json(messages)
            result = self._parse_result(result_data)
        except LLMError as exc:
            logger.error("Router LLM error: %s", exc)
            # Fallback: try keyword-based classification
            result = self._keyword_fallback(message)
        except Exception as exc:
            logger.error("Unexpected router error: %s", exc)
            result = RouterResult(pillar="general", action="unclear", confidence=0.3)

        # Update cache and cooldown timestamp
        self._cache[cache_key] = result
        if chat_id is not None:
            self._last_call[chat_id] = time.monotonic()

        return result

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
