"""Configuration management using pydantic-settings.

Loads settings from .env file in the project root directory.
Provides a singleton Settings instance via get_settings().
"""

from __future__ import annotations

import logging
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class LanguageEnum(str, Enum):
    """Supported bot language modes.

    Attributes:
        BILINGUAL: Auto-detect and match the user's language (EN, ID, ES, ZH, JA, and more).
        EN: Always respond in English.
        ID: Always respond in Bahasa Indonesia.
        ES: Always respond in Spanish.
        ZH: Always respond in Chinese (Simplified).
        JA: Always respond in Japanese.
    """

    BILINGUAL = "bilingual"
    EN = "en"
    ID = "id"
    ES = "es"
    ZH = "zh"
    JA = "ja"


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file.

    All credentials and configuration are loaded from environment
    variables or a .env file in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram (required) ---
    telegram_bot_token: str = Field(..., min_length=1)

    # --- LLM (required) ---
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = Field(..., min_length=1)
    llm_model: str = "gpt-4o"
    llm_router_model: str = ""
    llm_vision_model: str = ""  # Empty = use llm_model. Some providers need a different model for vision.
    llm_timeout: float = Field(default=120.0, gt=0, description="LLM API read timeout in seconds")
    llm_max_retries: int = Field(default=3, ge=1, le=10, description="Max retry attempts for LLM calls")
    llm_stale_timeout: float = Field(default=30.0, gt=0, description="Seconds without data before killing a stream")

    # --- Notion (optional) ---
    notion_api_key: str | None = None
    notion_content_calendar_db: str | None = None
    notion_campaign_tracker_db: str | None = None

    # --- Search (optional) ---
    tavily_api_key: str | None = None

    # --- Bot settings ---
    bot_language: LanguageEnum = LanguageEnum.BILINGUAL
    bot_name: str = "Digital Mate"
    max_conversation_turns: int = Field(default=10, ge=1, le=50)
    db_path: str = "data/digital_mate.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def router_model_effective(self) -> str:
        """Return the effective router model (falls back to llm_model if empty).

        Returns:
            Router model string.
        """
        return self.llm_router_model or self.llm_model

    @property
    def vision_model_effective(self) -> str:
        """Return the effective vision model (falls back to llm_model if empty).

        Returns:
            Vision model string.
        """
        return self.llm_vision_model or self.llm_model

    @property
    def notion_enabled(self) -> bool:
        """Check if Notion integration is configured.

        Returns:
            True if API key and at least one database ID are set.
        """
        return bool(self.notion_api_key and (self.notion_content_calendar_db or self.notion_campaign_tracker_db))

    @property
    def search_enabled(self) -> bool:
        """Check if any search provider is available.

        Returns:
            True — DuckDuckGo is always available as fallback.
        """
        return True

    @property
    def tavily_enabled(self) -> bool:
        """Check if Tavily search is configured.

        Returns:
            True if Tavily API key is set.
        """
        return bool(self.tavily_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton.

    Returns:
        Cached Settings instance.
    """
    settings = Settings()
    logger.info(
        "Settings loaded — model=%s, bot=%s",
        settings.llm_model,
        settings.bot_name,
    )
    return settings
