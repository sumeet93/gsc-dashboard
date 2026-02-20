"""SQLite database layer for GSC dashboard."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Generator

from config import DATABASE_PATH, DAYS_TO_KEEP

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    permission_level TEXT DEFAULT '',
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync TEXT
);

CREATE TABLE IF NOT EXISTS keyword_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    page TEXT DEFAULT '',
    query_date TEXT NOT NULL,
    clicks INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    ctr REAL DEFAULT 0.0,
    position REAL DEFAULT 0.0,
    synced_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    UNIQUE(site_id, keyword, page, query_date)
);

CREATE TABLE IF NOT EXISTS site_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id INTEGER NOT NULL,
    query_date TEXT NOT NULL,
    total_clicks INTEGER DEFAULT 0,
    total_impressions INTEGER DEFAULT 0,
    avg_position REAL DEFAULT 0.0,
    avg_ctr REAL DEFAULT 0.0,
    keyword_count INTEGER DEFAULT 0,
    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE,
    UNIQUE(site_id, query_date)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    sites_synced INTEGER DEFAULT 0,
    total_rows INTEGER DEFAULT 0,
    errors TEXT DEFAULT '',
    status TEXT DEFAULT 'running'
);

CREATE INDEX IF NOT EXISTS idx_kw_site_date ON keyword_data(site_id, query_date);
CREATE INDEX IF NOT EXISTS idx_kw_keyword ON keyword_data(keyword);
CREATE INDEX IF NOT EXISTS idx_kw_position ON keyword_data(position);
CREATE INDEX IF NOT EXISTS idx_sd_site_date ON site_daily(site_id, query_date);
"""


def init_db() -> None:
    """Create database tables if they don't exist."""
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Site operations
# ---------------------------------------------------------------------------

def upsert_site(url: str, permission_level: str = "") -> int:
    """Insert or update a site, return its id."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sites (url, permission_level)
               VALUES (?, ?)
               ON CONFLICT(url) DO UPDATE SET permission_level = excluded.permission_level""",
            (url, permission_level),
        )
        row = conn.execute("SELECT id FROM sites WHERE url = ?", (url,)).fetchone()
        return row["id"]


