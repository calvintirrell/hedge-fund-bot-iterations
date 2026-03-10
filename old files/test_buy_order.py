import os
import sys
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass

# Load environment variables
load_dotenv()
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')

if not API_KEY or not SECRET_KEY:
    print("Error: API keys not found.")
    sys.exit(1)

trading_client = TradingClient(api_key=API_KEY, secret_key=SECRET_KEY, paper=True)

symbol = "IBM"
qty = "1"
stop_loss_percent = 2.0

# Mocking a price for the test
current_price = 150.00 
stop_price = round(current_price * (1 - stop_loss_percent / 100), 2)

print(f"Attempting to submit OTO order for {symbol} at market with stop loss at {stop_price}...")

try:
    # This matches the logic in your bot
    oto_market_order_data = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.OTO, 
        stop_loss={'stop_price': stop_price}
    )
    
    order = trading_client.submit_order(order_data=oto_market_order_data)
    print(f"SUCCESS: Order submitted! ID: {order.id}, Status: {order.status}")

except Exception as e:
    print(f"FAILURE: {e}")
