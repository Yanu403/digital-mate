"""SQLite persistence for multi-step plans.

Stores plan metadata and individual steps, allowing the orchestrator
to track progress across a multi-step marketing plan execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from digital_mate.memory.database import AsyncConnection

logger = logging.getLogger(__name__)


class PlanStore:
    """SQLite persistence for multi-step plans.

    Args:
        db: Open AsyncConnection to the database.
    """

    def __init__(self, db: AsyncConnection) -> None:
        self.db = db

    async def create_plan(self, chat_id: int, goal: str, steps: list[dict]) -> str:
        """Create a new plan with steps.

        Args:
            chat_id: Telegram chat ID.
            goal: High-level goal description.
            steps: List of step dicts with keys: pillar, action, description, input_from.

        Returns:
            The generated plan_id (UUID4 string).
        """
        plan_id = str(uuid4())
        await self.db.execute(
            "INSERT INTO plans (plan_id, chat_id, goal) VALUES (?, ?, ?)",
            (plan_id, chat_id, goal),
        )
        for i, step in enumerate(steps):
            await self.db.execute(
                "INSERT INTO plan_steps (plan_id, step_order, pillar, action, description, input_from) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan_id,
                    i + 1,
                    step["pillar"],
                    step["action"],
                    step["description"],
                    step.get("input_from", "user_request"),
                ),
            )
        await self.db.commit()
        logger.info("Created plan %s for chat %d with %d steps", plan_id, chat_id, len(steps))
        return plan_id

    async def get_active_plan(self, chat_id: int) -> dict | None:
        """Get the active plan for a chat, including all steps.

        Args:
            chat_id: Telegram chat ID.

        Returns:
            Dict with plan info and 'steps' list, or None if no active plan.
        """
        cursor = await self.db.execute(
            "SELECT plan_id, chat_id, goal, status, created_at, updated_at "
            "FROM plans WHERE chat_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        plan = {
            "plan_id": row[0],
            "chat_id": row[1],
            "goal": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

        steps_cursor = await self.db.execute(
            "SELECT step_id, step_order, pillar, action, description, input_from, "
            "status, result_text, error_message, started_at, completed_at "
            "FROM plan_steps WHERE plan_id = ? ORDER BY step_order",
            (plan["plan_id"],),
        )
        steps_rows = await steps_cursor.fetchall()
        plan["steps"] = [
            {
                "step_id": r[0],
                "step_order": r[1],
                "pillar": r[2],
                "action": r[3],
                "description": r[4],
                "input_from": r[5],
                "status": r[6],
                "result_text": r[7],
                "error_message": r[8],
                "started_at": r[9],
                "completed_at": r[10],
            }
            for r in steps_rows
        ]
        return plan

    async def update_step_status(
        self,
        plan_id: str,
        step_order: int,
        status: str,
        result_text: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update a step's status and optionally its result.

        Args:
            plan_id: The plan UUID.
            step_order: 1-based step order.
            status: New status (pending/running/completed/failed/skipped).
            result_text: Optional result text from pillar execution.
            error_message: Optional error message on failure.
        """
        now = datetime.utcnow().isoformat()
        if status == "running":
            await self.db.execute(
                "UPDATE plan_steps SET status = ?, started_at = ? "
                "WHERE plan_id = ? AND step_order = ?",
                (status, now, plan_id, step_order),
            )
        elif status in ("completed", "failed", "skipped"):
            await self.db.execute(
                "UPDATE plan_steps SET status = ?, result_text = ?, error_message = ?, completed_at = ? "
                "WHERE plan_id = ? AND step_order = ?",
                (status, result_text, error_message, now, plan_id, step_order),
            )
        else:
            await self.db.execute(
                "UPDATE plan_steps SET status = ? WHERE plan_id = ? AND step_order = ?",
                (status, plan_id, step_order),
            )
        await self.db.commit()

    async def complete_plan(self, plan_id: str) -> None:
        """Mark plan as completed.

        Args:
            plan_id: The plan UUID.
        """
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            "UPDATE plans SET status = 'completed', updated_at = ? WHERE plan_id = ?",
            (now, plan_id),
        )
        await self.db.commit()
        logger.info("Plan %s marked as completed", plan_id)

    async def cancel_plan(self, plan_id: str) -> None:
        """Mark plan as cancelled.

        Args:
            plan_id: The plan UUID.
        """
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            "UPDATE plans SET status = 'cancelled', updated_at = ? WHERE plan_id = ?",
            (now, plan_id),
        )
        await self.db.commit()
        logger.info("Plan %s cancelled", plan_id)

    async def fail_plan(self, plan_id: str, error: str | None = None) -> None:
        """Mark plan as failed.

        Args:
            plan_id: The plan UUID.
            error: Optional error description.
        """
        now = datetime.utcnow().isoformat()
        await self.db.execute(
            "UPDATE plans SET status = 'failed', updated_at = ? WHERE plan_id = ?",
            (now, plan_id),
        )
        await self.db.commit()
        logger.warning("Plan %s failed: %s", plan_id, error)

    async def cleanup_old_plans(self, days: int = 7) -> int:
        """Delete plans older than N days.

        Args:
            days: Age threshold in days.

        Returns:
            Number of deleted plans.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        # Delete steps first (FK constraint)
        cursor = await self.db.execute(
            "DELETE FROM plan_steps WHERE plan_id IN "
            "(SELECT plan_id FROM plans WHERE created_at < ?)",
            (cutoff,),
        )
        cursor = await self.db.execute(
            "DELETE FROM plans WHERE created_at < ?",
            (cutoff,),
        )
        deleted = cursor.rowcount
        await self.db.commit()
        if deleted > 0:
            logger.info("Cleaned up %d old plans (older than %d days)", deleted, days)
        return deleted

    async def get_interrupted_plans(self) -> list[dict]:
        """Find all active plans with interrupted steps.

        An interrupted plan is one with status='active' that has at least
        one step with status='running' (the bot was killed mid-execution).
        These steps are reset to 'pending' before the plan list is returned.

        Returns:
            List of plan dicts with 'steps' key, each plan containing
            plan_id, chat_id, goal, status, and steps list.
        """
        cursor = await self.db.execute(
            "SELECT DISTINCT p.plan_id FROM plans p "
            "JOIN plan_steps ps ON p.plan_id = ps.plan_id "
            "WHERE p.status = 'active' AND ps.status = 'running'"
        )
        rows = await cursor.fetchall()

        plans: list[dict] = []
        for row in rows:
            plan_id = row[0]
            plan = await self.get_active_plan_by_id(plan_id)
            if plan is not None:
                # Reset running steps back to pending
                for step in plan.get("steps", []):
                    if step["status"] == "running":
                        await self.update_step_status(plan_id, step["step_order"], "pending")
                        step["status"] = "pending"
                plans.append(plan)

        if plans:
            logger.info("Found %d interrupted plans for resume", len(plans))
        return plans

    async def get_active_plan_by_id(self, plan_id: str) -> dict | None:
        """Get a plan by its ID, including all steps.

        Args:
            plan_id: The plan UUID.

        Returns:
            Dict with plan info and 'steps' list, or None if not found.
        """
        cursor = await self.db.execute(
            "SELECT plan_id, chat_id, goal, status, created_at, updated_at "
            "FROM plans WHERE plan_id = ?",
            (plan_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        plan = {
            "plan_id": row[0],
            "chat_id": row[1],
            "goal": row[2],
            "status": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

        steps_cursor = await self.db.execute(
            "SELECT step_id, step_order, pillar, action, description, input_from, "
            "status, result_text, error_message, started_at, completed_at "
            "FROM plan_steps WHERE plan_id = ? ORDER BY step_order",
            (plan["plan_id"],),
        )
        steps_rows = await steps_cursor.fetchall()
        plan["steps"] = [
            {
                "step_id": r[0],
                "step_order": r[1],
                "pillar": r[2],
                "action": r[3],
                "description": r[4],
                "input_from": r[5],
                "status": r[6],
                "result_text": r[7],
                "error_message": r[8],
                "started_at": r[9],
                "completed_at": r[10],
            }
            for r in steps_rows
        ]
        return plan
        deleted = cursor.rowcount
        await self.db.commit()
        if deleted > 0:
            logger.info("Cleaned up %d old plans (older than %d days)", deleted, days)
        return deleted
