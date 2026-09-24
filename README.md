# Market Data Ticker Service

Real-time stock price polling and automated daily bar aggregation service built with FastAPI, SQLAlchemy, and Alpaca Markets API.

## Overview

This service maintains two concurrent jobs:
- **Job 1** (Every 10 seconds): Fetch latest bid/ask prices for 421 stocks and update database
- **Job 3** (Daily at 16:15 ET, Mon-Fri): Load previous day's OHLCV bar for each stock

Initial setup requires:
- **Job 2** (One-time manual): Load 365 days of historical data for all stocks (local only)

---

## Directory Structure

```
ticker_service/
├── app/                              # Main application package
│   ├── __init__.py
│   ├── main.py                       # FastAPI app, startup/shutdown, health endpoint
│   ├── config.py                     # Settings management (reads .env)
│   ├── database.py                   # SQLAlchemy session, connection pooling
│   ├── models.py                     # ORM models: Instrument, InstrumentPriceHistory
│   ├── health.py                     # Health check logic
│   │
│   ├── bootstrap_instruments.py      # Script: Load 469 symbols, validate with Alpaca
│   ├── cold_start_bars.py            # Script: Load 365 days of historical bars
│   │
│   └── services/                     # Business logic layer
│       ├── __init__.py
│       ├── alpaca_service.py         # Alpaca API wrapper (quotes, bars)
│       ├── price_service.py          # Job 1 implementation (real-time polling)
│       ├── bars_service.py           # Jobs 2&3 implementation (historical + daily)
│       └── scheduler.py              # APScheduler setup (Job 1 & 3 timing)
│
├── schema.sql                        # PostgreSQL schema (instruments + price_history)
├── requirements.txt                  # Python dependencies
├── Dockerfile                        # Multi-stage production build
├── docker-compose.yml                # Service orchestration
├── .env                              # ⚠️  Local credentials (NOT COMMITTED)
├── .gitignore                        # Excludes test files, credentials, images
├── README.md                         # This file
├── IMPLEMENTATION_PLAN.md            # Detailed architecture & design decisions
│
└── overlap.txt                       # 469 stock symbols to validate
```

---

## Quick Start

### 1. Local Development

**Setup (one-time):**
```bash
# Create virtual environment
python -m venv ticker_venv
source ticker_venv/bin/activate  # Windows: .\ticker_venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Create .env with local credentials
cat > .env << EOF
DB_HOST=localhost
DB_PORT=5432
DB_NAME=test_db
DB_USER=test
DB_PASSWORD=test
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_DATA_URL=https://data.alpaca.markets
POLL_INTERVAL_SECONDS=10
REQUEST_TIMEOUT_SECONDS=30
EOF

# Start local PostgreSQL and load schema
psql -U test -d test_db -f schema.sql
```

**Bootstrap data (one-time, local only):**
```bash
# Step 1: Load 469 symbols, validate against Alpaca (filters to 421 valid)
python -m app.bootstrap_instruments

# Step 2: Load 365 days of historical data for all 421 symbols (~5-10 minutes)
python -m app.cold_start_bars
```

**Run locally:**
```bash
# Start FastAPI service (Job 1 & Job 3 start automatically)
uvicorn app.main:app --reload

# In another terminal, test:
curl http://localhost:8000/health
```

---

## Database Setup

### Schema
Two tables store all data:

**`instruments`** (421 rows)
- `instrument_id` (UUID): Primary key
- `ticker` (VARCHAR): Stock symbol (AAPL, MSFT, etc.)
- `name` (VARCHAR): Company name
- `asset_class` (ENUM): 'STOCK'
- `bid` (NUMERIC): Current bid price (updated by Job 1)
- `ask` (NUMERIC): Current ask price (updated by Job 1)
- `mid_price` (NUMERIC): Generated as (bid + ask) / 2
- `price_updated_at` (TIMESTAMP): When prices were last refreshed

**`instrument_price_history`** (~106,000 rows)
- `price_history_id` (UUID): Primary key
- `instrument_id` (UUID): FK to instruments
- `timestamp` (TIMESTAMP): Date of bar (UTC)
- `open`, `high`, `low`, `close` (NUMERIC): OHLCV data
- `volume` (INTEGER): Trading volume

Index: `(instrument_id, timestamp DESC)` for efficient time-series queries

---

## Job Specifications

### Job 1: Real-Time Quote Polling (Every 10 seconds)
**Implementation:** [app/services/price_service.py](app/services/price_service.py)

**Process:**
1. Batch all 421 symbols into groups of 100
2. Use ThreadPoolExecutor (5 workers) to fetch quotes in parallel
3. For each symbol, update `bid`, `ask`, `mid_price`, `price_updated_at` in `instruments` table
4. Log: "inserted 421 prices from 5 batches"

**API:** Alpaca Quotes (`/v2/stocks/quotes/latest`)

