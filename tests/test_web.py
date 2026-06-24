"""Tests for the Digital Mate web dashboard.

Covers API endpoints, settings service, brand service, and stats service.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Settings Service Tests
# ---------------------------------------------------------------------------

class TestSettingsService:
    """Tests for SettingsService .env read/write."""

    def _make_service(self, tmp_path: Path, env_content: str = ""):
        from digital_mate.web.settings_service import SettingsService

        env_file = tmp_path / ".env"
        if env_content:
            env_file.write_text(env_content, encoding="utf-8")
        return SettingsService(tmp_path)

    def test_read_empty_env(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.get("ANY_KEY") == ""
        assert svc.get("ANY_KEY", "default") == "default"

    def test_read_existing_env(self, tmp_path):
        svc = self._make_service(tmp_path, "TELEGRAM_BOT_TOKEN=abc123\nLLM_MODEL=gpt-4o\n")
        assert svc.get("TELEGRAM_BOT_TOKEN") == "abc123"
        assert svc.get("LLM_MODEL") == "gpt-4o"

    def test_exists_true(self, tmp_path):
        svc = self._make_service(tmp_path, "TOKEN=x\n")
        assert svc.exists() is True

    def test_exists_false(self, tmp_path):
        svc = self._make_service(tmp_path)
        assert svc.exists() is False

    def test_has_required_true(self, tmp_path):
        svc = self._make_service(tmp_path, "TELEGRAM_BOT_TOKEN=abc\nLLM_API_KEY=def\n")
        assert svc.has_required() is True

    def test_has_required_false(self, tmp_path):
        svc = self._make_service(tmp_path, "TELEGRAM_BOT_TOKEN=abc\n")
        assert svc.has_required() is False

    def test_get_all_redacted(self, tmp_path):
        svc = self._make_service(
            tmp_path,
            "TELEGRAM_BOT_TOKEN=1234567890abcdef\nLLM_API_KEY=sk-abcdef1234567890\nLLM_MODEL=gpt-4o\n",
        )
        data = svc.get_all_redacted()
        assert data["_exists"] is True
        # Token should be redacted (has 'token' in name)
        assert "•" in data["TELEGRAM_BOT_TOKEN"]
        # Model should NOT be redacted
        assert data["LLM_MODEL"] == "gpt-4o"

    def test_save_creates_env(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.save({"TELEGRAM_BOT_TOKEN": "new-token", "LLM_MODEL": "llama3"})
        content = (tmp_path / ".env").read_text()
        assert "TELEGRAM_BOT_TOKEN=new-token" in content
        assert "LLM_MODEL=llama3" in content

    def test_save_updates_existing(self, tmp_path):
        svc = self._make_service(tmp_path, "TELEGRAM_BOT_TOKEN=old\nLLM_MODEL=gpt-4o\n")
        svc.save({"LLM_MODEL": "llama3"})
        assert svc.get("LLM_MODEL") == "llama3"
        assert svc.get("TELEGRAM_BOT_TOKEN") == "old"

    def test_save_removes_empty(self, tmp_path):
        svc = self._make_service(tmp_path, "TOKEN=abc\nMODEL=gpt-4o\n")
        svc.save({"TOKEN": ""})
        assert svc.get("TOKEN") == ""
        assert svc.get("MODEL") == "gpt-4o"

    def test_save_quoted_values(self, tmp_path):
        svc = self._make_service(tmp_path)
        svc.save({"BOT_NAME": "Digital Mate Bot"})
        content = (tmp_path / ".env").read_text()
        assert 'BOT_NAME="Digital Mate Bot"' in content


# ---------------------------------------------------------------------------
# FastAPI App Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    """Create a test client for the FastAPI app with a temp .env."""
    # Patch PROJECT_ROOT so settings service uses tmp_path
    with patch("digital_mate.web.app.PROJECT_ROOT", tmp_path):
        from digital_mate.web.app import create_app
        app = create_app()
        yield TestClient(app)


@pytest.fixture
def client_with_env(tmp_path):
    """Create a test client with a pre-populated .env."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=test-token-123\n"
        "LLM_API_KEY=test-key-456\n"
        "LLM_MODEL=gpt-4o\n"
        "BOT_LANGUAGE=bilingual\n",
        encoding="utf-8",
    )
    with patch("digital_mate.web.app.PROJECT_ROOT", tmp_path):
        from digital_mate.web.app import create_app
        app = create_app()
        yield TestClient(app)


