# MARTIN — Non-Negotiable Rules

> Human-readable trading logic sanity checklist.
> Review before any refactor or major change.

---

## Signal Detection Rules

### ✅ EMA20 on 1m with 2-bar confirmation

**Rule**: Signal requires two consecutive bars confirming direction.

```
UP:   low[i] <= ema20[i]  AND  close[i] > ema20[i]  AND  close[i+1] > ema20[i+1]
DOWN: high[i] >= ema20[i] AND  close[i] < ema20[i] AND  close[i+1] < ema20[i+1]
```

**Why**: Single-bar signals are noise. Two-bar confirmation filters false signals.

---

## Timing Rules

### ✅ CAP_PASS only after confirm_ts

**Rule**: Only ticks in `[confirm_ts, end_ts]` count for CAP_PASS. Ticks before `confirm_ts` are IGNORED.

**Why**: Price behavior before signal confirmation is irrelevant. Acting on early dips would be premature.

### ✅ confirm_ts = signal_ts + CONFIRM_DELAY_SECONDS

**Rule**: The confirmation window starts after a delay from signal detection.

**Why**: Gives time for the signal to be validated before checking prices.

### ✅ If confirm_ts >= end_ts, skip (LATE)

**Rule**: If there's no time for CAP check, don't trade.

**Why**: No time for validation = unsafe to proceed.

---

## CAP_PASS Rules

### ✅ Require CAP_MIN_TICKS consecutive ticks

**Rule**: Must see at least N consecutive price ticks ≤ PRICE_CAP.

**Why**: A single tick below cap could be noise. Consecutive ticks confirm liquidity.

### ✅ Reset count when price exceeds cap

**Rule**: If any tick > PRICE_CAP, reset consecutive count to zero.

**Why**: Continuous validation required. Gaps in availability invalidate prior ticks.

---

## Streak Rules

### ✅ Trade-level streak counts only taken+filled trades

**Rule**: A trade counts toward streak only if:
1. Decision is OK or AUTO_OK (taken)
2. Fill status is FILLED (executed)

**Why**: Skipped windows, failed fills, and no-signal windows are not "trades" for risk management.

### ✅ Skipped windows do NOT break streak

**Rule**: A user SKIP or system AUTO_SKIP does not reset streak.

**Why**: Choosing not to trade is not a loss. Streak measures actual trade performance.

### ✅ Loss resets everything

**Rule**: On any loss:
- `trade_level_streak = 0`
- `night_streak = 0`
- `policy_mode = BASE`

**Why**: Hot streak logic only applies while winning. Losses reset confidence.

---

## Day/Night Rules

### ✅ Day trades require explicit user OK

**Rule**: In day mode, trade card is sent and user must click ✅ OK to execute.

**Why**: Human oversight during active hours. User makes final decision.

### ✅ Night trading is opt-in only

**Rule**: `night_autotrade_enabled` defaults to `false`. No autonomous trading unless explicitly enabled.

**Why**: Autonomous trading while sleeping is high-risk. Must be consciously enabled.

### ✅ Night session caps at NIGHT_MAX_WIN_STREAK

**Rule**: After N consecutive night wins:
- Reset `night_streak = 0`
- Reset `policy_mode = BASE`
- Optionally reset `trade_level_streak`

**Why**: Limits maximum autonomous exposure per session.

---

## Quality Rules

### ✅ Quality must meet threshold to proceed

**Rule**: Signal quality must be ≥ threshold (BASE or STRICT depending on mode).

**Why**: Low-quality signals are filtered out to improve win rate.

### ✅ STRICT mode uses rolling quantile thresholds

**Rule**: When in STRICT mode, threshold is calculated from recent trade quality distribution.

**Why**: STRICT adapts to actual performance, not arbitrary values.

### ✅ STRICT activates at SWITCH_STREAK_AT wins

**Rule**: After N consecutive wins, switch from BASE to STRICT mode.

**Why**: Hot streaks suggest market conditions are favorable. Apply stricter filters.

---

## Execution Rules

### ✅ Paper mode is default

**Rule**: `execution.mode = "paper"` by default. No real orders unless explicitly changed.

**Why**: Safety first. New deployments must prove themselves before risking real money.

### ✅ No secrets in code

**Rule**: API keys, tokens, and credentials must be in `.env` file, never in code.

**Why**: Security. Code is committed; secrets should not be.

---

## State Machine Rules

### ✅ Terminal states are final

**Rule**: SETTLED, CANCELLED, and ERROR are terminal. No transitions out.

**Why**: Once a trade is resolved, it cannot be reopened.

### ✅ State transitions must follow valid paths

**Rule**: Only transitions defined in STATE_MACHINE.md are allowed.

**Why**: Invalid transitions could corrupt trade state and accounting.

---

## Data Integrity Rules

### ✅ One trade per window

**Rule**: Each market window has at most one trade record.

**Why**: Prevents duplicate trading on the same market.

### ✅ Stats is singleton

**Rule**: Stats table always has exactly one row with `id = 1`.

**Why**: Global state must be consistent.

### ✅ Schema changes require migration

**Rule**: No field removal or repurposing without proper migration.

**Why**: Data integrity across deployments.

---

## Checklist for Refactors

Before any significant code change, verify:

- [ ] Signal detection still uses EMA20 1m with 2-bar confirm
- [ ] CAP_PASS ignores ticks before confirm_ts
- [ ] Streak logic only counts taken+filled trades
- [ ] Day mode still requires user confirmation
- [ ] Night autotrade respects streak cap
- [ ] Paper mode is still default
- [ ] No hardcoded magic numbers (use config)
- [ ] No secrets in code
- [ ] State machine transitions are unchanged
- [ ] Existing tests still pass

---

*This file is the authoritative trading rules reference for project MARTIN.*
*Last updated: 2026-01-21*
