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

**Discovery Model (Event-Driven)**:
- Gamma API returns `events[]` array with nested `markets[]` per event
- Discovery extracts markets from BOTH top-level markets AND nested event markets
- Filtering is applied at MARKET level, not event level

**API Flow**:
- Calls Gamma API `/public-search` endpoint
- Parses response: `{ "events": [...], "markets": [...] }`
- Extracts nested markets from each event
- Propagates event-level data (timestamps, title) to markets for fallback

**Market Filtering Rules** (case-insensitive):
- Title/question must contain: "up or down", "up/down", or "updown"
- Title/question must contain asset symbol (BTC, ETH) or name (Bitcoin, Ethereum)

**Time Window Handling**:
- Timestamp fallback chain: market-level → event-level
- Configurable `forward_horizon_seconds` (default: 2 hours)
- Configurable `grace_period_seconds` (default: 5 minutes)

**Token ID Extraction**:
- Extracts from `tokens[]` array with outcome field
- Falls back to `outcomes[]` + `clobTokenIds[]` arrays
- Handles JSON string arrays and Yes/No as Up/Down equivalents

**Diagnostic Logging**:
- Events scanned, markets scanned
- Title matches before/after time filter
- Sample market titles and end times

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

### 4a. Day/Night Configuration Service (`services/day_night_config.py`)

**Purpose**: Manage user-configurable day/night time ranges

- Supports wrap-around midnight scenarios (e.g., 22:00 to 06:00)
- Persists settings to SQLite settings table
- All changes apply immediately without restart

**Wrap-Around Logic**:
```
Normal:    day_start < day_end   → DAY if hour in [start, end)
Wrap:      day_start >= day_end  → DAY if hour >= start OR hour < end
```

**Configurable Settings**:
- `day_start_hour` (0-23)
- `day_end_hour` (0-23)
- `night_autotrade_enabled` (boolean)
- `reminder_minutes_before_day_end` (0-180)

---

### 4b. Day End Reminder Service (`services/day_end_reminder.py`)

**Purpose**: Send automatic reminders before day trading window ends

- Configurable X minutes before day end
- Rate-limited: max one reminder per calendar day
- Timezone-aware (Europe/Zurich)
- Shows night session mode options (OFF/SOFT/HARD)

**Reminder Content**:
- Current local time
- Day window end time
- Night session mode with explanation
- Execution mode and auth status
- Quick action buttons

---

### 5. Execution Engine (`services/execution.py`)

**Purpose**: Place orders

- **Paper mode** (default): Simulates fills at PRICE_CAP
- **Live mode**: Places real orders via Polymarket CLOB
  - Wallet-based auth (MetaMask compatible): Uses `POLYMARKET_PRIVATE_KEY`
  - API key-based auth: Uses `POLYMARKET_API_KEY`, `API_SECRET`, `PASSPHRASE`
- Calculates stake amount (fixed mode)
- Records order ID, token ID, fill status, and fill price

**Live Mode Components**:
- `adapters/polymarket/signer.py`: Wallet signing (EIP-712) and API key auth
- `adapters/polymarket/clob_client.py`: Order placement, status check, cancellation
- `services/secure_vault.py`: Encrypted credential storage

**Flow** (Day Mode):
```
User OK → ExecutionService.place_order() → 
  If paper: Generate PAPER_xxx order ID, fill at PRICE_CAP
  If live:  Sign order → CLOB.place_limit_order() → Return order_id
```

**Inputs**: Trade, signal, window, stake amount
**Outputs**: Order ID, token ID, fill price

---

### 5a. Security Layer (`common/crypto.py`, `services/secure_vault.py`)

**Purpose**: Protect credentials at rest

**CryptoService** (`common/crypto.py`):
- AES-256-GCM authenticated encryption
- Master key from `MASTER_ENCRYPTION_KEY` env var
- Random IV per encryption (prevents pattern analysis)
- Tamper detection via authentication tag

**SecureVault** (`services/secure_vault.py`):
- Encrypted storage for wallet private keys
- Session management for autonomous trading
- Vault persistence to encrypted file

**Security Requirements**:
- SEC-1: No plaintext secrets at rest
- SEC-2: Master key in environment only (never persisted)
- SEC-3: Session expiration for autonomous trades

**Flow** (One-time authorization):
```
1. User initiates /authorize in Telegram
2. Bot generates authorization message
3. User signs with MetaMask (one-time)
4. Bot creates AuthSession (encrypted)
5. Session used for autonomous trades
6. Session expires after 24 hours
```

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

