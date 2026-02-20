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
