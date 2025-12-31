# Project Structure

## Core Application Files

```
JobSniper/
├── main.py                    # Main application entry point
├── health_server.py           # Health check HTTP server
├── prometheus_exporter.py     # Prometheus metrics exporter
│
├── core/                      # Core utilities
│   ├── __init__.py
│   ├── config.py             # Configuration (Pydantic)
│   ├── database.py           # Database manager
│   ├── logger.py             # Logging setup
│   ├── cache.py              # Cache utilities
│   └── circuit_breaker.py    # Circuit breaker for OpenAI API
│
├── models/                    # Database models
│   ├── __init__.py
│   └── models.py             # SQLAlchemy models
│
├── services/                  # Business logic
│   ├── __init__.py
│   ├── fetcher.py            # Just Join IT fetcher
│   ├── foreign_fetcher.py   # International job boards
│   ├── storage.py            # Database operations
│   ├── matcher.py            # AI matching service
│   └── notification.py       # Telegram notifications
│
├── tests/                     # Test suite
│   ├── conftest.py
│   ├── test_integration.py
│   ├── test_full_workflow.py
│   └── services/             # Service tests
│
├── scripts/                   # Utility scripts
│   ├── check_offers.py
│   ├── check_settings.py
│   ├── recreate_db.py
│   ├── reset_offers.py
│   └── update_sources.py
│
└── manual_tests/             # Manual testing scripts
    ├── test_apis_python.py
    ├── test_fetcher_v2.py
    ├── test_filters.py
    └── test_match_modes.py
```

## Configuration Files

```
├── docker-compose.yml         # Full stack orchestration
├── Dockerfile                 # Application container
├── Dockerfile.exporter        # Prometheus exporter container
├── prometheus.yml             # Prometheus configuration
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
├── .gitignore                 # Git ignore rules
└── grafana_provisioning/     # Grafana auto-configuration
    ├── datasources/
    └── dashboards/
```

## Documentation

```
├── README.md                  # Main project documentation
├── PROJECT_STRUCTURE.md       # This file
└── docs/                      # Detailed documentation
    ├── README.md
    ├── QUICK_START.md
    ├── MIGRATION_GUIDE.md
    └── REDIS_SETUP.md
```

## Data Directories (Git-ignored)

```
├── data/                      # User data (CV files)
├── logs/                      # Application logs
├── db_data/                   # PostgreSQL data
├── redis_data/                # Redis data
├── prometheus_data/           # Prometheus time-series data
├── grafana_data/              # Grafana configuration data
└── archive/                   # Old documentation (not in git)
```

## Key Features by File

- **main.py**: Application orchestrator, cycle management
- **health_server.py**: Production health checks (DB, Redis, CV, circuit breaker)
- **prometheus_exporter.py**: Converts health JSON to Prometheus metrics
- **core/circuit_breaker.py**: Resilient OpenAI API calls
- **services/matcher.py**: AI-powered CV matching with caching
- **services/fetcher.py**: Multi-source job fetching
- **services/notification.py**: Telegram bot with interactive UI
