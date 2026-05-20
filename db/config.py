"""
Database configuration and connection pool management.

Loads MySQL credentials from .env and provides an async connection pool
via aiomysql for use across the project.
"""

import os
from contextlib import asynccontextmanager

import aiomysql
from dotenv import load_dotenv

# Load environment variables from .env at project root
load_dotenv()

# Database configuration from environment
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "db": os.getenv("DB_DATABASE", "nepsego"),
    "user": os.getenv("DB_USERNAME", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "charset": "utf8mb4",
    "autocommit": True,
}

# Module-level pool singleton
_pool: aiomysql.Pool | None = None


async def init_pool(minsize: int = 1, maxsize: int = 10) -> aiomysql.Pool:
    """Initialize the global connection pool. Safe to call multiple times."""
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            minsize=minsize,
            maxsize=maxsize,
            **DB_CONFIG,
        )
    return _pool


async def get_pool() -> aiomysql.Pool:
    """Return the existing pool, creating it if necessary."""
    if _pool is None:
        await init_pool()
    return _pool


@asynccontextmanager
async def get_connection():
    """Yield a connection from the pool as an async context manager."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def close_pool() -> None:
    """Close the connection pool and release all connections."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
