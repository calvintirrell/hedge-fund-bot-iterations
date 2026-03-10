from notifications import send_discord_alert
import os
from dotenv import load_dotenv

# Load Env
load_dotenv()
webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

if not webhook_url:
    print("Error: DISCORD_WEBHOOK_URL not found in .env")
    exit(1)

# Mimic the V5 Hedge Fund SELL Format for NVDA
symbol = "NVDA"
qty = 200
buy_price = 140.00
sell_price = 150.00 # $10 Profit per share
total_val = qty * sell_price
pnl = (sell_price - buy_price) * qty 
pnl_pct = (pnl / (qty * buy_price)) * 100

pnl_msg = f"\n📈 Profit: ${pnl:.2f} ({pnl_pct:.2f}%)"

msg = (f"💰 **HEDGE FUND SELL**: {symbol}\n"
       f"📉 Sold {qty} shares @ ${sell_price:.2f}\n"
       f"💵 Total: ${total_val:.2f}"
       f"{pnl_msg}")

print(f"Sending test message to Discord:\n---\n{msg}\n---")
try:
    send_discord_alert(msg, webhook_url)
    print("✅ Notification sent successfully!")
except Exception as e:
    print(f"❌ Failed to send notification: {e}")
