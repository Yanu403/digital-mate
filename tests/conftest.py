"""Shared test fixtures for Digital Mate test suite.

Provides mock LLM client, temporary SQLite database, mock Notion service,
and sample brand profile for use across all test modules.
"""

from __future__ import annotations

import os
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from digital_mate.config import Settings
from digital_mate.llm.client import LLMClient
from digital_mate.memory.database import init_memory_db, AsyncConnection
from digital_mate.memory.session import SessionManager
from digital_mate.memory.brand_profile import BrandProfile, BrandProfileManager
from digital_mate.integrations.notion_client import NotionService
from digital_mate.integrations.search import SearchService
from digital_mate.router import IntentRouter, RouterResult


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Create a mock LLMClient that returns configurable responses.

    Returns:
        MagicMock with async chat() and chat_json() methods.
    """
    client = MagicMock(spec=LLMClient)
    client.model = "test-model"
    client.router_model = "test-router-model"
    client.max_retries = 1

    # Default chat response
    chat_response = AsyncMock(return_value="This is a mock LLM response for testing.")
    client.chat = chat_response

    # Default JSON response for router
    json_response = AsyncMock(return_value={
        "pillar": "content",
        "action": "caption",
        "confidence": 0.9,
        "language_detected": "en",
    })
    client.chat_json = json_response

    return client


@pytest_asyncio.fixture
async def temp_db() -> AsyncConnection:
    """Create an in-memory SQLite database with schema for testing.

    Yields:
        Open AsyncConnection to in-memory database.
    """
    conn = await init_memory_db()
    yield conn
    await conn.close()


@pytest.fixture
def mock_notion_client() -> MagicMock:
    """Create a mock NotionService with preset data.

    Returns:
        MagicMock NotionService with mock methods.
    """
    service = MagicMock(spec=NotionService)
    service.api_key = "test-notion-key"
    service.content_calendar_db = "test-calendar-db-id"
    service.campaign_tracker_db = "test-campaign-db-id"
    service.is_configured = True

    service.get_content_calendar = AsyncMock(return_value=[
        {
            "date": "2024-01-15",
            "platform": "Instagram",
            "content_type": "Reel",
            "topic": "Product Launch Teaser",
            "status": "planned",
        },
        {
            "date": "2024-01-17",
            "platform": "Twitter",
            "content_type": "Thread",
            "topic": "Industry Tips",
            "status": "draft",
        },
    ])

    service.get_campaigns = AsyncMock(return_value=[
        {
            "name": "Q1 Launch Campaign",
            "status": "active",
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "budget": "$5,000",
            "reach": "50,000",
            "engagement": "3,500",
            "conversions": "250",
        },
    ])

    return service


@pytest.fixture
def sample_brand_profile() -> BrandProfile:
    """Create a sample BrandProfile for testing.

    Returns:
        BrandProfile with realistic test data.
    """
    return BrandProfile(
        chat_id=123456789,
        name="TestBrand Coffee",
        industry="Food & Beverage",
        audience="Young professionals aged 25-35 who value quality and sustainability",
        tone="Warm, friendly, and slightly playful",
        products="Specialty coffee beans, brewing equipment, coffee subscriptions",
        hashtags="#CoffeeLovers, #SpecialtyCoffee, #SustainableBrew",
        competitors="Blue Bottle, Stumptown, Intelligentsia",
        language_pref="bilingual",
        platform_preference="instagram,tiktok,email",
        budget_range="medium",
        business_stage="growth",
    )


@pytest.fixture
def sample_settings() -> Settings:
    """Create test Settings instance.

    Returns:
        Settings with test values.
    """
    return Settings(
        _env_file=None,
        telegram_bot_token="test-token-123",
        llm_base_url="https://api.test.com/v1",
        llm_api_key="test-api-key",
        llm_model="test-model",
    )
