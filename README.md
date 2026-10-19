# Ticker Service

FastAPI service that collects current bid/ask prices and daily historical bars
for stocks, foreign exchange, and cryptocurrency instruments. Current prices
are stored on `instruments`; daily OHLCV history is stored on
`instrument_price_history` in PostgreSQL.

## Data Sources And Schedules

All schedules use wall-clock seconds in `America/New_York`.

| Job | Schedule | Source | Scope |
| --- | --- | --- | --- |
| Stock quotes | `:00, :10, :20, :30, :40, :50` | Alpaca stocks | Stock market hours, weekdays |
| FX quotes | `:03, :13, :23, :33, :43, :53` | Frankfurter v2 | Configured currencies, independent of stock hours |
| Crypto quotes | `:08, :18, :28, :38, :48, :58` | Alpaca crypto | Configured crypto pairs, independent of stock hours |
| EOD bars | `16:15 ET`, Monday-Friday | Alpaca, Frankfurter | All instruments in the database |

Each scheduled job is isolated with one active instance and coalesced missed
runs. A failure in one provider does not stop the other jobs.

### Instruments

- Stocks: 469 symbols from `overlap.txt`.
- FX: all 20 directed pairs among `USD`, `CAD`, `EUR`, `JPY`, and `CNY`,
  using compact tickers such as `USDCAD` and `CADUSD`.
- Crypto: configured base symbols such as `BTC`, `ETH`, `SOL`, `XRP`, `USDT`,
  `USDC`, and `BNB`; Alpaca requests them as pairs such as `BTC/USD`.

Frankfurter supplies reference rates rather than bid/ask quotes, so current FX
`bid` and `ask` are equal. Reverse current rates are calculated by reciprocal.
Historical FX rates become synthetic daily bars with equal OHLC values and
zero volume; weekend records are skipped.

## Requirements

- Python 3.12+
- PostgreSQL 14+
- Docker and Docker Compose for container deployment
- Alpaca API credentials for stock and crypto data

Frankfurter does not require Alpaca credentials. The service expects PostgreSQL
to be running externally; `docker-compose.yml` starts only the ticker service.

## Configuration

Create a `.env` file. Never commit it or expose API credentials.

```env
SERVICE_NAME=market-data-service
SERVICE_PORT=8000
SERVICE_HOST=0.0.0.0
LOG_LEVEL=INFO

DB_HOST=postgres
DB_PORT=5432
DB_NAME=test_db
DB_USER=test
DB_PASSWORD=test
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10

ALPACA_API_KEY=<rotated-key>
ALPACA_SECRET_KEY=<rotated-secret>
ALPACA_DATA_URL=https://data.alpaca.markets
ALPACA_FEED=delayed_sip
ALPACA_CRYPTO_FEED=

FOREX_ENABLED=true
FOREX_CURRENCIES=USD,CAD,EUR,JPY,CNY
FRANKFURTER_URL=https://api.frankfurter.dev/v2/rates
FOREX_OFFSET_SECOND=3

CRYPTO_ENABLED=true
CRYPTO_SYMBOLS=BTC,ETH,SOL,XRP,USDT,USDC,BNB
CRYPTO_OFFSET_SECOND=8
```

When PostgreSQL is a separate container on the same Docker network, use its
container name for `DB_HOST` and port `5432`. When connecting through the VM's
published port, use the VM address and the published port instead.

## Database Setup

For a new database, apply the complete schema directly:

```bash
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f schema.sql
```

The schema defines `FOREX` and `CRYPTO` directly in the `asset_class` enum;
there is no separate migration directory.

The `instruments` table keeps current prices and metadata. The
`instrument_price_history` table has a unique `(instrument_id, timestamp)`
constraint, so a cold start should normally be run against an empty history
table.

## Running Locally

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
uvicorn app.main:app --reload
```

The application runs on `http://localhost:8000` by default.

## Running With Docker

```bash
docker compose up -d --build ticker-service
docker compose logs -f ticker-service
```

The image runs as a non-root `appuser` and starts with:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For an isolated PostgreSQL container:

```bash
docker network create ticker-net 2>/dev/null || true

docker run -d \
  --name test-db \
  --restart unless-stopped \
  --network ticker-net \
  -e POSTGRES_USER=test \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=test_db \
  -p 15432:5432 \
  -v ticker-postgres-data:/var/lib/postgresql/data \
  postgres:18
```

Attach the ticker service to the same network or use the VM's published port.
Inside the shared network, configure `DB_HOST=test-db` and `DB_PORT=5432`.

## Bootstrap And Historical Bars

Startup bootstraps instruments when the table is empty. The manual bootstrap
command validates stocks through Alpaca, creates configured FX/crypto rows, and
backfills industry metadata for existing stocks:

```bash
python -m app.bootstrap_instruments
```

Stock industry values come from
`app/data/sp500_industries.csv`, using S&P 500 GICS Sub-Industry names. FX and
crypto receive `Foreign Exchange` and `Cryptocurrency` respectively.

Run the one-time 365-day historical load with:

```bash
python -m app.cold_start_bars
```

In Docker, run it from the repository root with the module form:

```bash
docker compose run --rm --no-deps ticker-service \
  python -m app.cold_start_bars
```

Stop the ticker service while performing a large cold start to avoid competing
with the quote scheduler:

```bash
docker compose stop ticker-service
docker compose run --rm --no-deps ticker-service \
  python -m app.cold_start_bars
docker compose up -d ticker-service
```

Alpaca rate limits can produce HTTP 429 failures during a 496-instrument cold
start. Those failures are partial; already inserted bars remain in the
database. BNB may also have no historical bars available through the selected
Alpaca account/feed.

## Health Endpoints

The current API exposes only these application endpoints:

```text
GET /health
GET /health/ready
GET /docs
```

`/health/ready` returns HTTP 200 only when readiness checks pass; otherwise it
returns HTTP 503.

## Tests

Run the complete suite with the repository virtual environment:

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

The tests mock external APIs and database sessions. They cover stock, FX, and
crypto quote/bar routing, scheduler offsets, persistence, bootstrap behavior,
and error handling.

## Project Structure

```text
app/
  main.py                         FastAPI app and startup lifecycle
  config.py                       Environment-backed settings
  database.py                     SQLAlchemy connection/session manager
  models.py                       Instrument and price-history models
  bootstrap_instruments.py        Stock/non-stock bootstrap and industries
  cold_start_bars.py              Manual historical-bar loader
  services/
    alpaca_service.py             Stock and crypto Alpaca API client
    forex_service.py              Frankfurter current and historical rates
    price_service.py              Quote validation and persistence
    bars_service.py               Asset-aware OHLCV loading and persistence
    scheduler.py                  APScheduler jobs
  data/
    sp500_industries.csv          Ticker-to-GICS sub-industry mapping
tests/                             Unit and integration-style tests
schema.sql                         Complete PostgreSQL schema
overlap.txt                        Stock ticker input
docker-compose.yml                 Ticker-service container definition
Dockerfile                         Production image definition
```

## Operational Notes

- Use `docker compose config` to verify interpolated environment variables.
- Use `docker exec <postgres-container> pg_isready` to verify PostgreSQL.
- Never commit `.env` or API credentials.
- A clean test reset can remove the PostgreSQL container and its named volume;
  this permanently deletes all data.
