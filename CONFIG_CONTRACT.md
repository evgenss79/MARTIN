# MARTIN — Configuration Contract

> All configurable parameters documented.
> If logic depends on a value, it MUST be configurable.

---

## Configuration Sources

1. **Primary**: `config/config.json`
2. **Schema**: `config/config.schema.json`
3. **Environment overrides**: `.env` file
4. **Runtime overrides**: `settings` table in database

Priority: Runtime > Environment > Config file

---

## Section: app

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `app.timezone` | string | "Europe/Zurich" | Timezone for day/night determination |
| `app.log_level` | string | "INFO" | Log level: DEBUG, INFO, WARNING, ERROR |
| `app.log_format` | string | "json" | Log format: json, text |

**Environment Override**: `LOG_LEVEL`, `TIMEZONE`

---

## Section: trading

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `trading.assets` | array | ["BTC", "ETH"] | — | Assets to trade |
| `trading.window_seconds` | int | 3600 | ≥ 60 | Market window duration |
| `trading.price_cap` | float | 0.55 | 0.01–1.0 | ⚠️ Maximum price for CAP_PASS |
| `trading.confirm_delay_seconds` | int | 120 | ≥ 0 | ⚠️ Delay after signal before CAP check |
| `trading.cap_min_ticks` | int | 3 | ≥ 1 | ⚠️ Consecutive ticks needed for CAP_PASS |

**Safety-Critical** (⚠️):
- `price_cap`: Lower = stricter filtering
- `confirm_delay_seconds`: Higher = more confirmation time
- `cap_min_ticks`: Higher = more consecutive price validation

---

## Section: day_night

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `day_night.day_start_hour` | int | 8 | 0–23 | Day mode start (local timezone) |
| `day_night.day_end_hour` | int | 22 | 0–23 | Day mode end (local timezone) |
| `day_night.base_day_min_quality` | float | 50.0 | ≥ 0 | ⚠️ Minimum quality for day BASE mode |
| `day_night.base_night_min_quality` | float | 60.0 | ≥ 0 | ⚠️ Minimum quality for night BASE mode |
| `day_night.switch_streak_at` | int | 3 | ≥ 1 | Streak count to trigger STRICT mode |
| `day_night.strict_day_q` | string | "p95" | p90/p95/p97/p99 | Quantile for STRICT day threshold |
| `day_night.strict_night_q` | string | "p95" | p90/p95/p97/p99 | Quantile for STRICT night threshold |
| `day_night.night_max_win_streak` | int | 5 | ≥ 1 | ⚠️ Max night wins before session reset |
| `day_night.night_autotrade_enabled` | bool | false | — | ⚠️ Enable autonomous night trading |
| `day_night.night_session_mode` | string | "OFF" | OFF/SOFT/HARD | ⚠️ Night session reset behavior |
| `day_night.reminder_minutes_before_day_end` | int | 30 | 0–180 | Reminder minutes (0=disabled) |

**Night Session Mode** (⚠️ Safety-Critical):
- `OFF`: Night trading disabled. Series freezes overnight.
- `SOFT`: On night session cap, reset only night_streak. Trade-level streak continues.
- `HARD`: On night session cap, reset ALL streaks and series counters.

**Safety-Critical** (⚠️):
- `night_autotrade_enabled`: Only enable when confident in system
- `night_max_win_streak`: Caps autonomous trading risk
- `night_session_mode`: Controls reset behavior on session cap
- Quality thresholds: Control trade selectivity

---

## Section: ta

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `ta.warmup_seconds` | int | 7200 | ≥ 0 | Historical data for indicator warmup |
| `ta.adx_period` | int | 14 | ≥ 1 | ADX calculation period |
| `ta.ema50_slope_bars` | int | 5 | ≥ 1 | Bars for EMA50 slope calculation |
| `ta.anchor_scale` | float | 10000.0 | > 0 | Scale factor for anchor edge |
| `ta.w_anchor` | float | 0.3 | 0–1 | Weight for anchor edge component |
| `ta.w_adx` | float | 0.4 | 0–1 | Weight for ADX component |
| `ta.w_slope` | float | 0.3 | 0–1 | Weight for slope component |
| `ta.trend_bonus` | float | 1.2 | ≥ 1 | Multiplier when trend confirms |
| `ta.trend_penalty` | float | 0.8 | 0–1 | Multiplier when trend opposes |

**Note**: `w_anchor + w_adx + w_slope` should equal 1.0 for normalized quality.

---

## Section: apis

### Gamma API
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `apis.gamma.base_url` | string | "https://gamma-api.polymarket.com" | API endpoint |
| `apis.gamma.timeout` | int | 30 | Request timeout (seconds) |
| `apis.gamma.retries` | int | 3 | Retry attempts |
| `apis.gamma.backoff` | float | 2.0 | Backoff multiplier |

### CLOB API
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `apis.clob.base_url` | string | "https://clob.polymarket.com" | API endpoint |
| `apis.clob.timeout` | int | 30 | Request timeout (seconds) |
| `apis.clob.retries` | int | 3 | Retry attempts |
| `apis.clob.backoff` | float | 2.0 | Backoff multiplier |

### Binance API
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `apis.binance.base_url` | string | "https://api.binance.com" | API endpoint |
| `apis.binance.timeout` | int | 30 | Request timeout (seconds) |
| `apis.binance.retries` | int | 3 | Retry attempts |
| `apis.binance.backoff` | float | 2.0 | Backoff multiplier |

---

## Section: telegram

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `telegram.admin_user_ids` | array | [] | ⚠️ Authorized Telegram user IDs |
| `telegram.message_rate_limit_per_minute` | int | 20 | Messages per minute limit |

**Safety-Critical** (⚠️):
- `admin_user_ids`: Only listed users can control the bot

