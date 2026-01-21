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

## 2026-01-21: Security Hardening - Encryption at Rest

**Change**: Implemented encryption for secrets at rest (SEC-1, SEC-2 compliance).

**Details**:
- Created `src/common/crypto.py`:
  - `CryptoService`: AES-256-GCM encryption/decryption
  - `EncryptedData`: Container for encrypted data (iv || ciphertext || tag)
  - `generate_master_key()`: Utility to generate new master keys
  - `validate_master_key()`: Validation of MASTER_ENCRYPTION_KEY
- Created `src/services/secure_vault.py`:
  - `SecureVault`: Encrypted storage for credentials
  - `AuthSession`: Session management for autonomous trading
  - `check_secure_auth_status()`: Comprehensive auth status check
  - Vault persistence with encrypted file storage
- Updated `src/services/status_indicator.py`:
  - Added `EncryptionIndicator` (🔒/🔓)
  - Added `compute_encryption_indicator()` function
  - Added `get_security_summary()` for comprehensive status
- Updated `src/common/exceptions.py`:
  - Added `SecurityError` exception class
- Updated `.env.example`:
  - Added `MASTER_ENCRYPTION_KEY` documentation
  - Added security warnings and key generation instructions
- Updated `requirements.txt`:
  - Added `cryptography>=41.0.0` for AES-GCM
- Created comprehensive tests:
  - `src/tests/test_crypto.py`: Encryption roundtrip, tampering detection
  - `src/tests/test_secure_vault.py`: Vault storage, session management

**Security Requirements Implemented**:
- SEC-1: No plaintext secrets at rest - all credentials encrypted with AES-256-GCM
- SEC-2: Master key handling via MASTER_ENCRYPTION_KEY environment variable
- SEC-3: Session keys for autonomous trading with expiration

**Files Created**:
- `src/common/crypto.py`
- `src/services/secure_vault.py`
- `src/tests/test_crypto.py`
- `src/tests/test_secure_vault.py`

**Files Modified**:
- `src/common/exceptions.py`
- `src/services/status_indicator.py`
- `.env.example`
- `requirements.txt`
- `CONFIG_CONTRACT.md`
- `CHANGE_LOG.md`

**Reason**: Security hardening per user request. Enables secure storage of wallet credentials.

**Behavior Changed**: Yes
- New encryption layer for secrets at rest
- New environment variable: MASTER_ENCRYPTION_KEY
- New status indicator: Encryption Status (🔒/🔓)
- If MASTER_ENCRYPTION_KEY is not set:
  - Live trading still works (credentials from env only)
  - Security warning is logged
  - Encryption indicator shows 🔓

---

## 2026-01-21: Day/Night Configuration with Telegram Settings

**Change**: Implemented user-adjustable day/night trading time ranges via Telegram settings.

**Details**:
- Created `src/services/day_night_config.py`:
  - `DayNightConfigService`: Manages day/night time ranges with persistence
  - Supports wrap-around midnight scenarios (e.g., 22:00 to 06:00)
  - All settings persist to SQLite settings table
- Updated `src/adapters/telegram/bot.py`:
  - Full settings menu with interactive editing
  - Day hours selection with visual hour grid (0-23)
  - Night autotrade toggle
  - Reminder minutes configuration
- Updated `/status` command:
  - Shows current local time (Europe/Zurich)
  - Shows day/night hours and current mode
  - Shows reminder configuration

**Persisted Settings** (via Telegram /settings):
- Day Start Hour (0-23)
- Day End Hour (0-23)
- Night Auto-trade enabled/disabled
- Reminder before day end (0-180 minutes)

**Wrap-Around Logic**:
- Normal: day_start < day_end (e.g., 8 to 22) → DAY if hour in [start, end)
- Wrap: day_start >= day_end (e.g., 22 to 6) → DAY if hour >= start OR hour < end

**Files Created**:
- `src/services/day_night_config.py`
- `src/tests/test_day_night_config.py` (11 tests)

