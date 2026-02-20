"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Google Service Account
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    str(BASE_DIR / "service-account.json"),
)

# Dashboard
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-to-a-random-string")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin")

# Sync
SYNC_INTERVAL_HOURS = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))

# Database
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "gsc.db"))

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5050"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# GSC API
GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
MAX_ROWS_PER_REQUEST = 25000
DAYS_TO_KEEP = 90  # Keep 90 days of historical data
BATCH_SIZE = 5  # Concurrent property syncs (be gentle on API)
