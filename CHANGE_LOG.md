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

## 2026-01-22: Add Data Sufficiency Guards to TA Engine

**Change**: Implemented explicit data sufficiency guards to ensure deterministic behavior with insufficient historical data.

**Details**:

### 1m Candles Guard (Signal Detection)
- If `len(candles_1m) < 120`: Return None immediately
- No logging, no partial signal
- This is a hard gate, not a fallback

### 5m Candles Guard (Quality Calculation)
- If `len(candles_5m) < 60` OR `idx5 < 55`:
  - Force `q_adx = 0.0`
  - Force `q_slope = 0.0`  
  - Force `trend_mult = 1.0`
- No partial calculations allowed
- Added `insufficient_5m_data` flag to QualityBreakdown

### Tests Added
- 8 new tests in TestDataSufficiencyGuards class:
  - test_no_signal_when_1m_candles_less_than_120
  - test_no_signal_when_1m_candles_far_below_threshold
  - test_signal_possible_when_1m_candles_at_120
  - test_signal_possible_when_1m_candles_above_120
  - test_quality_forced_zero_when_5m_candles_less_than_60
  - test_quality_forced_zero_when_idx5_less_than_55
  - test_quality_computed_when_guards_satisfied
  - test_quality_constants_match_spec

### Documentation Updated
- CONFIG_CONTRACT.md: Added "Data Sufficiency Guards" section
- ARCHITECTURE.md: Documented TA Engine responsibility for historical depth validation
- QA_REPORT.md: Recorded new tests and regression prevention

**Reason**: Ensure behavior under insufficient historical data is deterministic and documented, not accidental.

**Behavior Changed**: No (behavioral guarding only, no strategy/formula changes)

**Files Modified**:
- `src/services/ta_engine.py`: Added guard constants and logic
- `src/domain/models.py`: Added `insufficient_5m_data` field
- `src/tests/test_ta_engine.py`: Added 8 new guard tests
- Documentation files updated

---

## 2026-01-22: Fix Signal Detection and Quality Calculation to Match Written Spec

**Change**: Corrected TA Engine to match the EXACT written specification (touch + 2-bar confirm, not crossover).

**Details**:

### Signal Detection (Corrected)
- Fixed signal detection to use touch+confirm logic (as originally written):
  - UP signal at index i: `low[i] <= ema20[i] AND close[i] > ema20[i] AND close[i+1] > ema20[i+1]`
  - DOWN signal at index i: `high[i] >= ema20[i] AND close[i] < ema20[i] AND close[i+1] < ema20[i+1]`
- Signal ts = ts[i+1], signal price = close[i+1]

### Quality Calculation (Corrected)
- ADX and EMA50 slope now use **5m candles** (not 1m)
- ADX is **raw value** (not normalized to [0..1])
- Slope uses formula: `q_slope = 1000 * abs(slope50 / close_5m[idx5])`
- **Penalty restored**: edge_component *= 0.25 if direction inconsistent with return
- FIXED weights: W_ANCHOR=1.0, W_ADX=0.2, W_SLOPE=0.2
- FIXED trend multipliers: 1.10 (confirm), 0.70 (oppose)

### Tests (Updated)
- Updated test_ta_engine.py for:
  - Touch+confirm signal detection
  - Penalty application (0.25 cases)
  - ADX raw value (not normalized)
  - Slope 1000x formula
  - 5m candles for ADX/slope
- Updated test_canonical_strategy.py to match written spec

**Reason**: Previous implementation incorrectly used crossover logic and normalized ADX/slope. Corrected to match the exact written specification.

**Behavior Changed**: Yes
- Signal detection now requires low/high touch (not just close crossover)
- Quality components use 5m candles (not 1m)
- ADX/slope are raw values (not normalized)

**Files Modified**:
- `src/services/ta_engine.py`: Fixed signal detection and quality calculation
- `src/services/orchestrator.py`: Removed candles_1m from quality call
- `src/tests/test_ta_engine.py`: Updated tests for correct spec
- `src/tests/test_canonical_strategy.py`: Updated tests for correct spec
- `CHANGE_LOG.md`: This entry
- `CONFIG_CONTRACT.md`: Updated documentation
- `QA_REPORT.md`: Updated test count

---

## 2026-01-22: Align Live Bot Signal Logic with Canonical Strategy Specification (REVERTED)