**Files Modified**:
- `src/adapters/telegram/bot.py`
- `CHANGE_LOG.md`
- `CONFIG_CONTRACT.md`

**Reason**: User request (R-1 through R-4) - Enable configurable day/night time ranges.

**Behavior Changed**: Yes
- Settings now persist to database and are editable via Telegram
- Day/Night mode detection supports wrap-around midnight
- /settings menu is now fully interactive

---

## 2026-01-21: Day End Reminder Service

**Change**: Implemented automatic reminder before day trading window ends.

**Details**:
- Created `src/services/day_end_reminder.py`:
  - `DayEndReminderService`: Sends reminders X minutes before day end
  - `NightSessionMode`: OFF / SOFT_RESET / HARD_RESET options
  - Rate-limited: max one reminder per day
  - Timezone-aware (Europe/Zurich)
- Reminder message includes:
  - Current local time
  - Day window end time
  - Night Session Mode with explanation
  - Execution mode and auth status
  - Quick action buttons

**Configurable via Telegram**:
- `reminder_minutes_before_day_end`: 0-180 (0 = disabled)
- Preset options: Off, 15, 30, 45, 60, 90, 120, 180 minutes

**Files Created**:
- `src/services/day_end_reminder.py`
- `src/tests/test_day_end_reminder.py` (13 tests)

**Reason**: User request - Add reminder before day window ends.

**Behavior Changed**: Yes
- New reminder feature (disabled by default)
- Reminder can be configured via /settings

---

## 2026-01-21: Night Session Mode (A/B/C) Toggles

**Change**: Implemented user-controllable Night Session switch with three behaviors.

**Details**:
- Added `NightSessionMode` enum to `src/domain/enums.py`:
  - `OFF`: Night autotrade disabled. Series freezes overnight.
  - `SOFT_RESET`: On night session cap, reset only night_streak. trade_level_streak continues.
  - `HARD_RESET`: On night session cap, reset both night_streak AND trade_level_streak.
- Updated `src/services/day_night_config.py`:
  - Added `get_night_session_mode()` / `set_night_session_mode()` methods
  - Added `get_night_session_mode_description()` / `get_night_session_mode_short()` helpers
  - Setting OFF automatically disables night_autotrade; SOFT/HARD enables it
  - Mode persists to settings table
- Updated `src/services/stats_service.py`:
  - Changed from boolean `night_session_resets_trade_streak` to `NightSessionMode` enum
  - `_apply_night_session_reset()` now checks mode for reset behavior
  - Added `set_night_session_mode()` / `get_night_session_mode()` for runtime updates
- Updated `src/adapters/telegram/bot.py`:
  - Added Night Session Mode to `/status` display
  - Added "🌙 Night Mode" button to `/settings` menu
  - New `_show_night_mode_settings()`: Mode selection with description
  - New `_set_night_session_mode()`: Handle mode change callbacks
  - Mode buttons show current selection with ✓ marker
- Created `src/tests/test_night_session_mode.py` (19 tests)

**UI Presentation**:
- /status shows: 🌙❌ OFF / 🌙🔵 SOFT / 🌙🔴 HARD
- /settings menu has "🌙 Night Mode" button
- Mode selection shows full description of each mode

**Reset Behavior by Mode**:
| Mode | On Night Session Cap | On Loss |
|------|---------------------|---------|
| OFF | N/A (no night trades) | Reset all |
| SOFT | Reset night_streak only | Reset all |
| HARD | Reset all streaks + series | Reset all |

**Files Created**:
- `src/tests/test_night_session_mode.py`

**Files Modified**:
- `src/domain/enums.py`
- `src/services/day_night_config.py`
- `src/services/stats_service.py`
- `src/adapters/telegram/bot.py`
- `CHANGE_LOG.md`
- `CONFIG_CONTRACT.md`

**Reason**: User request - Enable quick switching between night trading behaviors.

**Behavior Changed**: Yes
- Night session reset now respects NightSessionMode (SOFT vs HARD)
- User can toggle mode via Telegram /settings → Night Mode
- Mode persists and applies immediately

