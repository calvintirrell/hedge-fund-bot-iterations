# Alpaca Trading Bot

An AI-powered algorithmic trading system built on the [Alpaca](https://alpaca.markets/) brokerage API. The bot runs a multi-agent consensus model that combines sentiment analysis, fundamental analysis, and technical indicators to make automated trading decisions across a configurable watchlist of equities.

## Architecture

```
alpaca_bot_v8.py                    # Main entry point
v8_modules/
  config.py                         # Centralized TradingConfig dataclass
  base_agent.py                     # Abstract base for all agents
  agent_coordinator.py              # Multi-agent orchestration & adaptive weighting
  agent_performance.py              # Per-agent accuracy tracking & learning
  consensus_engine.py               # Weighted voting & decision consensus
  cache_manager.py                  # DataCache & IndicatorCache (TTL-based)
  data_provider.py                  # Market data retrieval (Yahoo Finance)
  data_validator.py                 # Data quality & staleness checks
  analysis_optimizer.py             # Technical analysis with indicator caching
  market_regime.py                  # Bull / bear / sideways regime detection
  risk_manager.py                   # Portfolio-level risk controls & emergency stop
  order_executor.py                 # Order execution & validation via Alpaca API
  trade_tracker.py                  # Full trade lifecycle (entry -> exit, P&L, commissions)
  position_tracker.py               # In-memory position management
  reconciliation_manager.py         # Position verification & discrepancy alerts
  async_api_wrapper.py              # Parallel API call execution
dashboard/                          # Streamlit web dashboard for monitoring
v8_deployment/                      # Self-contained deployment package
```

### Agents

| Agent | Role | Data Sources |
|-------|------|-------------|
| **SentimentAgent** | AI-driven news & market sentiment scoring | Google Gemini API, VADER |
| **FundamentalAgent** | Company fundamentals evaluation | Yahoo Finance |
| **TechnicalAgent** | Indicator-based signals (SMA, RSI, MACD, ATR) | Yahoo Finance (cached) |

Each agent produces an independent recommendation. The **AgentCoordinator** combines them via weighted consensus voting, with weights that adapt over time based on each agent's track record.

### Trade Types

| Type | Portfolio Allocation | Strategy |
|------|---------------------|----------|
| Swing | 50% | Multi-day holds, up to 5 positions |
| Scalp | 40% | Intraday, up to 8 positions |
| Options | 10% | 0-5 DTE scalp options |

### Risk Management

- 1% risk per trade with ATR-based stop losses
- 5% max daily drawdown with emergency stop
- Position correlation analysis (0.7 threshold)
- Trailing stop management
- 15-minute position reconciliation against Alpaca
- Commission simulation (SEC fees, FINRA TAF, options per-contract)

## Prerequisites

- Python 3.10+
- An [Alpaca](https://alpaca.markets/) brokerage account (paper or live)
- A [Google Gemini API](https://ai.google.dev/) key (for sentiment analysis)
- A [Discord webhook URL](https://discord.com/developers/docs/resources/webhook) (for trade notifications)

## Setup

```bash
# Clone and enter the project
cd alpaca_bot

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```env
BASE_URL=https://paper-api.alpaca.markets   # or https://api.alpaca.markets for live
API_KEY=your_alpaca_api_key
SECRET_KEY=your_alpaca_secret_key
GEMINI_API_KEY=your_gemini_api_key
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

## Usage

```bash
# Run the trading bot
python alpaca_bot_v8.py
```

The bot will:
1. Initialize all agents and load configuration from `v8_modules/config.py`
2. Wait for market open (9:30 AM ET)
3. Run continuous analysis cycles during market hours
4. Execute trades based on multi-agent consensus
5. Manage open positions (trailing stops, exits)
6. Send Discord notifications on trades and end-of-day summaries
7. Sleep outside market hours and resume the next trading day

### Monitoring

```bash
# Follow live logs
tail -f trading_bot_v8.log

# Watch cache performance
tail -f trading_bot_v8.log | grep "Cache"
```

## Configuration

All trading parameters are centralized in `v8_modules/config.py` via the `TradingConfig` dataclass. Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `symbols` | 16 tickers | Watchlist (AMD, AAPL, GOOGL, NVDA, etc.) |
| `risk_pct` | 0.01 | Risk per trade (1%) |
| `max_daily_drawdown_pct` | 5.0 | Daily loss limit before emergency stop |
| `consensus_threshold` | 0.6 | Min consensus score to trigger a BUY |
| `data_cache_ttl` | 60s | Market data cache lifetime |
| `trailing_stop_pct` | 3.0 | Trailing stop percentage |
| `enable_options` | false | Master switch for swing options |
| `enable_options_scalp` | true | Master switch for 0-5 DTE scalp options |

See `v8_modules/config.py` for the full list of tunable parameters.

## Dashboard

A Streamlit web dashboard provides real-time trade monitoring.

```bash
# Install dashboard dependencies
pip install -r dashboard/requirements-dashboard.txt

# Start the dashboard
./dashboard/start_dashboard.sh
```

Access at `http://localhost:8501`. Features include:
- Trade timeline visualization (9:30 AM - 4:00 PM ET)
- Daily P&L, win rate, and trade count metrics
- Symbol and trade-type filtering
- Open positions monitoring
- Password-protected access

Dashboard configuration lives in `.env.dashboard` (see `dashboard/.env.dashboard.template` for the schema).

## Deployment

The project is designed for deployment on a Google Cloud Compute VM.

```bash
# Quick deploy to a GCE instance
./quick_deploy.sh

# Or use the Python deployment tool
python deploy_v8_updates.py
```

A self-contained deployment package is available in `v8_deployment/` with its own README.

## Testing

```bash
# Run all tests
python -m pytest test_*.py tests/ -v

# Run a specific test module
python -m pytest test_v8_trade_tracker.py -v

# Run dashboard tests
python -m pytest dashboard/test_*.py -v
```

Test coverage spans caching, agent coordination, consensus voting, trade tracking, risk management, market regime detection, order execution, data validation, and end-to-end integration.

## Project History

| Version | Focus |
|---------|-------|
| V5 | Initial trading bot |
| V6 | Multi-agent architecture |
| V7 | Expanded technical analysis & trade management |
| V8 | Performance optimization (6x faster cycles), modular architecture, agent learning, commission simulation, risk controls, dashboard |

Previous versions are retained as `alpaca_bot_v5.py` through `alpaca_bot_v7.py` for reference.

## License

Feel free to use my project as a basis for your own version and reference if you do - thanks.
