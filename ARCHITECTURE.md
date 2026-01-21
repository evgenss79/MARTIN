# MARTIN — Architecture

> Single source of truth for system architecture.
> Read this before modifying any code.

---

## High-Level Overview

**MARTIN** is a Telegram trading bot that:

1. **Discovers** hourly "BTC Up or Down" and "ETH Up or Down" markets on Polymarket (via Gamma API)
2. **Computes** a trading signal using Binance price data and technical analysis (EMA/ADX)
3. **Validates** entry price via CAP_PASS logic (CLOB price history)
4. **Sends** trade recommendations to Telegram with quality scoring
5. **Executes** trades (paper mode by default) with day/night safety controls
6. **Tracks** streaks and adjusts filtering mode (BASE/STRICT)
7. **Settles** trades and records results

---

## Module Responsibilities

### 1. Market Discovery (`adapters/polymarket/gamma_client.py`)

**Purpose**: Find active Polymarket hourly markets

- Calls Gamma API `/public-search` endpoint
- Filters for BTC/ETH "up or down" hourly markets
- Extracts token IDs, timestamps, condition IDs
- Creates `MarketWindow` objects

**Inputs**: Asset list, current timestamp
**Outputs**: List of `MarketWindow` models

---

### 2. TA Engine (`services/ta_engine.py`)

**Purpose**: Detect trading signals and calculate quality scores

- Fetches 1m and 5m candles from Binance
- Computes EMA20 on 1m for signal detection (2-bar confirm)
- Computes ADX, EMA50 slope, trend confirmation on 5m
- Applies quality formula exactly per spec

**Signal Detection Rules**:
```
UP signal:  low[i] <= ema20[i] AND close[i] > ema20[i] AND close[i+1] > ema20[i+1]
DOWN signal: high[i] >= ema20[i] AND close[i] < ema20[i] AND close[i+1] < ema20[i+1]
```

**Inputs**: Candle data, window start timestamp
**Outputs**: `SignalResult` with direction, timestamp, quality breakdown

---

### 3. CAP_PASS Engine (`services/cap_check.py`)

**Purpose**: Validate that entry price is acceptable

- Fetches CLOB price history for token
- Checks ONLY ticks in `[confirm_ts, end_ts]` (MG-2)
- Counts consecutive ticks ≤ `PRICE_CAP`
- Passes when `consecutive >= CAP_MIN_TICKS`

**Critical Rule**: Ticks before `confirm_ts` are IGNORED.

**Inputs**: Token ID, confirm_ts, end_ts, price_cap
**Outputs**: `CapCheck` with PASS/FAIL/LATE status

---

### 4. Decision Engine (`services/time_mode.py`, `services/stats_service.py`)

**Purpose**: Determine if trade should proceed

- Calculates current time mode (DAY/NIGHT) using Europe/Zurich timezone
- Determines quality threshold based on policy mode (BASE/STRICT)
- Checks if quality meets threshold
- Day mode: requires user confirmation
- Night mode: auto-proceeds if enabled and within streak limit

**Inputs**: Time mode, policy mode, signal quality
**Outputs**: Decision (OK/SKIP/AUTO_OK/AUTO_SKIP)

---

### 5. Execution Engine (`services/execution.py`)

**Purpose**: Place orders

- Paper mode (default): Simulates fills
- Live mode: Placeholder for real order placement (requires credentials)
- Calculates stake amount
- Records order ID and fill status

**Inputs**: Trade, signal, window, stake amount
**Outputs**: Order ID, fill price

---

### 6. Settlement Engine (`services/orchestrator.py`)

**Purpose**: Resolve trades after market closes

- Fetches market outcome from Polymarket
- Compares signal direction to outcome
- Calculates PnL
- Updates trade record

**Inputs**: Trade, window outcome
**Outputs**: is_win, pnl

---

### 7. Stats & Streak Engine (`services/stats_service.py`)

**Purpose**: Track performance and manage filtering

- Maintains `trade_level_streak` (only taken+filled trades count)
- Maintains `night_streak` for night session
- Switches to STRICT mode at `SWITCH_STREAK_AT`
- Resets on loss or night session cap
- Calculates rolling quantile thresholds

**Key Invariant**: Skipped/failed windows do NOT break streak.

