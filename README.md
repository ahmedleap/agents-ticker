# Market Data Ticker Service

Real-time market data collection and persistence service using Alpaca API and PostgreSQL.

**Version:** 0.3.5  
**Status:** Production Ready ✅  
**Coverage:** 81.88% (96 tests passing)

## Quick Start

### Prerequisites
- Python 3.12+
- PostgreSQL 14+
- Docker (optional)

### Local Development
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure .env with Alpaca credentials and DB connection
cp .env.example .env

# Test
pytest tests/ --cov=app --cov-report=term-missing

# Run
uvicorn app.main:app --reload
```

### Docker
```bash
docker-compose up
```

## Architecture

| Component | Schedule | Details |
|-----------|----------|---------|
| Quote Fetcher | Every 10s | Bid/ask prices (market hours: 9:30-16:00 ET) |
| EOD Bar Loader | 16:15 ET | Daily closing bars |
| Bootstrap | Startup | Auto-init instruments table if empty |
| Health Checks | On-demand | Service status endpoints |

## Data Model

- **Instruments**: ticker, bid, ask, mid_price, price_updated_at (timezone-aware)
- **Price History**: OHLCV bars with TIMESTAMP WITH TIME ZONE

## API

- `GET /health` - Service status
- `GET /market-data-status` - Collection status  
- `GET /ready` - Readiness probe
- `GET /quotes/{symbol}` - Latest quote
- `GET /bars/{symbol}` - Historical bars

## Testing

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

✅ 96 tests | 81.88% coverage | All passing

## Project Structure

```
app/
├── main.py              # FastAPI + lifespan
├── database.py          # PostgreSQL connection
├── models.py            # SQLAlchemy ORM
├── config.py            # Configuration
├── health.py            # Health endpoints
└── services/
    ├── alpaca_service.py
    ├── price_service.py
    ├── bars_service.py
    └── scheduler.py

tests/                  # 96 comprehensive tests
schema.sql             # Database schema
overlap.txt            # 469 stock symbols
```

## Key Features

✅ Timezone-aware timestamps  
✅ Auto-bootstrap on startup  
✅ Market hours awareness  
✅ Graceful error handling  
✅ Health monitoring  
✅ 81.88% code coverage  

## Configuration

Set in `.env`:
```
ALPACA_API_KEY=<key>
ALPACA_SECRET_KEY=<secret>
DATABASE_URL=postgresql://user:pass@host/db
LOG_LEVEL=INFO
```

## Development

```bash
# Database only
docker-compose up postgres

# Full stack
docker-compose up

# Tests
pytest tests/ -v --cov=app
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design.

## License

Proprietary - Agents of Leap
