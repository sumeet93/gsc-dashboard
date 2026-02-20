"""Tests for database operations."""

from __future__ import annotations

from datetime import date, timedelta

from database import (
    upsert_site,
    get_all_sites,
    bulk_upsert_keywords,
    update_site_daily_aggregates,
    get_overview,
    get_opportunities,
    get_movers,
    get_low_ctr,
    get_site_trends,
    get_all_trends,
    create_sync_log,
    update_sync_log,
    get_sync_log,
    cleanup_old_data,
)


class TestSiteOperations:
    def test_upsert_site_creates_new(self):
        site_id = upsert_site("https://example.com/", "siteFullUser")
        assert site_id > 0
        sites = get_all_sites()
        assert len(sites) == 1
        assert sites[0]["url"] == "https://example.com/"

    def test_upsert_site_updates_existing(self):
        id1 = upsert_site("https://example.com/", "siteOwner")
        id2 = upsert_site("https://example.com/", "siteFullUser")
        assert id1 == id2
        sites = get_all_sites()
        assert len(sites) == 1
        assert sites[0]["permission_level"] == "siteFullUser"

    def test_multiple_sites(self):
        upsert_site("https://a.com/")
        upsert_site("https://b.com/")
        upsert_site("https://c.com/")
        sites = get_all_sites()
        assert len(sites) == 3


class TestKeywordOperations:
    def test_bulk_upsert_keywords(self):
        site_id = upsert_site("https://example.com/")
        today = date.today().isoformat()
        rows = [
            {"keyword": "test keyword", "page": "/page1", "date": today, "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
            {"keyword": "another keyword", "page": "/page2", "date": today, "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 12.0},
        ]
        count = bulk_upsert_keywords(site_id, rows)
        assert count == 2

    def test_bulk_upsert_updates_existing(self):
        site_id = upsert_site("https://example.com/")
        today = date.today().isoformat()
        rows = [{"keyword": "test", "page": "/p", "date": today, "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0}]
        bulk_upsert_keywords(site_id, rows)

        # Update with new data
        rows[0]["clicks"] = 20
        bulk_upsert_keywords(site_id, rows)

        # Should still be 1 row, updated
        from database import get_db
        with get_db() as conn:
            row = conn.execute("SELECT clicks FROM keyword_data WHERE keyword = 'test'").fetchone()
            assert row["clicks"] == 20

    def test_bulk_upsert_empty_list(self):
        site_id = upsert_site("https://example.com/")
        count = bulk_upsert_keywords(site_id, [])
        assert count == 0

    def test_update_site_daily_aggregates(self):
        site_id = upsert_site("https://example.com/")
        today = date.today().isoformat()
        rows = [
            {"keyword": "kw1", "page": "/p1", "date": today, "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
            {"keyword": "kw2", "page": "/p2", "date": today, "clicks": 20, "impressions": 200, "ctr": 0.1, "position": 3.0},
        ]
        bulk_upsert_keywords(site_id, rows)
        update_site_daily_aggregates(site_id)

        from database import get_db
        with get_db() as conn:
            row = conn.execute("SELECT * FROM site_daily WHERE site_id = ?", (site_id,)).fetchone()
            assert row["total_clicks"] == 30
            assert row["total_impressions"] == 300
            assert row["keyword_count"] == 2


class TestDashboardQueries:
    def _seed_data(self):
        """Seed test data for dashboard queries."""
        site_id = upsert_site("https://example.com/")
        today = date.today()
        rows = []
        for i in range(14):
            d = (today - timedelta(days=i)).isoformat()
            rows.extend([
                {"keyword": "page 1 keyword", "page": "/p1", "date": d, "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 3.0},
                {"keyword": "opportunity keyword", "page": "/p2", "date": d, "clicks": 2, "impressions": 200, "ctr": 0.01, "position": 12.5},
                {"keyword": "low ctr keyword", "page": "/p3", "date": d, "clicks": 1, "impressions": 500, "ctr": 0.002, "position": 4.0},
            ])
        bulk_upsert_keywords(site_id, rows)
        update_site_daily_aggregates(site_id)
        return site_id

    def test_get_overview(self):
        self._seed_data()
        data = get_overview(28)
        assert len(data) == 1
        assert data[0]["clicks"] > 0
        assert data[0]["impressions"] > 0

    def test_get_opportunities(self):
        self._seed_data()
        data = get_opportunities(8.0, 20.0, 28)
        # "opportunity keyword" at position 12.5 should be found
        keywords = [r["keyword"] for r in data]
        assert "opportunity keyword" in keywords
        assert "page 1 keyword" not in keywords  # position 3 is outside range

    def test_get_movers(self):
        site_id = upsert_site("https://example.com/")
        today = date.today()

        # This week: position 5
        for i in range(7):
            d = (today - timedelta(days=i)).isoformat()
            bulk_upsert_keywords(site_id, [
                {"keyword": "moving keyword", "page": "/p", "date": d, "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
            ])

        # Previous week: position 15
        for i in range(7, 14):
            d = (today - timedelta(days=i)).isoformat()
            bulk_upsert_keywords(site_id, [
                {"keyword": "moving keyword", "page": "/p", "date": d, "clicks": 2, "impressions": 50, "ctr": 0.04, "position": 15.0},
            ])

        data = get_movers(7)
        assert len(data["winners"]) > 0
        assert data["winners"][0]["keyword"] == "moving keyword"
        assert data["winners"][0]["pos_change"] > 0  # Improved (went from 15 to 5)

    def test_get_low_ctr(self):
        self._seed_data()
        data = get_low_ctr(28, min_impressions=100, max_ctr=0.005)
        keywords = [r["keyword"] for r in data]
        assert "low ctr keyword" in keywords

    def test_get_site_trends(self):
        site_id = self._seed_data()
        data = get_site_trends(site_id, 90)
        assert len(data) > 0
        assert "query_date" in data[0]
        assert "total_clicks" in data[0]

    def test_get_all_trends(self):
        self._seed_data()
        data = get_all_trends(90)
        assert len(data) > 0


class TestSyncLog:
    def test_create_and_update_sync_log(self):
        log_id = create_sync_log()
        assert log_id > 0
        update_sync_log(log_id, 10, 5000, "", "completed")
        logs = get_sync_log()
        assert len(logs) == 1
        assert logs[0]["sites_synced"] == 10
        assert logs[0]["total_rows"] == 5000
        assert logs[0]["status"] == "completed"

    def test_sync_log_with_errors(self):
        log_id = create_sync_log()
        update_sync_log(log_id, 8, 3000, "site1: access denied\nsite2: timeout", "completed_with_errors")
        logs = get_sync_log()
        assert "access denied" in logs[0]["errors"]


class TestCleanup:
    def test_cleanup_old_data(self):
        site_id = upsert_site("https://example.com/")
        old_date = (date.today() - timedelta(days=120)).isoformat()
        recent_date = date.today().isoformat()

        bulk_upsert_keywords(site_id, [
            {"keyword": "old", "page": "/p", "date": old_date, "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0},
            {"keyword": "new", "page": "/p", "date": recent_date, "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0},
        ])

        deleted = cleanup_old_data()
        assert deleted == 1  # Only old row deleted

        from database import get_db
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM keyword_data").fetchone()["c"]
            assert count == 1