**Duration:** ~500ms per batch × 5 batches = ~2.5 seconds

**Timing:** Configurable via `POLL_INTERVAL_SECONDS` (default: 10s)

---

### Job 2: Cold-Start Historical Data (Manual, One-Time)
**Implementation:** [app/cold_start_bars.py](app/cold_start_bars.py)

**Purpose:** Backload 365 days of historical data for all symbols

**Process:**
1. Query all 421 instruments from database
2. For each symbol:
   - Calculate date range: (now - 15 minutes) - 365 days back
   - Fetch bars from Alpaca using `/v2/stocks/bars` endpoint
   - Batch insert into `instrument_price_history`
3. Log progress per symbol, summary stats

**API:** Alpaca Bars (`/v2/stocks/bars?feed=iex`)

**Duration:** ~280 seconds (~4.7 minutes) for 421 symbols

**Result:** ~106,000 bars inserted (~252 trading days × 421 symbols)

**Run once locally:**
```bash
python -m app.cold_start_bars
```

**Note:** Requires Job 2 to complete before service can run (instruments must exist first)

---

### Job 3: Daily EOD Bar Loading (Automated, Mon-Fri at 16:15 ET)
**Implementation:** [app/services/bars_service.py](app/services/bars_service.py)

**Purpose:** Append previous trading day's OHLCV bar to history

**Process:**
1. Runs daily at 16:15 ET (20:15 UTC) on trading days (Mon-Fri)
2. For each of 421 symbols:
   - Fetch most recent bar (previous trading day)
   - Extract OHLCV + volume
   - Insert single row to `instrument_price_history`
3. Log: "Completed EOD bar loading: 421 successful, 0 failed"

**API:** Alpaca Bars (`/v2/stocks/bars?feed=iex&end_date=<yesterday>`)

**Constraint:** End date must be ≥ 15 minutes in the past (Alpaca Basic plan requirement)

**Duration:** ~2-3 seconds

**Timing:** Scheduled via APScheduler `CronTrigger(hour=16, minute=15, day_of_week="mon-fri")`

---

## Deployment

### Production (EC2 Linux VM)

**Prerequisites:**
- Docker & Docker Compose
- PostgreSQL 18 running separately (not in docker-compose)
- Network access to Alpaca API

**Steps:**

1. **Clone repository:**
   ```bash
   cd /home/ec2-user
   git clone <repo-url> agents-ticker
   cd agents-ticker
   ```

2. **Create .env with credentials:**
   ```bash
   cat > .env << EOF
   DB_HOST=10.14.136.99
   DB_PORT=5432
   DB_NAME=test_db
   DB_USER=test
   DB_PASSWORD=<password>
   ALPACA_API_KEY=<key>
   ALPACA_SECRET_KEY=<secret>
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ALPACA_DATA_URL=https://data.alpaca.markets
   POLL_INTERVAL_SECONDS=10
   EOF
   ```

3. **Load schema (one-time):**
   ```bash
   docker exec -i test_postgres psql -U test -d test_db < schema.sql
   ```

4. **Build & run:**
   ```bash
   docker-compose build
   docker-compose up -d ticker-service
   ```

5. **Verify:**
   ```bash
   docker logs -f ticker-service
   curl http://localhost:8000/health
   ```

---

## API Endpoints

### Health Check
```bash
GET /health
```
Response:
```json
{
  "status": "healthy",
  "timestamp": "2026-09-24T16:00:00.000Z"
}
```

---

## Configuration

All settings read from `.env`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DB_HOST` | localhost | PostgreSQL hostname |
| `DB_PORT` | 5432 | PostgreSQL port |
| `DB_NAME` | test_db | Database name |
| `DB_USER` | test | Database user |
| `DB_PASSWORD` | test | Database password |
| `ALPACA_API_KEY` | (required) | Paper trading API key |
| `ALPACA_SECRET_KEY` | (required) | Paper trading secret |
| `ALPACA_BASE_URL` | https://paper-api.alpaca.markets | Quote API endpoint |
| `ALPACA_DATA_URL` | https://data.alpaca.markets | Bars API endpoint |
| `POLL_INTERVAL_SECONDS` | 10 | Job 1 frequency |
| `REQUEST_TIMEOUT_SECONDS` | 30 | API timeout |
| `LOG_LEVEL` | INFO | Logging level (DEBUG/INFO/ERROR) |

---

## Monitoring

### Job 1 Logs (Every 10 seconds)
```bash
docker logs ticker-service | grep "inserted.*prices"
# 2026-09-24 16:00:00,000 - app.services.scheduler - INFO - inserted 421 prices from 5 batches
```

### Job 3 Logs (Daily at 16:15 ET)
```bash
docker logs ticker-service | grep "EOD"
# 2026-09-24 20:15:00,000 - app.services.scheduler - INFO - Completed EOD bar loading: 421 successful
```

### Database Queries
```bash
# Check latest prices
docker exec test_postgres psql -U test -d test_db -c "
  SELECT ticker, bid, ask, mid_price, price_updated_at 
  FROM instruments 
  ORDER BY price_updated_at DESC 
  LIMIT 5;
