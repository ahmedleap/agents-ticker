# Architecture - Market Data Ticker Service

## System Design

```
┌─────────────────────────────────────────┐
│      FastAPI Application (main.py)      │
│  - Lifespan: startup & shutdown         │
│  - Health checks, quote/bar endpoints   │
└────────────────┬────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
   ┌────▼─────┐   ┌──────▼──────┐
   │ Database  │   │ Scheduler   │
   │ Manager   │   │ (APScheduler)
   └────▲─────┘   └──┬───────┬──┘
        │            │       │
        │       Job 1 │       │ Job 3
        │       (10s) │       │ (16:15 ET)
        │            │       │
   ┌────┴────────────▼─┐  ┌──▼──────────────┐
   │ Price Service     │  │ Bars Service    │
   │ - Fetch quotes    │  │ - Load EOD bars │
   │ - Persist prices  │  │ - Historical    │
   │ - Batch process   │  │   loading       │
   └────┬─────────────┘  └──┬──────────────┘
        │                   │
        └────┬──────────────┘
             │
        ┌────▼──────────────┐
        │ Alpaca Service    │
        │ (data.alpaca.com) │
        └───────────────────┘
```

## Data Flow

### Job 1: Real-Time Quote Polling (Every 10 seconds, market hours)
1. `Scheduler` triggers `_poll_market_data_threaded()`
2. `PriceService.fetch_and_persist_prices()` calls Alpaca API
3. `AlpacaService.get_latest_quotes()` fetches bid/ask prices
4. Quotes parsed and validated
5. DB session created via `DatabaseManager.session_scope()`
6. Prices persisted via `Instrument` model with updated timestamp
7. Stats tracked (total_fetches, successful_fetches, failed_fetches)

### Job 3: End-of-Day Bar Loading (16:15 ET weekdays)
1. `Scheduler` triggers `_load_eod_bar_threaded()`
2. For each instrument: `BarsService.load_eod_bar()`
3. `AlpacaService.get_bars()` fetches 1 bar (previous day)
4. `InstrumentPriceHistory` record created with Decimal precision
5. Timestamp stored as TIMESTAMP WITH TIME ZONE

## Database Schema

```sql
-- Instruments table
CREATE TABLE instruments (
  instrument_id UUID PRIMARY KEY,
  ticker VARCHAR(10) UNIQUE NOT NULL,
  bid NUMERIC(10,4),
  ask NUMERIC(10,4),
  mid_price NUMERIC(10,4) GENERATED AS (ROUND((bid + ask) / 2, 4)),
  price_updated_at TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Price history (OHLCV bars)
CREATE TABLE instrument_price_history (
  id SERIAL PRIMARY KEY,
  instrument_id UUID NOT NULL REFERENCES instruments,
  timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
  open NUMERIC(10,4),
  high NUMERIC(10,4),
  low NUMERIC(10,4),
  close NUMERIC(10,4),
  volume BIGINT,
  UNIQUE(instrument_id, timestamp)
);
```

## Service Layers

### AlpacaService
- **Purpose**: Alpaca API integration
- **Methods**:
  - `get_latest_quotes(symbols)` → Dict[symbol, {bp, ap, t}]
  - `get_bars(symbol, start, end, timeframe)` → List[{t, o, h, l, c, v}]
  - `parse_quote(ticker, quote_data)` → {bid, ask, timestamp}
  - `health_check()` → bool

### PriceService
- **Purpose**: Real-time quote collection
- **Methods**:
  - `fetch_and_persist_prices(symbols)` → {success, count, errors}
  - `persist_price(session, ticker, bid, ask, timestamp)` → bool
  - `get_status()` → {total_fetches, successful, failed, rate}
  - `get_latest_price(ticker)` → {bid, ask, timestamp}

