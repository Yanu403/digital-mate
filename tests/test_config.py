"""Tests for digital_mate.config module."""

import os
import pytest
from unittest.mock import patch
from digital_mate.config import Settings, LanguageEnum


class TestSettings:
    """Test Settings configuration class."""

    def test_required_fields(self) -> None:
        """Test that Settings can be created with minimal fields."""
        settings = Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            _env_file=None,
        )
        assert settings.telegram_bot_token == "test-token"
        assert settings.llm_api_key == "test-key"

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        settings = Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            _env_file=None,
        )
        assert settings.llm_base_url == "https://api.openai.com/v1"
        assert settings.llm_model == "gpt-4o"
        assert settings.bot_name == "Digital Mate"
        assert settings.bot_language == LanguageEnum.BILINGUAL
        assert settings.max_conversation_turns == 10

    def test_router_model_fallback(self) -> None:
        """Test that router_model falls back to llm_model when empty."""
        settings = Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            llm_model="gpt-4o",
            llm_router_model="",
            _env_file=None,
        )
        assert settings.router_model_effective == "gpt-4o"

        # Explicit router model
        settings2 = Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            llm_model="gpt-4o",
            llm_router_model="gpt-3.5-turbo",
            _env_file=None,
        )
        assert settings2.router_model_effective == "gpt-3.5-turbo"

    def test_db_path_default(self) -> None:
        """Test default database path."""
        settings = Settings(
            telegram_bot_token="test-token",
            llm_api_key="test-key",
            _env_file=None,
        )
        assert settings.db_path == "data/digital_mate.db"

    def test_language_enum_values(self) -> None:
        """Test LanguageEnum has correct values."""
        assert LanguageEnum.BILINGUAL == "bilingual"
        assert LanguageEnum.EN == "en"
        assert LanguageEnum.ID == "id"

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        settings = Settings(
            telegram_bot_token="custom-token",
            llm_base_url="https://custom.api.com/v1",
            llm_api_key="custom-key",
            llm_model="custom-model",
            bot_name="MyBot",
            bot_language=LanguageEnum.ID,
            max_conversation_turns=20,
            notion_api_key="notion-key",
            notion_content_calendar_db="cal-db-123",
            notion_campaign_tracker_db="camp-db-456",
            tavily_api_key="tavily-key",
            _env_file=None,
        )
        assert settings.bot_name == "MyBot"
        assert settings.bot_language == LanguageEnum.ID
        assert settings.max_conversation_turns == 20
        assert settings.notion_api_key == "notion-key"
        assert settings.tavily_api_key == "tavily-key"

    def test_notion_enabled(self) -> None:
        """Test notion_enabled property."""
        s1 = Settings(telegram_bot_token="t", llm_api_key="k", _env_file=None)
        assert s1.notion_enabled is False

        s2 = Settings(
            telegram_bot_token="t", llm_api_key="k",
            notion_api_key="key", notion_content_calendar_db="db",
            _env_file=None,
        )
        assert s2.notion_enabled is True

    def test_search_always_available(self) -> None:
        """Test that search is always available."""
        settings = Settings(telegram_bot_token="t", llm_api_key="k", _env_file=None)
        assert settings.search_enabled is True

    def test_tavily_enabled(self) -> None:
        """Test tavily_enabled property."""
        s1 = Settings(telegram_bot_token="t", llm_api_key="k", _env_file=None)
        assert s1.tavily_enabled is False

        s2 = Settings(
            telegram_bot_token="t", llm_api_key="k",
            tavily_api_key="tav-key",
            _env_file=None,
        )
        assert s2.tavily_enabled is True