"

# Check price history
docker exec test_postgres psql -U test -d test_db -c "
  SELECT i.ticker, COUNT(*) as bars, MAX(h.timestamp) as latest_date
  FROM instrument_price_history h
  JOIN instruments i ON h.instrument_id = i.instrument_id
  GROUP BY i.ticker
  ORDER BY latest_date DESC
  LIMIT 5;
"
```

---

## Symbol Validation

**Input:** 469 symbols from [overlap.txt](overlap.txt)

**Validation Process:**
- `bootstrap_instruments.py` batches symbols and queries Alpaca Quotes API
- Only symbols with available quote data are inserted into database
- Invalid symbols logged but not fatal

**Result:** 421 valid symbols (48 rejected by Alpaca)

**To check invalid symbols:**
```bash
python -m app.test_symbols  # Generates invalid_symbols.txt (local only)
```

---

## Troubleshooting

### Service won't start
```bash
docker logs ticker-service
# Check for:
# - Database connection errors
# - Invalid Alpaca credentials (401)
# - Schema not loaded
```

### Prices not updating
- Job 1 runs every 10 seconds during service runtime
- Check logs: `docker logs ticker-service | grep "inserted"`
- Verify Alpaca API credentials in .env

### EOD bars not loading
- Job 3 only runs Mon-Fri at 16:15 ET
- Requires symbols to be bootstrapped first
- Check logs: `docker logs ticker-service | grep "EOD"`

### Database connection refused
```bash
# Verify PostgreSQL is running and accessible
docker exec test_postgres psql -U test -d test_db -c "SELECT 1;"
```

---

## Architecture Decisions

**See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for:**
- Detailed rationale for Bars API vs Quotes API for historical data
- Threading model (ThreadPoolExecutor with 5 workers)
- Scheduling strategy (APScheduler with CronTrigger)
- Schema design & indexing
- Performance benchmarks (1.8s for 365 days vs 27s for quotes)

---

## File Usage Summary

| File | Purpose | Run When |
|------|---------|----------|
| [bootstrap_instruments.py](app/bootstrap_instruments.py) | Load symbols from overlap.txt, validate against Alpaca | Once locally, before cold_start_bars |
| [cold_start_bars.py](app/cold_start_bars.py) | Load 365 days of historical data | Once locally, before deploying service |
| [main.py](app/main.py) | FastAPI service + Job 1 & 3 schedulers | Every deployment (Docker) |
| [test_symbols.py](app/test_symbols.py) | Test which of 469 symbols are valid | Local testing only (not deployed) |
| [sanity_check.py](app/sanity_check.py) | End-to-end local validation | Local testing only (not deployed) |

---

## Testing

### Local Testing
```bash
# Test symbol validation
python -m app.test_symbols

# Full sanity check (wipe, bootstrap, cold-start, verify)
python -m app.sanity_check
```

### Sample Queries
```bash
# Get latest prices for top 5 symbols
psql -U test -d test_db << EOF
SELECT ticker, bid, ask, mid_price, price_updated_at 
FROM instruments 
WHERE bid IS NOT NULL 
ORDER BY price_updated_at DESC 
LIMIT 5;
EOF

# Get 30-day price history for AAPL
psql -U test -d test_db << EOF
SELECT timestamp, open, high, low, close, volume 
FROM instrument_price_history 
WHERE instrument_id = (SELECT instrument_id FROM instruments WHERE ticker = 'AAPL')
ORDER BY timestamp DESC 
LIMIT 30;
EOF
```

---

## Production Checklist

- [ ] PostgreSQL 18 running on separate VM/container
- [ ] Database credentials in .env (not committed)
- [ ] Alpaca API credentials verified
- [ ] Docker image built and tested locally
- [ ] Schema loaded into production database
- [ ] bootstrap_instruments.py run locally
- [ ] cold_start_bars.py run locally
- [ ] Service container started with docker-compose
- [ ] Health endpoint returns "healthy"
- [ ] Job 1 logging prices every 10 seconds
- [ ] Job 3 scheduled for 16:15 ET (next trading day test)

---

## Support

For detailed implementation notes, see [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)

Issues? Check:
1. `.env` credentials (DB & Alpaca)
2. PostgreSQL connection: `psql -h $DB_HOST -U $DB_USER -d $DB_NAME`
3. Alpaca API key validity: `curl -H "APCA-API-KEY-ID: $KEY" https://paper-api.alpaca.markets/v1/account`
4. Service logs: `docker logs ticker-service`
