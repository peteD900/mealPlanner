"""
Tests that simulate VPS conditions: WAL mode, concurrent access, error handling.
These use a real file-backed DB rather than the shared in-memory fixture.
"""
import asyncio
import json
import os
import tempfile
import pytest
import aiosqlite

from mealplanner.db.database import init_db, open_db, DB_PATH
from mealplanner.bot.tools import execute_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_file_db(path: str) -> None:
    """Initialise a fresh file-backed DB at the given path."""
    original = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = path
    try:
        await init_db()
    finally:
        if original is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = original


# ---------------------------------------------------------------------------
# WAL mode
# ---------------------------------------------------------------------------

async def test_open_db_enables_wal():
    """open_db() should produce a connection running in WAL journal mode."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        os.environ["DB_PATH"] = db_path
        await _make_file_db(db_path)

        async with open_db() as db:
            async with db.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
            assert row[0] == "wal", f"Expected WAL mode, got: {row[0]}"
    finally:
        os.environ.pop("DB_PATH", None)
        os.unlink(db_path)
        for ext in ("-shm", "-wal"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


async def test_open_db_sets_busy_timeout():
    """open_db() should set a non-zero busy_timeout."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        os.environ["DB_PATH"] = db_path
        await _make_file_db(db_path)

        async with open_db() as db:
            async with db.execute("PRAGMA busy_timeout") as cursor:
                row = await cursor.fetchone()
            assert int(row[0]) > 0, f"Expected non-zero busy_timeout, got: {row[0]}"
    finally:
        os.environ.pop("DB_PATH", None)
        os.unlink(db_path)
        for ext in ("-shm", "-wal"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# Concurrent writes (simulates bot + web server hitting the same file)
# ---------------------------------------------------------------------------

async def test_concurrent_writes_both_succeed():
    """
    Two connections writing concurrently to the same file-backed DB should
    both succeed without 'database is locked' errors. This would fail
    without WAL mode + busy_timeout under concurrent load.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        os.environ["DB_PATH"] = db_path
        await _make_file_db(db_path)

        async def write_recipe(title: str) -> str:
            async with open_db() as db:
                return await execute_tool("save_recipe", {
                    "title": title,
                    "ingredients": [{"name": "a"}, {"name": "b"}],
                    "instructions": ["do it"],
                }, db)

        results = await asyncio.gather(
            write_recipe("Concurrent Recipe A"),
            write_recipe("Concurrent Recipe B"),
            write_recipe("Concurrent Recipe C"),
        )

        for r in results:
            data = json.loads(r)
            assert data["success"] is True, f"Concurrent write failed: {data}"

        # Verify all three are actually in the DB
        async with open_db() as db:
            result = await execute_tool("list_recipes", {}, db)
        data = json.loads(result)
        assert "Concurrent Recipe A" in data["message"]
        assert "Concurrent Recipe B" in data["message"]
        assert "Concurrent Recipe C" in data["message"]
    finally:
        os.environ.pop("DB_PATH", None)
        os.unlink(db_path)
        for ext in ("-shm", "-wal"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


async def test_concurrent_read_during_write():
    """
    A read on one connection should not be blocked by a write on another.
    With WAL mode, readers and writers can proceed simultaneously.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        os.environ["DB_PATH"] = db_path
        await _make_file_db(db_path)

        # Pre-populate so the reader has something to return
        async with open_db() as db:
            await execute_tool("save_recipe", {
                "title": "Existing Recipe",
                "ingredients": [{"name": "a"}],
                "instructions": ["b"],
            }, db)

        async def do_write():
            async with open_db() as db:
                return await execute_tool("save_recipe", {
                    "title": "New Recipe",
                    "ingredients": [{"name": "x"}],
                    "instructions": ["y"],
                }, db)

        async def do_read():
            async with open_db() as db:
                return await execute_tool("list_recipes", {}, db)

        write_result, read_result = await asyncio.gather(do_write(), do_read())

        assert json.loads(write_result)["success"] is True
        assert json.loads(read_result)["success"] is True
    finally:
        os.environ.pop("DB_PATH", None)
        os.unlink(db_path)
        for ext in ("-shm", "-wal"):
            try:
                os.unlink(db_path + ext)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# Error handling: broken connection
# ---------------------------------------------------------------------------

async def test_execute_tool_db_error_returns_failure(db):
    """
    If the DB raises an unexpected error, execute_tool should return
    success=False rather than propagating the exception.
    """
    await db.close()  # Force the connection into a broken state

    result = await execute_tool("save_recipe", {
        "title": "Ghost Recipe",
        "ingredients": [{"name": "nothing"}],
        "instructions": ["nowhere"],
    }, db)
    data = json.loads(result)
    assert data["success"] is False
    assert "Tool error" in data["message"]