class TestHealthEndpoint:
    """Tests for /api/health."""

    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "timestamp" in data


class TestStatusEndpoint:
    """Tests for /api/status."""

    def test_status_stopped_by_default(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"


class TestSettingsEndpoints:
    """Tests for /api/settings."""

    def test_get_settings_empty(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        # Should have _exists key
        assert "_exists" in data

    def test_get_settings_with_env(self, client_with_env):
        resp = client_with_env.get("/api/settings")
        data = resp.json()
        assert data.get("LLM_MODEL") == "gpt-4o"
        assert data.get("_exists") is True
        # Secrets should be redacted
        assert "•" in data.get("TELEGRAM_BOT_TOKEN", "•")

    def test_save_settings(self, client):
        resp = client.post("/api/settings", json={
            "TELEGRAM_BOT_TOKEN": "new-token",
            "LLM_API_KEY": "new-key",
            "LLM_MODEL": "llama3",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"

        # Verify saved
        get_resp = client.get("/api/settings")
        data = get_resp.json()
        assert data.get("LLM_MODEL") == "llama3"


class TestStatsEndpoint:
    """Tests for /api/stats."""

    def test_stats_returns_zeroes_when_no_db(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_messages"] == 0
        assert data["active_users"] == 0
        assert data["plans_created"] == 0
        assert data["feedback_score"] == 0.0
        assert data["recent_activity"] == []


class TestBotControlEndpoints:
    """Tests for /api/bot/start and /api/bot/stop."""

    def test_stop_when_not_running(self, client):
        resp = client.post("/api/bot/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_running"


class TestLogEndpoint:
    """Tests for /api/logs."""

    def test_logs_empty(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        assert resp.json() == []


class TestIndexPage:
    """Tests for the root HTML page."""

    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Digital Mate" in resp.text
        assert "Dashboard" in resp.text

    def test_index_has_wizard(self, client):
        resp = client.get("/")
        assert "wizard" in resp.text.lower()

    def test_index_has_dark_theme(self, client):
        resp = client.get("/")
        assert "#0a0a12" in resp.text

    def test_index_has_prompts_nav(self, client):
        resp = client.get("/")
        assert "prompts" in resp.text.lower()
        assert "page-prompts" in resp.text


# ---------------------------------------------------------------------------
# Prompt API Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_prompts(tmp_path):
    """Create a test client with prompt files in place."""
    # Create prompt directory structure
    prompts_dir = tmp_path / "digital_mate" / "prompts"
    prompts_dir.mkdir(parents=True)

    # Create AGENT.md
    agent_md = tmp_path / "digital_mate" / "AGENT.md"
    agent_md.write_text("# Agent Definition\n\nTest agent personality.\n", encoding="utf-8")

    # Create prompt files
    prompt_files = {
        "router.md": "# Intent Router\n\nClassify user intents.\n",
        "content.md": "# Content Expert\n\nGenerate content.\n",
        "strategy.md": "# Strategy Expert\n\nStrategic planning.\n",
        "research.md": "# Research Expert\n\nResearch methodology.\n",
        "analytics.md": "# Analytics Expert\n\nAnalytics interpretation.\n",
        "planner.md": "# Goal Planner\n\nGoal decomposition.\n",
        "general.md": "# General Chat\n\nChitchat responses.\n",
    }
    for name, content in prompt_files.items():
        (prompts_dir / name).write_text(content, encoding="utf-8")

    with patch("digital_mate.web.app.PROJECT_ROOT", tmp_path):
        from digital_mate.web.app import create_app
        app = create_app()
        yield TestClient(app)


class TestPromptListEndpoint:
    """Tests for GET /api/prompts."""

    def test_list_prompts(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 8
        # Check structure
        for item in data:
            assert "path" in item
            assert "name" in item
            assert "description" in item
            assert "group" in item
            assert "size" in item
            assert "modified" in item

    def test_list_prompts_has_agent_md(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts")
        data = resp.json()
        paths = [p["path"] for p in data]
        assert "AGENT.md" in paths

    def test_list_prompts_has_all_groups(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts")
        data = resp.json()
        groups = {p["group"] for p in data}
        assert "Core" in groups
        assert "Pillars" in groups
        assert "Agent" in groups

    def test_list_prompts_metadata(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts")
        data = resp.json()
        agent = next(p for p in data if p["path"] == "AGENT.md")
        assert agent["name"] == "Agent Personality"
        assert agent["group"] == "Core"
        assert agent["size"] > 0
        assert agent["modified"] is not None


class TestPromptReadEndpoint:
    """Tests for GET /api/prompts/{path}."""

    def test_read_agent_md(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts/AGENT.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "AGENT.md"
        assert data["name"] == "Agent Personality"
        assert "Agent Definition" in data["content"]
        assert "modified" in data

    def test_read_prompt_file(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts/prompts/content.md")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "prompts/content.md"
        assert "Content Expert" in data["content"]

    def test_read_nonexistent_file(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts/prompts/nonexistent.md")
        assert resp.status_code == 400  # Not in allowed list

    def test_read_traversal_rejected(self, client_with_prompts):
        resp = client_with_prompts.get("/api/prompts/../../../etc/passwd")
        # FastAPI normalizes paths, stripping .. → results in 404
        assert resp.status_code in (400, 404)


class TestPromptSaveEndpoint:
    """Tests for PUT /api/prompts/{path}."""

    def test_save_prompt(self, client_with_prompts):
        resp = client_with_prompts.put(
            "/api/prompts/AGENT.md",
            json={"content": "# Updated Agent\n\nNew content here.\n"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["path"] == "AGENT.md"
        assert data["size"] > 0

    def test_save_creates_backup(self, client_with_prompts, tmp_path):
        # Save once to create .bak
        client_with_prompts.put(
            "/api/prompts/AGENT.md",
            json={"content": "# Updated\n"},
        )
        bak_file = tmp_path / "digital_mate" / "AGENT.md.bak"
        assert bak_file.exists()
        # .bak should have original content
        assert "Agent Definition" in bak_file.read_text(encoding="utf-8")

    def test_save_persists_content(self, client_with_prompts):
        new_content = "# Brand New Content\n\nCompletely rewritten.\n"
        client_with_prompts.put(
            "/api/prompts/prompts/content.md",
            json={"content": new_content},
        )
        # Read back
        resp = client_with_prompts.get("/api/prompts/prompts/content.md")
        data = resp.json()
        assert data["content"] == new_content

    def test_save_missing_content_field(self, client_with_prompts):
        resp = client_with_prompts.put(
            "/api/prompts/AGENT.md",
            json={"wrong_field": "value"},
        )
        assert resp.status_code == 400

    def test_save_traversal_rejected(self, client_with_prompts):
        resp = client_with_prompts.put(
            "/api/prompts/../../../etc/passwd",
            json={"content": "evil"},
        )
        # FastAPI normalizes paths, stripping .. → results in 404
        assert resp.status_code in (400, 404)

    def test_save_unknown_file_rejected(self, client_with_prompts):
        resp = client_with_prompts.put(
            "/api/prompts/prompts/unknown.md",
            json={"content": "test"},
        )
        assert resp.status_code == 400

    def test_save_updates_size_in_listing(self, client_with_prompts):
        # Save new content
        client_with_prompts.put(
            "/api/prompts/AGENT.md",
            json={"content": "# Short\n"},
        )
        # Check listing shows new size
        resp = client_with_prompts.get("/api/prompts")
        data = resp.json()
        agent = next(p for p in data if p["path"] == "AGENT.md")
        assert agent["size"] == len("# Short\n".encode("utf-8"))


# ---------------------------------------------------------------------------
# Stats Service Tests
# ---------------------------------------------------------------------------

class TestStatsService:
    """Tests for StatsService with in-memory database."""

    @pytest.mark.asyncio
    async def test_get_stats_empty_db(self, temp_db):
        from digital_mate.web.stats_service import StatsService

        svc = StatsService(temp_db)
        stats = await svc.get_stats()
        assert stats["total_messages"] == 0
        assert stats["active_users"] == 0
        assert stats["plans_created"] == 0
        assert stats["feedback_score"] == 0.0
        assert stats["recent_activity"] == []

    @pytest.mark.asyncio
    async def test_get_stats_with_data(self, temp_db):
        from digital_mate.web.stats_service import StatsService

        # Insert some test data
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content) VALUES (?, ?, ?)",
            (123, "user", "Hello"),
        )
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content) VALUES (?, ?, ?)",
            (123, "assistant", "Hi there"),
        )
        await temp_db.execute(
            "INSERT INTO sessions (chat_id, role, content) VALUES (?, ?, ?)",
            (456, "user", "Test message"),
        )
        await temp_db.commit()

        svc = StatsService(temp_db)
        stats = await svc.get_stats()
        assert stats["total_messages"] == 3
        assert stats["active_users"] == 2

    @pytest.mark.asyncio
    async def test_close(self, temp_db):
        from digital_mate.web.stats_service import StatsService

        svc = StatsService(temp_db)
        await svc.close()


# ---------------------------------------------------------------------------
# Brand Service Tests
# ---------------------------------------------------------------------------

class TestBrandService:
    """Tests for BrandService with in-memory database."""

    @pytest.mark.asyncio
    async def test_list_all_empty(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        profiles = await svc.list_all()
        assert profiles == []

    @pytest.mark.asyncio
    async def test_create_and_get(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        result = await svc.create_or_update({
            "chat_id": 123,
            "name": "Test Brand",
            "industry": "Tech",
        })
        assert result["name"] == "Test Brand"
        assert result["chat_id"] == 123

        # Get it back
        profile = await svc.get(123)
        assert profile is not None
        assert profile["name"] == "Test Brand"
        assert profile["industry"] == "Tech"

    @pytest.mark.asyncio
    async def test_update_existing(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        await svc.create_or_update({"chat_id": 123, "name": "Brand v1"})
        await svc.create_or_update({"chat_id": 123, "name": "Brand v2", "industry": "SaaS"})

        profile = await svc.get(123)
        assert profile["name"] == "Brand v2"
        assert profile["industry"] == "SaaS"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        assert await svc.get(999) is None

    @pytest.mark.asyncio
    async def test_create_missing_chat_id(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        with pytest.raises(ValueError, match="chat_id"):
            await svc.create_or_update({"name": "No ID"})

    @pytest.mark.asyncio
    async def test_list_multiple(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        await svc.create_or_update({"chat_id": 1, "name": "Brand A"})
        await svc.create_or_update({"chat_id": 2, "name": "Brand B"})

        profiles = await svc.list_all()
        assert len(profiles) == 2
        names = {p["name"] for p in profiles}
        assert "Brand A" in names
        assert "Brand B" in names

    @pytest.mark.asyncio
    async def test_close(self, temp_db):
        from digital_mate.web.brand_service import BrandService

        svc = BrandService(temp_db)
        await svc.close()


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------

class TestCLI:
    """Tests for the CLI entry point."""

    def test_cli_import(self):
        from digital_mate.cli import main
        assert callable(main)

    def test_cli_help(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "digital_mate.cli", "--help"],
            capture_output=True, text=True, cwd="/root/projects/digital-mate",
            env={**os.environ, "PYTHONPATH": "/root/projects/digital-mate"},
        )
        assert "Digital Mate" in result.stdout or "digital-mate" in result.stdout.lower()

    def test_cli_serve_help(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "digital_mate.cli", "serve", "--help"],
            capture_output=True, text=True, cwd="/root/projects/digital-mate",
            env={**os.environ, "PYTHONPATH": "/root/projects/digital-mate"},
        )
        assert "--port" in result.stdout
        assert "--host" in result.stdout


import sys
