# Market Data Service

A standalone, containerized market data service that fetches real-time bid/ask prices from Alpaca and persists them to PostgreSQL. The service is designed to operate independently from authentication, user management, trading logic, and order execution systems.

## Architecture

```
Alpaca API → Market Data Service → PostgreSQL ← Spring Backend
```

### Components

- **Alpaca API Integration**: Fetches latest quotes (bid/ask prices) every 10 seconds
- **Data Transformation**: Calculates midpoint prices from bid/ask data
- **PostgreSQL Persistence**: Stores raw bid, ask, and calculated midpoint prices
- **Health Endpoints**: Provides monitoring and status information
- **Resilience**: Continues operating even if Alpaca becomes temporarily unavailable

## Features

✅ **Periodic Market Data Polling**: Configurable interval (default: 10 seconds)  
✅ **Bid/Ask Price Storage**: Stores raw market data from Alpaca  
✅ **Midpoint Calculation**: Automatically calculates `(bid + ask) / 2`  
✅ **Error Resilience**: Failures don't crash the service or modify database  
✅ **Health Monitoring**: Comprehensive health check endpoints  
✅ **Status Reporting**: Detailed statistics on fetch success rates  
✅ **Docker Support**: Complete containerization with Docker Compose  
✅ **Environment-Driven Configuration**: All settings via environment variables  
✅ **Logging**: Comprehensive logging with timestamps and symbol counts  

## Prerequisites

- Docker and Docker Compose (for containerized deployment)
- OR Python 3.11+ (for local development)
- Alpaca API credentials (get them at https://app.alpaca.markets)
- PostgreSQL 13+ (or use the containerized version)

## Quick Start

### Using Docker Compose (Recommended)

1. **Clone the repository and navigate to the service directory:**
```bash
cd ticker_service
```

2. **Configure environment variables:**
```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your Alpaca API credentials
nano .env
```

3. **Update these required environment variables:**
```env
ALPACA_API_KEY=your_actual_alpaca_api_key
ALPACA_SECRET_KEY=your_actual_alpaca_secret_key
DB_PASSWORD=your_secure_password  # Change from default
```

4. **Start the services:**
```bash
docker-compose up -d
```

5. **Verify the service is running:**
```bash
# Check service health
curl http://localhost:8000/health

# Check market data status
curl http://localhost:8000/market-data/status
```

### Local Development Setup

1. **Create a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your settings
```

4. **Set up the database:**
```bash
# Start PostgreSQL (must be running)
# Then run migrations:
psql -h localhost -U postgres -d agents_of_leap -f migrations/001_add_bid_ask_prices.sql
```

5. **Run the service:**
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

### Health & Status

#### `GET /health`
Check overall service health.

**Response:**
```json
{
  "status": "up",
  "timestamp": "2024-01-15T14:30:00.123456",
  "database": "up",
  "alpaca": "up",
  "service_name": "market-data-service",
  "uptime_info": "service started"
}
```

**Status Values:**
- `up`: All systems operational
- `degraded`: Some systems down but service is attempting to recover
- `down`: Service cannot operate

#### `GET /health/ready`
Kubernetes readiness probe endpoint.

**Response:**
```json
{
  "ready": true,
  "database_connected": true,
  "alpaca_accessible": true
}
```

#### `GET /market-data/status`
Detailed market data service status and statistics.

**Response:**
```json
{
  "service": "market-data-service",
  "timestamp": "2024-01-15T14:30:00.123456",
  "status": "operational",
  "last_successful_fetch": "2024-01-15T14:29:50.123456",
  "last_error": null,
  "symbols_tracked": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "SPY", "QQQ"],
  "symbols_count": 7,
  "provider": "alpaca",
  "poll_interval_seconds": 10,
  "statistics": {
    "total_fetches": 42,
    "successful_fetches": 40,
    "failed_fetches": 2,
    "total_prices_inserted": 280,
    "success_rate_percent": 95.24
  }
}
```

### Market Data

#### `GET /market-data/latest/{symbol}`
Get the latest price for a specific symbol.

**Parameters:**
- `symbol` (path): Ticker symbol (e.g., `AAPL`)

**Response:**
```json
{
  "symbol": "AAPL",
  "bid": 150.25,
  "ask": 150.35,
  "midpoint": 150.30,
  "as_of": "2024-01-15T14:30:00"
}
```

### Scheduler

#### `GET /scheduler/status`
Get the status of the polling scheduler.

**Response:**
```json
{
  "is_running": true,
  "poll_interval_seconds": 10,
  "next_run": "2024-01-15T14:30:10.123456",
  "job_count": 1
}
```

### Service Information

#### `GET /`
Service information and available endpoints.

**Response:**
```json
{
  "service": "market-data-service",
  "version": "1.0.0",
  "status": "operational",
  "documentation": "/docs",
  "endpoints": {
    "health": "GET /health",
    "readiness": "GET /health/ready",
    "market_data_status": "GET /market-data/status",
    "scheduler_status": "GET /scheduler/status",
    "latest_price": "GET /market-data/latest/{symbol}"
  }
}
```

## Configuration

All configuration is managed through environment variables in the `.env` file.

### Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | localhost | PostgreSQL host |
| `DB_PORT` | 15432 | PostgreSQL port |
| `DB_NAME` | agents_of_leap | Database name |
| `DB_USER` | postgres | Database user |
| `DB_PASSWORD` | postgres | Database password |
| `DB_POOL_SIZE` | 5 | Connection pool size |
| `DB_MAX_OVERFLOW` | 10 | Maximum overflow connections |

### Alpaca Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ALPACA_API_KEY` | (required) | Alpaca API key |
| `ALPACA_SECRET_KEY` | (required) | Alpaca secret key |
| `ALPACA_BASE_URL` | https://paper-api.alpaca.markets | Alpaca API base URL |
| `ALPACA_DATA_URL` | https://data.alpaca.markets | Alpaca data API URL |