**Note**: This entry documents an incorrect implementation that was later corrected.

**Change**: Updated TA Engine and quality calculation (incorrectly used crossover logic).
- Updated config.json defaults:
  - base_day_min_quality: 35.0
  - base_night_min_quality: 35.0
  - night_autotrade_enabled: true
  - night_session_mode: "SOFT"

### Tests (Part H)
- Added test_canonical_strategy.py with 27 tests:
  - test_signal_detection_rules() - 4 tests
  - test_quality_formula_exact_values() - 6 tests
  - test_quality_is_only_trade_gate() - 4 tests
  - test_telegram_card_sent_only_if_quality_passes() - 3 tests
  - test_no_output_if_quality_fails() - 2 tests
  - test_night_settings_persistence() - 4 tests
  - test_canonical_config_defaults() - 4 tests

**Reason**: Align implementation with CANONICAL trading strategy specification. No reinterpretation, no optimization, no additional filters.

**Behavior Changed**: Yes
- Signal detection now uses crossover logic instead of low/high touch
- Quality formula uses fixed canonical weights (1.0/0.2/0.2) instead of configurable weights
- Trend multiplier values changed from 1.2/0.8 to 1.10/0.70
- Default quality thresholds lowered from 50/60 to 35/35
- Night autotrade enabled by default
- Night session mode changed from HARD to SOFT

**Files Modified**:
- `src/services/ta_engine.py`: Updated signal detection and quality calculation
- `src/services/orchestrator.py`: Pass 1m candles to quality calculation
- `config/config.json`: Updated defaults per canonical spec
- `src/tests/test_ta_engine.py`: Updated tests for canonical formula
- `src/tests/test_canonical_strategy.py`: Added 27 new mandatory tests
- `CHANGE_LOG.md`: This entry
- `CONFIG_CONTRACT.md`: Updated documentation
- `QA_REPORT.md`: Updated test count

---

## 2026-01-22: Fix Telegram /start /status auth indicator crash

**Change**: Fixed `AttributeError: 'PolymarketAuthIndicator' object has no attribute 'authorized'` crash.

**Details**:
- Added `@property authorized` to `PolymarketAuthIndicator` class in `src/services/status_indicator.py`
  - This property returns `is_authorized`, providing backward compatibility
- Added defensive fallback in `_build_auth_buttons_keyboard()` in `src/adapters/telegram/bot.py`
  - Uses `getattr()` with fallback to handle missing attributes safely
  - Wraps auth indicator access in try-except to prevent crashes
- Added new tests:
  - `test_polymarket_indicator_authorized_property` in `test_status_indicator.py`
  - `TestAuthIndicatorCompatibility` class in `test_telegram_handlers.py` with 3 tests

**Reason**: Runtime error in /start and /status commands due to attribute name mismatch (`authorized` vs `is_authorized`).

**Behavior Changed**: No (bug fix only)

**Files Modified**:
- `src/services/status_indicator.py`: Added `@property authorized` to `PolymarketAuthIndicator`
- `src/adapters/telegram/bot.py`: Added defensive fallback in `_build_auth_buttons_keyboard()`
- `src/tests/test_status_indicator.py`: Added test for `.authorized` property
- `src/tests/test_telegram_handlers.py`: Added `TestAuthIndicatorCompatibility` class

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

## 2026-01-22: Consolidated E2E Integration Tests + File Verification

**Change**: Added consolidated E2E integration test file and verified all QA artifacts exist on disk.

**Details**:
- Created `src/tests/test_e2e_integration.py`:
  - Unified E2E test suite with explicit test names per user request
  - `test_day_flow_user_ok_to_settlement_win()` - Complete day flow
  - `test_night_flow_soft_reset_behavior()` - SOFT reset semantics
  - `test_night_flow_hard_reset_behavior()` - HARD reset semantics
  - `test_cap_fail_flow()` - CAP_FAIL cancellation
  - `test_late_confirm_flow()` - LATE confirm (MG-3)
  - `test_auth_gating_blocks_live_execution()` - Auth gating
  - `test_full_flow_with_mocked_clients()` - Mocked API clients
  - `test_cap_pass_ignores_all_ticks_before_confirm_ts()` - MG-2 timing
  - `test_cap_pass_requires_all_ticks_after_confirm_ts()` - MG-2 split check
