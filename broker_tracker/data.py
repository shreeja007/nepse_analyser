"""broker_tracker.data

All database queries and raw aggregations for the broker tracker.

Constraints:
- Bulk fetch only (no per-broker DB loops)
- Parameterized SQL where parameters are used
- Sync pymysql connection using DictCursor (mirrors analysor/logic.py)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pymysql

from broker_tracker.config import ACTIVITY_LOOKBACK_DAYS, DB_CONFIG


def get_db_connection():
    """Return a sync pymysql connection (DictCursor)."""
    return pymysql.connect(**DB_CONFIG)


def q(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def qone(conn, sql: str, params=None):
    rows = q(conn, sql, params)
    return rows[0] if rows else {}


def get_total_transactions(conn) -> int:
    row = qone(conn, "SELECT COUNT(*) AS c FROM floorsheet_transactions")
    return int(row.get("c") or 0)


def get_broker_universe(conn) -> list[dict[str, Any]]:
    """Return all brokers observed in floorsheet transactions."""
    return q(
        conn,
        """
        SELECT 
            broker_id, broker_name,
            COUNT(*) AS total_transactions,
            MIN(trading_date) AS first_seen_date,
            MAX(trading_date) AS last_seen_date
        FROM (
            SELECT buyer_broker_id AS broker_id, buyer_broker_name AS broker_name, trading_date
            FROM floorsheet_transactions
            UNION ALL
            SELECT seller_broker_id, seller_broker_name, trading_date
            FROM floorsheet_transactions
        ) combined
        GROUP BY broker_id, broker_name
        ORDER BY total_transactions DESC
        """,
    )


def get_all_broker_activity(conn, lookback_days: int | None = ACTIVITY_LOOKBACK_DAYS) -> list[dict[str, Any]]:
    """Core bulk query: aggregated broker activity over a configurable rolling window."""
    where_clause = ""
    params = None
    if lookback_days is not None and int(lookback_days) > 0:
        where_clause = "WHERE trading_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
        params = (int(lookback_days), int(lookback_days))

    sql = f"""
        SELECT
            trading_date,
            symbol,
            security_name,
            buyer_broker_id   AS broker_id,
            buyer_broker_name AS broker_name,
            SUM(quantity) AS bought_qty,
            SUM(amount)   AS bought_value,
            0 AS sold_qty,
            0 AS sold_value,
            SUM(CASE WHEN buyer_broker_id = seller_broker_id THEN quantity ELSE 0 END) AS matching_qty
        FROM floorsheet_transactions
        {where_clause}
        GROUP BY trading_date, symbol, buyer_broker_id, buyer_broker_name

        UNION ALL

        SELECT
            trading_date,
            symbol,
            security_name,
            seller_broker_id   AS broker_id,
            seller_broker_name AS broker_name,
            0 AS bought_qty,
            0 AS bought_value,
            SUM(quantity) AS sold_qty,
            SUM(amount)   AS sold_value,
            0 AS matching_qty
        FROM floorsheet_transactions
        {where_clause}
        GROUP BY trading_date, symbol, seller_broker_id, seller_broker_name
        """
    return q(conn, sql, params)


def aggregate_broker_activity(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Aggregate raw union rows into a clean ledger per broker-symbol-session."""
    if not rows:
        cols = [
            "trading_date",
            "symbol",
            "security_name",
            "broker_id",
            "broker_name",
            "bought_qty",
            "bought_value",
            "sold_qty",
            "sold_value",
            "matching_qty",
        ]
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)

    # Ensure numeric columns are not NaN
    for c in ("bought_qty", "sold_qty", "matching_qty"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in ("bought_value", "sold_value"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)

    group_cols = ["broker_id", "broker_name", "symbol", "security_name", "trading_date"]
    df = (
        df.groupby(group_cols, dropna=False, as_index=False)[
            ["bought_qty", "bought_value", "sold_qty", "sold_value", "matching_qty"]
        ]
        .sum()
        .sort_values(["broker_id", "symbol", "trading_date"], ascending=True)
        .reset_index(drop=True)
    )

    df["net_qty"] = df["bought_qty"] - df["sold_qty"]
    df["total_qty"] = df["bought_qty"] + df["sold_qty"]

    # Asymmetry: 50 when no activity
    df["asymmetry"] = 50.0
    mask = df["total_qty"] > 0
    df.loc[mask, "asymmetry"] = (df.loc[mask, "bought_qty"] / df.loc[mask, "total_qty"]) * 100.0

    df["avg_buy_price"] = pd.NA
    buy_mask = df["bought_qty"] > 0
    df.loc[buy_mask, "avg_buy_price"] = (
        df.loc[buy_mask, "bought_value"] / df.loc[buy_mask, "bought_qty"]
    )

    df["avg_sell_price"] = pd.NA
    sell_mask = df["sold_qty"] > 0
    df.loc[sell_mask, "avg_sell_price"] = (
        df.loc[sell_mask, "sold_value"] / df.loc[sell_mask, "sold_qty"]
    )

    return df


def get_latest_prices(conn) -> dict[str, dict[str, Any]]:
    """Most recent close price per symbol with fallback to daily_prices."""
    rows_ohlcv = q(
        conn,
        """
        SELECT symbol, close_price, trading_date
        FROM daily_ohlcv
        WHERE (symbol, trading_date) IN (
            SELECT symbol, MAX(trading_date)
            FROM daily_ohlcv
            GROUP BY symbol
        )
        """,
    )

    rows_daily_prices = q(
        conn,
        """
        SELECT symbol, close_price, trading_date
        FROM daily_prices
        WHERE (symbol, trading_date) IN (
            SELECT symbol, MAX(trading_date)
            FROM daily_prices
            GROUP BY symbol
        )
        """,
    )

    fallback_map: dict[str, dict[str, Any]] = {}
    for r in rows_daily_prices:
        sym = r.get("symbol")
        if not sym:
            continue
        px = float(r.get("close_price") or 0) if r.get("close_price") is not None else None
        if px is not None and px > 0:
            fallback_map[sym] = {
                "symbol": sym,
                "close_price": px,
                "trading_date": r.get("trading_date"),
            }

    out: dict[str, dict[str, Any]] = {}
    for r in rows_ohlcv:
        sym = r.get("symbol")
        if not sym:
            continue
        px = float(r.get("close_price") or 0) if r.get("close_price") is not None else None
        if px is None or px <= 0:
            fb = fallback_map.get(sym)
            if fb:
                out[sym] = fb
            continue
        out[sym] = {
            "symbol": sym,
            "close_price": px,
            "trading_date": r.get("trading_date"),
        }

    # Symbols only present in daily_prices still get a valid current price.
    for sym, rec in fallback_map.items():
        if sym not in out:
            out[sym] = rec

    return out


def get_symbol_price_history(conn) -> dict[str, list[tuple[Any, float]]]:
    """Return merged per-symbol close-price history sorted by trading date."""
    rows = q(
        conn,
        """
        SELECT symbol, trading_date, close_price
        FROM daily_ohlcv
        WHERE close_price IS NOT NULL AND close_price > 0

        UNION ALL

        SELECT dp.symbol, dp.trading_date, dp.close_price
        FROM daily_prices dp
        LEFT JOIN daily_ohlcv do
          ON do.symbol = dp.symbol AND do.trading_date = dp.trading_date
        WHERE do.symbol IS NULL
          AND dp.close_price IS NOT NULL
          AND dp.close_price > 0
          AND dp.trading_date < CURDATE()

        ORDER BY symbol, trading_date ASC
        """,
    )

    history: dict[str, list[tuple[Any, float]]] = {}
    for r in rows:
        sym = r.get("symbol")
        dt = r.get("trading_date")
        close_price = r.get("close_price")
        if not sym or dt is None or close_price is None:
            continue
        px = float(close_price)
        if px <= 0:
            continue
        history.setdefault(str(sym), []).append((dt, px))

    return history


def get_atr_14(conn) -> dict[str, float]:
    """Fetch latest 14-session ATR using True Range with previous close."""
    rows = q(
        conn,
        """
        SELECT symbol, AVG(true_range) AS atr_14
        FROM (
            SELECT
                symbol,
                GREATEST(
                    (high_price - low_price),
                    COALESCE(
                        ABS(
                            high_price - LAG(close_price) OVER (
                                PARTITION BY symbol ORDER BY trading_date
                            )
                        ),
                        0
                    ),
                    COALESCE(
                        ABS(
                            low_price - LAG(close_price) OVER (
                                PARTITION BY symbol ORDER BY trading_date
                            )
                        ),
                        0
                    )
                ) AS true_range,
                trading_date,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trading_date DESC) AS rn
            FROM daily_ohlcv
            WHERE high_price IS NOT NULL
              AND low_price IS NOT NULL
              AND close_price IS NOT NULL
              AND high_price > 0
              AND low_price > 0
              AND close_price > 0
              AND high_price >= low_price
        ) s
        WHERE rn <= 14
        GROUP BY symbol
        """,
    )

    out: dict[str, float] = {}
    for r in rows:
        sym = r.get("symbol")
        atr = r.get("atr_14")
        if not sym or atr is None:
            continue
        try:
            val = float(atr)
        except Exception:
            continue
        if val > 0:
            out[str(sym)] = val
    return out


def get_market_index_history(conn, index_name: str = "NEPSE") -> list[tuple[Any, float]]:
    """Return sorted index value history for a benchmark index name."""
    rows = q(
        conn,
        """
        SELECT date, current_value
        FROM market_indices
        WHERE index_name = %s
          AND current_value IS NOT NULL
        ORDER BY date ASC
        """,
        (index_name,),
    )

    out: list[tuple[Any, float]] = []
    for r in rows:
        dt = r.get("date")
        val = r.get("current_value")
        if dt is None or val is None:
            continue
        px = float(val)
        if px <= 0:
            continue
        out.append((dt, px))

    return out


def get_company_sector_map(conn) -> dict[str, dict[str, Any]]:
    """Sector and company context from company_details."""
    rows = q(
        conn,
        """
        SELECT symbol, sector_name, market_capitalization, fifty_two_week_high, fifty_two_week_low
        FROM company_details
        """,
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        out[sym] = {
            "symbol": sym,
            "sector_name": r.get("sector_name"),
            "market_capitalization": r.get("market_capitalization"),
            "fifty_two_week_high": r.get("fifty_two_week_high"),
            "fifty_two_week_low": r.get("fifty_two_week_low"),
        }
    return out


def get_securities_sector_fallback(conn) -> dict[str, dict[str, Any]]:
    """Fallback sector lookup for symbols missing company_details."""
    rows = q(conn, "SELECT symbol, sector_name, instrument_type FROM securities")
    return {r.get("symbol"): r for r in rows if r.get("symbol")}


def build_sector_map(conn) -> dict[str, dict[str, Any]]:
    """Merge company_details and securities sector mapping."""
    company = get_company_sector_map(conn)
    securities = get_securities_sector_fallback(conn)

    merged: dict[str, dict[str, Any]] = {}

    all_syms = set(company) | set(securities)
    for sym in all_syms:
        cd = company.get(sym, {})
        sd = securities.get(sym, {})
        merged[sym] = {
            "symbol": sym,
            "sector_name": cd.get("sector_name") or sd.get("sector_name"),
            "market_capitalization": cd.get("market_capitalization"),
            "fifty_two_week_high": cd.get("fifty_two_week_high"),
            "fifty_two_week_low": cd.get("fifty_two_week_low"),
            "instrument_type": sd.get("instrument_type"),
        }

    return merged