---

## 2026-01-21: Production QA Verification

**Change**: Comprehensive end-to-end QA verification of all MARTIN components.

**Details**:
- Verified all 137 tests passing
- Verified all imports work correctly
- Tested database migrations apply cleanly
- Tested repository CRUD operations
- Verified state machine transitions match STATE_MACHINE.md
- Tested day/night configuration with wrap-around midnight
- Tested Night Session Mode (OFF/SOFT/HARD) toggles
- Verified encryption/decryption with AES-256-GCM
- Tested status indicators (Series Active, Polymarket Auth)
- Confirmed Memory Gate MG-1 through MG-12 compliance

**QA Results**:
- 137 tests: ✅ ALL PASSING
- Repository layer: ✅ WORKING
- State machine: ✅ CORRECT
- Day/Night config: ✅ WORKING
- Night Session Mode: ✅ WORKING
- Security components: ✅ WORKING
- Status indicators: ✅ WORKING

**Memory Gate Compliance Verified**:
- MG-1: Streak counts only taken+filled trades ✅
- MG-2: CAP_PASS ignores ticks before confirm_ts ✅
- MG-3: confirm_ts = signal_ts + delay ✅
- MG-4: EMA20 1m 2-bar confirm signal rules ✅
- MG-5: Quality formula with components ✅
- MG-6: Day/Night mode behavior ✅
- MG-7: BASE/STRICT auto-switch ✅
- MG-8: All parameters configurable ✅
- MG-9: Paper mode default (safety) ✅
- MG-10: No secrets in code ✅
- MG-11: No regression in existing tests ✅
- MG-12: SQLite schema integrity ✅

**Reason**: Production readiness verification per user request.

**Behavior Changed**: No (QA verification only)

---

## 2026-01-21: Production-Like QA Expansion

**Change**: Added comprehensive production-like QA tests (smoke, scheduler, E2E integration).

**Details**:
- Created `src/tests/test_smoke.py`:
  - Bootstrap and config validation tests
  - DB initialization and migrations tests
  - Stats singleton verification
  - Module import tests
- Created `src/tests/test_scheduler.py`:
  - Scheduler instantiation tests
  - Job registration tests
  - Job invocation with mocked APIs
- Created `src/tests/test_e2e_day_flow.py`:
  - Complete day flow: discovery → signal → OK → CAP_PASS → execute → WIN
  - Quality fail scenario
  - User SKIP scenario
  - Mocked Gamma/Binance/CLOB APIs
- Created `src/tests/test_e2e_night_flow.py`:
  - SOFT_RESET behavior verification
  - HARD_RESET behavior verification
  - OFF mode verification
  - Loss reset behavior
- Created `src/tests/test_e2e_edge_cases.py`:
  - LATE confirm (confirm_ts >= end_ts) - MG-3
  - CAP_FAIL (never reaches min_ticks) - MG-2
  - Ticks before confirm_ts ignored - MG-2
  - Auth gating (live mode without master key)
  - Logout clears authorization
- Created `QA_REPORT.md`:
  - Test commands
  - Smoke tests summary
  - Scheduler wiring summary
  - E2E scenarios covered
  - Memory Gate compliance matrix
  - Security verification
  - Known limitations

**Test Count**: 157 total
- 137 original unit tests
- 4 smoke tests
- 4 scheduler tests
- 6 E2E day flow tests
- 6 E2E night flow tests

**Files Created**:
- `src/tests/test_smoke.py`
- `src/tests/test_scheduler.py`
- `src/tests/test_e2e_day_flow.py`
- `src/tests/test_e2e_night_flow.py`
- `src/tests/test_e2e_edge_cases.py`
- `QA_REPORT.md`

**Files Modified**:
- `CHANGE_LOG.md`

**Reason**: Production-like QA verification per user request - expand test coverage beyond unit tests.

**Behavior Changed**: No (test additions only)

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
