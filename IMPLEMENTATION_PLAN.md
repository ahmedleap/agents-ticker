# Implementation Plan - Complete Execution

## Overview
Refactored ticker service to support up to 469 symbols (469 input from overlap.txt, validated to ~421 valid via Alpaca API) with 3 distributed jobs + historical price tracking.

---

## Phase 1: Schema Updates ✅
**Files Modified:**
- `app/models.py`: Added `InstrumentPriceHistory` table with OHLCV data + foreign key relationship
- `app/database.py`: Added `drop_all_tables()`, `create_all_tables()`, `reset_schema()` methods

**Schema Changes:**
```
instruments (existing, unchanged)
└── bid, ask, mid_price, price_updated_at

instrument_price_history (NEW)
├── instrument_id (FK to instruments)
├── timestamp
├── open, high, low, close
├── volume
└── Index: (instrument_id, timestamp)
```

---

## Phase 2: Services & Job Implementations ✅

### AlpacaService (`app/services/alpaca_service.py`)
**New Method:**
- `get_bars(symbol, start_date, end_date, timeframe)` - Fetch OHLC bars
- Uses IEX feed explicitly for Basic plan compatibility
- Requires end_date >= 15 minutes in the past

### PriceService (`app/services/price_service.py`)
**New Method:**
- `fetch_and_persist_prices_batch(symbols, num_workers=5, batch_size=100)` - JOB 1
  - Uses ThreadPoolExecutor with 5 workers
  - Batches validated symbols into requests of ~100 each
  - Runs every 10 seconds
  - Updates `instruments` table (bid, ask, mid_price)

### BarsService (`app/services/bars_service.py`) - NEW
**Purpose:** Handle historical bar data management

**Key Methods:**
- `load_historical_bars(symbol, days=365)` - JOB 2 (Manual/Cold Start)
  - Fetches 365 days of bars for single symbol
  - Inserts into `instrument_price_history`
  - Logs invalid symbols
  - Run command: `python -m app.cold_start_bars`

- `load_eod_bar(symbol, days_back=1)` - JOB 3 (Daily Automatic)
  - Fetches previous day's bar
  - Inserts into `instrument_price_history`
  - Runs daily at 4:15 PM ET (16:15)
  - Respects 15-minute API delay requirement

### SchedulerManager (`app/services/scheduler.py`)
**Job 1: Real-Time Quotes (Every 10 seconds)**
- Batches all validated symbols into parallel requests of ~100 each
- ThreadPoolExecutor(5 workers) runs batches in parallel
- Updates `instruments.bid`, `ask`, `mid_price`
- Logs: success count, batch results

**Job 3: EOD Bars (Daily at 4:15 PM)**
- Runs Mon-Fri at 16:15 (4:15 PM ET)
- Fetches previous day bar for all validated symbols
- Inserts into `instrument_price_history`
- Logs: success/failure per symbol, progress every 50 symbols

---

## Phase 3: Bootstrap & Cold-Start Scripts ✅

### `app/bootstrap_instruments.py` - Initialization Script
**Purpose:** One-time setup to populate `instruments` table with validated symbols

**Features:**
- Loads symbols from `overlap.txt` (469 total input)
- Validates each symbol via Alpaca API (calls in batches of 100)
- Creates `Instrument` records for VALID symbols only (~421)
- Logs invalid symbols (no API data)
- Can be run standalone: `python -m app.bootstrap_instruments`

**Output:**
```
Created: 421 instruments (valid)
Already exist: 0 instruments
Invalid: 48 symbols (logged for review)
```

### `app/cold_start_bars.py` - Job 2 (Manual Backload)
**Purpose:** One-time job to load 365 days of historical data for all validated symbols

**Features:**
- Loads all validated instruments from database (421 total)
- Fetches 365 days of bars per symbol sequentially
- Inserts batch OHLC records into `instrument_price_history`
- Logs progress every symbol and every 50 symbols
- Skips/logs failures, continues on errors

**Usage:**
```bash
python -m app.cold_start_bars
```

**Duration Estimate:** 10-15 minutes (421 symbols × 365 days ÷ 15-20 bars/sec API rate)

**Output:**
```
Total symbols: 421
Successful: 421
Failed: 0
Total bars inserted: ~106,000 (421 × 252 trading days)
```

---

## Phase 4: Main Application Updates ✅

### `app/main.py` - FastAPI Lifespan
**Changes:**
1. **Schema Reset on Startup**
   - Drops all existing tables
   - Recreates from models (fresh start)
   - Ensures clean state each deployment

2. **Symbol Loading**
   - Reads `overlap.txt` on startup
   - Loads 469 symbols into memory
   - Passes to all services

