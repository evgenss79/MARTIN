# MARTIN — State Machine

> Authoritative definition of trade lifecycle.
> This document is sufficient to rebuild the trade engine without reading code.

---

## TradeStatus Enum

| Status | Description |
|--------|-------------|
| `NEW` | Trade record created for a market window. Initial state before signal search begins. |
| `SEARCHING_SIGNAL` | Trade is actively scanning for a qualifying signal within the window. TA re-evaluated each tick. |
| `SIGNALLED` | TA engine detected a valid signal with quality >= threshold. |
| `WAITING_CONFIRM` | Quality passed threshold. Waiting for `confirm_ts`. |
| `WAITING_CAP` | `confirm_ts` reached. Waiting for CAP_PASS. |
| `READY` | CAP_PASS achieved. Ready for user confirmation (Day) or execution (Night). |
| `ORDER_PLACED` | Order submitted. Waiting for fill and settlement. |
| `SETTLED` | **Terminal**. Trade completed. Win/loss recorded. |
| `CANCELLED` | **Terminal**. Trade cancelled for a specific reason. |
| `ERROR` | **Terminal**. Trade failed due to error. |

---

## State Transition Table

| Current State | Event | Next State | Notes |
|---------------|-------|------------|-------|
| `NEW` | Start signal search | `SEARCHING_SIGNAL` | Begin scanning for signals |
| `NEW` | Signal detected (legacy) | `SIGNALLED` | Backward compatibility |
| `NEW` | No signal found | `CANCELLED` | Reason: NO_SIGNAL |
| `NEW` | Window expired | `CANCELLED` | Reason: EXPIRED |
| `NEW` | Bot paused | `CANCELLED` | Reason: PAUSED |
| `SEARCHING_SIGNAL` | Signal with quality >= threshold | `SIGNALLED` | Qualifying signal found |
| `SEARCHING_SIGNAL` | Signal with quality < threshold | (stay) | Remain, better signal may appear |
| `SEARCHING_SIGNAL` | No signal detected | (stay) | Re-evaluate next tick |
| `SEARCHING_SIGNAL` | Window expired | `CANCELLED` | Reason: NO_SIGNAL or EXPIRED |
| `SIGNALLED` | Quality >= threshold | `WAITING_CONFIRM` | Wait for confirm_ts |
| `SIGNALLED` | Quality < threshold | `CANCELLED` | Reason: LOW_QUALITY |
| `SIGNALLED` | confirm_ts >= end_ts | `CANCELLED` | Reason: LATE |
| `SIGNALLED` | Window expired | `CANCELLED` | Reason: EXPIRED |
| `WAITING_CONFIRM` | confirm_ts reached | `WAITING_CAP` | Begin CAP check |
| `WAITING_CONFIRM` | Window expired | `CANCELLED` | Reason: EXPIRED |
| `WAITING_CONFIRM` | Bot paused | `CANCELLED` | Reason: PAUSED |
| `WAITING_CAP` | CAP_PASS | `READY` | Price validated |
| `WAITING_CAP` | CAP_FAIL | `CANCELLED` | Reason: CAP_FAIL |
| `WAITING_CAP` | LATE (confirm_ts >= end_ts) | `CANCELLED` | Reason: LATE |
| `WAITING_CAP` | Window expired | `CANCELLED` | Reason: EXPIRED |
| `READY` | User OK (Day mode) | `ORDER_PLACED` | Order submitted |
| `READY` | User SKIP (Day mode) | `CANCELLED` | Reason: SKIP |
| `READY` | No response timeout (Day) | `CANCELLED` | Reason: EXPIRED (auto-skip) |
| `READY` | AUTO_OK (Night mode) | `ORDER_PLACED` | Order submitted |
| `READY` | Night disabled | `CANCELLED` | Reason: NIGHT_DISABLED |
| `READY` | Window expired | `CANCELLED` | Reason: EXPIRED |
| `ORDER_PLACED` | Order filled + settled | `SETTLED` | Final PnL recorded |
| `ORDER_PLACED` | Order rejected | `ERROR` | Fill failed |
| `SETTLED` | — | — | Terminal state |
| `CANCELLED` | — | — | Terminal state |
| `ERROR` | — | — | Terminal state |

---

## SEARCHING_SIGNAL Behavior (In-Window Signal Scanning)

The `SEARCHING_SIGNAL` status implements continuous signal scanning within an active window:

