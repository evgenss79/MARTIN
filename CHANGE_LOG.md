# MARTIN — Change Log

> Chronological history of project changes.
> Every non-trivial code change MUST add an entry.

---

## Format

Each entry includes:
- **Date**: When the change was made
- **Change**: What was changed
- **Reason**: Why it was changed
- **Behavior Changed**: Yes/No

---

## 2026-01-21: Initial Architecture Baseline

**Change**: Complete implementation of MARTIN Telegram trading bot.

**Details**:
- Created project structure following spec
- Implemented all core modules:
  - Market discovery (Gamma API client)
  - Price data (Binance client with caching)
  - CAP validation (CLOB client)
  - TA engine (EMA, ADX, signal detection, quality calculation)
  - State machine (trade lifecycle)
  - Stats service (streaks, quantiles)
  - Execution service (paper mode default)
  - Telegram bot (trade cards, commands, settings)
- Created SQLite schema with migrations
- Created configuration with JSON schema validation
- Created comprehensive test suite (47 tests)
- Created Docker deployment support

**Reason**: Initial project creation per specification.

**Behavior Changed**: N/A (initial release)

**Files Created**:
- `config/config.json`
- `config/config.schema.json`
- `src/main.py`
- `src/bootstrap.py`
- `src/common/` (config, logging, exceptions)
- `src/domain/` (enums, models)
- `src/adapters/telegram/bot.py`
- `src/adapters/polymarket/` (gamma, clob, binance clients)
- `src/adapters/storage/` (database, repositories)
- `src/services/` (ta_engine, cap_check, state_machine, time_mode, stats, execution, orchestrator)
- `src/tests/` (test_cap_pass, test_ta_engine, test_state_machine)
- `docker-compose.yml`
- `requirements.txt`
- `README.md`
- `.env.example`
- `.gitignore`

---

## 2026-01-21: Code Review Improvements

**Change**: Addressed code review feedback for concurrent candle fetching and quality extraction refactor.

**Details**:
- Improved concurrent fetching of 1m and 5m candles using asyncio.gather
- Refactored quality extraction from signal repository for better separation of concerns

**Reason**: Code review feedback improvements.

**Behavior Changed**: No (performance and code quality improvements only)

---

## 2026-01-21: Long-Term Memory Files

**Change**: Created project memory and governance documentation.

**Details**:
- Created MEMORY_GATE.md with immutable constraints MG-1 through MG-12
- Created ARCHITECTURE.md with system overview and data flow
- Created STATE_MACHINE.md with complete transition table
- Created DATA_CONTRACTS.md with schema definitions
- Created CONFIG_CONTRACT.md with all configuration parameters
- Created NON_NEGOTIABLE_RULES.md with trading rules checklist
- Created CHANGE_LOG.md (this file)
- Created DEVELOPMENT_PROTOCOL.md with development process

**Reason**: Establish authoritative project memory layer per owner request.

**Behavior Changed**: No (documentation only)

---

## 2026-01-21: Live Execution Implementation

**Change**: Implemented full live trading support with wallet-based authentication.

**Details**:
- Created `src/adapters/polymarket/signer.py`:
  - `WalletSigner`: EIP-712 signing using wallet private key (MetaMask compatible)
  - `ApiKeySigner`: HMAC signing using API key/secret/passphrase
  - `OrderData`: Order structure for CLOB API
- Updated `src/adapters/polymarket/clob_client.py`:
  - Added `place_limit_order()`: Place orders on CLOB
  - Added `get_order_status()`: Check order fill status
  - Added `cancel_order()`: Cancel open orders
  - Added `get_open_orders()`: List all open orders
  - Added `OrderResult` and `OrderStatus` classes
- Updated `src/services/execution.py`:
  - Full live mode implementation using CLOB client
  - Automatic auth method detection (wallet first, then API key)
  - Order cancellation support
- Updated configuration:
  - Added `execution.live` section in config.json
  - Added wallet auth environment variables in .env.example
- Added `eth-account>=0.10.0` to requirements.txt
- Updated documentation:
  - CONFIG_CONTRACT.md: New execution settings and env vars
  - ARCHITECTURE.md: Execution engine details

**Files Created**:
- `src/adapters/polymarket/signer.py`

**Files Modified**:
- `src/adapters/polymarket/clob_client.py`
- `src/adapters/polymarket/__init__.py`
- `src/services/execution.py`
- `config/config.json`
- `.env.example`
- `requirements.txt`
- `CONFIG_CONTRACT.md`
- `ARCHITECTURE.md`

**Reason**: Feature request (Item 1 & 2) - Enable live bet placement after user confirmation in Day mode.

**Behavior Changed**: Yes
- Live mode now functional when credentials are provided
- Paper mode remains default (MG-9 constraint preserved)
- New environment variable `POLYMARKET_PRIVATE_KEY` for wallet auth

---

## 2026-01-21: Add Telegram Status Indicators

**Change**: Added two visual status indicators to Telegram UI.

**Details**:
- Created `src/services/status_indicator.py`:
  - `SeriesIndicator`: 🟢 Series Active / 🔴 Series Inactive
  - `PolymarketAuthIndicator`: 🟡 Authorized / ⚪ Not Authorized
  - `compute_series_indicator()`: Deterministic series activity check
  - `compute_polymarket_auth_indicator()`: Auth status check
- Updated `src/adapters/telegram/bot.py`:
  - Added indicators to `/status` command response
  - Added indicators to trade card headers
  - New helper methods: `_get_series_indicator()`, `_get_polymarket_auth_indicator()`

**Series Active Definition** (strict and deterministic):
- series_active = TRUE if:
  a) trading is not paused, AND
  b) there is at least one in-progress trade (WAITING_CONFIRM, WAITING_CAP, READY, ORDER_PLACED) OR trade_level_streak > 0, AND
  c) bot is allowed to trade in current mode (day: always; night: night_autotrade_enabled)

**Polymarket Auth Definition**:
- Authorized (🟡) if:
  - execution.mode == "live" AND
  - POLYMARKET_PRIVATE_KEY exists OR (API_KEY + SECRET + PASSPHRASE exist)
- Not Authorized (⚪) otherwise, with context:
  - Paper Mode: "Polymarket Live Disabled (Paper Mode)"
  - Missing creds: "Polymarket Not Authorized (Missing Credentials)"

**Files Created**:
- `src/services/status_indicator.py`

**Files Modified**:
- `src/adapters/telegram/bot.py`
- `CHANGE_LOG.md`

**Reason**: User request to add visual indicators showing series activity and Polymarket authorization status.

**Behavior Changed**: Yes (UI only)
- New status indicators shown in `/status` response
- New status indicators shown in trade card headers

---

## Template for Future Entries

```markdown
## YYYY-MM-DD: Brief Title

**Change**: One-line summary of what changed.

**Details**:
- Bullet points of specific changes
- Files modified

**Reason**: Why this change was made.

**Behavior Changed**: Yes/No. If yes, describe how.
```

---

*This file is the authoritative change log for project MARTIN.*
*Last updated: 2026-01-21*
