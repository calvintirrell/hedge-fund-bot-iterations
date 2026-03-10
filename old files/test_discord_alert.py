from notifications import send_discord_alert
import os
from dotenv import load_dotenv

# Load Env
load_dotenv()
webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

if not webhook_url:
    print("Error: DISCORD_WEBHOOK_URL not found in .env")
    exit(1)

# Mimic the V5 Hedge Fund Message Format
symbol = "TEST"
qty = 10
price = 150.00
stop_price = 145.00
sent_score = 0.85
fund_score = 9

msg = (f"🚀 **HEDGE FUND BUY**: {symbol}\n"
       f"📊 Quant: {qty} shares @ ${price:.2f}\n"
       f"🛡️ ATR Stop: ${stop_price:.2f}\n"
       f"🧠 Sentiment: {sent_score:.2f} | 🏢 Fundamentals: {fund_score}/10")

print(f"Sending test message to Discord:\n---\n{msg}\n---")
try:
    send_discord_alert(msg, webhook_url)
    print("✅ Notification sent successfully!")
except Exception as e:
    print(f"❌ Failed to send notification: {e}")
