# MARTIN Telegram Trading Bot

A Telegram bot that discovers Polymarket hourly "BTC Up or Down" and "ETH Up or Down" markets, computes trading signals using technical analysis, and provides trade recommendations.

## Features

- **Market Discovery**: Automatically discovers hourly BTC/ETH markets via Polymarket Gamma API
- **Technical Analysis**: Uses EMA20 (1m) for signal detection with 2-bar confirmation
- **Quality Scoring**: Calculates quality based on anchor edge, ADX, EMA50 slope, and trend confirmation
- **CAP Validation**: Ensures price stays below cap for required consecutive ticks
- **Day/Night Modes**: Manual confirmation during day, autonomous trading at night (configurable)
- **Streak Tracking**: Tracks win streaks and auto-switches between BASE and STRICT modes
- **Paper Trading**: Safe default mode that simulates trades without real execution

## Project Structure

```
MARTIN/
├── config/
│   ├── config.json          # Main configuration
│   └── config.schema.json   # JSON schema for validation
├── src/
│   ├── main.py              # Entry point
│   ├── bootstrap.py         # Initialization
│   ├── common/              # Shared utilities
│   │   ├── config.py        # Configuration loader
│   │   ├── logging.py       # Structured logging
│   │   └── exceptions.py    # Custom exceptions
│   ├── domain/              # Domain models
│   │   ├── enums.py         # Status enumerations
│   │   └── models.py        # Data models
│   ├── services/            # Business logic
│   │   ├── orchestrator.py  # Main coordinator
│   │   ├── ta_engine.py     # Technical analysis
│   │   ├── cap_check.py     # CAP validation
│   │   ├── state_machine.py # Trade lifecycle
│   │   ├── time_mode.py     # Day/Night mode
│   │   ├── execution.py     # Order execution
│   │   └── stats_service.py # Stats & streaks
│   ├── adapters/
│   │   ├── telegram/        # Telegram bot
│   │   ├── polymarket/      # API clients
│   │   └── storage/         # Database
│   └── tests/               # Unit tests
├── docker/                  # Docker support
├── .env.example             # Environment template
└── README.md
```

## Quick Start (For Non-Programmers)

### Prerequisites