**Routing Architecture**:
- Uses aiogram `Dispatcher` with command and callback handlers
- Commands registered via `@self._dp.message(Command("command_name"))`
- Callbacks registered via `@self._dp.callback_query()`
- All handlers check authorization before processing

**Callback Timeout Prevention**:
- CRITICAL: `await callback.answer()` MUST be called FIRST in callback handlers
- This prevents "query is too old and response timeout expired" errors
- Slow work (DB queries, API calls) happens AFTER answering

**Settings Persistence**:
- Settings editable via interactive inline keyboard menus
- Changes persisted to SQLite `settings` table via `SettingsRepository`
- Priority: Database settings > Environment > config.json
- Editable via +/- buttons:
  - Day/Night hours (hour grid 0-23)
  - Quality thresholds (base_day_min_quality, base_night_min_quality)
  - Streak settings (switch_streak_at, night_max_win_streak)
  - Trading params (price_cap, confirm_delay_seconds, cap_min_ticks, base_stake)
  - Night session mode (OFF/SOFT/HARD)
  - Reminder minutes

**Unknown Command Handler**:
- BotFather placeholder commands (/command1..8) return helpful error
- Lists available commands: /start, /status, /settings, etc.

**Auth Buttons**:
- `/start` and `/status` show authorization status and action buttons
- Paper mode: informational "Paper Mode Active" button (always visible)
- Live mode: Authorize, Recheck, Logout buttons

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
    │   ├── crypto.py        # AES-256-GCM encryption
    │   └── exceptions.py    # Custom exceptions
    ├── domain/
    │   ├── enums.py         # Status enumerations
    │   └── models.py        # Data models
    ├── adapters/
    │   ├── telegram/
    │   │   └── bot.py       # Telegram bot
    │   ├── polymarket/
    │   │   ├── gamma_client.py   # Market discovery
    │   │   ├── clob_client.py    # Price history + orders
    │   │   ├── signer.py         # Wallet/API signing
    │   │   └── binance_client.py # Candle data
    │   └── storage/
    │       ├── database.py       # SQLite connection
    │       └── repositories.py   # Data access
    ├── services/
    │   ├── ta_engine.py        # Technical analysis
    │   ├── cap_check.py        # CAP_PASS validation
    │   ├── state_machine.py    # Trade lifecycle
    │   ├── time_mode.py        # Day/Night mode detection
    │   ├── day_night_config.py # Day/Night configuration with persistence
    │   ├── day_end_reminder.py # Automatic day end reminders
    │   ├── stats_service.py    # Streaks & quantiles
    │   ├── execution.py        # Order execution
    │   ├── secure_vault.py     # Encrypted credential storage
    │   ├── status_indicator.py # Status indicators
    │   └── orchestrator.py     # Main coordinator (includes scheduling)
    ├── jobs/
    │   └── __init__.py         # Jobs module (scheduling via Orchestrator's async loop)
    └── tests/
        ├── test_cap_pass.py         # CAP_PASS tests
        ├── test_ta_engine.py        # TA engine tests
        ├── test_state_machine.py    # State machine tests
        ├── test_status_indicator.py # Status indicator tests
        ├── test_crypto.py           # Encryption tests
        ├── test_secure_vault.py     # Vault tests
        ├── test_day_night_config.py # Day/Night config tests
        ├── test_day_end_reminder.py # Reminder tests
        └── test_startup_smoke.py    # Startup smoke tests
```

---

## Dual-Loop Architecture

MARTIN implements a dual-loop architecture for continuous operation:

### PRIMARY LOOP: Continuous TA Snapshot (Independent of Windows)

The TA Snapshot Worker (`src/jobs/ta_snapshot_worker.py`) runs independently:

```python
# Runs every 30 seconds regardless of Polymarket windows
while self._running:
    for asset in self._assets:
        candles_1m, candles_5m = await self._fetch_candles(asset)
        self._cache.update(asset, candles_1m, candles_5m)
    await asyncio.sleep(30)
```

**Purpose**: Maintain fresh TA context even when no windows exist.

### PARALLEL LOOP: Window Discovery + Signal Scanning

The main Orchestrator loop:

```python
# Runs every 60 seconds
while self._running:
    await self._tick()
    await asyncio.sleep(60)
