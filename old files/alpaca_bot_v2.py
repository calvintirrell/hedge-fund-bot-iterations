# Welcome to your first Alpaca Trading Bot Starter Script!
#
# This script has been updated to use python-dotenv for API key management,
# and now includes a simple SMA Crossover trading strategy.
#
# INSTRUCTIONS:
# 1. Create a new file in this *same directory* named:
#    .env
#
# 2. Open the .env file and add your keys like this (no quotes):
#    API_KEY=YOUR_API_KEY_ID_HERE
#    SECRET_KEY=YOUR_SECRET_KEY_HERE
#    BASE_URL=https://paper-api.alpaca.markets/v2
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
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

# Load API keys from .env file
load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
# BASE_URL = os.getenv('BASE_URL')

# --- STRATEGY PARAMETERS ---
STRATEGY_SYMBOL = "AMD"   # The symbol we will trade
ORDER_QTY = 10            # Number of shares to trade
FAST_SMA = 20             # Fast Simple Moving Average period
SLOW_SMA = 50             # Slow Simple Moving Average period
DATA_TIMEFRAME = TimeFrame.Day # Timeframe for data (1-Hour bars)
DATA_LIMIT = 100          # Number of bars to fetch (need enough for slow SMA)
# ---------------------------

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
    
    # if not BASE_URL:
    #     print("Warning: BASE_URL not found in .env file. ")
    #     print("Using paper=True as fallback, but recommend setting BASE_URL.")

    # --- SECTION 1: INITIALIZATION ---
    try:
        trading_client = TradingClient(api_key=API_KEY, 
                                       secret_key=SECRET_KEY, 
                                       paper=True)
                                    #    , base_url=BASE_URL)
        print("Trading Client initialized successfully.")
    except Exception as e:
        print(f"Error initializing Trading Client: {e}")
        sys.exit(1)

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
        account = dict(trading_client.get_account())
        
        if account.get('trading_blocked'):
            print("Account is currently restricted from trading.")
            return # Exit if trading is blocked
        
        print(f"Account Status: {account.get('status')}")
        print(f"Buying Power: ${account.get('buying_power')}")

        # --- 2. Get Market Data ---
        print(f"\n--- Fetching Market Data for {STRATEGY_SYMBOL} ---")
        
        request_params = StockBarsRequest(
                            symbol_or_symbols=[STRATEGY_SYMBOL],
                            timeframe=DATA_TIMEFRAME,
                            limit=DATA_LIMIT
                       )
        
        # Get data and convert directly to a DataFrame
        bars_df = data_client.get_stock_bars(request_params).df

        if bars_df.empty:
            print(f"No market data found for {STRATEGY_SYMBOL}.")
            return

        # --- 3. Calculate Strategy Indicators (SMA Crossover) ---
        print(f"\n--- Calculating Strategy for {STRATEGY_SYMBOL} ---")
        
        # Calculate SMAs using pandas-ta
        # We must reset the index to use the 'close' column
        bars_df = bars_df.reset_index(level=0, drop=True) 
        bars_df.ta.sma(length=FAST_SMA, append=True)
        bars_df.ta.sma(length=SLOW_SMA, append=True)
        
        # Drop rows with NaN values (at the beginning)
        bars_df = bars_df.dropna()

        if bars_df.empty:
            print(f"Not enough data to calculate SMAs. Need > {SLOW_SMA} bars.")
            return

        # Get the most recent (last) row of data
        latest_data = bars_df.iloc[-1]
        
        fast_sma_col = f'SMA_{FAST_SMA}'
        slow_sma_col = f'SMA_{SLOW_SMA}'
        
        latest_fast_sma = latest_data[fast_sma_col]
        latest_slow_sma = latest_data[slow_sma_col]

        print(f"  Latest Close Price: ${latest_data['close']:.2f}")
        print(f"  Latest Fast SMA ({FAST_SMA}): {latest_fast_sma:.2f}")
        print(f"  Latest Slow SMA ({SLOW_SMA}): {latest_slow_sma:.2f}")

        # --- 4. Get Current Position ---
        print("\n--- Checking Current Position ---")
        try:
            position = trading_client.get_open_position(STRATEGY_SYMBOL)
            have_position = True
            print(f"  Currently hold {position.qty} share(s) of {STRATEGY_SYMBOL}.")
        except Exception as e:
            # Exception means "position not found", so we have no position
            have_position = False
            print(f"  No position found for {STRATEGY_SYMBOL}.")


        # --- 5. Execute Strategy & Place Order ---
        print("\n--- Executing Strategy ---")

        # BUY SIGNAL
        if (latest_fast_sma > latest_slow_sma) and (not have_position):
            print(f"  BUY SIGNAL: Fast SMA ({latest_fast_sma:.2f}) crossed above Slow SMA ({latest_slow_sma:.2f}).")
            
            # Prepare buy order
            market_order_data = MarketOrderRequest(
                                symbol=STRATEGY_SYMBOL,
                                qty=ORDER_QTY,
                                side=OrderSide.BUY,
                                time_in_force=TimeInForce.DAY
                            )
            try:
                market_order = trading_client.submit_order(order_data=market_order_data)
                print(f"  Market BUY order submitted for {ORDER_QTY} share(s) of {STRATEGY_SYMBOL}.")
                print(f"  Order ID: {market_order.id}, Status: {market_order.status}")
            except Exception as e:
                print(f"  Error submitting BUY order: {e}")

        # SELL SIGNAL
        elif (latest_fast_sma < latest_slow_sma) and (have_position):
            print(f"  SELL SIGNAL: Fast SMA ({latest_fast_sma:.2f}) crossed below Slow SMA ({latest_slow_sma:.2f}).")
            
            try:
                # Close the position (sells all shares)
                trading_client.close_position(STRATEGY_SYMBOL)
                print(f"  Market SELL order submitted to close position in {STRATEGY_CHANNEL}.")
            except Exception as e:
                print(f"  Error submitting SELL order: {e}")

        # HOLD SIGNAL
        else:
            print("  HOLD SIGNAL: No crossover. No action taken.")


        # --- 6. Check on Our Orders (for verification) ---
        print("\nWaiting 5 seconds to check order status...")
        time.sleep(5)
        
        print("\n--- Checking All Orders ---")
        orders = [order for order in trading_client.get_orders()]
        print(f"Found {len(orders)} total order(s):")
        if orders:
            # Just print the most recent order for brevity
            print(f"  Most recent order: {orders[0].id}, Status: {orders[0].status}")


    except Exception as e:
        print(f"\nAn error occurred during bot execution: {e}")
    
    finally:
        print("\n--- Alpaca Bot Finished ---")


if __name__ == "__main__":
    run_bot()