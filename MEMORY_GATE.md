# MARTIN — Memory Gate

> **Authority Level: ABSOLUTE**
> This file is the highest authority in project MARTIN.
> No code change may violate rules defined here without explicit written approval from the project owner.

---

## Project Identity

- **Name**: MARTIN
- **Purpose**: Telegram trading bot for Polymarket hourly BTC/ETH Up or Down markets
- **Core Function**: Discover markets, compute trading signals, validate prices, execute trades with day/night safety controls

---

## Roles

| Role         | Identity           | Responsibilities |
|--------------|--------------------|--------------------|
| **Owner**    | Project creator    | Defines requirements, approves spec changes, final authority |
| **Copilot**  | GitHub Copilot AI  | Implements code, maintains documentation, follows rules exactly |

---

## Immutable Constraints (MG-1 through MG-12)

These constraints are **NON-NEGOTIABLE**. Violation of any constraint requires explicit written approval from the project owner.

### MG-1: Streak Definition
> Trade-level streak counts ONLY trades that were **taken** (OK/AUTO_OK) AND **filled**.
> Skips, no-signal, cap-fail, and expired windows do NOT break streak.

**Why**: Win streak logic drives policy switching. Counting non-trades would corrupt risk control.

### MG-2: CAP_PASS Timing
> CAP_PASS is valid ONLY if the consecutive ≤cap ticks occur **AFTER** `confirm_ts`, inside `[confirm_ts, end_ts]`.
> Any ≤cap ticks **before** `confirm_ts` must be **IGNORED**.

**Why**: Early price dips before signal confirmation are noise. Acting on them would be premature.

### MG-3: Time Model
> `confirm_ts = signal_ts + CONFIRM_DELAY_SECONDS`
> If `confirm_ts >= end_ts` ⇒ **LATE** ⇒ skip trade.

**Why**: If there's no time for CAP check after confirmation, the trade cannot proceed safely.

### MG-4: TA Signal Rules
> Signal detection MUST use **EMA20 on 1m** with **2-bar confirm** exactly as specified.
> No alternative indicators or extra filters unless explicitly approved.

**Why**: Consistency. The spec defines exact entry logic. Deviating changes behavior.

### MG-5: Quality Formula
> Quality MUST be computed exactly as specified:
> - Anchor edge with penalty
> - ADX on 5m
> - EMA50 slope on 5m
> - Trend multiplier using EMA20 on 5m
>
> `quality = (W_ANCHOR*edge + W_ADX*adx + W_SLOPE*slope) * trend_mult`

**Why**: Quality score drives filtering. Wrong formula = wrong trades.

### MG-6: Day/Night Behavior
> - **Day mode**: Requires **manual Telegram confirmation** (OK button).
> - **Night mode**: May be autonomous ONLY if `night_autotrade_enabled=true` and must respect `NIGHT_MAX_WIN_STREAK`.

**Why**: Day trades need human oversight. Night automation is opt-in with caps.

### MG-7: Auto-switch BASE ↔ STRICT
> - STRICT activates when `trade_level_streak >= SWITCH_STREAK_AT`
> - STRICT uses rolling quantile thresholds (separate for DAY and NIGHT)
> - On **loss** or **night session reset** ⇒ revert to BASE

**Why**: Hot streaks deserve stricter filters. Losses reset everything.

### MG-8: Config-Driven
> All key parameters MUST be configurable via `config.json` and/or environment.
> No hardcoding of business logic values.

**Why**: Config enables tuning without code changes.

### MG-9: Safety Defaults
> Default execution mode is **paper-trade**.
> Real orders NEVER placed by default.

**Why**: Safety first. No accidental real trades.

### MG-10: No Secrets
> No tokens, keys, or credentials in code.
> Use `.env` file. Provide `.env.example`.

**Why**: Security. Secrets in code = leaked secrets.

### MG-11: No Regression
> Any refactor MUST preserve existing behavior unless spec change is explicitly approved.
> Add tests **before** refactors.

**Why**: Refactors must not break logic.

### MG-12: SQLite Schema Integrity
> Tables and fields defined in spec (`market_windows`, `signals`, `trades`, `cap_checks`, `stats`) MUST exist and be used consistently.
> No field removal or repurposing without migration.

**Why**: Schema stability protects data integrity.

---

## Conflict Resolution

If any future instruction conflicts with this file:

1. **STOP immediately**
2. **Do NOT guess or improvise**
3. **Ask the owner for explicit written approval**

---

## Definition of Regression

A **regression** in MARTIN means:

- Behavior that previously worked now fails
- Logic that matched the spec now deviates
- Tests that passed now fail
- Data that was valid is now corrupted

All regressions are **unacceptable** unless explicitly approved.

---

## Session Protocol

Before every coding session, Copilot MUST:

1. **Read this file** (`MEMORY_GATE.md`)
2. **Read ARCHITECTURE.md** for system overview
3. **Check CHANGE_LOG.md** for recent context
4. **Confirm understanding** of the task scope

---

## Amendment Process

To change any MG-* rule:

1. Owner provides explicit written instruction
2. Copilot updates this file first
3. Copilot updates affected code second
4. Copilot adds entry to CHANGE_LOG.md

---

*This file is the authoritative memory gate of project MARTIN.*
*Last updated: 2026-01-21*
