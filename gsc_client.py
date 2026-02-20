"""Google Search Console API client."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import (
    GOOGLE_APPLICATION_CREDENTIALS,
    GSC_SCOPES,
    MAX_ROWS_PER_REQUEST,
    BATCH_SIZE,
)
from database import (
    upsert_site,
    bulk_upsert_keywords,
    update_site_daily_aggregates,
    update_site_last_sync,
    create_sync_log,
    update_sync_log,
    cleanup_old_data,
)

logger = logging.getLogger(__name__)


def _build_service():
    """Build the GSC API service."""
    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_APPLICATION_CREDENTIALS,
        scopes=GSC_SCOPES,
    )
    return build("searchconsole", "v1", credentials=credentials)


def discover_properties(service=None) -> list[dict]:
    """Auto-discover all GSC properties accessible by the service account.

    Returns list of dicts with 'siteUrl' and 'permissionLevel'.
    """
    if service is None:
        service = _build_service()

    response = service.sites().list().execute()
    entries = response.get("siteEntry", [])
    logger.info("Discovered %d GSC properties", len(entries))
    return [
        {
            "siteUrl": entry["siteUrl"],
            "permissionLevel": entry.get("permissionLevel", ""),
        }
        for entry in entries
    ]


def fetch_property_data(
    service,
    site_url: str,
    start_date: date,
    end_date: date,
    dimensions: list[str] | None = None,
) -> list[dict]:
    """Fetch all keyword rows for a GSC property.

    Handles pagination automatically. Returns list of row dicts.
    """
    if dimensions is None:
        dimensions = ["query", "page"]

    all_rows: list[dict] = []
    start_row = 0

    while True:
        request_body = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "dimensions": dimensions,
            "rowLimit": MAX_ROWS_PER_REQUEST,
            "startRow": start_row,
        }

        try:
            response = service.searchanalytics().query(
                siteUrl=site_url,
                body=request_body,
            ).execute()
        except HttpError as e:
            if e.resp.status == 403:
                logger.warning("No access to %s: %s", site_url, e)
                return []
            raise

        rows = response.get("rows", [])
        if not rows:
            break

        for row in rows:
            keys = row.get("keys", [])
            all_rows.append({
                "keyword": keys[0] if len(keys) > 0 else "",
                "page": keys[1] if len(keys) > 1 else "",
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0.0),
                "position": row.get("position", 0.0),
            })

        start_row += len(rows)
        if len(rows) < MAX_ROWS_PER_REQUEST:
            break

    return all_rows


def sync_property(service, site_url: str, site_id: int, days: int = 7) -> tuple[int, str]:
    """Sync data for a single property.

    Returns (rows_synced, error_message).
    """
    end_date = date.today() - timedelta(days=2)  # GSC data has ~2-day delay
    start_date = end_date - timedelta(days=days)

    try:
        # Fetch data date by date for granularity
        total_rows = 0
        for day_offset in range(days):
            d = start_date + timedelta(days=day_offset)
            rows = fetch_property_data(service, site_url, d, d)

            if rows:
                for row in rows:
                    row["date"] = d.isoformat()
                count = bulk_upsert_keywords(site_id, rows)
                total_rows += count

        # Update aggregates
        update_site_daily_aggregates(site_id)
        update_site_last_sync(site_id)

        logger.info("Synced %s: %d rows", site_url, total_rows)
        return total_rows, ""

    except Exception as e:
        error_msg = f"{site_url}: {e}"
        logger.error("Sync failed for %s: %s", site_url, e)
        return 0, error_msg


def full_sync(days: int = 7) -> dict:
    """Full sync: discover properties, fetch data, update DB.

    Args:
        days: Number of days to sync (default 7 for incremental, use 90 for initial).

    Returns dict with sync summary.
    """
    log_id = create_sync_log()
    service = _build_service()

    # Step 1: Discover and register properties
    properties = discover_properties(service)
    site_map: dict[str, int] = {}
    for prop in properties:
        site_id = upsert_site(prop["siteUrl"], prop["permissionLevel"])
        site_map[prop["siteUrl"]] = site_id

    logger.info("Registered %d properties, starting sync for %d days", len(site_map), days)

    # Step 2: Sync each property (batched to avoid rate limits)
    total_rows = 0
    errors: list[str] = []
    synced_count = 0

    urls = list(site_map.keys())
    for i in range(0, len(urls), BATCH_SIZE):
        batch = urls[i : i + BATCH_SIZE]
        for url in batch:
            site_id = site_map[url]
            rows, error = sync_property(service, url, site_id, days)
            total_rows += rows
            if error:
                errors.append(error)
            else:
                synced_count += 1

        # Rate limit pause between batches
        if i + BATCH_SIZE < len(urls):
            time.sleep(1)

    # Step 3: Cleanup old data
    deleted = cleanup_old_data()
    if deleted:
        logger.info("Cleaned up %d old rows", deleted)

    # Step 4: Update sync log
    status = "completed" if not errors else "completed_with_errors"
    update_sync_log(log_id, synced_count, total_rows, "\n".join(errors), status)

    summary = {
        "properties_discovered": len(properties),
        "sites_synced": synced_count,
        "total_rows": total_rows,
        "errors": errors,
        "status": status,
    }
    logger.info("Sync complete: %s", summary)
    return summary
