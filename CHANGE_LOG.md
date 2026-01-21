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