1. **Python 3.11 or higher** - Download from [python.org](https://www.python.org/downloads/)
2. **A Telegram Bot Token** - Get one from [@BotFather](https://t.me/BotFather)

### Step-by-Step Setup

1. **Download the code**
   ```bash
   git clone https://github.com/yourusername/MARTIN.git
   cd MARTIN
   ```

2. **Create a virtual environment** (recommended)
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On Mac/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the bot**
   
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your settings:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
   ```

5. **Review configuration** (optional)
   
   Edit `config/config.json` to customize:
   - Trading assets (BTC, ETH)
   - Day/Night hours
   - Quality thresholds
   - Night auto-trading
   
6. **Run the bot**
   ```bash
   python -m src.main
   ```

### Using Docker (Alternative)

If you have Docker installed:

```bash
docker-compose up -d
```

## Configuration

### Key Settings in `config/config.json`

| Setting | Description | Default |
|---------|-------------|---------|
| `trading.assets` | Assets to trade | `["BTC", "ETH"]` |
| `trading.price_cap` | Maximum price for CAP_PASS | `0.55` |
| `trading.confirm_delay_seconds` | Delay after signal before CAP check | `120` |
| `trading.cap_min_ticks` | Minimum consecutive ticks ≤ cap | `3` |
| `day_night.day_start_hour` | Day mode start (local time) | `8` |
| `day_night.day_end_hour` | Day mode end (local time) | `22` |
| `day_night.night_autotrade_enabled` | Allow autonomous night trading | `false` |
| `day_night.switch_streak_at` | Win streak to trigger STRICT mode | `3` |
| `execution.mode` | `paper` (simulated) or `live` | `paper` |

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token | Yes |
| `LOG_LEVEL` | Log level (DEBUG/INFO/WARNING/ERROR) | No |
| `EXECUTION_MODE` | Override execution mode | No |
| `POLYMARKET_PRIVATE_KEY` | Wallet private key for live trading | For live |

## Live Trading Setup

⚠️ **WARNING**: Live trading uses real money. Start with paper mode to test.

### Step 1: Enable Live Mode

Set in `config/config.json`:
```json
{
  "execution": {
    "mode": "live"
  }
}
```

Or via environment variable:
```bash
EXECUTION_MODE=live
```

### Step 2: Configure Authentication

**Option A: Wallet-based Auth (MetaMask)**

1. Open MetaMask in your browser
2. Click the account menu (three dots)
3. Select "Account details"
4. Click "Show private key"
5. Enter your password and copy the key
6. Add to `.env` file:
   ```
   POLYMARKET_PRIVATE_KEY=your_private_key_here
   ```

**Option B: API Key Auth**

If you have Polymarket API credentials:
```
POLYMARKET_API_KEY=your_api_key
POLYMARKET_API_SECRET=your_api_secret
POLYMARKET_PASSPHRASE=your_passphrase
```

### Step 3: Security Best Practices

- **Use a dedicated wallet** with only trading funds
- **Never share** your private key or `.env` file
- **Test first** with small amounts
- **Monitor regularly** especially at the start

### Live Trading Flow

1. **Signal detected** → Quality calculated
2. **Quality passes** → Wait for confirm_ts
3. **CAP_PASS achieved** → Trade card sent to Telegram
4. **User clicks ✅ OK** → Order placed on Polymarket CLOB
5. **Order fills** → Wait for market resolution
6. **Market resolves** → PnL calculated and recorded

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message and help |
| `/status` | Current stats and mode |
| `/settings` | View/edit configuration |
| `/pause` | Pause trading |
| `/resume` | Resume trading |
| `/dayonly` | Enable day-only mode |
| `/nightonly` | Enable night-only mode |
| `/report` | Performance report |

## Trading Logic

### Signal Detection

The bot uses EMA20 on 1-minute candles with 2-bar confirmation:

- **UP Signal**: `low[i] ≤ EMA20[i]` AND `close[i] > EMA20[i]` AND `close[i+1] > EMA20[i+1]`
- **DOWN Signal**: `high[i] ≥ EMA20[i]` AND `close[i] < EMA20[i]` AND `close[i+1] < EMA20[i+1]`

### Quality Score

Quality is calculated as:
```
Quality = (W_ANCHOR × edge + W_ADX × adx + W_SLOPE × slope) × trend_mult
```

Where:
- `edge`: Distance from anchor price (scaled)
- `adx`: ADX value on 5m timeframe
- `slope`: EMA50 slope magnitude on 5m
- `trend_mult`: 1.2 (bonus) if trend confirms, 0.8 (penalty) otherwise

### CAP_PASS Validation

After `confirm_delay_seconds`, the bot checks CLOB prices:
- Requires `cap_min_ticks` consecutive ticks with price ≤ `price_cap`
- Only ticks AFTER confirm_ts are considered (critical rule)

### Day/Night Modes

- **Day Mode** (8:00-22:00 Zurich): Requires manual Telegram confirmation
- **Night Mode** (22:00-8:00 Zurich): Can trade autonomously if enabled

### Streak Management

- Win streaks count only **taken AND filled** trades
- At `switch_streak_at` wins → switch to STRICT mode (higher quality threshold)
- On loss → reset to BASE mode
- Night session caps at `night_max_win_streak` wins → reset

## Testing

Run the test suite:

```bash
# All tests
pytest src/tests/ -v

# Specific test file
pytest src/tests/test_cap_pass.py -v
pytest src/tests/test_ta_engine.py -v
pytest src/tests/test_state_machine.py -v
```

## Troubleshooting

### Bot doesn't respond
- Check that `TELEGRAM_BOT_TOKEN` is correct
- Ensure your user ID is in `telegram.admin_user_ids` config

### No markets found
- Polymarket may not have active hourly markets
- Check API connectivity

### Database errors
- Delete `data/martin.db` to reset
- Ensure `data/` directory exists

## Safety Notes

⚠️ **IMPORTANT**:
- Default mode is `paper` (simulated trading)
- Live trading requires real API credentials
- Never share your `.env` file or bot token
- The bot does NOT guarantee profits

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please open an issue or pull request.