**Environment Variables** (not in config):
- `TELEGRAM_BOT_TOKEN`: Bot authentication token (REQUIRED)

---

## Section: storage

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `storage.driver` | string | "sqlite" | Storage driver type |
| `storage.dsn` | string | "sqlite:///data/martin.db" | Database connection string |

---

## Section: risk

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `risk.stake.mode` | string | "fixed" | Stake calculation mode |
| `risk.stake.base_amount_usdc` | float | 10.0 | ⚠️ Base stake amount in USDC |

**Safety-Critical** (⚠️):
- `base_amount_usdc`: Controls trade size

---

## Section: execution

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `execution.mode` | string | "paper" | ⚠️ Execution mode: paper or live |
| `execution.live.chain_id` | int | 137 | Polygon chain ID |
| `execution.live.order_timeout_seconds` | int | 30 | Order timeout |
| `execution.live.max_slippage` | float | 0.02 | Maximum slippage allowed |

**Safety-Critical** (⚠️):
- `execution.mode`: 
  - `paper` (default): Simulates trades, no real orders
  - `live`: Places real orders (requires credentials)

**Environment Override**: `EXECUTION_MODE`

---

## Section: rolling_quantile

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `rolling_quantile.rolling_days` | int | 14 | ≥ 1 | Days in rolling window |
| `rolling_quantile.max_samples` | int | 500 | ≥ 1 | Maximum samples for quantile |
| `rolling_quantile.min_samples` | int | 50 | ≥ 1 | Minimum samples required |
| `rolling_quantile.strict_fallback_mult` | float | 1.25 | ≥ 1 | Fallback multiplier when insufficient samples |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram bot authentication token |
| `LOG_LEVEL` | No | Override config log level |
| `TIMEZONE` | No | Override config timezone |
| `EXECUTION_MODE` | No | Override execution mode |
| `MASTER_ENCRYPTION_KEY` | Recommended | ⚠️ Master key for encrypting secrets at rest (32 bytes, base64) |
| `POLYMARKET_PRIVATE_KEY` | For live | ⚠️ Wallet private key (MetaMask export) - Option 1 |
| `POLYMARKET_API_KEY` | For live | Polymarket API key - Option 2 |
| `POLYMARKET_API_SECRET` | For live | Polymarket API secret - Option 2 |
| `POLYMARKET_PASSPHRASE` | For live | Polymarket passphrase - Option 2 |

**Security-Critical** (⚠️):
- `MASTER_ENCRYPTION_KEY`: Enables encryption of secrets at rest (SEC-1). Generate with:
  ```
  python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
  ```

**Live Mode Authentication**:
- **Option 1 (Wallet)**: Set `POLYMARKET_PRIVATE_KEY` with your wallet private key
- **Option 2 (API Key)**: Set all three: `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_PASSPHRASE`
- If both are set, wallet-based auth takes priority
- If `MASTER_ENCRYPTION_KEY` is set, credentials are encrypted before persistence

---

## Security Configuration

### SEC-1: No Plaintext Secrets at Rest

When `MASTER_ENCRYPTION_KEY` is configured:
- Wallet private keys are encrypted using AES-256-GCM before storage
- Session tokens are encrypted before persistence
- API secrets are encrypted in the vault

### SEC-2: Master Key Handling

- Master key must be exactly 32 bytes (256 bits), base64 encoded
- If `MASTER_ENCRYPTION_KEY` is missing and `execution.mode == "live"`:
  - Live trading still works but with security warning
  - Credentials remain in environment only (not persisted encrypted)
- Master key should be:
  - Generated once and stored securely
  - Never committed to version control
  - Backed up securely (losing it means re-encrypting all secrets)

### SEC-3: Session Management

- One-time wallet authorization creates a session
- Sessions are cached (encrypted) for autonomous trades
- Default session expiry: 24 hours
- Sessions can be invalidated via Telegram commands

---

## Validation

Configuration is validated against `config/config.schema.json` at startup.

Invalid configuration will prevent the bot from starting.

---

## Runtime Modification

Settings can be changed at runtime via Telegram /settings with full interactive UI:

**Currently Implemented** (with Telegram UI):
- `day_start_hour`, `day_end_hour` - Hour selection grid (0-23)
- `night_autotrade_enabled` - Toggle button
- `night_session_mode` - OFF/SOFT/HARD selection
- `reminder_minutes_before_day_end` - Preset options (0-180 min)
- `base_day_min_quality`, `base_night_min_quality` - +/- buttons (±5, ±10)
- `switch_streak_at`, `night_max_win_streak` - +/- buttons (±1, ±2)
- `price_cap` - +/- buttons (±0.01, ±0.05) with validation 0.01-0.99
- `confirm_delay_seconds` - +/- buttons (±10s, ±30s)
- `cap_min_ticks` - +/- buttons (±1, ±2) with validation ≥1
- `base_amount_usdc` (stake) - +/- buttons (±$1, ±$5)

**Not Editable via Telegram** (requires config.json edit):
- `strict_day_q`, `strict_night_q` - Quantile selectors
- API endpoints and timeouts
- TA parameters (weights, periods)

Runtime changes are stored in the `settings` table and persist across restarts.

**Priority**: Database settings > Environment variables > config.json defaults

---

## Section: reminder (NEW)

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `day_night.reminder_minutes_before_day_end` | int | 30 | 0–180 | Minutes before day end to send reminder (0 = disabled) |

**Features**:
- Rate-limited: maximum one reminder per calendar day
- Timezone-aware (Europe/Zurich)
- Shows current night session mode with explanation
- Quick action buttons for night mode toggle

---

*This file is the authoritative configuration contract for project MARTIN.*
*Last updated: 2026-01-22*
