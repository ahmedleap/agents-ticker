# Deployment Guide

## Quick Start

This is a **standalone microservice** that connects to an existing PostgreSQL database via environment variables.

### Prerequisites
- Docker installed on Linux VM
- PostgreSQL already running and populated with schema
- Alpaca API credentials

### Build
```bash
docker build -t ticker-service:v1.0 .
```

### Run
```bash
docker run -d \
  --name ticker-service \
  -p 8000:8000 \
  -e DB_HOST=postgres_ip_or_hostname \
  -e DB_PORT=5432 \
  -e DB_NAME=test_db \
  -e DB_USER=test \
  -e DB_PASSWORD=test \
  -e ALPACA_API_KEY=your_key \
  -e ALPACA_SECRET_KEY=your_secret \
  -e LOG_LEVEL=INFO \
  ticker-service:v1.0
```

### Verify
```bash
# Health check
curl http://localhost:8000/health

# Get quotes
curl http://localhost:8000/quotes?symbols=AAPL,MSFT
```

### View Logs
```bash
docker logs ticker-service -f
```

---

## Environment Variables

**Required:**
- `DB_HOST` — PostgreSQL hostname/IP
- `DB_PORT` — PostgreSQL port (default: 5432)
- `DB_NAME` — Database name
- `DB_USER` — Database username
- `DB_PASSWORD` — Database password
- `ALPACA_API_KEY` — Alpaca API key
- `ALPACA_SECRET_KEY` — Alpaca secret key

**Optional:**
- `LOG_LEVEL` — DEBUG, INFO, ERROR (default: INFO)
- `POLL_INTERVAL_SECONDS` — Quote polling interval (default: 10)
- `TRACKED_SYMBOLS` — Comma-separated symbols (default: AAPL,MSFT,GOOGL,AMZN,TSLA,SPY,QQQ,BND,JNJ,JPM)

---

## Using Docker Compose

```yaml
# docker-compose.yml
version: '3.8'
services:
  ticker-service:
    build: .
    container_name: ticker-service
    ports:
      - "8000:8000"
    environment:
      DB_HOST: your_db_host
      DB_PORT: 5432
      DB_NAME: test_db
      DB_USER: test
      DB_PASSWORD: test
      ALPACA_API_KEY: your_key
      ALPACA_SECRET_KEY: your_secret
      LOG_LEVEL: INFO
    restart: unless-stopped
```

Run:
```bash
docker-compose up -d
docker-compose logs -f ticker-service
```

---

## API Endpoints

### GET /health
Returns service status:
```json
{
  "status": "healthy",
  "database": "connected",
  "alpaca_api": "accessible",
  "scheduler": "running",
  "last_price_update": "2026-09-22T15:30:45.123Z"
}
```

### GET /quotes?symbols=AAPL,MSFT
Returns latest bid/ask/mid_price for symbols:
```json
{
  "AAPL": {
    "bid": 342.19,
    "ask": 342.75,
    "mid_price": 342.47,
    "updated_at": "2026-09-22T15:30:42Z"
  }
}
```

---

## Troubleshooting

### Service exits immediately
```bash
docker logs ticker-service
# Check for:
# - Database connection errors (wrong host/credentials)
# - Invalid Alpaca API key (401 Unauthorized)
```

### Connection refused to database
Verify `DB_HOST` is correct and PostgreSQL is accessible:
```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1"
```

### 401 Unauthorized from Alpaca
Check API credentials:
```bash
docker inspect ticker-service | grep -A 50 '"Env"'
```

### Logs keep growing
Limit log file size:
```bash
docker run --log-driver json-file --log-opt max-size=10m --log-opt max-file=5 ... ticker-service
```

---

## Monitoring

**Real-time logs:**
```bash
docker logs ticker-service -f
```

**Check container status:**
```bash
docker ps | grep ticker-service
```

**View resource usage:**
```bash
docker stats ticker-service
```

**Test endpoints:**
```bash
curl http://localhost:8000/health | jq .
curl http://localhost:8000/quotes?symbols=AAPL,MSFT | jq .
```

