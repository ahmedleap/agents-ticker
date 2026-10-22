# Ticker Service

**Version:** 0.4.4

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
| Market movers | `:00, :10, :20, :30, :40, :50` | Alpaca stock/crypto screeners | Database instruments, stock market hours only |
| EOD bars | `16:15 ET`, Monday-Friday | Alpaca, Frankfurter | All instruments in the database |

Each scheduled job is isolated with one active instance and coalesced missed
runs. A failure in one provider does not stop the other jobs.

### Instruments

- Stocks: 466 symbols from `overlap.txt`.
- FX: all 20 directed pairs among `USD`, `CAD`, `EUR`, `JPY`, and `CNY`,
  using compact tickers such as `USDCAD` and `CADUSD`.
- Crypto: configured base symbols such as `BTC`, `ETH`, `SOL`, `XRP`, `USDT`,
  `USDC`; Alpaca requests them as pairs such as `BTC/USD`.

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
CRYPTO_SYMBOLS=BTC,ETH,SOL,XRP,USDT,USDC
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

The schema defines `FOREX` and `CRYPTO` directly in the `asset_class` enum.
Numbered additive migrations are maintained in `migrations/` and applied manually.

The `instruments` table keeps current prices and metadata. The
`instrument_price_history` table has a unique `(instrument_id, timestamp)`
constraint, so a cold start should normally be run against an empty history
table.

## Market Movers

The ticker service is the only component calling Alpaca. It fetches
`/v1beta1/screener/stocks/movers?top=50` and
`/v1beta1/screener/crypto/movers?top=50` when matching instruments exist, filters
to database `STOCK` and `CRYPTO` instruments, combines gainers and losers, and
persists up to five ordered by absolute percentage change. Ties are ordered by
ticker, then instrument ID. Crypto base tickers such as `BTC` match `BTC/USD`,
not other quote currencies. No instruments are created by this job.

Prices and signed percentages come from Alpaca; no opening-price fallback or
financial change calculation is performed. Forex is excluded. Because these
are filtered market-wide top-50 lists, fewer than five matches are possible,
and the result is not guaranteed to be the true top five of the tracked universe.
Stock and crypto changes retain Alpaca's respective daily reset semantics
(market open for stocks and midnight for crypto). Screener prices can differ
from the separately polled, possibly delayed bid/ask midpoint.

### Apply The Migration

Before starting the updated ticker service or calling the backend endpoint,
open `migrations/003_add_market_movers.sql` in pgAdmin's Query Tool connected
to the shared primary database and execute the entire script. It only creates
`market_movers`; it does not alter instruments, price history, or asset classes.
It can be rerun against the same table definition. No migration is executed by
application startup. If using separate roles, the ticker role needs
`SELECT`, `DELETE`, and `INSERT` on this table; the backend role needs `SELECT`.
Both also need their existing instrument-read permissions.

Deploy the ticker producer next, then the Java backend. Do not drop the table
while either application uses it. To roll back, first revert/disable the consuming
application code, then manually run `DROP TABLE IF EXISTS market_movers;` only
if the cached snapshot is no longer needed.

The producer replaces the entire latest-only table in one transaction. If a
required stock/crypto request fails or a database write fails, the previous
snapshot remains. A successful refresh with no matching valid instruments
clears it. Run one ticker scheduler instance; multiple writers are not supported.

This job uses the existing weekday 09:30-16:00 `America/New_York` guard,
including for crypto. It freezes outside that window. The guard does not
handle exchange holidays or early closes. Missed ticks are coalesced and do not
overlap; a slow request can skip a tick. Provider updates are not guaranteed
every ten seconds just because polling occurs at that interval.

### Backend Contract And Curl

For closed-market manual testing, seed five **synthetic** movers using existing
stock/crypto instruments after applying the migration:

```powershell
.\.venv\Scripts\python.exe -m app.seed_market_movers
```

This only writes `market_movers`; it does not create instruments, change prices,
or call Alpaca. Prices reuse stored positive midpoints, falling back to a demo
price of 100 when absent; percentage changes are synthetic. The script refuses
to overwrite an existing snapshot unless run with `--replace`. Do not use this
data for trading. Live scheduled polling replaces it during market hours.

Authenticated `GET http://localhost:8081/api/instruments/market-movers` reads
only the shared database in persisted rank order. Each item contains exactly
the three frontend fields: `ticker`, `price`, and `changePercent`. Percentages
are percentage points: `-2.5` means a decline of 2.5 percent. Example:

```json
{
  "marketMovers": [{"ticker": "BTC", "price": 65000.25, "changePercent": -2.5}],
  "asOf": "2026-10-22T14:00:00Z",
  "refreshedAt": "2026-10-22T14:00:05Z",
  "isStale": false
}
```

`asOf` is the oldest provider timestamp among selected items. `refreshedAt`
is the successful publication time. `isStale` is true if either is more than
60 seconds old. Closed-market snapshots remain available and become stale.
Before any results, or after a successful zero-match refresh, return HTTP 200
with `marketMovers: []`, null timestamps, and `isStale: true`. A database read
failure returns 503; unauthenticated requests return 401.

Start both services normally after applying the migration. Set `ACCESS_TOKEN`
locally to your existing login access token; do not put it in source control.
No Docker setup or additional database instance is needed for these checks.

```powershell
curl.exe -i --max-time 10 http://localhost:8081/actuator/health
curl.exe -i --max-time 10 http://localhost:8081/api/instruments/market-movers
curl.exe -i --max-time 10 http://localhost:8081/api/instruments/market-movers -H "Authorization: Bearer $env:ACCESS_TOKEN"
```

The second command should return 401. The authenticated call should return
200 after schema setup, even if the list is still empty outside market hours.
For manual frontend testing, consume this endpoint's `marketMovers` array.
The legacy backend dashboard movers query is unchanged and is a separate source.

In pgAdmin, verify publication and ordering with:

```sql
SELECT movers.rank, instruments.ticker, movers.price, movers.change_percent,
       movers.source_market, movers.source_as_of, movers.refreshed_at, movers.snapshot_id
FROM market_movers movers
JOIN instruments USING (instrument_id)
ORDER BY movers.rank;
```

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
database. The configured crypto universe excludes BNB because Alpaca did not
provide usable historical bars for it during validation.

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
