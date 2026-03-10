import os
import time
from dotenv import load_dotenv
from notifications import send_discord_alert

load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# SCALP SELL SIMULATION
# Scalps usually have tight take profits (approx 1%).
# Scenario: Bought at 140.00, Sold at 141.40 (Hit TP).
msg_scalp_sell = (
    "💰 **HEDGE FUND SELL**: AMD\n"
    "📉 Sold 50 shares @ $141.40\n"
    "💵 Total: $7,070.00\n"
    "📈 Profit: $70.00 (1.00%)\n"
    "-----------------------------------------------------"
)

print("Sending Scalp Sell Alert...")
send_discord_alert(msg_scalp_sell, DISCORD_WEBHOOK_URL)
print("✅ Sent.")
