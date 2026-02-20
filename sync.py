"""CLI tool to manually trigger a GSC data sync."""

from __future__ import annotations

import argparse
import logging
import sys

from database import init_db
from gsc_client import full_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="Sync GSC data")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to sync (default: 7, use 90 for initial sync)",
    )
    parser.add_argument(
        "--initial",
        action="store_true",
        help="Run initial sync (90 days)",
    )
    args = parser.parse_args()

    days = 90 if args.initial else args.days

    init_db()
    print(f"Starting GSC sync for {days} days...")
    result = full_sync(days)

    print(f"\n{'='*50}")
    print(f"Properties discovered: {result['properties_discovered']}")
    print(f"Sites synced: {result['sites_synced']}")
    print(f"Total rows: {result['total_rows']:,}")
    print(f"Status: {result['status']}")

    if result["errors"]:
        print(f"\nErrors ({len(result['errors'])}):")
        for err in result["errors"]:
            print(f"  - {err}")

    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
