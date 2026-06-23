"""Tests for PlanStore — SQLite persistence for multi-step plans."""

from __future__ import annotations

import pytest
import pytest_asyncio

from digital_mate.memory.database import init_memory_db, AsyncConnection
from digital_mate.agent.plan_store import PlanStore


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


class TestCreatePlan:
    """Tests for PlanStore.create_plan."""

    @pytest.mark.asyncio
    async def test_create_plan_returns_uuid(self, store: PlanStore):
        steps = [
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
            {"pillar": "content", "action": "caption", "description": "Write caption", "input_from": "step_1"},
        ]
        plan_id = await store.create_plan(123, "Test goal", steps)
        assert isinstance(plan_id, str)
        assert len(plan_id) == 36  # UUID4 format

    @pytest.mark.asyncio
    async def test_create_plan_stores_goal(self, store: PlanStore):
        steps = [
            {"pillar": "research", "action": "trends", "description": "Research trends"},
        ]
        plan_id = await store.create_plan(123, "My marketing goal", steps)
        plan = await store.get_active_plan(123)
        assert plan is not None
        assert plan["goal"] == "My marketing goal"
        assert plan["plan_id"] == plan_id

    @pytest.mark.asyncio
    async def test_create_plan_stores_steps(self, store: PlanStore):
        steps = [
            {"pillar": "research", "action": "trends", "description": "Research trends", "input_from": "user_request"},
            {"pillar": "strategy", "action": "plan", "description": "Create plan", "input_from": "step_1"},
            {"pillar": "content", "action": "caption", "description": "Write captions", "input_from": "step_2"},
        ]
        await store.create_plan(123, "Goal", steps)
        plan = await store.get_active_plan(123)
        assert plan is not None
        assert len(plan["steps"]) == 3
        assert plan["steps"][0]["pillar"] == "research"
        assert plan["steps"][0]["step_order"] == 1
        assert plan["steps"][1]["pillar"] == "strategy"
        assert plan["steps"][1]["step_order"] == 2
        assert plan["steps"][2]["pillar"] == "content"
        assert plan["steps"][2]["step_order"] == 3


class TestGetActivePlan:
    """Tests for PlanStore.get_active_plan."""

    @pytest.mark.asyncio
    async def test_no_active_plan(self, store: PlanStore):
        plan = await store.get_active_plan(999)
        assert plan is None

    @pytest.mark.asyncio
    async def test_returns_active_plan(self, store: PlanStore):
        steps = [
            {"pillar": "research", "action": "trends", "description": "Research"},
            {"pillar": "content", "action": "caption", "description": "Write"},
        ]
        await store.create_plan(123, "Test goal", steps)
        plan = await store.get_active_plan(123)
        assert plan is not None
        assert plan["status"] == "active"
        assert plan["chat_id"] == 123

    @pytest.mark.asyncio
    async def test_does_not_return_completed_plan(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.complete_plan(plan_id)
        plan = await store.get_active_plan(123)
        assert plan is None

    @pytest.mark.asyncio
    async def test_does_not_return_cancelled_plan(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.cancel_plan(plan_id)
        plan = await store.get_active_plan(123)
        assert plan is None


class TestUpdateStepStatus:
    """Tests for PlanStore.update_step_status."""

    @pytest.mark.asyncio
    async def test_update_to_running(self, store: PlanStore):
        steps = [
            {"pillar": "research", "action": "trends", "description": "Research"},
            {"pillar": "content", "action": "caption", "description": "Write"},
        ]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.update_step_status(plan_id, 1, "running")
        plan = await store.get_active_plan(123)
        assert plan["steps"][0]["status"] == "running"
        assert plan["steps"][0]["started_at"] is not None

    @pytest.mark.asyncio
    async def test_update_to_completed_with_result(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.update_step_status(plan_id, 1, "completed", result_text="trend data here")
        plan = await store.get_active_plan(123)
        assert plan["steps"][0]["status"] == "completed"
        assert plan["steps"][0]["result_text"] == "trend data here"
        assert plan["steps"][0]["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_update_to_failed_with_error(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.update_step_status(plan_id, 1, "failed", error_message="API down")
        plan = await store.get_active_plan(123)
        assert plan["steps"][0]["status"] == "failed"
        assert plan["steps"][0]["error_message"] == "API down"


class TestCompletePlan:
    """Tests for PlanStore.complete_plan."""

    @pytest.mark.asyncio
    async def test_complete_plan(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.complete_plan(plan_id)
        plan = await store.get_active_plan(123)
        assert plan is None  # No longer active


class TestCancelPlan:
    """Tests for PlanStore.cancel_plan."""

    @pytest.mark.asyncio
    async def test_cancel_plan(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.cancel_plan(plan_id)
        plan = await store.get_active_plan(123)
        assert plan is None  # No longer active


class TestFailPlan:
    """Tests for PlanStore.fail_plan."""

    @pytest.mark.asyncio
    async def test_fail_plan(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Goal", steps)
        await store.fail_plan(plan_id, "Something went wrong")
        plan = await store.get_active_plan(123)
        assert plan is None  # No longer active


class TestCleanupOldPlans:
    """Tests for PlanStore.cleanup_old_plans."""

    @pytest.mark.asyncio
    async def test_cleanup_returns_zero_when_no_old_plans(self, store: PlanStore):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        await store.create_plan(123, "Goal", steps)
        deleted = await store.cleanup_old_plans(days=7)
        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_deletes_old_plans(self, store: PlanStore, db: AsyncConnection):
        steps = [{"pillar": "research", "action": "trends", "description": "Research"}]
        plan_id = await store.create_plan(123, "Old goal", steps)
        # Manually backdate the plan
        await db.execute(
            "UPDATE plans SET created_at = datetime('now', '-10 days') WHERE plan_id = ?",
            (plan_id,),
        )
        await db.commit()
        deleted = await store.cleanup_old_plans(days=7)
        assert deleted == 1
