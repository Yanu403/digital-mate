"""Tests for BasePillar and MAX_RESPONSE_TOKENS configuration."""

from __future__ import annotations

import pytest

from digital_mate.pillars.base import BasePillar
from digital_mate.pillars.strategy import StrategyPillar
from digital_mate.pillars.analytics import AnalyticsPillar
from digital_mate.pillars.research import ResearchPillar
from digital_mate.pillars.content import ContentPillar


class TestMaxResponseTokens:
    """Test MAX_RESPONSE_TOKENS class attributes on pillars."""

    def test_base_pillar_default_tokens(self) -> None:
        """BasePillar should default to 2048."""
        assert BasePillar.MAX_RESPONSE_TOKENS == 2048

    def test_strategy_pillar_tokens(self) -> None:
        """StrategyPillar should use 4096 tokens."""
        assert StrategyPillar.MAX_RESPONSE_TOKENS == 4096

    def test_analytics_pillar_tokens(self) -> None:
        """AnalyticsPillar should use 3072 tokens."""
        assert AnalyticsPillar.MAX_RESPONSE_TOKENS == 3072

    def test_research_pillar_tokens(self) -> None:
        """ResearchPillar should use 3072 tokens."""
        assert ResearchPillar.MAX_RESPONSE_TOKENS == 3072

    def test_content_pillar_tokens(self) -> None:
        """ContentPillar should use default 2048 tokens."""
        assert ContentPillar.MAX_RESPONSE_TOKENS == 2048
