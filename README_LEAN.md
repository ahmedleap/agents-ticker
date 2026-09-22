# Market Data Service

Standalone microservice that fetches real-time market data from Alpaca and updates PostgreSQL.

## Quick Start

### Prerequisites
- Docker
- PostgreSQL database (separate container or external)
- Alpaca API credentials

### Build & Run

```bash
# Build
docker build -t ticker-service:v1.0 .

# Run
docker run -d \
  --name ticker-service \
  -p 8000:8000 \
  -e DB_HOST=your_db_host \
  -e DB_PORT=5432 \
  -e DB_NAME=test_db \
  -e DB_USER=test \
  -e DB_PASSWORD=test \
  -e ALPACA_API_KEY=your_key \
  -e ALPACA_SECRET_KEY=your_secret \
  ticker-service:v1.0
```

### Docker Compose

```bash
docker-compose up -d
docker-compose logs -f ticker-service
```

## API Endpoints

### Health Check
```
GET /health
```
Response: Service status (database, Alpaca API, scheduler)

### Quotes
```
GET /quotes?symbols=AAPL,MSFT
```
Response: Latest bid/ask/mid_price for symbols

## Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `DB_HOST` | Yes | - |
| `DB_PORT` | Yes | 5432 |
| `DB_NAME` | Yes | - |
| `DB_USER` | Yes | - |
| `DB_PASSWORD` | Yes | - |
| `ALPACA_API_KEY` | Yes | - |
| `ALPACA_SECRET_KEY` | Yes | - |
| `LOG_LEVEL` | No | INFO |
| `POLL_INTERVAL_SECONDS` | No | 10 |
| `TRACKED_SYMBOLS` | No | AAPL,MSFT,GOOGL,AMZN,TSLA,SPY,QQQ,BND,JNJ,JPM |

## Logs

```bash
# View logs
docker logs ticker-service -f

# Specific logs
docker logs ticker-service | grep ERROR
```

## Monitoring

```bash
# Health check
curl http://localhost:8000/health

# Get quotes
curl http://localhost:8000/quotes?symbols=AAPL

# Container status
docker ps | grep ticker-service
```

## Database Schema

Run `schema.sql` on PostgreSQL before starting the service:
```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f schema.sql
```

## Documentation

- `ARCHITECTURE.md` — Microservice design & implementation
- `DEPLOYMENT.md` — Detailed deployment guide
- `README.md` — Original project documentation
