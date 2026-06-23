"""Tests for PlanExecutor — executes plan steps with progress reporting."""

from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from digital_mate.memory.database import init_memory_db, AsyncConnection
from digital_mate.pillars.base import PillarResult
from digital_mate.agent.plan_store import PlanStore
from digital_mate.agent.executor import PlanExecutor


@pytest_asyncio.fixture
async def db() -> AsyncConnection:
    """Create an in-memory database with schema."""
    conn = await init_memory_db()
    yield conn
    await conn.close()


@pytest.fixture
def store(db: AsyncConnection) -> PlanStore:
    """Create a PlanStore with the test database."""
    return PlanStore(db)


class TestExecuteAllSteps:
    """Tests for PlanExecutor.execute running all steps."""

    @pytest.mark.asyncio
    async def test_execute_all_steps(self, store: PlanStore):
        mock_research = AsyncMock()
        mock_research.handle_structured = AsyncMock(
            return_value=PillarResult(text="trend: AI marketing")
        )
        mock_content = AsyncMock()
        mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="✨ AI caption!")
        )
        pillars = {"research": mock_research, "content": mock_content}
        executor = PlanExecutor(pillars, store)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
            {"pillar": "content", "action": "caption", "description": "Write caption", "input_from": "step_1"},
        ]
        plan_id = await store.create_plan(123, "Test goal", steps)

        result = await executor.execute(
            plan_id=plan_id,
            steps=steps,
            user_message="Launch campaign",
            context=[],
        )
        assert "trend: AI marketing" in result
        assert "AI caption" in result
        mock_research.handle_structured.assert_called_once()
        mock_content.handle_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_marks_plan_completed(self, store: PlanStore):
        mock_pillar = AsyncMock()
        mock_pillar.handle_structured = AsyncMock(
            return_value=PillarResult(text="done")
        )
        executor = PlanExecutor({"research": mock_pillar}, store)

        steps = [{"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"}]
        plan_id = await store.create_plan(123, "Goal", steps)

        await executor.execute(plan_id=plan_id, steps=steps, user_message="test", context=[])

        # Plan should no longer be active
        plan = await store.get_active_plan(123)
        assert plan is None


class TestExecuteWithProgressCallback:
    """Tests for progress callback during execution."""

    @pytest.mark.asyncio
    async def test_execute_with_progress_callback(self, store: PlanStore):
        mock_pillar = AsyncMock()
        mock_pillar.handle_structured = AsyncMock(
            return_value=PillarResult(text="result")
        )
        executor = PlanExecutor({"research": mock_pillar}, store)

        progress_calls = []

        async def on_progress(msg: str):
            progress_calls.append(msg)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
            {"pillar": "research", "action": "competitors", "description": "Analyze competitors", "input_from": "user_request"},
        ]
        plan_id = await store.create_plan(123, "Test goal", steps)

        await executor.execute(
            plan_id=plan_id,
            steps=steps,
            user_message="test",
            context=[],
            on_progress=on_progress,
        )
        # Should have: init + step1 running + step2 running + final done = 4 calls
        assert len(progress_calls) == 4
        assert "🚀" in progress_calls[0]  # Init
        assert "⏳" in progress_calls[1]  # Step 1 running
        assert "✅" in progress_calls[2]  # Step 2 running (step 1 done in display)
        assert "✅" in progress_calls[3]  # Final done


