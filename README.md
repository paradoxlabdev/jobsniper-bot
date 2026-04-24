# JobSniper

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?logo=openai&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7+-DC382D?logo=redis&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)

AI-powered job-board monitor with CV matching and Telegram notifications.

JobSniper scans five job boards (Just Join IT, RemoteOK, Remotive, Arbeitnow, WeWorkRemotely), parses your CV, and uses GPT-4o-mini to score each offer 0–100%. High-scoring matches trigger a Telegram alert with the matching justification.

![JobSniper Logo](images/logo.png)

## How It Works

1. **Fetch** — scans five job boards every 5 minutes (configurable)
2. **Store** — writes all offers to PostgreSQL, deduplicated by `(company_name, title, city)` and source-specific IDs
3. **Analyze** — sends the offer + your CV to GPT-4o-mini for a structured match score and justification
4. **Score** — returns a 0–100% match based on skills, experience, and requirements
5. **Notify** — sends a Telegram alert if the score clears your threshold

Settings (threshold, sources, keywords, CV) can be changed live via the Telegram menu — no restart needed.

## Key Features

- **AI matching** — GPT-4o-mini scores each offer against the CV, with reasoning surfaced in the notification
- **Telegram control panel** — full UI for filters, CV upload, and manual scan triggers
- **Multi-source** — Just Join IT, RemoteOK, Remotive, Arbeitnow, WeWorkRemotely
- **Monitoring** — Prometheus metrics, Grafana dashboard, health-check endpoints
- **Resilience** — circuit breaker around the OpenAI API, exponential backoff with jitter on fetch retries

## Tech Stack

| Category | Technology |
|----------|------------|
| **Runtime** | Python 3.11+ with async/await |
| **Database** | PostgreSQL 14+ (SQLAlchemy 2.0 + AsyncPG) |
| **Cache** | Redis 7+ |
| **AI** | OpenAI GPT-4o-mini |
| **Notifications** | Telegram Bot API |
| **Monitoring** | Prometheus + Grafana |
| **Deployment** | Docker Compose |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key
- Telegram Bot (token + chat ID)

### Installation

```bash
# Clone repository
git clone https://github.com/paradoxlabdev/jobsniper-bot.git
cd jobsniper-bot

# Configure environment
cp .env.example .env
# Edit .env and add your API keys

# Run setup script (creates directories and sets permissions)
chmod +x setup.sh
./setup.sh

# Add your CV (optional)
cp /path/to/your/cv.pdf data/cv.pdf

# Start all services
docker-compose build && docker-compose up -d
```

### Health Check

```bash
curl http://localhost:8080/health
```

### Troubleshooting

**Problem: Permission denied errors**

If you see `PermissionError` in logs, fix directory permissions:

```bash
# Stop containers
docker-compose down

# Run setup script to fix permissions
./setup.sh

# Restart
docker-compose up -d
```

**Problem: Services restarting (Grafana/Prometheus)**

Check logs to identify the issue:

```bash
docker-compose logs grafana | tail -50
docker-compose logs prometheus | tail -50
docker-compose logs app | tail -50
```

**Problem: Port already in use**

If you get port conflicts, change ports in `docker-compose.yml` or stop conflicting containers:

```bash
# Find container using port
sudo lsof -i :5433
docker ps | grep <port>

# Stop conflicting container or change port in docker-compose.yml
```

## Telegram Control Panel

Type `/start` in Telegram to access the interactive control panel.

### Text Commands

| Command | Description |
|---------|-------------|
| `/start` | Open control panel (main menu) |
| `/help` | Show AI explanation and feature guide |
| `/stats` | View work statistics |
| `/mycv` | View your CV settings |
| `/reset` | Force full re-analysis of all offers |

### Menu Functions

