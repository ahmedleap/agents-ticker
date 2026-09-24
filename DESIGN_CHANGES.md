# Design Changes: Database Initialization Architecture

## Current Problem

The current code assumes schema reset on every startup (`db_manager.reset_schema()`), which:
- Drops ALL tables including dependent tables (`orders`, `holdings`)
- Fails with foreign key constraint errors
- Is inappropriate for production where data persistence is required

## New Architecture

**Goal:** Decouple schema initialization from service startup.

```
┌─────────────────────────────────────────────────────────────┐
│                        Bootstrap Phase                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Manual: Reset database                                    │
│    docker exec test_postgres psql -U test -d test_db -c \    │
│      "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"     │
│                                                               │
│ 2. Manual: Run bootstrap (validate 469 → insert 421)        │
│    docker-compose exec ticker-service \                      │
│      python -m app.bootstrap_instruments                     │
│                                                               │
│ 3. Manual: Run cold start (load 365 days of bars)           │
│    docker-compose exec ticker-service \                      │
│      python -m app.cold_start_bars                           │
│                                                               │
│ Result: Schema + instruments + instrument_price_history      │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│                    Production Service Phase                   │
├─────────────────────────────────────────────────────────────┤
│ 1. Service starts: docker-compose up -d ticker-service      │
│                                                               │
│ 2. Startup sequence:                                         │
│    a. Initialize DB connection only                          │
│    b. Load validated symbols from instruments table          │
│    c. Start Job 1 (quote polling every 10s)                 │
│    d. Start Job 3 (daily EOD bars at 16:15 ET)              │
│                                                               │
│ 3. Running state: Data freshness maintained                  │
│    - Job 1: Updates bid/ask prices                           │
│    - Job 3: Inserts daily OHLCV bars                         │
│    - NO schema operations (data safe)                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Code Changes Required

### 1. `app/database.py`

**Note:** Keep `reset_schema()` and `drop_all_tables()` as manual-only utilities. They should NEVER be called from production startup.

No changes needed—these methods exist only for manual one-time cleanup via scripts.

---

### 2. `app/main.py` Startup Sequence

**Current (broken):**
```python
# Initialize database
db_manager.initialize()
db_manager.reset_schema()  # ❌ Fails with FK constraint errors
```

**New (production-safe):**
```python
# Initialize database connection only
logger.info("Initializing database connection")
if not db_manager.initialize():
    logger.error("Failed to initialize database")
    sys.exit(1)

# Load validated symbols from database (assume schema exists)
logger.info("Loading validated symbols from database")
all_symbols = load_symbols_from_overlap()
if not all_symbols:
    logger.error("No symbols found in database")
    logger.error("Run bootstrap_instruments.py and cold_start_bars.py first")
    sys.exit(1)

logger.info(f"Loaded {len(all_symbols)} symbols")

# Initialize services and scheduler...
```

**Key Changes:**
- ✅ No schema creation or dropping
- ✅ No table creation on startup
- ✅ Assumes database schema already exists (guaranteed by bootstrap)
- ✅ Simply connects and loads data
- ✅ Idempotent and production-safe

---

### 3. `app/bootstrap_instruments.py` (No Changes)

Remains a **manual one-time script**:
- Loads 469 symbols from `overlap.txt`
- Validates each against Alpaca API
- Inserts only valid symbols (~421) into `instruments` table
- Usage: `docker-compose exec ticker-service python -m app.bootstrap_instruments`

---

### 4. `app/cold_start_bars.py` (No Changes)

Remains a **manual one-time script**:
- Loads all validated instruments from database
- Fetches 365 days of bars for each
- Inserts into `instrument_price_history` table
- Usage: `docker-compose exec ticker-service python -m app.cold_start_bars`

---

### 5. `app/services/scheduler.py` (Minor Update)

**Current:** Assumes `all_symbols` passed at init time

**New:** No changes needed—still receives `all_symbols` list from startup

---

## Deployment Workflow

### First Deployment (New System)

```bash
# 1. Stop existing service
docker-compose down ticker-service

# 2. Clean database (if needed)
docker exec test_postgres psql -U test -d test_db -c \
  "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# 3. Rebuild with new code
docker-compose build --no-cache ticker-service

# 4. Bootstrap: Validate and insert 421 symbols
docker-compose up -d ticker-service
sleep 5
docker-compose exec ticker-service python -m app.bootstrap_instruments

# 5. Cold start: Load 365 days of bars (~5-10 min)
docker-compose exec ticker-service python -m app.cold_start_bars

# 6. Restart service (now clean startup)
docker-compose restart ticker-service

# 7. Verify service started successfully
docker-compose logs ticker-service | tail -30
```

### Subsequent Restarts (Normal Operations)

```bash
# Just restart the service—schema already exists, no reset
docker-compose restart ticker-service

# Verify it started
docker ps
docker logs -f ticker-service | grep -E "(Loaded|Starting Market Data Service)"
```

---

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Schema Reset** | Every startup (destructive) | Never in production |
| **Data Persistence** | ❌ Lost on restart | ✅ Preserved across restarts |
| **Production Ready** | ❌ No | ✅ Yes |
| **Startup Logic** | ❌ Complex (drop/create) | ✅ Simple (connect/load) |
| **FK Constraints** | ❌ Break on reset | ✅ Always intact |
| **Manual Control** | ❌ Automatic reset | ✅ User controls bootstrap timing |
| **Restart Safety** | ❌ Risky | ✅ Safe anytime |

---

## Testing Checklist

- [ ] Local: Run bootstrap → cold start → service starts cleanly (no schema reset)
- [ ] Local: Restart service → stays healthy, no errors, data persists
- [ ] EC2: Run bootstrap → cold start → service starts
- [ ] EC2: Check startup logs: "Loaded 421 symbols from database" (no schema operations)
- [ ] EC2: Verify prices updating every 10 seconds (Job 1 working)
- [ ] EC2: Restart service without bootstrap/cold-start → service starts normally
- [ ] EC2: Check data persists across restarts

---

## Files to Modify

1. ✅ `app/main.py` — Replace startup to only initialize connection, no schema operations
2. ✅ `app/database.py` — Keep as-is (reset_schema/drop_all_tables are manual-only)
3. ✅ `app/services/scheduler.py` — No changes
4. ✅ `app/bootstrap_instruments.py` — No changes
5. ✅ `app/cold_start_bars.py` — No changes

---

## Rollout Steps

1. **Code changes** (app/main.py only)
2. **Commit & push** to main
3. **Rebuild Docker image** on EC2
4. **Manual bootstrap/cold-start** on EC2 (one-time)
5. **Restart service** and verify logs

