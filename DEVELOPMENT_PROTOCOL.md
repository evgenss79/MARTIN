# MARTIN — Development Protocol

> How development proceeds. Controls to avoid chaos.

---

## Before Any Coding Session

1. **Read MEMORY_GATE.md** — Understand immutable constraints
2. **Read ARCHITECTURE.md** — Understand system structure
3. **Check CHANGE_LOG.md** — Understand recent context
4. **Confirm task scope** — Know exactly what you're changing

---

## Required Order of Work (Phases)

Follow phases sequentially. Do not skip ahead.

### Phase 1: Skeleton
- Repository structure
- Configuration loading
- Logging setup
- Storage layer
- Database migrations

### Phase 2: Data Adapters
- Gamma client (market discovery)
- Binance client (price data)
- CLOB client (CAP validation)

### Phase 3: TA Engine
- EMA, ADX implementations
- Signal detection
- Quality calculation

### Phase 4: CAP_PASS + Trade Flow
- CAP check logic
- Trade creation
- Day confirmation flow
- Night auto flow

### Phase 5: Execution + Settlement
- Paper mode (default)
- Live mode adapter
- Settlement logic

### Phase 6: Rolling Quantiles + Strict Policy
- Stats updates
- Quantile computation
- Threshold management

### Phase 7: Polish
- Telegram UX improvements
- Documentation
- Tests
- Docker support

---

## Golden Rules

### Rule: Never Mix Refactor + Feature in One Change

**Do this**:
```
Commit 1: Refactor function X for clarity
Commit 2: Add new feature Y using refactored X
```

**Don't do this**:
```
Commit 1: Refactor X and also add Y in the same change
```

**Why**: If something breaks, you can't tell if it was the refactor or the feature.

---

### Rule: Tests Before Refactor

**Do this**:
```
1. Verify existing tests pass
2. Make refactor changes
3. Verify tests still pass
4. Only then add new functionality
```

**Don't do this**:
```
1. Refactor code
2. Tests now fail
3. "Fix" tests to pass
4. Claim refactor was safe
```

**Why**: Tests verify behavior is unchanged. Changing tests during refactor hides regressions.

---

### Rule: When to Stop and Ask the Owner

Stop and ask for guidance when:

- [ ] Task conflicts with MEMORY_GATE.md constraints
- [ ] Behavior change is required but not explicitly approved
- [ ] Multiple valid interpretations exist
- [ ] External API behavior is unclear
- [ ] Security implications are uncertain
- [ ] Schema change is needed
- [ ] You're unsure if a change is "trivial" or "significant"

**Phrase to use**: "Before proceeding, I need clarification on..."

---

### Rule: Always Keep README Updated

After any significant change:

1. Update README.md if it affects:
   - Installation steps
   - Configuration
   - Running the bot
   - Testing
   - Deployment

2. Ensure examples still work

3. Update version if applicable

---

## Definition of "Done"

A task is **done** when:

- [ ] Code is implemented and working
- [ ] Existing tests pass
- [ ] New tests cover the change (if applicable)
- [ ] Documentation is updated (if applicable)
- [ ] CHANGE_LOG.md has an entry
- [ ] Code review feedback is addressed
- [ ] No known regressions introduced

---

## Commit Message Format

```
<type>: <short description>

<optional body with details>
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code restructuring without behavior change
- `test`: Adding or updating tests
- `docs`: Documentation changes
- `chore`: Maintenance tasks

Examples:
```
feat: Add night session streak reset

fix: Ignore CAP ticks before confirm_ts

refactor: Extract quality calculation to separate method

test: Add CAP_PASS timing validation tests

docs: Update README with Docker instructions
```

---

## Code Style Guidelines

1. **Functions should be small and testable** — If a function does too much, split it
2. **No magic numbers** — Use config or named constants
3. **No hardcoded strings** — Use enums for fixed values
4. **Clear docstrings** — Every public function needs documentation
5. **Type hints** — Use Python type hints consistently
6. **Error handling** — Catch specific exceptions, log errors
7. **No business logic in handlers** — Telegram handlers call services

---

## Testing Requirements

### Test Types

1. **Unit tests**: Individual functions in isolation
2. **Integration tests**: Service interactions
3. **End-to-end tests**: Full workflow validation

### Test Naming

```python
def test_<what>_<condition>_<expected>():
    """Test that <what> does <expected> when <condition>."""
```

Example:
```python
def test_cap_check_ignores_ticks_before_confirm_ts():
    """Test that CAP check ignores price ticks before confirm_ts."""
```

### Coverage Targets

- CAP_PASS logic: 100% coverage
- State machine transitions: 100% coverage
- TA signal detection: 100% coverage
- Quality calculation: 100% coverage

---

## Debugging Protocol

When something doesn't work:

1. **Check logs first** — Structured logs have context
2. **Reproduce in test** — If you can't test it, you can't fix it reliably
3. **Isolate the problem** — Which component is failing?
4. **Check MEMORY_GATE.md** — Is the code violating a constraint?
5. **Check DATA_CONTRACTS.md** — Is the data valid?
6. **Check STATE_MACHINE.md** — Is the transition allowed?

---

## Deployment Checklist

Before deploying:

- [ ] All tests pass
- [ ] Config is valid
- [ ] .env.example is up to date
- [ ] README reflects current state
- [ ] Docker builds successfully
- [ ] No secrets in code
- [ ] execution.mode is "paper" for new deployments

---

## Emergency Procedures

### Bot is placing unexpected trades

1. Stop the bot immediately
2. Check `execution.mode` in config
3. Check `is_paused` in stats table
4. Review recent CHANGE_LOG entries
5. Review trade records for anomalies

### Streak logic seems wrong

1. Check MEMORY_GATE.md MG-1 (streak definition)
2. Review recent trades in database
3. Verify decision and fill_status fields
4. Check if trades were "taken" (OK/AUTO_OK) AND "filled"

### CAP_PASS passing when it shouldn't

1. Check MEMORY_GATE.md MG-2 (timing constraint)
2. Verify confirm_ts calculation
3. Review price ticks being considered
4. Ensure ticks before confirm_ts are ignored

---

*This file is the authoritative development protocol for project MARTIN.*
*Last updated: 2026-01-21*
