# Market Data Service - Architecture

## Microservice Overview

This is a **standalone ticker/market data microservice** that:
- Connects to an existing PostgreSQL database via environment variables
- Fetches real-time market data from Alpaca API every 10 seconds
- Updates bid/ask/mid-price in the `instruments` table
- Provides `/health` and `/quotes` endpoints for other services

**Does NOT include:**
- Database initialization/schema management
- User authentication
- Order processing or portfolio calculations
- PostgreSQL startup

These belong in separate services.

---

## File Structure & Usage

```
ticker_service/
├── app/                       # Application source code
│   ├── __init__.py           # Package initialization
│   ├── main.py               # FastAPI application & endpoints
│   ├── config.py             # Environment config via Pydantic
│   ├── database.py           # SQLAlchemy engine & session management
│   ├── models.py             # SQLAlchemy ORM models
│   ├── health.py             # Health check service
│   └── services/
│       ├── alpaca_service.py # Alpaca API client (quote fetching)
│       ├── price_service.py  # Price update & persistence logic
│       └── scheduler.py      # APScheduler background jobs
│
├── schema.sql                # PostgreSQL DDL for instruments & pricing tables
├── requirements.txt          # Python 3.12 dependencies
├── Dockerfile                # Lean Alpine-based container image
├── docker-compose.yml        # Orchestration with PostgreSQL
├── .env.test                 # Template environment variables
├── .gitignore                # Git ignore rules
└── README_LEAN.md            # Quick start guide
```

### Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI endpoints: `/health`, `/quotes?symbols=AAPL,MSFT` |
| `app/services/alpaca_service.py` | HTTP wrapper for Alpaca v2 API (uses header auth) |
| `app/services/price_service.py` | Fetches quotes, upserts to `instruments` table |
| `app/services/scheduler.py` | APScheduler job to poll prices every 10 seconds |
| `schema.sql` | Creates `instruments` table with bid/ask/mid_price columns |
| `Dockerfile` | Multi-stage build, Python 3.12-slim base image |
| `docker-compose.yml` | Starts PostgreSQL 18 + ticker service containers |

---

## Database Schema Changes

### Updated `instruments` Table

```sql
CREATE TABLE instruments (
    instrument_id   UUID PRIMARY KEY,
    ticker          VARCHAR(10) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    asset_class     asset_class NOT NULL,
    industry        VARCHAR(100),
    bid              NUMERIC(18,4) CHECK (bid > 0),
    ask              NUMERIC(18,4) CHECK (ask > 0),
    mid_price        NUMERIC(18,4) GENERATED ALWAYS AS ((bid + ask) / 2) STORED,
    price_updated_at TIMESTAMP
);
```

**Key Columns:**
- `bid` - Highest buy price from Alpaca
- `ask` - Lowest sell price from Alpaca
- `mid_price` - **Computed column** = (bid + ask) / 2 (automatically calculated, no manual updates needed)
- `price_updated_at` - Timestamp of last Alpaca API refresh

### Removed Tables & Indexes

**Why `instrument_prices` was deleted:**
- Used as a time-series archive (every 15 minutes)
- Not needed for a real-time pricing microservice
- Kept schema lean and focused on current quotes only
- If historical pricing is needed, it belongs in a separate **Data Warehouse** microservice

**Removed Indexes:**
- ✗ `idx_instrument_prices_instrument_as_of` — Table was removed
- ✗ `idx_orders_instrument` — Foreign key index already maintained by PostgreSQL
- ✗ `idx_holdings_instrument` — Foreign key index already maintained by PostgreSQL

**Why These Were Removed:**
1. **Foreign key indexes are implicit** - PostgreSQL automatically indexes FK columns for referential integrity checks
2. **This service doesn't do order/holding lookups** - It only updates the `instruments` table; other microservices query it
3. **Reduced storage & faster writes** - Every INSERT to `orders` or `holdings` also updates implicit indexes; one less index = faster DML

**Remaining Indexes:**
```sql
CREATE INDEX idx_accounts_client ON accounts (client_id);
CREATE INDEX idx_orders_account ON orders (account_id);
CREATE INDEX idx_orders_account_status ON orders (account_id, status);  -- Composite for reserved-funds check
CREATE INDEX idx_orders_status ON orders (status);                       -- For EOD order matching
CREATE INDEX idx_transactions_account_created ON transactions (account_id, created_at);
CREATE INDEX idx_instruments_ticker ON instruments (ticker);            -- For quick symbol lookup
CREATE INDEX idx_instruments_price_updated_at ON instruments (price_updated_at DESC);  -- For "stale pricing" detection
```

---

## API Endpoints

### Health Check
```
GET /health
```
**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "alpaca_api": "accessible",
  "scheduler": "running",
  "last_price_update": "2026-09-22T15:30:45.123Z"
}
```

### Get Quotes
```
GET /quotes?symbols=AAPL,MSFT,GOOGL
```
**Response:**
```json
{
  "AAPL": {
    "bid": 342.19,
    "ask": 342.75,
    "mid_price": 342.47,
    "updated_at": "2026-09-22T15:30:42.000Z"
  },
  "MSFT": { ... }
}
```

---

## Deployment

### Docker Build
```bash
docker build -t ticker-service:latest .
```

### Docker Compose
```bash
docker-compose up -d
```

This starts:
- **PostgreSQL 18** on port 5432
- **ticker-service** on port 8000

### Environment Variables
Create `.env`:
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
DB_HOST=postgres  # Docker service name, or IP for external DB
DB_PORT=5432
DB_NAME=test_db
DB_USER=test
DB_PASSWORD=test
```

---

## Integration with Other Microservices

Example: **Portfolio Service** querying bid/ask for valuation:

```python
# In a different microservice
import requests

response = requests.get("http://ticker-service:8000/quotes", 
                       params={"symbols": "AAPL,MSFT"})
quotes = response.json()

aapl_mid = quotes["AAPL"]["mid_price"]  # Use computed mid_price
# Calculate portfolio value...
```

---

## Why This Design?

| Feature | Benefit |
|---------|---------|
| Lean schema | Single `instruments` table; no archive tables |
| Computed `mid_price` | Always accurate, no logic in application code |
| Removed FK indexes | Faster inserts to `orders`/`holdings` tables |
| Separate containers | Independent scaling, deployment, monitoring |
| Stateless service | Easy to replicate for high availability |

---

## Monitoring

**Check service logs:**
```bash
docker-compose logs ticker-service -f
```

**Check database:**
```bash
psql -h localhost -U test test_db
SELECT ticker, bid, ask, mid_price, price_updated_at FROM instruments LIMIT 5;
```

**Verify scheduler is working:**
```bash
curl http://localhost:8000/health
# Look for "scheduler": "running" and recent price_updated_at
```