### Polling Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL_SECONDS` | 10 | How often to fetch data (seconds) |
| `REQUEST_TIMEOUT_SECONDS` | 30 | Alpaca request timeout (seconds) |
| `MAX_RETRIES` | 3 | Maximum retry attempts |
| `RETRY_BACKOFF_FACTOR` | 2.0 | Exponential backoff factor |

### Tracked Symbols

| Variable | Default | Description |
|----------|---------|-------------|
| `TRACKED_SYMBOLS` | AAPL,MSFT,GOOGL,AMZN,TSLA,SPY,QQQ | Comma-separated ticker symbols |

### Service Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` | market-data-service | Service name |
| `SERVICE_PORT` | 8000 | HTTP port |
| `SERVICE_HOST` | 0.0.0.0 | Bind address |
| `DEBUG` | false | Enable debug logging |
| `LOG_LEVEL` | INFO | Logging level |

## Database Schema

### instrument_prices Table

The service persists market data to the `instrument_prices` table:

```sql
CREATE TABLE instrument_prices (
    price_id        UUID PRIMARY KEY,
    instrument_id   UUID NOT NULL,
    bid_price       NUMERIC(18,4),         -- Raw bid price from Alpaca
    ask_price       NUMERIC(18,4),         -- Raw ask price from Alpaca
    price           NUMERIC(18,4),         -- Calculated midpoint
    as_of           TIMESTAMP NOT NULL,    -- Quote timestamp from provider
    created_at      TIMESTAMP NOT NULL,    -- When record was inserted
    data_source     VARCHAR(50),           -- Source (e.g., 'alpaca')
    FOREIGN KEY (instrument_id) REFERENCES instruments(instrument_id)
);
```

### Example Query

Get the latest prices for all tracked symbols:

```sql
SELECT 
    i.ticker,
    ip.bid_price,
    ip.ask_price,
    ip.price as midpoint,
    ip.as_of,
    ip.created_at
FROM instrument_prices ip
JOIN instruments i ON ip.instrument_id = i.instrument_id
WHERE ip.as_of IN (
    SELECT MAX(as_of) 
    FROM instrument_prices 
    GROUP BY instrument_id
)
ORDER BY i.ticker;
```

## Logging

The service provides comprehensive logging with the following events:

```
[2024-01-15 14:30:00] Market data poll triggered for 7 symbols
[2024-01-15 14:30:00] Fetching quotes for 7 symbols: AAPL,MSFT,GOOGL,AMZN,TSLA,SPY,QQQ
[2024-01-15 14:30:01] Successfully fetched 7 quotes from Alpaca
[2024-01-15 14:30:01] Successfully inserted 7 prices into database
[2024-01-15 14:30:01] Fetch completed successfully: requested=7, inserted=7
```

## Docker Deployment

### Start the Service

```bash
docker-compose up -d
```

### View Logs

```bash
# All services
docker-compose logs -f

# Market data service only
docker-compose logs -f market-data-service

# PostgreSQL only
docker-compose logs -f postgres
```

### Stop the Service

```bash
docker-compose down
```

### Rebuild Images

```bash
docker-compose build --no-cache
```

### Access the Service

- **API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **ReDoc Docs**: http://localhost:8000/redoc
- **Database**: localhost:15432 (from outside container)

## Error Handling & Resilience

### Alpaca Unavailability

If Alpaca becomes temporarily unavailable:

1. **Logging**: Error is logged with details
2. **Database**: No records are modified or deleted
3. **State**: Service continues running
4. **Retry**: Polling continues on the next scheduled cycle
5. **Status**: Error is visible in `/market-data/status` endpoint

### Database Connection Loss

If the database becomes unavailable:

1. **Connection**: Service attempts to reconnect on startup
2. **Polling**: Scheduled polling does not execute (no crash)
3. **Status**: Database status shown as "down" in health check
4. **Logging**: Connection errors are logged

