import os
import time
from dotenv import load_dotenv
from notifications import send_discord_alert

load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

print("Sending Complete Suite of Notification Examples...")

# --- ENTRIES ---

# 1. SWING ENTRY
msg_swing_buy = (
    "🚀 **HEDGE FUND BUY**: AMD\n"
    "📊 Quant: 10 shares @ $140.00\n"
    "🛡️ ATR Stop: $135.50\n"
    "🧠 Sentiment: 0.85 | 🏢 Fundamentals: 8/10\n"
    "ℹ️ | ⚡ Beta: 1.5 | 🔊 Vol High\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_swing_buy, DISCORD_WEBHOOK_URL)
time.sleep(1)

# 2. SCALP ENTRY
msg_scalp_buy = (
    "⚡ **SCALP ENTRY**: AMD\n"
    "📊 Qty: 100 @ $100.00\n"
    "🛑 Initial Stop: $98.00 (-2.0%)\n"
    "🛡️ Strategy: Will upgrade to Trailing Stop\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_scalp_buy, DISCORD_WEBHOOK_URL)
time.sleep(1)

# 3. OPTION ENTRY (New)
msg_option_buy = (
    "🧬 **QUANT OPTION ENTRY**: AMD\n"
    "🎫 Contract: AMD230616C00150000\n"
    "💵 Price: $5.50 (x100)\n"
    "📅 Expiry: 2023-06-16\n"
    "🧠 Reasoning: Sentiment 0.92 + Strong Fundamentals\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_option_buy, DISCORD_WEBHOOK_URL)
time.sleep(1)

# --- UPDATES ---

# 4. UPGRADE
msg_upgrade = (
    "🔄 **POSITION UPGRADE**: AMD\n"
    "✅ Fixed Stop Cancelled.\n"
    "🛡️ Trailing Stop Set: 3.0%\n"
    "📈 Profit Locked In.\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_upgrade, DISCORD_WEBHOOK_URL)
time.sleep(1)

# --- EXITS ---

# 5. SWING EXIT
msg_swing_sell = (
    "💰 **HEDGE FUND SELL**: AMD\n"
    "📉 Sold 10 shares @ $150.00\n"
    "💵 Total: $1,500.00\n"
    "📈 Profit: $100.00 (7.14%)\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_swing_sell, DISCORD_WEBHOOK_URL)
time.sleep(1)

# 6. SCALP EXIT
msg_scalp_exit = (
    "⚡ **SCALP EXIT**: AMD\n"
    "📉 Sold 100 shares @ $103.00\n"
    "💵 Total: $10,300.00\n"
    "📈 Profit: $300.00 (3.00%)\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_scalp_exit, DISCORD_WEBHOOK_URL)
time.sleep(1)

# 7. OPTION EXIT (New)
msg_option_exit = (
    "🧬 **OPTION EXIT**: AMD230616C00150000\n"
    "📉 Sold 5 contracts @ $8.00\n"
    "💵 Total: $4,000.00\n"
    "📈 Profit: $1,250.00 (45.45%)\n"
    "-----------------------------------------------------"
)
send_discord_alert(msg_option_exit, DISCORD_WEBHOOK_URL)

print("✅ Sent all 7 Strategy Examples.")