```

The `_tick()` method handles:
1. Market discovery via Gamma API
2. **SEARCHING_SIGNAL trade scanning** (in-window signal detection)
3. Active trade processing (other states)
4. Settlement checks

### Signal Decision = Overlay (TA Context + Anchor + Window)

For each SEARCHING_SIGNAL trade each tick:
1. Get latest candles from snapshot cache (or fetch fresh)
2. Run TA signal detection (BLACK BOX - no modifications)
3. If no signal → remain SEARCHING_SIGNAL
4. If signal found but quality < threshold → remain SEARCHING_SIGNAL
5. If signal found with quality >= threshold → persist Signal, transition to SIGNALLED

---

## Scheduling Mechanism

MARTIN uses a simple internal async loop for scheduling, managed by the Orchestrator:

```python
# In Orchestrator.start():
while self._running:
    await self._tick()
    await asyncio.sleep(60)  # Check every minute
```

The `_tick()` method handles:
- Market discovery via Gamma API
- SEARCHING_SIGNAL trade scanning
- Active trade processing
- Settlement checks

This approach is simpler than external schedulers (like APScheduler) and is sufficient for MARTIN's needs since all tasks run on a fixed 60-second interval aligned with the hourly market windows.

---

## Data Flow Pipeline

```
1. [TA Snapshot Worker] Continuously updates candle cache (every 30s)
       ↓ (independent)
2. [Scheduler] Triggers window discovery (every 60s)
       ↓
3. [Gamma Client] Fetches active Polymarket markets
       ↓
4. [Orchestrator] Creates MarketWindow records + SEARCHING_SIGNAL trades
       ↓
5. [Signal Scanner] Re-evaluates SEARCHING_SIGNAL trades each tick:
   5a. [TA Snapshot Cache] Provides candle data
   5b. [TA Engine] Detects signal (BLACK BOX)
   5c. If quality < threshold → remain SEARCHING_SIGNAL
   5d. If quality >= threshold → persist Signal → SIGNALLED
       ↓
6. [Decision Engine] Checks quality threshold (with strictness increment)
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

## Logging Architecture

MARTIN implements comprehensive INFO-level logging throughout the orchestration pipeline. All logs are structured with prefixed categories for easy filtering and analysis.

### Log Categories

| Prefix | Phase | Description |
|--------|-------|-------------|
| `STARTUP:` | Initialization | Bot startup, config loading, module initialization |
| `CYCLE_*` | Main Loop | Cycle start/end, skip reasons, errors |
| `DISCOVERY_*` | Market Discovery | Polymarket market discovery via Gamma API |
| `WINDOW_*` | Window Processing | Window selection and deduplication |
| `BINANCE_*` | Data Fetching | 1m and 5m candle data loading |
| `ANCHOR_*` | Reference Price | Anchor/reference price resolution |
| `TA_*` | Signal Detection | TA engine signal detection (black box) |
| `QUALITY_*` | Quality Scoring | Quality calculation (black box) |
| `SCORE_*` | Score Output | Quality breakdown output |
| `DECISION_*` | Decision Making | ACCEPTED or REJECTED with reasons |
| `TELEGRAM_*` | User Interaction | Signal cards, confirmations |
| `ENTRY_*` | Order Entry | Confirmation and execution flow |
| `ORDER_*` | Order Execution | Order placement results |
| `CAP_*` | CAP Check | Price cap validation |
| `SETTLEMENT_*` | Settlement | Trade settlement and PnL |

### Key Log Events for Decision Tracing

The following events enable full reconstruction of bot decisions:

1. **CYCLE_START**: Marks beginning of each 60-second processing cycle with unique `cycle_id`
2. **DECISION_ACCEPTED**: Signal passed all gates, proceeding to trade
3. **DECISION_REJECTED**: Signal rejected with explicit reason:
   - `reason=NIGHT_DISABLED`: Night autotrade not enabled
   - `reason=NO_SIGNAL`: No valid signal detected
   - `reason=LOW_QUALITY`: Quality below threshold (includes actual vs required)
   - `reason=LATE`: Signal confirm_ts >= window end_ts (MG-3 violation)
4. **SCORE_COMPUTED**: Full quality breakdown (edge, ADX, slope, trend multiplier)
5. **ORDER_SUBMITTED/ORDER_FAILED**: Execution result
6. **SETTLEMENT_COMPLETE**: Final trade outcome

### Logging Configuration

Log level is configurable via:
- `config/config.json`: `app.log_level` (default: "INFO")
- Environment: `LOG_LEVEL` override

Log format:
- `config/config.json`: `app.log_format` (default: "json")
- Options: "json" (structured) or "text" (human-readable)

---

*This file is the authoritative architecture reference for project MARTIN.*
*Last updated: 2026-01-22*