class TestExecuteStepFailureContinues:
    """Tests that step failures don't stop execution."""

    @pytest.mark.asyncio
    async def test_execute_step_failure_continues(self, store: PlanStore):
        mock_research = AsyncMock()
        mock_research.handle_structured = AsyncMock(side_effect=RuntimeError("API down"))
        mock_content = AsyncMock()
        mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="caption text")
        )
        pillars = {"research": mock_research, "content": mock_content}
        executor = PlanExecutor(pillars, store)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
            {"pillar": "content", "action": "caption", "description": "Write", "input_from": "step_1"},
        ]
        plan_id = await store.create_plan(123, "Goal", steps)

        result = await executor.execute(
            plan_id=plan_id,
            steps=steps,
            user_message="test",
            context=[],
        )
        # First step failed, second step still ran
        assert "error" in result.lower() or "Error" in result
        assert "caption text" in result
        mock_content.handle_structured.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_missing_pillar_continues(self, store: PlanStore):
        mock_content = AsyncMock()
        mock_content.handle_structured = AsyncMock(
            return_value=PillarResult(text="caption text")
        )
        # Only content pillar available, not research
        executor = PlanExecutor({"content": mock_content}, store)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
            {"pillar": "content", "action": "caption", "description": "Write", "input_from": "user_request"},
        ]
        plan_id = await store.create_plan(123, "Goal", steps)

        result = await executor.execute(
            plan_id=plan_id,
            steps=steps,
            user_message="test",
            context=[],
        )
        assert "not available" in result.lower()
        assert "caption text" in result


class TestExecuteStoresResultsInDB:
    """Tests that step results are stored in the database."""

    @pytest.mark.asyncio
    async def test_step_status_updated_in_db(self, store: PlanStore, db: AsyncConnection):
        mock_pillar = AsyncMock()
        mock_pillar.handle_structured = AsyncMock(
            return_value=PillarResult(text="step result data")
        )
        executor = PlanExecutor({"research": mock_pillar}, store)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
        ]
        plan_id = await store.create_plan(123, "Goal", steps)

        await executor.execute(plan_id=plan_id, steps=steps, user_message="test", context=[])

        # Check step was marked as completed in DB
        cursor = await db.execute(
            "SELECT status, result_text FROM plan_steps WHERE plan_id = ?",
            (plan_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "completed"
        assert row[1] == "step result data"

    @pytest.mark.asyncio
    async def test_failed_step_stored_in_db(self, store: PlanStore, db: AsyncConnection):
        mock_pillar = AsyncMock()
        mock_pillar.handle_structured = AsyncMock(side_effect=RuntimeError("boom"))
        executor = PlanExecutor({"research": mock_pillar}, store)

        steps = [
            {"pillar": "research", "action": "trends", "description": "Research", "input_from": "user_request"},
        ]
        plan_id = await store.create_plan(123, "Goal", steps)

        await executor.execute(plan_id=plan_id, steps=steps, user_message="test", context=[])

        cursor = await db.execute(
            "SELECT status, error_message FROM plan_steps WHERE plan_id = ?",
            (plan_id,),
        )
        row = await cursor.fetchone()
        assert row[0] == "failed"
        assert "boom" in row[1]


class TestResolveInput:
    """Tests for PlanExecutor._resolve_input."""

    def test_user_request(self):
        result = PlanExecutor._resolve_input("user_request", "original msg", {})
        assert result == "original msg"

    def test_step_reference(self):
        outputs = {1: "previous step output"}
        result = PlanExecutor._resolve_input("step_1", "original msg", outputs)
        assert "previous step output" in result
        assert "original msg" in result

    def test_missing_step_reference_fallback(self):
        result = PlanExecutor._resolve_input("step_5", "original msg", {})
        assert result == "original msg"

    def test_invalid_format_fallback(self):
        result = PlanExecutor._resolve_input("bad_format", "original msg", {})
        assert result == "original msg"


class TestCombineResults:
    """Tests for PlanExecutor._combine_results."""

    def test_single_result(self):
        steps = [{"description": "Step 1"}]
        result = PlanExecutor._combine_results(steps, ["hello"], "goal")
        assert result == "hello"

    def test_multiple_results(self):
        steps = [{"description": "Research"}, {"description": "Write"}]
        result = PlanExecutor._combine_results(steps, ["data", "caption"], "goal")
        assert "Research" in result
        assert "data" in result
        assert "Write" in result
        assert "caption" in result
        assert "---" in result

    def test_empty_results(self):
        result = PlanExecutor._combine_results([], [], "goal")
        assert "no results" in result