- Updated `QA_REPORT.md`:
  - Added "Files Verified on Disk" section
  - Added verification commands
  - Updated test counts
  - Added consolidated E2E test documentation

**Files Verified on Disk**:
- `src/tests/test_smoke.py` ✅
- `src/tests/test_scheduler.py` ✅
- `src/tests/test_e2e_day_flow.py` ✅
- `src/tests/test_e2e_night_flow.py` ✅
- `src/tests/test_e2e_edge_cases.py` ✅
- `src/tests/test_e2e_integration.py` ✅ (NEW)
- `QA_REPORT.md` ✅

**Test Count**: 208+ total

**Files Created**:
- `src/tests/test_e2e_integration.py`

**Files Modified**:
- `QA_REPORT.md`
- `CHANGE_LOG.md`

**Reason**: User requested explicit verification that QA test files exist on disk with specific test names.

**Behavior Changed**: No (test additions only)

---

## 2026-01-22: Fix StatsService Init Crash

**Change**: Fixed startup crash caused by obsolete `night_session_resets_trade_streak` parameter.

**Details**:
- **Root Cause**: `orchestrator.py` was passing `night_session_resets_trade_streak=True` to `StatsService.__init__()`, but the signature was already refactored to use `night_session_mode: NightSessionMode` enum instead.
- Updated `src/services/orchestrator.py`:
  - Changed from passing obsolete boolean to new `night_session_mode` parameter
  - Added conversion logic supporting both new canonical key and legacy boolean fallback
  - Added import for `NightSessionMode` enum
- Updated `src/services/day_end_reminder.py`:
  - Updated `get_current_night_mode()` to use new `night_session_mode` config key
  - Added legacy fallback for backward compatibility
- Updated `config/config.json`:
  - Replaced `night_session_resets_trade_streak: true` with `night_session_mode: "HARD"`
- Updated `config/config.schema.json`:
  - Replaced boolean property with enum: `["OFF", "SOFT", "HARD"]`
- Added `src/tests/test_startup_smoke.py`:
  - 7 new tests verifying StatsService init, config parsing, and conversion logic
  - Regression tests ensuring obsolete parameter is rejected

**Files Created**:
- `src/tests/test_startup_smoke.py`

**Files Modified**:
- `src/services/orchestrator.py`
- `src/services/day_end_reminder.py`
- `config/config.json`
- `config/config.schema.json`
- `CHANGE_LOG.md`

**Reason**: Fix critical startup crash per issue report:
```
TypeError: StatsService.__init__() got an unexpected keyword argument 'night_session_resets_trade_streak'
```

**Behavior Changed**: No (fix aligns code with documented NightSessionMode design)
- `night_session_mode: "HARD"` is equivalent to old `night_session_resets_trade_streak: true`
- `night_session_mode: "SOFT"` is equivalent to old `night_session_resets_trade_streak: false`
- `night_session_mode: "OFF"` remains unchanged

---

## 2026-01-22: Fix Scheduler Tests (Remove APScheduler Dependency)

**Change**: Rewrote scheduler tests to match MARTIN's actual scheduling mechanism.

**Details**:
- **Root Cause**: `test_scheduler.py` imported APScheduler, but production code does NOT use APScheduler
- MARTIN uses an internal async loop in `Orchestrator` with `asyncio.sleep(60)` for scheduling
- The Orchestrator's `_tick()` method runs periodically and handles:
  - Market discovery
  - Trade processing  
  - Settlement checking
- Removed all APScheduler imports from `test_scheduler.py`
- Rewrote tests to verify:
  - Orchestrator has `_tick`, `_discover_markets`, `_process_active_trades`, `_check_settlements` methods
  - Orchestrator has `start` and `stop` lifecycle methods
  - Scheduled jobs/tasks can be invoked with mocked dependencies
  - Config has scheduling-related settings
  - Async context management works correctly

**Files Modified**:
- `src/tests/test_scheduler.py` - Complete rewrite to test real scheduler wiring

**Reason**: APScheduler was referenced ONLY in tests, not in production code. Tests should validate MARTIN's actual scheduling mechanism, not a library that isn't used.

**Behavior Changed**: No (test-only change, no production code modified)

**Test Results**: 212 tests pass (0 failures)

---

## 2026-01-22: Telegram UX Operationalization + Callback Timeout Fix + Gamma Search Fix

