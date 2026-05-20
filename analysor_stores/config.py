"""
analysor_stores.config — Database configuration for the nepsego_analysis database.

Self-bootstrapping: ensure_database() auto-creates the DB and all tables
on first use using schema.sql. Zero manual setup required.
"""

import os
import pathlib

import pymysql
from dotenv import load_dotenv

load_dotenv()

# ── Connection config ──────────────────────────────────────────────────
#  Same MySQL server as nepsego, but a dedicated analysis database.
#  Override DB name via DB_ANALYSIS_DATABASE env var if needed.
# ───────────────────────────────────────────────────────────────────────

_BASE_CFG = {
    "host":     os.getenv("DB_HOST", "127.0.0.1"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USERNAME", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "charset":  "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

ANALYSIS_DB = os.getenv("DB_ANALYSIS_DATABASE", "nepsego_analysis")
SOURCE_DB   = os.getenv("DB_DATABASE", "nepsego")  # for cross-DB reads in evaluator

SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"

_bootstrapped = False


def get_conn(database: str = None):
    """Return a sync pymysql connection to the analysis database."""
    cfg = {**_BASE_CFG, "db": database or ANALYSIS_DB}
    return pymysql.connect(**cfg)


def get_source_conn():
    """Return a sync pymysql connection to the main nepsego database."""
    cfg = {**_BASE_CFG, "db": SOURCE_DB}
    return pymysql.connect(**cfg)


def ensure_database():
    """
    Create the nepsego_analysis database and all tables if they don't exist.
    Safe to call multiple times — fully idempotent (CREATE IF NOT EXISTS).
    Called once automatically on first save_*() invocation per process.
    """
    global _bootstrapped
    if _bootstrapped:
        return

    # Step 1: Connect without selecting a database and create the DB
    conn = pymysql.connect(
        host=_BASE_CFG["host"],
        port=_BASE_CFG["port"],
        user=_BASE_CFG["user"],
        password=_BASE_CFG["password"],
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW DATABASES LIKE %s", (ANALYSIS_DB,))
            db_exists = cur.fetchone() is not None

            if not db_exists:
                print(f"  📦 Creating database '{ANALYSIS_DB}'...")

            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{ANALYSIS_DB}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()

    # Step 2: Connect TO the new database and run table/view creation
    conn = pymysql.connect(
        host=_BASE_CFG["host"],
        port=_BASE_CFG["port"],
        user=_BASE_CFG["user"],
        password=_BASE_CFG["password"],
        db=ANALYSIS_DB,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        sql_text = SCHEMA_PATH.read_text(encoding="utf-8")

        # Split by semicolons, strip comments, execute each statement
        for raw_stmt in sql_text.split(";"):
            # Remove comment-only lines, keep inline content
            lines = []
            for line in raw_stmt.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith("--"):
                    lines.append(line)
            stmt = "\n".join(lines).strip()

            if not stmt:
                continue

            # Skip CREATE DATABASE / USE — we already handled that
            lower = stmt.lower()
            if lower.startswith("create database") or lower.startswith("use "):
                continue

            try:
                with conn.cursor() as cur:
                    cur.execute(stmt)
            except Exception:
                pass  # Views may fail on first create if tables aren't ready yet

        # Retry views after all tables exist
        for raw_stmt in sql_text.split(";"):
            lines = [l for l in raw_stmt.split("\n")
                     if l.strip() and not l.strip().startswith("--")]
            stmt = "\n".join(lines).strip()
            if stmt and stmt.lower().startswith("create or replace view"):
                try:
                    with conn.cursor() as cur:
                        cur.execute(stmt)
                except Exception:
                    pass

        if not db_exists:
            print(f"  ✅ Database '{ANALYSIS_DB}' created with all tables")

        _bootstrapped = True

    finally:
        conn.close()
