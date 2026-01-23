# MARTIN — Data Contracts

> Schema stability and data integrity guarantees.
> No field may be removed or repurposed without migration + update here.

---

## Entity: market_windows

**Purpose**: Stores Polymarket hourly market windows.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Auto-increment primary key |
| `asset` | TEXT | Yes | Asset symbol (BTC, ETH) |
| `slug` | TEXT | Yes (UNIQUE) | Polymarket market slug |
| `condition_id` | TEXT | Yes | Polymarket condition ID |
| `up_token_id` | TEXT | Yes | Token ID for UP outcome |
| `down_token_id` | TEXT | Yes | Token ID for DOWN outcome |
| `start_ts` | INTEGER | Yes | Window start (unix seconds) |
| `end_ts` | INTEGER | Yes | Window end (unix seconds) |
| `outcome` | TEXT | No | Resolved outcome (UP/DOWN) |
| `created_at` | TIMESTAMP | Yes | Record creation time |

**Invariants**:
- `end_ts > start_ts`
- `slug` is unique (one record per market)
- `outcome` is NULL until market resolves, then UP or DOWN

**Relationships**:
- One-to-many with `signals`
- One-to-many with `trades`

---

## Entity: signals

**Purpose**: Stores detected trading signals.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Auto-increment primary key |
| `window_id` | INTEGER | Yes (FK) | References market_windows(id) |
| `direction` | TEXT | Yes | Signal direction (UP/DOWN) |
| `signal_ts` | INTEGER | Yes | Signal timestamp (unix seconds) |
| `confirm_ts` | INTEGER | Yes | Confirmation timestamp |
| `quality` | REAL | Yes | Calculated quality score |
| `quality_breakdown` | TEXT | No | JSON breakdown of quality components |
| `anchor_bar_ts` | INTEGER | Yes | Anchor bar timestamp |
| `created_at` | TIMESTAMP | Yes | Record creation time |

**Invariants**:
- `confirm_ts = signal_ts + CONFIRM_DELAY_SECONDS`
- `direction` is either "UP" or "DOWN"
- `quality >= 0`
- One signal per window (at most)

**Relationships**:
- Many-to-one with `market_windows` (FK: window_id)
- One-to-one with `trades` (via trade.signal_id)

---

## Entity: trades

**Purpose**: Stores trade lifecycle records.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Auto-increment primary key |
| `window_id` | INTEGER | Yes (FK) | References market_windows(id) |
| `signal_id` | INTEGER | No (FK) | References signals(id) |
| `status` | TEXT | Yes | Trade status enum |
| `time_mode` | TEXT | No | DAY or NIGHT |
| `policy_mode` | TEXT | Yes | BASE or STRICT |
| `decision` | TEXT | Yes | Decision enum |
| `cancel_reason` | TEXT | No | Cancel reason enum |
| `token_id` | TEXT | No | Token ID traded |
| `order_id` | TEXT | No | Exchange order ID |
| `fill_status` | TEXT | Yes | Fill status enum |
| `fill_price` | REAL | No | Actual fill price |
| `stake_amount` | REAL | Yes | Trade size in USDC |
| `pnl` | REAL | No | Profit/loss |
| `is_win` | INTEGER | No | 1=win, 0=loss, NULL=pending |
| `trade_level_streak` | INTEGER | Yes | Streak at trade time |
| `night_streak` | INTEGER | Yes | Night streak at trade time |
| `created_at` | TIMESTAMP | Yes | Record creation time |
| `updated_at` | TIMESTAMP | Yes | Last update time |

**Invariants**:
- `status` is one of: NEW, SEARCHING_SIGNAL, SIGNALLED, WAITING_CONFIRM, WAITING_CAP, READY, ORDER_PLACED, SETTLED, CANCELLED, ERROR
- `decision` is one of: PENDING, OK, AUTO_OK, SKIP, AUTO_SKIP
- `fill_status` is one of: PENDING, FILLED, PARTIAL, REJECTED, CANCELLED
- `stake_amount >= 0`
- `is_win` is NULL until settled
- If `status = SETTLED`, then `is_win` and `pnl` are NOT NULL

