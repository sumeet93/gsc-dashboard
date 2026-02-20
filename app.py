"""Flask web application for GSC Dashboard."""

from __future__ import annotations

import json
import logging
import os
from functools import wraps
from threading import Thread

import bcrypt
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash

from config import SECRET_KEY, DASHBOARD_PASSWORD, HOST, PORT, DEBUG, SYNC_INTERVAL_HOURS
from database import (
    init_db,
    get_overview,
    get_opportunities,
    get_movers,
    get_low_ctr,
    get_site_trends,
    get_all_trends,
    get_all_sites,
    get_sync_log,
)
from gsc_client import full_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Hash the password on startup
_password_hash = bcrypt.hashpw(DASHBOARD_PASSWORD.encode(), bcrypt.gensalt())

# Track sync state
_sync_running = False


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_required(f):
    """Decorator to require login."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if request.method == "POST":
        password = request.form.get("password", "")
        if bcrypt.checkpw(password.encode(), _password_hash):
            session["logged_in"] = True
            return redirect(url_for("overview"))
        flash("Invalid password", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    """Logout."""
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def overview():
    """Overview: all sites at a glance."""
    days = int(request.args.get("days", 28))
    data = get_overview(days)

    # Compute totals
    totals = {
        "clicks": sum(r["clicks"] for r in data),
        "impressions": sum(r["impressions"] for r in data),
        "sites": len(data),
        "ctr": 0.0,
        "avg_position": 0.0,
    }
    if totals["impressions"] > 0:
        totals["ctr"] = totals["clicks"] / totals["impressions"]
        totals["avg_position"] = sum(
            r["avg_position"] * r["impressions"] for r in data
        ) / totals["impressions"]

    return render_template("overview.html", sites=data, totals=totals, days=days)


@app.route("/opportunities")
@login_required
def opportunities():
    """Keywords ranking position 8-20."""
    min_pos = float(request.args.get("min_pos", 8))
    max_pos = float(request.args.get("max_pos", 20))
    days = int(request.args.get("days", 28))
    data = get_opportunities(min_pos, max_pos, days)
    return render_template("opportunities.html", keywords=data, min_pos=min_pos, max_pos=max_pos, days=days)


@app.route("/movers")
@login_required
def movers():
    """Biggest winners and losers this week."""
    days = int(request.args.get("days", 7))
    data = get_movers(days)
    return render_template("movers.html", winners=data["winners"], losers=data["losers"], days=days)


@app.route("/low-ctr")
@login_required
def low_ctr():
    """High-impression keywords with low CTR."""
    days = int(request.args.get("days", 28))
    min_impressions = int(request.args.get("min_imp", 100))
    max_ctr_val = float(request.args.get("max_ctr", 0.02))
    data = get_low_ctr(days, min_impressions, max_ctr_val)
    return render_template("low_ctr.html", keywords=data, days=days, min_imp=min_impressions, max_ctr=max_ctr_val)


@app.route("/trends")
@login_required
def trends():
    """Historical trends."""
    site_id = request.args.get("site_id")
    days = int(request.args.get("days", 90))

    if site_id:
        trend_data = get_site_trends(int(site_id), days)
        sites = get_all_sites()
        site_name = next((s["url"] for s in sites if s["id"] == int(site_id)), "Unknown")
    else:
        trend_data = get_all_trends(days)
        sites = get_all_sites()
        site_name = "All Sites"

    return render_template(
        "trends.html",
        trend_data=json.dumps(trend_data),
        sites=sites,
        selected_site=site_id,
        site_name=site_name,
        days=days,
    )


@app.route("/sync-log")
@login_required
def sync_log_page():
    """Sync history."""
    logs = get_sync_log()
    return render_template("sync_log.html", logs=logs)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.route("/api/sync", methods=["POST"])
@login_required
def trigger_sync():
    """Trigger a manual sync."""
    global _sync_running
    if _sync_running:
        return jsonify({"status": "already_running"}), 409

    days = int(request.json.get("days", 7)) if request.is_json else 7

    def run_sync():
        global _sync_running
        _sync_running = True
        try:
            result = full_sync(days)
            logger.info("Manual sync complete: %s", result)
        except Exception as e:
            logger.error("Manual sync failed: %s", e)
        finally:
            _sync_running = False

    thread = Thread(target=run_sync, daemon=True)
    thread.start()
    return jsonify({"status": "started", "days": days})


@app.route("/api/sync-status")
@login_required
def sync_status():
    """Check if sync is running."""
    return jsonify({"running": _sync_running})


@app.route("/api/overview")
@login_required
def api_overview():
    """API endpoint for overview data."""
    days = int(request.args.get("days", 28))
    return jsonify(get_overview(days))


# ---------------------------------------------------------------------------
# Scheduled sync
# ---------------------------------------------------------------------------

def start_scheduler():
    """Start background scheduler for periodic syncs."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: full_sync(7),
        "interval",
        hours=SYNC_INTERVAL_HOURS,
        id="gsc_sync",
        name="GSC Data Sync",
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started: syncing every %d hours", SYNC_INTERVAL_HOURS)
    return scheduler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Application factory."""
    init_db()
    return app


if __name__ == "__main__":
    init_db()
    scheduler = start_scheduler()
    try:
        app.run(host=HOST, port=PORT, debug=DEBUG)
    finally:
        scheduler.shutdown()
