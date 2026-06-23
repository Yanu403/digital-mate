"""Async SQLite database initialization and schema management.

Uses synchronous sqlite3 calls wrapped in coroutines.
SQLite operations on local files are fast enough that synchronous
calls don't meaningfully block the event loop.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_chat_id ON sessions(chat_id);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at ON sessions(created_at);

CREATE TABLE IF NOT EXISTS brand_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,
    industry TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
    tone TEXT NOT NULL DEFAULT '',
    products TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '',
    competitors TEXT NOT NULL DEFAULT '',
    language_pref TEXT NOT NULL DEFAULT 'bilingual',
    platform_preference TEXT NOT NULL DEFAULT '',
    budget_range TEXT NOT NULL DEFAULT '',
    business_stage TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_brand_profiles_chat_id ON brand_profiles(chat_id);

CREATE TABLE IF NOT EXISTS autocalendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    day_of_week INTEGER NOT NULL DEFAULT 0,
    hour INTEGER NOT NULL DEFAULT 9,
    last_run_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id)
);

CREATE INDEX IF NOT EXISTS idx_autocalendar_chat_id ON autocalendar(chat_id);
CREATE INDEX IF NOT EXISTS idx_autocalendar_enabled ON autocalendar(enabled);

CREATE TABLE IF NOT EXISTS autocalendar_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    week_start DATE NOT NULL,
    platform TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    hashtags TEXT NOT NULL DEFAULT '',
    notion_page_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_autocalendar_entries_chat_week
    ON autocalendar_entries(chat_id, week_start);

CREATE TABLE IF NOT EXISTS feedback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    pillar TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    user_request TEXT NOT NULL DEFAULT '',
    response_text TEXT NOT NULL DEFAULT '',
    feedback TEXT,
    regen_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feedback_log_chat_id ON feedback_log(chat_id);
CREATE INDEX IF NOT EXISTS idx_feedback_log_created_at ON feedback_log(created_at);

CREATE TABLE IF NOT EXISTS key_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    fact_text TEXT NOT NULL,
    fact_category TEXT DEFAULT 'general',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    UNIQUE(chat_id, fact_text)
);

CREATE INDEX IF NOT EXISTS idx_key_facts_chat_id ON key_facts(chat_id);
CREATE INDEX IF NOT EXISTS idx_key_facts_active ON key_facts(is_active);

CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    goal TEXT NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'completed', 'failed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    pillar TEXT NOT NULL,
    action TEXT NOT NULL,
    description TEXT NOT NULL,
    input_from TEXT DEFAULT 'user_request',
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    result_text TEXT,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id)
);

CREATE INDEX IF NOT EXISTS idx_plans_chat_id ON plans(chat_id);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);
CREATE INDEX IF NOT EXISTS idx_plan_steps_plan_id ON plan_steps(plan_id);

CREATE TABLE IF NOT EXISTS trigger_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    trigger_name TEXT NOT NULL,
    last_fired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    result_summary TEXT,
    UNIQUE(chat_id, trigger_name)
);

CREATE INDEX IF NOT EXISTS idx_trigger_log_chat_id ON trigger_log(chat_id);
"""

SCHEMA_VERSION = 7


class AsyncCursor:
    """Async-compatible cursor wrapper.

    Wraps sqlite3.Cursor with async methods that perform synchronous
    operations (fast for local SQLite).
    """

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        """Initialize with a synchronous cursor.

        Args:
            cursor: The underlying sqlite3 cursor.
        """
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        """Return the number of rows affected.

        Returns:
            Row count from the cursor.
        """
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        """Return the rowid of the last inserted row.

        Returns:
            The last insert rowid, or None if no insert has occurred.
        """
        return self._cursor.lastrowid

    async def fetchone(self) -> tuple[Any, ...] | None:
        """Fetch one result row.

        Returns:
            A tuple of values or None.
        """
        return self._cursor.fetchone()

    async def fetchall(self) -> list[tuple[Any, ...]]:
        """Fetch all result rows.

        Returns:
            List of tuples.
        """
        return self._cursor.fetchall()


class AsyncConnection:
    """Async-compatible connection wrapper around sqlite3.

    Wraps synchronous sqlite3 operations in async methods.
    SQLite local operations are fast enough that this approach
    is acceptable for this application.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with a synchronous connection.

        Args:
            conn: The underlying sqlite3 connection.
        """
        self._conn = conn

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> AsyncCursor:
        """Execute a SQL statement.

        Args:
            sql: SQL statement.
            parameters: Query parameters.

        Returns:
            AsyncCursor wrapping the result.
        """
        cursor = self._conn.execute(sql, parameters)
        return AsyncCursor(cursor)

    async def executescript(self, script: str) -> None:
        """Execute a multi-statement SQL script.

        Args:
            script: SQL script string.
        """
        self._conn.executescript(script)

    async def commit(self) -> None:
        """Commit the current transaction."""
        self._conn.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        self._conn.rollback()

    async def close(self) -> None:
        """Close the connection."""
        self._conn.close()

    @property
    def IntegrityError(self) -> type:
        """Return the IntegrityError exception class.

        Returns:
            sqlite3.IntegrityError class.
        """
        return sqlite3.IntegrityError


async def _migrate_brand_profiles(conn: AsyncConnection) -> None:
    """Run lightweight additive migrations on the brand_profiles table.

    New columns added after the initial release need ALTER TABLE for existing
    databases (CREATE TABLE IF NOT EXISTS won't add columns to an existing
    table). Each new column is added only if it doesn't already exist.

    Args:
        conn: Open AsyncConnection to the database.
    """
    # PRAGMA table_info returns one row per column: (cid, name, type, notnull, dflt_value, pk)
    cursor = await conn.execute("PRAGMA table_info(brand_profiles)")
    rows = await cursor.fetchall()
    existing_columns = {row[1] for row in rows}

    new_columns = {
        "platform_preference": "TEXT NOT NULL DEFAULT ''",
        "budget_range": "TEXT NOT NULL DEFAULT ''",
        "business_stage": "TEXT NOT NULL DEFAULT ''",
    }

    for column_name, column_def in new_columns.items():
        if column_name not in existing_columns:
            logger.info("Migrating brand_profiles: adding column %s", column_name)
            await conn.execute(
                f"ALTER TABLE brand_profiles ADD COLUMN {column_name} {column_def}"
            )
    await conn.commit()


async def init_db(db_path: str | Path = "data/digital_mate.db") -> AsyncConnection:
    """Initialize the database, creating tables if they don't exist.

    Runs schema creation plus additive migrations for existing databases.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        An open AsyncConnection.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Initializing database at %s", db_path)
    conn = sqlite3.connect(str(db_path))
    async_conn = AsyncConnection(conn)
    await async_conn.executescript(SCHEMA_SQL)
    await async_conn.commit()
    await _migrate_brand_profiles(async_conn)
    logger.info("Database initialized successfully")
    return async_conn


async def init_memory_db() -> AsyncConnection:
    """Create an in-memory database (useful for testing).

    Returns:
        An open AsyncConnection to in-memory database.
    """
    conn = sqlite3.connect(":memory:")
    async_conn = AsyncConnection(conn)
    await async_conn.executescript(SCHEMA_SQL)
    await async_conn.commit()
    await _migrate_brand_profiles(async_conn)
    return async_conn