---

### 8. Telegram Interface (`adapters/telegram/bot.py`)

**Purpose**: User interaction

- Sends trade recommendation cards
- Handles OK/SKIP button clicks
- Provides commands: /start, /status, /settings, /pause, /resume, /report
- Settings menu for runtime config changes
- Rate-limited message sending

**Critical Rule**: No business logic in handlers. Handlers call services.

---

## Repository Structure

```
MARTIN/
├── MEMORY_GATE.md           # Immutable constraints (read first)
├── ARCHITECTURE.md          # This file
├── STATE_MACHINE.md         # Trade lifecycle
├── DATA_CONTRACTS.md        # Schema definitions
├── CONFIG_CONTRACT.md       # Configuration contract
├── NON_NEGOTIABLE_RULES.md  # Trading rules summary
├── CHANGE_LOG.md            # Change history
├── DEVELOPMENT_PROTOCOL.md  # Development process
├── README.md                # User documentation
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Docker deployment
├── .env.example             # Environment template
├── config/
│   ├── config.json          # Runtime configuration
│   └── config.schema.json   # Config validation schema
└── src/
    ├── main.py              # Entry point
    ├── bootstrap.py         # Initialization
    ├── common/
    │   ├── config.py        # Config loading
    │   ├── logging.py       # Structured logging
    │   └── exceptions.py    # Custom exceptions
    ├── domain/
    │   ├── enums.py         # Status enumerations
    │   └── models.py        # Data models
    ├── adapters/
    │   ├── telegram/
    │   │   └── bot.py       # Telegram bot
    │   ├── polymarket/
    │   │   ├── gamma_client.py   # Market discovery
    │   │   ├── clob_client.py    # Price history
    │   │   └── binance_client.py # Candle data
    │   └── storage/
    │       ├── database.py       # SQLite connection
    │       └── repositories.py   # Data access
    ├── services/
    │   ├── ta_engine.py      # Technical analysis
    │   ├── cap_check.py      # CAP_PASS validation
    │   ├── state_machine.py  # Trade lifecycle
    │   ├── time_mode.py      # Day/Night logic
    │   ├── stats_service.py  # Streaks & quantiles
    │   ├── execution.py      # Order execution
    │   └── orchestrator.py   # Main coordinator
    ├── jobs/
    │   └── scheduler.py      # Scheduled tasks
    └── tests/
        ├── test_cap_pass.py       # CAP_PASS tests
        ├── test_ta_engine.py      # TA engine tests
        └── test_state_machine.py  # State machine tests
```

---

## Data Flow Pipeline

```
1. [Scheduler] Triggers window discovery
       ↓
2. [Gamma Client] Fetches active Polymarket markets
       ↓
3. [Orchestrator] Creates MarketWindow records
       ↓
4. [Binance Client] Fetches 1m and 5m candles
       ↓
5. [TA Engine] Detects signal and calculates quality
       ↓
6. [Decision Engine] Checks quality threshold
       ↓
7. [Time Mode] Determines DAY/NIGHT behavior
       ↓
8. [Telegram Bot] Sends trade card (Day) or auto-proceeds (Night)
       ↓
9. [State Machine] Transitions: SIGNALLED → WAITING_CONFIRM
       ↓
10. [Scheduler] Waits for confirm_ts
       ↓
11. [CAP Check] Validates price in [confirm_ts, end_ts]
       ↓
12. [State Machine] Transitions: WAITING_CAP → READY (on PASS)
       ↓
13. [Execution] Places order (paper or live)
       ↓
14. [State Machine] Transitions: READY → ORDER_PLACED
       ↓
15. [Scheduler] Waits for market resolution
       ↓
16. [Settlement] Determines win/loss, calculates PnL
       ↓
17. [Stats Service] Updates streaks and policy mode
       ↓
18. [State Machine] Transitions: ORDER_PLACED → SETTLED
```

---

## Critical Architecture Rule

> **No business logic may be moved into Telegram handlers.**

Telegram handlers must:
- Receive user input
- Call service methods
- Format responses

They must NOT:
- Make trading decisions
- Calculate quality scores
- Manage state transitions
- Access database directly

---

*This file is the authoritative architecture reference for project MARTIN.*
*Last updated: 2026-01-21*
