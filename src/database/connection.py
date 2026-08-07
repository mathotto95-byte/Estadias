from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.config.settings import DB_PATH, ensure_directories


class DatabaseConnectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseConfig:
    db_type: str
    database_url: str = ""
    sqlite_path: Path = DB_PATH


class DbConnection:
    def __init__(self, conn: Any, db_type: str):
        self.conn = conn
        self.db_type = db_type

    def execute(self, sql: str, params: tuple | list | None = None):
        sql = _adapt_placeholders(sql, self.db_type)
        cursor = self.conn.cursor()
        cursor.execute(sql, tuple(params or ()))
        return cursor

    def executemany(self, sql: str, seq_of_params):
        sql = _adapt_placeholders(sql, self.db_type)
        cursor = self.conn.cursor()
        cursor.executemany(sql, seq_of_params)
        return cursor

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


def _read_secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value not in [None, ""]:
            return str(value)
        database = st.secrets.get("database", {})
        if database and database.get(name):
            return str(database.get(name))
    except Exception:
        pass
    return os.getenv(name, default)


def get_database_config() -> DatabaseConfig:
    database_url = _read_secret("DATABASE_URL").strip()
    if database_url:
        return DatabaseConfig(db_type="postgres", database_url=database_url)
    return DatabaseConfig(db_type="sqlite", sqlite_path=DB_PATH)


def _adapt_placeholders(sql: str, db_type: str) -> str:
    if db_type != "postgres":
        return sql
    result = []
    index = 0
    in_single = False
    for char in sql:
        if char == "'":
            in_single = not in_single
        if char == "?" and not in_single:
            index += 1
            result.append(f"%s")
        else:
            result.append(char)
    return "".join(result)


def _connect_sqlite(path: Path) -> DbConnection:
    ensure_directories()
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma synchronous = normal")
    conn.execute("pragma busy_timeout = 30000")
    return DbConnection(conn, "sqlite")


def _connect_postgres(database_url: str) -> DbConnection:
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
    except ImportError as exc:
        raise DatabaseConnectionError("psycopg2-binary nao instalado.") from exc
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return DbConnection(conn, "postgres")


@contextmanager
def get_connection() -> Iterator[DbConnection]:
    config = get_database_config()
    conn = _connect_postgres(config.database_url) if config.db_type == "postgres" else _connect_sqlite(config.sqlite_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_sql(sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    with get_connection() as conn:
        adapted = _adapt_placeholders(sql, conn.db_type)
        return pd.read_sql_query(adapted, conn.conn, params=tuple(params or ()))


def database_status() -> dict[str, Any]:
    config = get_database_config()
    try:
        with get_connection() as conn:
            row = conn.execute("select count(*) from mod_estadias_lcte_normalizada").fetchone()
            rows = int(row[0] if row else 0)
        return {
            "connected": True,
            "db_type": config.db_type,
            "database": "Supabase/PostgreSQL" if config.db_type == "postgres" else str(config.sqlite_path),
            "rows": rows,
            "error": "",
        }
    except Exception as exc:
        return {
            "connected": False,
            "db_type": config.db_type,
            "database": "Supabase/PostgreSQL" if config.db_type == "postgres" else str(config.sqlite_path),
            "rows": 0,
            "error": str(exc),
        }
