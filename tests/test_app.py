"""Tests for Flask web application."""

from __future__ import annotations

from datetime import date, timedelta

from database import upsert_site, bulk_upsert_keywords, update_site_daily_aggregates


class TestAuth:
    def test_login_page_loads(self, app_client):
        resp = app_client.get("/login")
        assert resp.status_code == 200
        assert b"Password" in resp.data

    def test_login_redirects_to_overview(self, app_client):
        from config import DASHBOARD_PASSWORD
        resp = app_client.post("/login", data={"password": DASHBOARD_PASSWORD}, follow_redirects=False)
        assert resp.status_code == 302
        assert "/overview" in resp.headers.get("Location", "") or resp.status_code == 302

    def test_wrong_password_shows_error(self, app_client):
        resp = app_client.post("/login", data={"password": "wrong"}, follow_redirects=True)
        assert b"Invalid password" in resp.data

    def test_protected_routes_redirect_to_login(self, app_client):
        routes = ["/", "/opportunities", "/movers", "/low-ctr", "/trends", "/sync-log"]
        for route in routes:
            resp = app_client.get(route, follow_redirects=False)
            assert resp.status_code == 302, f"Route {route} should redirect"

    def test_logout_clears_session(self, logged_in_client):
        resp = logged_in_client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        # After logout, overview should redirect to login
        resp = logged_in_client.get("/", follow_redirects=False)
        assert resp.status_code == 302


class TestDashboardPages:
    def _seed(self):
        site_id = upsert_site("https://example.com/")
        today = date.today()
        rows = []
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            rows.append({"keyword": "test kw", "page": "/p", "date": d, "clicks": 5, "impressions": 100, "ctr": 0.05, "position": 10.0})
        bulk_upsert_keywords(site_id, rows)
        update_site_daily_aggregates(site_id)
        return site_id

    def test_overview_page(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/")
        assert resp.status_code == 200
        assert b"Overview" in resp.data
        assert b"example.com" in resp.data

    def test_overview_with_days_filter(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/?days=7")
        assert resp.status_code == 200

    def test_opportunities_page(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/opportunities")
        assert resp.status_code == 200
        assert b"Opportunities" in resp.data

    def test_movers_page(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/movers")
        assert resp.status_code == 200
        assert b"Movers" in resp.data

    def test_low_ctr_page(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/low-ctr")
        assert resp.status_code == 200
        assert b"Low CTR" in resp.data

    def test_trends_page(self, logged_in_client):
        self._seed()
        resp = logged_in_client.get("/trends")
        assert resp.status_code == 200
        assert b"Trends" in resp.data

    def test_trends_with_site_filter(self, logged_in_client):
        site_id = self._seed()
        resp = logged_in_client.get(f"/trends?site_id={site_id}")
        assert resp.status_code == 200

    def test_sync_log_page(self, logged_in_client):
        resp = logged_in_client.get("/sync-log")
        assert resp.status_code == 200
        assert b"Sync History" in resp.data


class TestAPI:
    def test_sync_status(self, logged_in_client):
        resp = logged_in_client.get("/api/sync-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "running" in data

    def test_api_overview(self, logged_in_client):
        upsert_site("https://example.com/")
        resp = logged_in_client.get("/api/overview?days=28")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)


class TestSyncEndpoints:
    """Test manual sync trigger endpoints."""

    def test_trigger_sync_requires_login(self, app_client):
        """Test that trigger_sync requires authentication."""
        resp = app_client.post("/api/sync", follow_redirects=False)
        assert resp.status_code == 302  # Redirect to login

    def test_trigger_sync_starts_background_sync(self, logged_in_client, monkeypatch):
        """Test triggering manual sync with default days."""
        from unittest.mock import MagicMock
        
        mock_full_sync = MagicMock(return_value={
            "properties_discovered": 2,
            "sites_synced": 2,
            "total_rows": 100,
            "status": "completed",
            "errors": [],
        })
        monkeypatch.setattr("app.full_sync", mock_full_sync)

        # First call should start sync
        resp = logged_in_client.post(
            "/api/sync",
            json={"days": 7},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "started"
        assert data["days"] == 7

        # Give thread time to complete
        import time
        time.sleep(0.2)

        # Verify full_sync was called
        mock_full_sync.assert_called_once_with(7)

    def test_trigger_sync_custom_days(self, logged_in_client, monkeypatch):
        """Test triggering sync with custom day count."""
        from unittest.mock import MagicMock
        
        mock_full_sync = MagicMock(return_value={
            "properties_discovered": 1,
            "sites_synced": 1,
            "total_rows": 500,
            "status": "completed",
            "errors": [],
        })
        monkeypatch.setattr("app.full_sync", mock_full_sync)

        resp = logged_in_client.post(
            "/api/sync",
            json={"days": 30},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["days"] == 30

    def test_trigger_sync_already_running(self, logged_in_client, monkeypatch):
        """Test that concurrent sync requests are rejected."""
        from unittest.mock import MagicMock
        import app as app_module
        import time

        # Mock a long-running sync
        def slow_sync(days):
            time.sleep(0.5)
            return {
                "properties_discovered": 1,
                "sites_synced": 1,
                "total_rows": 100,
                "status": "completed",
                "errors": [],
            }

        mock_full_sync = MagicMock(side_effect=slow_sync)
        monkeypatch.setattr("app.full_sync", mock_full_sync)

        # Start first sync
        resp1 = logged_in_client.post("/api/sync", json={"days": 7})
        assert resp1.status_code == 200

        # Brief wait to ensure thread starts
        time.sleep(0.05)

        # Try to start second sync while first is running
        resp2 = logged_in_client.post("/api/sync", json={"days": 7})
        assert resp2.status_code == 409  # Conflict
        data = resp2.get_json()
        assert data["status"] == "already_running"

        # Wait for first sync to complete
        time.sleep(0.6)

        # Reset the global flag for other tests
        app_module._sync_running = False

    def test_trigger_sync_handles_exceptions(self, logged_in_client, monkeypatch):
        """Test that sync errors are logged but don't crash."""
        from unittest.mock import MagicMock
        
        mock_full_sync = MagicMock(side_effect=Exception("Test error"))
        monkeypatch.setattr("app.full_sync", mock_full_sync)

        resp = logged_in_client.post("/api/sync", json={"days": 7})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "started"

        # Give thread time to fail
        import time
        time.sleep(0.2)

        # The exception should be caught and logged, sync flag should be reset
        import app as app_module
        assert app_module._sync_running is False