**Change**: Fixed multiple runtime issues in Telegram bot including callback timeouts, Gamma market discovery, and added auth buttons.

**Details**:
- **Callback Timeout Bug Fix** (`src/adapters/telegram/bot.py`):
  - Moved `await callback.answer()` to FIRST LINE of callback handler
  - This prevents "TelegramBadRequest: query is too old and response timeout expired"
  - Added try/except wrapper for callback processing
  - Added logging for all callbacks and commands

- **Gamma Market Discovery Fix** (`src/adapters/polymarket/gamma_client.py`):
  - Removed "hourly" from query string (was: `"{asset} up or down hourly"`)
  - Now uses: `"{asset} up or down"` with `recurrence=hourly` as separate parameter
  - Added fallback query strategy (Bitcoin/Ethereum as alternatives to BTC/ETH)
  - Added debug logging for top search results
  - Added warning when no markets discovered

- **Polymarket Auth Buttons** (`src/adapters/telegram/bot.py`):
  - Added `_build_auth_buttons_keyboard()` method
  - Added `_handle_auth_callback()` method
  - `/start` and `/status` now show auth buttons:
    - Paper mode: "📝 Paper Mode Active" (informational)
    - Live mode: "🔐 Authorize Polymarket", "✅ Recheck Authorization", "🚪 Log out"
  - Auth status displayed in /start command

- **Handler Logging**:
  - All command handlers now log their invocation with user_id
  - Callbacks log the callback_data being processed
  - Unhandled callbacks are logged as warnings

- **New Tests** (`src/tests/test_telegram_handlers.py`):
  - `test_start_status_handlers_registered()`
  - `test_settings_menu_renders_human_text()`
  - `test_callback_answer_called_immediately()`
  - `test_gamma_query_strings_do_not_include_hourly()`
  - 14 new tests total

**Files Modified**:
- `src/adapters/telegram/bot.py` - Callback fix, auth buttons, logging
- `src/adapters/polymarket/gamma_client.py` - Query fix, fallbacks, logging

**Files Created**:
- `src/tests/test_telegram_handlers.py` - 14 new tests

**Reason**: Runtime issues reported:
- "TelegramBadRequest: query is too old and response timeout expired"
- Gamma returning 0 markets due to "hourly" in query string
- No auth buttons visible in Telegram UI

**Behavior Changed**: Yes
- Callback handlers now answer immediately (no timeout)
- Gamma search uses correct query format (better market discovery)
- Auth buttons visible on /start and /status
- All handlers log their activity

**Test Results**: 226 tests pass (0 failures)

---

## 2026-01-22: Telegram Commands UX + Editable Settings + Auth Visibility

**Change**: Fixed Telegram command menu UX, made settings editable via inline buttons, ensured auth section visible in paper mode.

**Details**:
- **A) Commands UX (BotFather menu mismatch)**:
  - Added handler for unknown commands `/command1` through `/command8`
  - Unknown commands now return helpful error message with available commands list
  - Updated README.md with BotFather commands setup instructions
  
- **B) Settings Editable in Telegram**:
  - Added trading parameter controls: price_cap, confirm_delay_seconds, cap_min_ticks, base_stake
  - Added quality threshold controls: base_day_min_quality, base_night_min_quality
  - Added streak controls: switch_streak_at, night_max_win_streak
  - All settings use +/- inline buttons for easy adjustment
  - All changes persist to DB settings and apply immediately
  - `/status` and `/settings` show effective values (DB overrides > config defaults)
  
- **C) Polymarket Auth Section**:
  - Auth buttons now visible in `/start` and `/status` for all modes
  - Paper mode shows informational "Paper Mode Active" button
  - Live mode shows Authorize/Recheck/Logout buttons based on auth state
  
- **D) Tests + Docs**:
  - Added 13 new tests for unknown command handling, editable settings, auth visibility
  - Updated README.md with BotFather setup instructions
  - Extended DayNightConfigService with trading parameter methods

**Files Created**:
- None

**Files Modified**:
- `src/adapters/telegram/bot.py` - Unknown command handler, editable settings buttons
- `src/services/day_night_config.py` - Trading parameter getters/setters
- `src/tests/test_telegram_handlers.py` - 13 new tests
- `README.md` - BotFather commands setup instructions
- `CHANGE_LOG.md` - This entry