def get_all_sites() -> list[dict]:
    """Return all registered sites."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, url, permission_level, added_at, last_sync FROM sites ORDER BY url"
        ).fetchall()
        return [dict(r) for r in rows]


def update_site_last_sync(site_id: int) -> None:
    """Update last_sync timestamp for a site."""
    with get_db() as conn:
        conn.execute(
            "UPDATE sites SET last_sync = datetime('now') WHERE id = ?",
            (site_id,),
        )


# ---------------------------------------------------------------------------
# Keyword data operations
# ---------------------------------------------------------------------------

def bulk_upsert_keywords(site_id: int, rows: list[dict]) -> int:
    """Bulk insert keyword data. Returns number of rows inserted."""
    if not rows:
        return 0
    with get_db() as conn:
        conn.executemany(
            """INSERT INTO keyword_data (site_id, keyword, page, query_date, clicks, impressions, ctr, position)
               VALUES (:site_id, :keyword, :page, :query_date, :clicks, :impressions, :ctr, :position)
               ON CONFLICT(site_id, keyword, page, query_date)
               DO UPDATE SET clicks=excluded.clicks, impressions=excluded.impressions,
                             ctr=excluded.ctr, position=excluded.position,
                             synced_at=datetime('now')""",
            [
                {
                    "site_id": site_id,
                    "keyword": r.get("keyword", ""),
                    "page": r.get("page", ""),
                    "query_date": r.get("date", ""),
                    "clicks": r.get("clicks", 0),
                    "impressions": r.get("impressions", 0),
                    "ctr": r.get("ctr", 0.0),
                    "position": r.get("position", 0.0),
                }
                for r in rows
            ],
        )
        return len(rows)


def update_site_daily_aggregates(site_id: int) -> None:
    """Recompute daily aggregates for a site from keyword_data."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO site_daily (site_id, query_date, total_clicks, total_impressions, avg_position, avg_ctr, keyword_count)
               SELECT site_id, query_date,
                      SUM(clicks), SUM(impressions),
                      CASE WHEN SUM(impressions) > 0
                           THEN SUM(position * impressions) / SUM(impressions)
                           ELSE 0 END,
                      CASE WHEN SUM(impressions) > 0
                           THEN CAST(SUM(clicks) AS REAL) / SUM(impressions)
                           ELSE 0 END,
                      COUNT(DISTINCT keyword)
               FROM keyword_data
               WHERE site_id = ?
               GROUP BY site_id, query_date""",
            (site_id,),
        )


# ---------------------------------------------------------------------------
# Dashboard queries
# ---------------------------------------------------------------------------

def get_overview(days: int = 28) -> list[dict]:
    """Get overview stats for all sites over the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.url, s.last_sync,
                      COALESCE(SUM(sd.total_clicks), 0) AS clicks,
                      COALESCE(SUM(sd.total_impressions), 0) AS impressions,
                      CASE WHEN SUM(sd.total_impressions) > 0
                           THEN CAST(SUM(sd.total_clicks) AS REAL) / SUM(sd.total_impressions)
                           ELSE 0 END AS ctr,
                      CASE WHEN SUM(sd.total_impressions) > 0
                           THEN SUM(sd.avg_position * sd.total_impressions) / SUM(sd.total_impressions)
                           ELSE 0 END AS avg_position,
                      COALESCE(MAX(sd.keyword_count), 0) AS keyword_count
               FROM sites s
               LEFT JOIN site_daily sd ON s.id = sd.site_id AND sd.query_date >= ?
               GROUP BY s.id
               ORDER BY clicks DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_opportunities(min_position: float = 8.0, max_position: float = 20.0, days: int = 28, limit: int = 200) -> list[dict]:
    """Keywords ranking between position 8-20 (close to page 1)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.url AS site_url, kd.keyword, kd.page,
                      SUM(kd.clicks) AS clicks,
                      SUM(kd.impressions) AS impressions,
                      CASE WHEN SUM(kd.impressions) > 0
                           THEN SUM(kd.position * kd.impressions) / SUM(kd.impressions)
                           ELSE 0 END AS avg_position,
                      CASE WHEN SUM(kd.impressions) > 0
                           THEN CAST(SUM(kd.clicks) AS REAL) / SUM(kd.impressions)
                           ELSE 0 END AS ctr
               FROM keyword_data kd
               JOIN sites s ON kd.site_id = s.id
               WHERE kd.query_date >= ?
               GROUP BY kd.site_id, kd.keyword
               HAVING avg_position >= ? AND avg_position <= ?
               ORDER BY impressions DESC
               LIMIT ?""",
            (cutoff, min_position, max_position, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_movers(days: int = 7, limit: int = 100) -> dict[str, list[dict]]:
    """Keywords with biggest position changes this week vs previous week."""
    today = date.today()
    this_week_start = (today - timedelta(days=days)).isoformat()
    prev_week_start = (today - timedelta(days=days * 2)).isoformat()
    prev_week_end = this_week_start

    with get_db() as conn:
        rows = conn.execute(
            """WITH this_week AS (
                 SELECT site_id, keyword,
                        CASE WHEN SUM(impressions) > 0
                             THEN SUM(position * impressions) / SUM(impressions)
                             ELSE 0 END AS avg_pos,
                        SUM(clicks) AS clicks,
                        SUM(impressions) AS impressions
                 FROM keyword_data
                 WHERE query_date >= ?
                 GROUP BY site_id, keyword
               ),
               prev_week AS (
                 SELECT site_id, keyword,
                        CASE WHEN SUM(impressions) > 0
                             THEN SUM(position * impressions) / SUM(impressions)
                             ELSE 0 END AS avg_pos,
                        SUM(clicks) AS clicks,
                        SUM(impressions) AS impressions
                 FROM keyword_data
                 WHERE query_date >= ? AND query_date < ?
                 GROUP BY site_id, keyword
               )
               SELECT s.url AS site_url, tw.keyword,
                      tw.avg_pos AS current_pos, pw.avg_pos AS prev_pos,
                      (pw.avg_pos - tw.avg_pos) AS pos_change,
                      tw.clicks AS current_clicks, pw.clicks AS prev_clicks,
                      (tw.clicks - pw.clicks) AS click_change,
                      tw.impressions AS current_impressions
               FROM this_week tw
               JOIN prev_week pw ON tw.site_id = pw.site_id AND tw.keyword = pw.keyword
               JOIN sites s ON tw.site_id = s.id
               WHERE ABS(pw.avg_pos - tw.avg_pos) > 1
               ORDER BY pos_change DESC
               LIMIT ?""",
            (this_week_start, prev_week_start, prev_week_end, limit * 2),
        ).fetchall()

    all_rows = [dict(r) for r in rows]
    winners = [r for r in all_rows if r["pos_change"] > 0][:limit]
    losers = sorted(
        [r for r in all_rows if r["pos_change"] < 0],
        key=lambda x: x["pos_change"],
    )[:limit]
    return {"winners": winners, "losers": losers}


def get_low_ctr(days: int = 28, min_impressions: int = 100, max_ctr: float = 0.02, limit: int = 200) -> list[dict]:
    """High-impression keywords with below-average CTR."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.url AS site_url, kd.keyword, kd.page,
                      SUM(kd.clicks) AS clicks,
                      SUM(kd.impressions) AS impressions,
                      CASE WHEN SUM(kd.impressions) > 0
                           THEN CAST(SUM(kd.clicks) AS REAL) / SUM(kd.impressions)
                           ELSE 0 END AS ctr,
                      CASE WHEN SUM(kd.impressions) > 0
                           THEN SUM(kd.position * kd.impressions) / SUM(kd.impressions)
                           ELSE 0 END AS avg_position
               FROM keyword_data kd
               JOIN sites s ON kd.site_id = s.id
               WHERE kd.query_date >= ?
               GROUP BY kd.site_id, kd.keyword
               HAVING impressions >= ? AND ctr <= ?
               ORDER BY impressions DESC
               LIMIT ?""",
            (cutoff, min_impressions, max_ctr, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_site_trends(site_id: int, days: int = 90) -> list[dict]:
    """Daily click/impression trend for a single site."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT query_date, total_clicks, total_impressions, avg_position, avg_ctr, keyword_count
               FROM site_daily
               WHERE site_id = ? AND query_date >= ?
               ORDER BY query_date""",
            (site_id, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_trends(days: int = 90) -> list[dict]:
    """Aggregated daily trends across ALL sites."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT query_date,
                      SUM(total_clicks) AS total_clicks,
                      SUM(total_impressions) AS total_impressions,
                      CASE WHEN SUM(total_impressions) > 0
                           THEN SUM(avg_position * total_impressions) / SUM(total_impressions)
                           ELSE 0 END AS avg_position,
                      CASE WHEN SUM(total_impressions) > 0
                           THEN CAST(SUM(total_clicks) AS REAL) / SUM(total_impressions)
                           ELSE 0 END AS avg_ctr
               FROM site_daily
               WHERE query_date >= ?
               GROUP BY query_date
               ORDER BY query_date""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_sync_log(limit: int = 20) -> list[dict]:
    """Get recent sync history."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_sync_log() -> int:
    """Create a new sync log entry and return its id."""
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO sync_log (started_at, status) VALUES (datetime('now'), 'running')"
        )
        return cursor.lastrowid


def update_sync_log(log_id: int, sites_synced: int, total_rows: int, errors: str, status: str) -> None:
    """Update a sync log entry."""
    with get_db() as conn:
        conn.execute(
            """UPDATE sync_log
               SET completed_at = datetime('now'), sites_synced = ?, total_rows = ?,
                   errors = ?, status = ?
               WHERE id = ?""",
            (sites_synced, total_rows, errors, status, log_id),
        )


def cleanup_old_data() -> int:
    """Remove keyword data older than DAYS_TO_KEEP. Returns rows deleted."""
    cutoff = (date.today() - timedelta(days=DAYS_TO_KEEP)).isoformat()
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM keyword_data WHERE query_date < ?", (cutoff,))
        conn.execute("DELETE FROM site_daily WHERE query_date < ?", (cutoff,))
        return cursor.rowcount
