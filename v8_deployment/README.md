# V8 Trading Bot Deployment Package

## Quick Start

1. Install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure .env file with your API keys:
   ```bash
   nano .env
   ```

3. Run the bot:
   ```bash
   python alpaca_bot_v8.py
   ```

4. Run in background (recommended):
   ```bash
   screen -S trading_bot
   python alpaca_bot_v8.py
   # Press Ctrl+A then D to detach
   ```

## Files Included

- alpaca_bot_v8.py - Main trading bot
- notifications.py - Discord notifications
- .env - Environment variables (configure with your keys)
- requirements.txt - Python dependencies
- v8_modules/ - Performance optimization modules

## Support

See DEPLOYMENT-GUIDE.md for detailed instructions.