### Service Recovery

The service is designed to remain alive and recover automatically:

- Connection pools are managed with configurable timeouts
- Failed requests don't crash the polling scheduler
- All errors are logged for monitoring and debugging

## Monitoring & Alerting

### Kubernetes Integration

The service includes health check endpoints suitable for Kubernetes probes:

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
```

### Metrics to Monitor

1. **Success Rate**: `statistics.success_rate_percent` from `/market-data/status`
2. **Last Successful Fetch**: `last_successful_fetch` timestamp
3. **Failed Fetches**: `statistics.failed_fetches` count
4. **Service Health**: Status from `/health` endpoint

## Testing

### Test the Service Locally

```bash
# Health check
curl http://localhost:8000/health

# Market data status
curl http://localhost:8000/market-data/status

# Get latest price for AAPL
curl http://localhost:8000/market-data/latest/AAPL

# Interactive API docs
open http://localhost:8000/docs
```

### Test Database Connection

```bash
# From inside the container
docker exec market-data-service psql -h postgres -U postgres -d agents_of_leap -c "SELECT COUNT(*) FROM instrument_prices;"

# From host machine
psql -h localhost -U postgres -d agents_of_leap -p 15432 -c "SELECT COUNT(*) FROM instrument_prices;"
```

## Troubleshooting

### Service won't start

1. **Check PostgreSQL is running**: `docker-compose logs postgres`
2. **Verify environment variables**: Check `.env` file has correct values
3. **Check port conflicts**: Ensure 8000 and 15432 are available
4. **View service logs**: `docker-compose logs market-data-service`

### No prices in database

1. **Check Alpaca credentials**: Verify `ALPACA_API_KEY` and `ALPACA_SECRET_KEY`
2. **Check tracked symbols**: Verify `TRACKED_SYMBOLS` includes valid tickers
3. **Check polling status**: `curl http://localhost:8000/scheduler/status`
4. **Check for Alpaca errors**: `curl http://localhost:8000/market-data/status` and review `last_error`

### Database connection errors

1. **Check PostgreSQL**: `docker-compose logs postgres`
2. **Verify credentials**: Ensure `DB_HOST`, `DB_USER`, `DB_PASSWORD` match
3. **Check network**: Services must be on same Docker network
4. **Wait for startup**: PostgreSQL takes a few seconds to start

## Future Extensions

The service is designed for extensibility to support additional data sources:

- **Cryptocurrency**: Extend `alpaca_service.py` to handle crypto quotes
- **Forex**: Add forex market data support
- **Other Providers**: Add adapters for other data providers (Yahoo, IEX, etc.)
- **Data Enrichment**: Add technical indicators, moving averages, etc.
- **Historical Data**: Backfill historical price data
- **Real-time WebSocket**: Add WebSocket support for streaming prices

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Market Data Service                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  FastAPI Application (main.py)                                   │
│  ├─ GET /health                     [Health Check]               │
│  ├─ GET /health/ready               [Readiness Probe]            │
│  ├─ GET /market-data/status         [Status & Statistics]        │
│  ├─ GET /market-data/latest/{sym}   [Latest Price Query]         │
│  └─ GET /scheduler/status           [Scheduler Status]           │
│                                                                   │
│  Background Scheduler (scheduler.py)                             │
│  └─ Every 10 seconds → fetch_and_persist_prices()               │
│                                                                   │
│  Price Service (price_service.py)                                │
│  ├─ Calls Alpaca API                                             │
│  ├─ Parses bid/ask prices                                        │
│  ├─ Calculates midpoint = (bid + ask) / 2                       │
│  └─ Persists to PostgreSQL                                       │
│                                                                   │
│  Alpaca Service (alpaca_service.py)                              │
│  ├─ HTTP client to Alpaca API                                    │
│  └─ Quote data transformation                                    │
│                                                                   │
│  Database Layer (database.py, models.py)                         │
│  └─ SQLAlchemy ORM with connection pooling                      │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
        ┌───────────▼──────────┐  ┌────▼─────────────┐
        │   Alpaca API         │  │  PostgreSQL      │
        │   (Market Data)      │  │  (Persistence)   │
        │                      │  │                  │
        │ Latest Quotes for    │  │ instrument_prices│
        │ - Bid Prices         │  │ - bid_price      │
        │ - Ask Prices         │  │ - ask_price      │
        │ - Timestamps         │  │ - price (midpoint)
        │                      │  │ - as_of          │
        └──────────────────────┘  └──────────────────┘
```

## Support & Issues

For issues, bugs, or feature requests, please check the logs and health endpoints:

```bash
# Comprehensive diagnostic information
curl http://localhost:8000/market-data/status | jq .

# Check application logs
docker-compose logs -f market-data-service

# Access PostgreSQL directly
docker exec -it agents-of-leap-db psql -U postgres -d agents_of_leap
```

## License

This project is part of the Agents of Leap platform.