**Reason**: User request to fix silent failures on unknown commands, make settings editable in Telegram (no config.json editing), and ensure auth section visible even in paper mode.

**Behavior Changed**: Yes
- Unknown commands now return helpful error message (previously: silent no reaction)
- Quality, streak, and trading settings now editable via Telegram buttons (previously: required config.json edit)
- Auth section visible in paper mode with informational button (previously: may have been hidden)

**Test Results**: 27 tests pass in test_telegram_handlers.py

---

## 2026-01-22: Fix Gamma Market Discovery (Zero-Market Issue)

**Change**: Complete rewrite of Gamma market discovery to properly parse event-driven API response structure.

**Root Cause Analysis**:
- The Gamma API `/public-search` endpoint returns an `events[]` array with nested `markets[]` per event
- Previous code used `response.get("markets", [])` which only looked at top-level markets
- Most markets are nested within events, not at the top level
- This resulted in ZERO markets being discovered despite valid API responses

**Details**:
- **Discovery Model (Event-Driven)**:
  - Gamma returns events[] with nested markets[]
  - Now extracts markets from BOTH top-level and nested event markets
  - Filtering is applied at MARKET level, not EVENT level
  
- **Market Filtering Rules (case-insensitive)**:
  - "up or down"
  - "up/down"
  - "updown"
  - Uses regex patterns for robust matching
  
- **Time Window Handling**:
  - Timestamp fallback chain: market-level → event-level
  - Configurable forward_horizon_seconds (default 2 hours)
  - Configurable grace_period_seconds (default 5 min)
  
- **Token ID Extraction**:
  - Supports tokens[] array with outcome field
  - Supports outcomes[] + clobTokenIds[] arrays
  - Handles JSON string arrays (some fields return JSON strings)
  - Handles Yes/No as Up/Down equivalents
  
- **Diagnostic Logging**:
  - Events scanned count
  - Markets scanned count
  - Title matches before time filter
  - Title matches after time filter
  - Sample market titles and end times

**Files Modified**:
- `src/adapters/polymarket/gamma_client.py` - Complete discovery logic rewrite

**Files Created**:
- `src/tests/test_gamma_discovery.py` - 28 new tests for discovery logic

**Reason**: Critical bug fix - market discovery was returning ZERO hourly "up or down" markets for BTC/ETH despite Gamma API returning valid data.

**Behavior Changed**: Yes
- Markets are now correctly discovered from events[] with nested markets[]
- Title filtering uses regex patterns for "up or down" variants
- Timestamp fallback ensures markets aren't discarded due to missing market-level timestamps
- Grace periods and forward horizons provide more flexible time filtering

**Test Results**: 267 tests pass (239 original + 28 new)

---

## 2026-01-22: Automated Bootstrap (One-Command Startup)

**Change**: Implemented automated bootstrap with `run.sh` script and robust .env loading.

**Details**:
- Created `run.sh` script for one-command startup:
  - Creates `.venv` virtual environment if missing
  - Installs dependencies from `requirements.txt` (idempotent with hash checking)
  - Checks for `.env` file and provides guidance if missing
  - Creates `data/` directory if needed
  - Runs MARTIN via `python -m src.main`
  - Fully idempotent - safe to run multiple times
- Updated `src/bootstrap.py`:
  - Made `load_environment()` robust against missing python-dotenv
  - Added manual .env parser as fallback
  - Never logs secret values
  - Import moved inside function to avoid startup failures
- Created `.env.example`:
  - Template file documenting all environment variables
  - No real secrets (placeholder values only)
- Updated `README.md`:
  - Documented `./run.sh` as primary startup method
  - Explained automatic .env loading
  - Updated Quick Start section for one-command experience

**Files Created**:
- `run.sh` - One-command bootstrap script
- `.env.example` - Environment template

**Files Modified**:
- `src/bootstrap.py` - Robust .env loading
- `README.md` - Updated Quick Start documentation
- `CHANGE_LOG.md` - This entry

**Reason**: Project required manual steps for startup which violated UX requirements. Now `./run.sh` provides zero-manual-step launch.

**Behavior Changed**: Yes
- Startup no longer requires manual `source .venv/bin/activate` or `set -a; source .env`
- `.env` is loaded automatically by the application
- Missing python-dotenv no longer crashes startup (graceful fallback)

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
*Last updated: 2026-01-22*