1. **Entry**: Trade created when window is discovered → transitions to `SEARCHING_SIGNAL`
2. **Each Tick**:
   - Check if window expired → `CANCELLED` (NO_SIGNAL)
   - Fetch latest candle data from TA snapshot cache
   - Run TA signal detection (BLACK BOX - unchanged)
   - If no signal → remain in `SEARCHING_SIGNAL`, try again next tick
   - If signal found but quality < threshold → remain in `SEARCHING_SIGNAL` (better may appear)
   - If signal found with quality >= threshold → persist Signal, transition to `SIGNALLED`
3. **Exit**: Either `SIGNALLED` (success) or `CANCELLED` (no qualifying signal before window end)

This fixes Defect A: signals appearing later inside the window are now detected.

---

## Terminal States

These states are **final**. No transitions out.

| State | Meaning |
|-------|---------|
| `SETTLED` | Trade completed successfully (win or loss) |
| `CANCELLED` | Trade cancelled for a valid reason |
| `ERROR` | Trade failed due to system error |

---

## Forbidden Transitions

The following transitions are **NEVER allowed**:

| From | To | Why |
|------|----|-----|
| `SETTLED` | Any | Terminal |
| `CANCELLED` | Any | Terminal |
| `ERROR` | Any | Terminal |
| `NEW` | `READY` | Must go through signal detection |
| `NEW` | `ORDER_PLACED` | Must validate first |
| `SIGNALLED` | `ORDER_PLACED` | Must confirm and CAP check first |
| `WAITING_CONFIRM` | `READY` | Must CAP check first |
| `WAITING_CAP` | `ORDER_PLACED` | Must be READY first |

---

## Day/Night Mode Effects

### Day Mode (DAY_START_HOUR ≤ hour < DAY_END_HOUR)

- When `READY`: Trade card sent to Telegram
- User must click ✅ OK to proceed to `ORDER_PLACED`
- User can click ❌ SKIP to go to `CANCELLED`
- No automatic execution

### Night Mode (outside day hours)

- If `night_autotrade_enabled = false`:
  - All trades auto-cancelled with reason `NIGHT_DISABLED`
- If `night_autotrade_enabled = true`:
  - When `READY`: Auto-proceeds to `ORDER_PLACED` with `AUTO_OK`
  - Night streak is tracked
  - When `night_streak >= NIGHT_MAX_WIN_STREAK`:
    - Night session resets
    - `night_streak = 0`
    - `policy_mode = BASE`
    - Optionally resets `trade_level_streak` (configurable)

---

## CAP_PASS as Gate

The transition `WAITING_CAP → READY` requires:

1. Ticks fetched for `[confirm_ts, end_ts]`
2. At least `CAP_MIN_TICKS` consecutive ticks where `price ≤ PRICE_CAP`
3. All ticks before `confirm_ts` are **IGNORED** (MG-2)

If these conditions are not met by `end_ts`:
- Status → `CANCELLED`
- Reason → `CAP_FAIL`

---

## Decision Field Values

| Decision | Meaning |
|----------|---------|
| `PENDING` | Awaiting user or system decision |
| `OK` | User confirmed (Day mode) |
| `AUTO_OK` | System auto-confirmed (Night mode) |
| `SKIP` | User skipped (Day mode) |
| `AUTO_SKIP` | System auto-skipped (low quality, no signal, etc.) |

---

## Cancel Reasons

| Reason | When Used |
|--------|-----------|
| `NO_SIGNAL` | TA engine found no valid signal |
| `LOW_QUALITY` | Quality < threshold |
| `SKIP` | User clicked SKIP |
| `EXPIRED` | Window ended before completion |
| `LATE` | `confirm_ts >= end_ts` |
| `CAP_FAIL` | Price never met CAP conditions |
| `PAUSED` | Bot was paused |
| `NIGHT_DISABLED` | Night trading not enabled |

---

## State Machine Implementation

Located in: `src/services/state_machine.py`

Key class: `TradeStateMachine`

Key methods:
- `can_transition(trade, new_status)` → bool
- `transition(trade, new_status, reason)` → Trade
- Event handlers: `on_signal()`, `on_cap_pass()`, `on_user_ok()`, etc.

Valid transitions defined in `VALID_TRANSITIONS` dict.

---

*This file is the authoritative state machine reference for project MARTIN.*
*Last updated: 2026-01-21*