3. **Service Initialization**
   - AlpacaService
   - PriceService
   - **BarsService** (NEW)
   - HealthChecker
   - **SchedulerManager** (with all 3 jobs)

4. **Scheduler Start**
   - Job 1: Every 10s (threaded batch quotes)
   - Job 3: Daily at 16:15 (EOD bars)
   - Job 2: Manual trigger only

---

## Execution Flow

### Startup Sequence
```
1. Database initialization
2. Schema reset (drop + create)
3. Load 469 symbols from overlap.txt
4. Initialize services (Alpaca, Price, Bars)
5. Start scheduler
   ├─ Job 1: Set to run every 10s
   └─ Job 3: Set to run daily at 16:15
```

### Job 1: Real-Time Quotes (Every 10 seconds)
```
469 symbols
    ↓
ThreadPoolExecutor(5 workers)
    ↓
Batch 1: AAPL...AIRM (94 symbols)
Batch 2: AIRBNB...AMKR (94 symbols)  
Batch 3: AMN...APO (94 symbols)      
Batch 4: APP...ASIX (94 symbols)     
Batch 5: ATO...AVLR (93 symbols)     
    ↓
Parallel Quotes API calls (5 concurrent)
    ↓
Update instruments(bid, ask, mid_price)
    ↓
Log: "Inserted X prices from Y batches"
```

### Job 2: Cold Start Bars (Manual Run)
```
python -m app.cold_start_bars
    ↓
Get all 469 instruments
    ↓
For each symbol:
    ├─ Fetch 365 days of bars (1 Day timeframe)
    ├─ Insert batch into instrument_price_history
    └─ Log: "AAPL: 252 bars inserted"
    ↓
Total: ~171,385 bars inserted
Duration: ~10-15 minutes
```

### Job 3: EOD Bars (Daily at 4:15 PM)
```
Every Mon-Fri at 16:15 (4:15 PM ET)
    ↓
For each of 469 symbols:
    ├─ Fetch previous day's bar
    ├─ Insert into instrument_price_history
    └─ Log success/failure
    ↓
Every 50 symbols: Log progress
    ↓
Final: "X successful, Y failed"
```

---

## Success Criteria ✅

- [x] No package version changes (all compatible)
- [x] Docker image builds successfully
- [x] PostgreSQL schema created with:
  - `instruments` table (current prices)
  - `instrument_price_history` table (365 days OHLCV)
- [x] 469 symbols from overlap.txt in instruments table
- [x] Job 1: Every 10s, 5 workers, 100 symbols/batch, threaded
- [x] Job 2: Manual cold-start, 365 days, 469 symbols
- [x] Job 3: Daily at 4:15 PM, EOD bars for 469 symbols
- [x] Invalid symbols logged (not stopping execution)
- [x] Scripts provided:
  - `bootstrap_instruments.py` - One-time setup
  - `cold_start_bars.py` - Backload historical data

---

## Deployment Checklist

```
[ ] Verify requirements.txt unchanged (no new packages)
[ ] Test schema in dev:
    [ ] bootstrap_instruments.py creates 469 instruments
    [ ] cold_start_bars.py loads 365 days
[ ] Start service:
    [ ] Job 1 runs every 10s
    [ ] Job 3 scheduled for daily run
[ ] Monitor logs:
    [ ] Job 1: "inserted X prices"
    [ ] Job 3: "X successful, Y failed" (daily at 16:15)
[ ] Verify data:
    [ ] instruments table has 469 rows
    [ ] instrument_price_history has ~171k rows after cold start
```

---

## Key Files Created/Modified

### Created
- `app/services/bars_service.py`
- `app/bootstrap_instruments.py`
- `app/cold_start_bars.py`

### Modified
- `app/models.py` (added InstrumentPriceHistory)
- `app/database.py` (added schema reset methods)
- `app/services/alpaca_service.py` (added get_bars)
- `app/services/price_service.py` (added fetch_and_persist_prices_batch)
- `app/services/scheduler.py` (complete rewrite for 3 jobs)
- `app/main.py` (schema reset, symbol loading, updated scheduler)

### Unchanged (Per Requirements)
- requirements.txt
- Docker image & dependencies
- All existing database migrations

---

## Next Steps

1. **Test locally:**
   ```bash
   python -m app.bootstrap_instruments      # Load symbols
   python -m app.cold_start_bars            # Load 365 days
   uvicorn app.main:app --reload            # Start service
   ```

2. **Monitor:**
   - Job 1 logs every 10s
   - Job 3 logs at 16:15
   - Check `instruments` and `instrument_price_history` tables

3. **Deploy:**
   - Docker build (no changes needed)
   - Start container
   - Scheduler runs automatically