| Function | Description |
|----------|-------------|
| 🚀 **SEARCH NOW** | Trigger immediate scan |
| 🛑 **STOP SEARCH** | Stop automatic scanning |
| 📊 **Statistics** | View performance metrics |
| 📂 **My CV** | View, upload, or delete CV |
| 🌐 **Sources** | Enable/disable job boards (5 sources) |
| 🌍 **Cities** | Set preferred locations |
| 🏠 **Remote** | Toggle remote-only filter |
| 🎯 **Threshold** | Adjust AI strictness (0-100) |
| 🔍 **Keywords** | Update search keywords |
| 📁 **Category IDs** | Change Just Join IT category IDs |
| ⚙️ **Match Mode** | Set keyword matching (Relaxed/Moderate/Strict) |

### Screenshots

<div align="center">
  <table>
    <tr>
      <td align="center">
        <img src="images/menu.png" alt="Telegram Menu" width="300"/>
        <p><em>Interactive Control Panel</em></p>
      </td>
      <td align="center">
        <img src="images/Statistics.png" alt="Statistics" width="300"/>
        <p><em>Performance Statistics</em></p>
      </td>
    </tr>
    <tr>
      <td align="center">
        <img src="images/Matching.png" alt="Matching" width="300"/>
        <p><em>AI Matching Results</em></p>
      </td>
      <td align="center">
        <img src="images/Threshold.jpg" alt="Threshold" width="300"/>
        <p><em>Threshold Configuration</em></p>
      </td>
    </tr>
  </table>
</div>

## Monitoring

### Health Checks

| Endpoint | Description |
|----------|-------------|
| `http://localhost:8080/health` | Main health check |
| `http://localhost:8080/health/db` | Database status |
| `http://localhost:8080/health/redis` | Redis status |
| `http://localhost:9090` | Prometheus |
| `http://localhost:3001` | Grafana (admin/admin) |

### Grafana Dashboard

<div align="center">
  <img src="images/grafana vc.png" alt="Grafana Dashboard" width="800"/>
  <p><em>Real-time monitoring with health metrics, response times, and circuit breaker status</em></p>
</div>

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | **Required** |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | **Required** |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | **Required** |
| `POSTGRES_PASSWORD` | Database password | **Required** |
| `MATCH_THRESHOLD` | Minimum score for notification | 80 |
| `OPENAI_MODEL` | OpenAI model | gpt-4o-mini |

## Security Features

- Non-root Docker user
- Resource limits on all containers
- Network isolation — DB and Redis only reachable from the Docker network
- Container-level health checks with automatic recovery
- Circuit breaker around outbound OpenAI calls

## Project Structure

```
JobSniper/
├── core/              # Config, database, logger, circuit breaker
├── models/            # SQLAlchemy 2.0 models
├── services/          # Fetcher, matcher, notification, storage
├── tests/             # Test suite
├── scripts/           # Utility scripts
├── docs/              # Documentation
├── docker-compose.yml # Full stack orchestration
└── main.py            # Main orchestrator
```

## Operational Notes

- Deep health checks cover DB, Redis, CV presence, and circuit-breaker state
- Prometheus metrics scraped by the bundled exporter, visualised via the Grafana dashboard JSON included in this repo
- The OpenAI circuit breaker trips after repeated failures and falls back to queue-only mode until it half-opens
- Docker containers run non-root with resource limits and `TimedRotatingFileHandler` log rotation
- Fetch retries use exponential backoff with jitter to avoid thundering-herd reconnects on upstream outages

## Known Limitations

- **Single instance only.** The scan loop assumes one process per database — running two in parallel would race on `mark_as_notified_if_not_sent`. Horizontal scaling would need a distributed lock or a per-worker shard.
- **AI cost scales linearly with offer volume.** No cheap-path pre-filter before the LLM call — every new offer hits the API at least once. Budget accordingly, or set `MATCH_THRESHOLD` high enough that the follow-up cost (notification render, justification) doesn't compound.
- **CV parsing is single-file and single-language.** Non-English CVs still work because GPT-4o-mini is multilingual, but structured extraction is weaker on non-tech-standard layouts.
- **Telegram as the only notification channel.** Slack / email / webhook targets are not built in; the hook is in `services/notification.py` if you want to add one.

## License

MIT

---

*Last updated: 2026*
