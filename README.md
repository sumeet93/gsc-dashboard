# GSC Dashboard

A self-hosted Google Search Console dashboard that monitors **120+ websites** and all their keywords from a single interface. No SaaS. No monthly fees. $0/month.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

| Tab | Description |
|-----|-------------|
| **Overview** | All sites at a glance — clicks, impressions, CTR, avg position |
| **Opportunities** | Keywords ranking position 8-20 (close to page 1, highest ROI) |
| **Movers** | Biggest winners & losers this week (catches problems before disasters) |
| **Low CTR** | High-impression keywords with poor CTR (title/meta optimization targets) |
| **Trends** | Historical charts per site or across all sites (Plotly interactive charts) |
| **Sync Log** | Full sync history with error tracking |

### Additional Features
- 🔐 Password-protected login (bcrypt + rate limiting)
- 🔄 Auto-sync every 6 hours via APScheduler
- 🔍 Client-side filtering on all tables
- 📊 Interactive Plotly charts (clicks, impressions, position, CTR)
- 🌙 Dark theme (GitHub-inspired)
- 📱 Mobile responsive
- ⚡ Auto-discovers new GSC properties
- 🗄️ SQLite — zero database setup

## Stack

- **Python 3.10+** + Flask
- **SQLite** (WAL mode for concurrent reads)
- **Google Search Console API** (free)
- **Plotly** for interactive charts
- **Bootstrap 5** for UI
- **APScheduler** for periodic syncs

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/sumeet93/gsc-dashboard.git
cd gsc-dashboard
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your settings
```

Key settings:
- `GOOGLE_APPLICATION_CREDENTIALS` — path to your Google service account JSON
- `DASHBOARD_PASSWORD` — login password
- `SECRET_KEY` — random string for session security

### 3. Set Up Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a service account (or use existing)
3. Enable the **Search Console API**
4. Download the JSON key file → save as `service-account.json`
5. **Add the service account email as a user** in Google Search Console for each property you want to monitor

> 💡 For bulk access, add the service account at the **organization level** in GSC if available.

### 4. Initial Sync

```bash
# Pull 90 days of historical data (takes a while for 120+ properties)
python sync.py --initial

# Or just pull last 7 days
python sync.py --days 7
```

### 5. Run

```bash
python app.py
# Open http://127.0.0.1:5050
```

For production:
```bash
gunicorn -w 2 -b 127.0.0.1:5050 "app:create_app()"
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | `service-account.json` | Path to Google SA JSON |
| `SECRET_KEY` | `change-me...` | Flask session secret |
| `DASHBOARD_PASSWORD` | `admin` | Login password |
| `SYNC_INTERVAL_HOURS` | `6` | Auto-sync interval |
| `DATABASE_PATH` | `data/gsc.db` | SQLite database path |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `5050` | Server port |
| `DEBUG` | `false` | Flask debug mode |

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────┐
│  APScheduler     │────▶│  GSC API (free)   │────▶│  SQLite DB │
│  (every 6 hours) │     │  120+ properties  │     │  (WAL)     │
└─────────────────┘     └──────────────────┘     └─────┬──────┘
                                                        │
                                                  ┌─────▼──────┐
                                                  │  Flask Web  │
                                                  │  Dashboard  │
                                                  │  :5050      │
                                                  └────────────┘
```

### Database Schema

- **sites** — Auto-discovered GSC properties
- **keyword_data** — Daily keyword-level data (query, page, clicks, impressions, CTR, position)
- **site_daily** — Pre-aggregated daily totals per site
- **sync_log** — Sync history and error tracking

Data retention: 90 days (configurable via `DAYS_TO_KEEP` in config.py)

## Scaling for 120+ Properties

- **Batch syncing**: Properties are synced in batches of 5 with rate-limiting pauses
- **WAL mode**: SQLite WAL allows concurrent reads during sync
- **Incremental syncs**: Only pulls last 7 days by default (vs 90 days for initial)
- **Daily aggregates**: Pre-computed in `site_daily` table for fast overview queries
- **Auto-cleanup**: Old data (>90 days) is automatically purged

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_database.py -v
```

## Cost

| Component | Cost |
|-----------|------|
| Development | $0 |
| GSC API | Free |
| Hosting | $0 (runs locally) |
| Database | $0 (SQLite) |
| **Monthly total** | **$0** |

vs Ahrefs ($99/mo) or SEMrush ($130/mo)

## Roadmap

- [ ] Telegram alerts for big keyword movers
- [ ] CSV/Excel export
- [ ] Keyword difficulty estimation
- [ ] Cross-site keyword cannibalization detection
- [ ] AI-powered optimization suggestions
- [ ] Docker deployment

## License

MIT