### BarsService
- **Purpose**: Historical and EOD bar loading
- **Methods**:
  - `load_historical_bars(ticker, days=365)` → {success, bars_inserted, errors}
  - `load_eod_bar(ticker)` → {success, bar_data, errors}
  - `persist_bar(session, instrument_id, timestamp, o, h, l, c, v)` → bool

### Scheduler
- **Purpose**: Background job scheduling
- **Market Hours**: 9:30-16:00 ET, Mon-Fri
- **Jobs**:
  - Job 1: `_poll_market_data_threaded()` every 10s
  - Job 3: `_load_eod_bar_threaded()` at 16:15 ET
- **Safety**: Market hours gate prevents off-hours execution

### DatabaseManager
- **Purpose**: Connection pool and session management
- **Methods**:
  - `initialize()` → bool (creates engine, tables)
  - `get_session()` → Session
  - `session_scope()` → context manager (auto-commit/rollback)
  - `create_all_tables()`, `drop_all_tables()`, `reset_schema()`
  - `close()` → disposes engine

## Error Handling

- **API Errors**: `AlpacaMarketDataError` caught and logged, returns error dict
- **DB Errors**: Caught in session scope, automatic rollback
- **Validation**: Quote/bar data validated before persistence
- **Retry Logic**: Each batch in PriceService catches errors individually

## Configuration

| Variable | Purpose | Default |
|----------|---------|---------|
| `ALPACA_API_KEY` | Alpaca API key | Required |
| `ALPACA_SECRET_KEY` | Alpaca secret | Required |
| `DATABASE_URL` | PostgreSQL URI | Required |
| `DB_POOL_SIZE` | Connection pool size | 5 |
| `DB_MAX_OVERFLOW` | Pool overflow | 10 |
| `LOG_LEVEL` | Logging level | INFO |

## Health Checks

- `GET /health` → {status, timestamp, database, alpaca}
- `GET /market-data-status` → {status, last_update, total_instruments}
- `GET /ready` → {ready: bool, components: {database, scheduler, alpaca}}

## Deployment

### Docker
- Multi-stage build: builder → runtime
- Base image: `python:3.12-slim`
- Non-root user: `appuser` (UID 1000)
- Health check: Python urllib (no curl dependency)
- Test files excluded via `.dockerignore`

### Database
- External PostgreSQL (not in Docker image)
- Connected via `DATABASE_URL` environment variable
- Schema applied via `schema.sql`
- Bootstrap auto-runs if instruments table empty

## Testing

**Coverage: 81.88%** (96 tests, all passing)

| Module | Coverage | Notes |
|--------|----------|-------|
| health.py | 100% | Fully tested |
| models.py | 100% | Fully tested |
| config.py | 94.59% | Edge cases uncovered |
| alpaca_service.py | 85.29% | API error paths tested |
| database.py | 83.15% | Connection errors tested |
| price_service.py | 80.77% | Error handling tested |
| bars_service.py | 78.57% | Bar processing tested |
| scheduler.py | 71.43% | Job error paths tested |

**Test Categories**:
- Unit tests: Service logic isolation
- Integration tests: Database session management
- Edge case tests: Error handling, data validation
- Mocking: Alpaca API calls, DB operations

## Performance

- **Throughput**: 421 instruments every 10s (1000+ quotes/min)
- **Concurrency**: ThreadPoolExecutor with 5 workers, 100 symbol batches
- **Latency**: <5s per 100-symbol batch
- **Storage**: ~500MB/month for 421 instruments (OHLCV daily)

## Security

- ✅ Non-root Docker user
- ✅ Credentials in `.env` (not committed)
- ✅ Connection pooling prevents exhaustion
- ✅ Input validation on all API data
- ✅ No SQL injection (SQLAlchemy ORM)
- ✅ Test files excluded from Docker

## Future Improvements

- [ ] Add minute-level OHLCV data
- [ ] Implement price alert system
- [ ] Add caching layer (Redis)
- [ ] Multi-exchange support
- [ ] WebSocket real-time updates
