"""Thin database helpers, so exactly one module knows how to reach Postgres."""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from . import config

log = logging.getLogger(__name__)


def connect() -> psycopg.Connection:
    """Open a connection with autocommit OFF.
    """
    return psycopg.connect(config.DATABASE_URL, autocommit=False)


def run_sql_file(conn: psycopg.Connection, filename: str) -> None:
    """Execute a .sql file from the sql/ directory."""
    path = Path(config.SQL_DIR) / filename
    sql = path.read_text(encoding="utf-8")
    log.info("running %s", path.name)
    with conn.cursor() as cur:
        cur.execute(sql)


def scalar(conn: psycopg.Connection, sql: str):
    """Run a query that returns one value"""
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return row[0] if row else None