**SEARCHING_SIGNAL Status**:
- Trade is actively scanning for a qualifying signal within the window
- TA is re-evaluated each tick until signal with quality >= threshold is found
- If window expires without qualifying signal, status becomes CANCELLED

**Relationships**:
- Many-to-one with `market_windows` (FK: window_id)
- Many-to-one with `signals` (FK: signal_id)
- One-to-one with `cap_checks` (via cap_checks.trade_id)

**Valid Record**:
A trade is valid if:
- `window_id` references existing window
- `status` is a valid enum value
- `stake_amount >= 0`

---

## Entity: cap_checks

**Purpose**: Stores CAP_PASS validation records.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Auto-increment primary key |
| `trade_id` | INTEGER | Yes (FK) | References trades(id) |
| `token_id` | TEXT | Yes | Token ID checked |
| `confirm_ts` | INTEGER | Yes | Check start time |
| `end_ts` | INTEGER | Yes | Window end time |
| `status` | TEXT | Yes | Cap status enum |
| `consecutive_ticks` | INTEGER | Yes | Count of consecutive valid ticks |
| `first_pass_ts` | INTEGER | No | Timestamp of first CAP_PASS |
| `price_at_pass` | REAL | No | Price when CAP_PASS achieved |
| `created_at` | TIMESTAMP | Yes | Record creation time |

**Invariants**:
- `status` is one of: PENDING, PASS, FAIL, LATE
- `consecutive_ticks >= 0`
- If `status = PASS`, then `first_pass_ts` is NOT NULL
- If `status = LATE`, then `confirm_ts >= end_ts`
- Only ticks in `[confirm_ts, end_ts]` are counted (MG-2)

**Relationships**:
- Many-to-one with `trades` (FK: trade_id)

---

## Entity: stats (Singleton)

**Purpose**: Global trading statistics. Always exactly one row with `id = 1`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Always 1 |
| `trade_level_streak` | INTEGER | Yes | Current trade-level win streak |
| `night_streak` | INTEGER | Yes | Current night session streak |
| `policy_mode` | TEXT | Yes | BASE or STRICT |
| `total_trades` | INTEGER | Yes | Total taken trades |
| `total_wins` | INTEGER | Yes | Total wins |
| `total_losses` | INTEGER | Yes | Total losses |
| `last_strict_day_threshold` | REAL | No | Cached day STRICT threshold |
| `last_strict_night_threshold` | REAL | No | Cached night STRICT threshold |
| `last_quantile_update_ts` | INTEGER | No | Last quantile calculation time |
| `is_paused` | INTEGER | Yes | Bot paused flag (0/1) |
| `day_only` | INTEGER | Yes | Day-only mode flag (0/1) |
| `night_only` | INTEGER | Yes | Night-only mode flag (0/1) |
| `updated_at` | TIMESTAMP | Yes | Last update time |

**Invariants**:
- `id = 1` always (singleton constraint)
- `trade_level_streak >= 0`
- `night_streak >= 0`
- `total_trades = total_wins + total_losses`
- `policy_mode` is either "BASE" or "STRICT"

**Singleton Guarantee**:
- Table has CHECK constraint: `id = 1`
- Only one row can exist

---

## Entity: settings

**Purpose**: Runtime configuration overrides.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | TEXT | Yes (PK) | Setting key |
| `value` | TEXT | Yes | Setting value (JSON or string) |
| `updated_at` | TIMESTAMP | Yes | Last update time |

**Invariants**:
- `key` is unique (primary key)
- `value` is never NULL

---

## Entity: migrations

**Purpose**: Track applied database migrations.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | INTEGER | Yes (PK) | Migration number |
| `applied_at` | TIMESTAMP | Yes | When migration was applied |

---

## Schema Change Rules

1. **Adding fields**: Add with DEFAULT value, update this document
2. **Removing fields**: NEVER remove. Deprecate instead.
3. **Renaming fields**: Create new field, migrate data, deprecate old
4. **Changing types**: Create migration, update this document

> **CRITICAL**: No field may be removed or repurposed without:
> - Database migration script
> - Update to this document
> - Update to CHANGE_LOG.md

---

*This file is the authoritative data contract for project MARTIN.*
*Last updated: 2026-01-21*
