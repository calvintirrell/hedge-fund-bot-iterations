# Welcome to your first Alpaca Trading Bot Starter Script!
#
# This script has been updated to use python-dotenv for API key management,
# which is a best practice for security.
#
# INSTRUCTIONS:
# 1. Create a new file in this *same directory* named:
#    .env
#
# 2. Open the .env file and add your keys like this (no quotes):
#    API_KEY=YOUR_API_KEY_ID_HERE
#    SECRET_KEY=YOUR_SECRET_KEY_HERE
#
# 3. Save the .env file.
#
# 4. Install all required packages:
#    pip install -r requirements.txt
#
# 5. Run the script:
#    python alpaca_bot_starter.py

import sys
import os
import time
from dotenv import load_dotenv
import pandas as pd
import pandas_ta as ta 
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Load API keys from .env file
load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
# ---------------------

def run_bot():
    """
    Main function to run the trading bot logic.
    """
    print("--- Alpaca Bot Started ---")

    # Basic check to ensure keys are set
    if not API_KEY or not SECRET_KEY:
        print("Error: API_KEY or SECRET_KEY not found in .env file.")
        print("Please create a .env file (see instructions in script).")
        return

    # --- SECTION 1: INITIALIZATION ---
    # Initialize the Trading Client
    # paper=True means we are using the paper trading (sandbox) environment
    try:
        trading_client = TradingClient(api_key=API_KEY, 
                                       secret_key=SECRET_KEY, 
                                       paper=True)
        print("Trading Client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Trading Client: {e}")
        sys.exit(1)

    # Initialize the Market Data Client
    try:
        data_client = StockHistoricalDataClient(api_key=API_KEY, 
                                                secret_key=SECRET_KEY)
        print("Market Data Client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Market Data Client: {e}")
        sys.exit(1)


    try:
        # --- 1. Get Account Information ---
        print("\n--- Checking Account ---")
        # Get account details
        account = dict(trading_client.get_account())
        for k, v in account.items():
            print(f"  {k:30}: {v}")
        
        # Check if our account is restricted from trading.
        if account.get('trading_blocked'):
            print("Account is currently restricted from trading.")
            return # Exit if trading is blocked

        # --- 2. Get Market Data (Example: Last day of SPY) ---
        print("\n--- Fetching Market Data for SPY ---")
        symbol = "SPY"
        request_params = StockBarsRequest(
                            symbol_or_symbols=[symbol],
                            timeframe=TimeFrame.Day,
                            limit=1 # Get the most recent 1-day bar
                       )
        
        bars = data_client.get_stock_bars(request_params)
        
        # *** THIS IS THE CORRECTED LINE ***
        # Check if 'bars' exists, if 'symbol' is a key in 'bars', AND if there's data in the list
        if bars and symbol in bars and bars[symbol]:
            last_bar = bars[symbol][0] # Get the first (and only) bar
            print(f"Latest data for {symbol}:")
            print(f"  Time: {last_bar.timestamp}")
            print(f"  Open: ${last_bar.open}")
            print(f"  High: ${last_bar.high}")
            print(f"  Low: ${last_bar.low}")
            print(f"  Close: ${last_bar.close}")
            print(f"  Volume: {last_bar.volume}")
        else:
            print(f"No market data found for {symbol}.")

        # --- 3. Place a Market Order (Example: Buy 10 shares of AMD) ---
        print("\n--- Placing a Test Order for AMD ---")
        order_symbol = "AMD"
        order_qty = 10

        # Prepare the order data
        market_order_data = MarketOrderRequest(
                            symbol=order_symbol,
                            qty=order_qty,
                            side=OrderSide.BUY,
                            time_in_force=TimeInForce.DAY # Good 'til close
                        )

        # Submit the order
        # This will fail if the market is closed, so we use a try/except
        try:
            market_order = trading_client.submit_order(
                            order_data=market_order_data
                        )
            print(f"Market order submitted for {order_qty} share(s) of {order_symbol}.")
            print(f"Order ID: {market_order.id}")
            print(f"Order Status: {market_order.status}")
        
        except Exception as e:
            print(f"Error submitting order: {e}")
            print("This often happens if the market is closed.")

        # --- 4. Check on Our Orders ---
        print("\nWaiting 5 seconds for order to (potentially) fill...")
        time.sleep(5)
        
        print("\n--- Checking All Orders ---")
        orders = [order for order in trading_client.get_orders()]
        print(f"Found {len(orders)} order(s):")
        if orders:
            print(orders) # Just print the list for now

        # --- 5. Check Our Current Positions ---
        print("\n--- Checking Current Positions ---")
        assets = [asset for asset in trading_client.get_all_positions()]
        
        if not assets:
            print("No positions currently held.")
        else:
            positions = [(asset.symbol, asset.qty, asset.current_price) for asset in assets]
            print("Positions:")
            print(f"{'Symbol':9}{'Qty':>4}{'Value':>15}")
            print("-" * 28)
            for position in positions:
                try:
                    # Ensure values are floats for calculation
                    qty = float(position[1])
                    price = float(position[2])
                    value = qty * price
                    print(f"{position[0]:9}{qty:>4}{value:>15.2f}")
                except ValueError:
                    print(f"Could not calculate value for {position[0]}")

        # --- 6. Examples for Next Steps (from your code) ---
        
        # Example: Close all positions
        # print("\n--- Closing all positions ---")
        # trading_client.close_all_positions(cancel_orders=True)
        # print("All positions closed.")


        # Example: Streaming trade events (see your code for handler)
        # print("\n--- Starting Trade Stream (Example) ---")
        # from alpaca.trading.stream import TradingStream
        # trades = TradingStream(api_key=API_KEY,
        #                        secret_key=SECRET_KEY,
        #                        paper=True)
        #
        # async def update_handler(data):
        #     print(data.event)
        #
        # trades.subscribe_trade_updates(update_handler)
        # trades.run() # This will block, so it's last


    except Exception as e:
        print(f"\nAn error occurred during bot execution: {e}")
    
    finally:
        print("\n--- Alpaca Bot Finished ---")


if __name__ == "__main__":
    run_bot()