# Welcome to your first Alpaca Trading Bot Starter Script!
#
# This script has been updated to run in a continuous loop
# to check an intraday SMA Crossover strategy, filtered by
# the daily trend using Multi-Timeframe Analysis (MTFA)
# and confirmed by RSI. It now includes logging and basic stop-loss.
#
# It will only run checks during US market hours when the loop is enabled.
# *** DEVELOPMENT NOTE: The main loop is currently commented out for testing. ***
# *** Uncomment the 'while True:' block in run_bot() to enable continuous operation. ***

import sys
import os
import time
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import pytz
import logging
from datetime import datetime, timedelta, time as dt_time
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus, OrderType, OrderClass
# from alpaca.trading.requests import MarketOrderRequest, OrderRequest, GetOrdersRequest
# from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus, OrderType

# --- Logging Configuration ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Console Handler
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

# File Handler
file_handler = logging.FileHandler("trading_bot.log")
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)
# ---------------------------

# Load API keys from .env file
load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')

# --- STRATEGY PARAMETERS ---
STRATEGY_SYMBOL = "MDB"       # The symbol we will trade
ORDER_QTY = 10                # Number of shares to trade
STOP_LOSS_PERCENT = 2.0       # Stop-loss percentage below entry price (approx)

# Intraday Parameters
INTRADAY_TIMEFRAME = '15m'    # The data interval to check for entry/exit
INTRADAY_LOOKBACK_DAYS = 5    # How many days of intraday data to fetch
INTRADAY_FAST_SMA = 20        # Fast SMA period for intraday
INTRADAY_SLOW_SMA = 50        # Slow SMA period for intraday
RSI_PERIOD = 14               # RSI lookback period
RSI_OVERBOUGHT = 70           # RSI overbought threshold
RSI_OVERSOLD = 30             # RSI oversold threshold

# Daily Trend Filter Parameters
DAILY_LOOKBACK_DAYS = 365     # How many days of daily data for trend filter
DAILY_SMA_FAST = 50           # Fast SMA period for daily trend
DAILY_SMA_SLOW = 200          # Slow SMA period for daily trend

# Bot Loop Parameters (Currently disabled for testing)
# LOOP_SLEEP_MINUTES = 15       # How long to wait between strategy checks
# ---------------------------

def is_market_open():
    """Checks if the US stock market is currently open."""
    tz = pytz.timezone('America/New_York')
    now = datetime.now(tz)
    # Basic check, does not account for holidays
    if now.weekday() >= 5: return False # Check if weekday
    market_open = dt_time(9, 30, tzinfo=tz)
    market_close = dt_time(16, 0, tzinfo=tz)
    return market_open <= now.time() <= market_close

def fetch_and_prepare_data(symbol, start_date, interval, is_daily=False):
    """Fetches data from yfinance and prepares the DataFrame."""
    data_type = 'Daily' if is_daily else interval
    logger.info(f"Fetching {data_type} data for {symbol}...")
    # Add a short delay to avoid rapid-fire requests if loop is enabled later
    # time.sleep(1)
    try:
        bars_df = yf.download(symbol,
                              start=start_date,
                              interval=interval,
                              auto_adjust=True,
                              progress=False) # Suppress yfinance progress bar
    except Exception as e:
        logger.error(f"Error fetching {data_type} data for {symbol} from yfinance: {e}")
        return None

    if bars_df.empty:
        logger.warning(f"No {data_type} data found for {symbol}.")
        return None

    # Flatten MultiIndex if necessary
    if isinstance(bars_df.columns, pd.MultiIndex):
        logger.info("  (Detected MultiIndex columns, flattening...)")
        bars_df.columns = bars_df.columns.get_level_values(0)

    # Convert columns to lowercase for consistency
    bars_df.columns = bars_df.columns.str.lower()
    logger.info(f"Successfully fetched {len(bars_df)} data points for {data_type}.")
    return bars_df

def check_strategy(trading_client):
    """
    Runs one full cycle of the trading strategy with MTFA + RSI + Stop Loss:
    1. Fetches account info
    2. Determines Daily Trend
    3. Fetches Intraday Data
    4. Calculates Intraday Indicators (SMAs + RSI)
    5. Checks position
    6. Executes filtered buy/sell/hold logic (including stop-loss placement)
    """
    try:
        # --- 1. Get Account Information ---
        logger.info("--- Checking Account ---")
        try:
            account = dict(trading_client.get_account())
            if account.get('trading_blocked'):
                logger.warning("Account is currently restricted from trading.")
                return
            logger.info(f"Account Status: {account.get('status')}")
            logger.info(f"Buying Power: ${account.get('buying_power')}")
        except Exception as e:
            logger.error(f"Failed to get account information: {e}")
            return # Cannot proceed without account info

        # --- 2. Determine Daily Trend ---
        logger.info(f"--- Determining Daily Trend for {STRATEGY_SYMBOL} ---")
        daily_start_date = datetime.now() - timedelta(days=DAILY_LOOKBACK_DAYS)
        daily_df = fetch_and_prepare_data(STRATEGY_SYMBOL, daily_start_date, '1d', is_daily=True)

        if daily_df is None or len(daily_df) < DAILY_SMA_SLOW:
             logger.warning("Not enough daily data to determine trend. Skipping check.")
             return

        # Calculate Daily SMAs
        try:
            daily_df.ta.sma(length=DAILY_SMA_FAST, append=True)
            daily_df.ta.sma(length=DAILY_SMA_SLOW, append=True)
            daily_df = daily_df.dropna() # Drop rows with NaN from SMA calculation
        except Exception as e:
            logger.error(f"Error calculating daily SMAs: {e}")
            return

        if daily_df.empty:
            logger.error("Error calculating daily SMAs (DataFrame became empty). Skipping check.")
            return

        latest_daily_data = daily_df.iloc[-1]
        daily_fast_sma_col = f'SMA_{DAILY_SMA_FAST}'
        daily_slow_sma_col = f'SMA_{DAILY_SMA_SLOW}'

        # Check if daily SMA columns exist
        if daily_fast_sma_col not in latest_daily_data or daily_slow_sma_col not in latest_daily_data:
            logger.error(f"Could not find Daily SMA columns ('{daily_fast_sma_col}', '{daily_slow_sma_col}') in data.")
            logger.debug(f"Available daily columns: {latest_daily_data.index.to_list()}")
            return

        latest_daily_fast = latest_daily_data[daily_fast_sma_col]
        latest_daily_slow = latest_daily_data[daily_slow_sma_col]

        # Determine Trend
        if latest_daily_fast > latest_daily_slow:
            daily_trend = 'UP'
        elif latest_daily_fast < latest_daily_slow:
            daily_trend = 'DOWN'
        else:
            daily_trend = 'SIDEWAYS'

        logger.info(f"Latest Daily Close: ${latest_daily_data['close']:.2f}")
        logger.info(f"Daily SMA {DAILY_SMA_FAST}: {latest_daily_fast:.2f}")
        logger.info(f"Daily SMA {DAILY_SMA_SLOW}: {latest_daily_slow:.2f}")
        logger.info(f"Determined Daily Trend: {daily_trend}")

        # If trend is sideways, no need to check intraday signals for entry
        if daily_trend == 'SIDEWAYS':
            logger.info("Daily trend is sideways. Holding.")
            # Future enhancement: Could still check for exits if a position is held.
            return

        # --- 3. Get Intraday Market Data ---
        logger.info(f"--- Fetching {INTRADAY_TIMEFRAME} Market Data for {STRATEGY_SYMBOL} ---")
        intraday_start_date = datetime.now() - timedelta(days=INTRADAY_LOOKBACK_DAYS)
        intraday_df = fetch_and_prepare_data(STRATEGY_SYMBOL, intraday_start_date, INTRADAY_TIMEFRAME)

        min_bars_needed = max(INTRADAY_SLOW_SMA, RSI_PERIOD)
        if intraday_df is None or len(intraday_df) < min_bars_needed:
            logger.warning(f"Not enough {INTRADAY_TIMEFRAME} data to calculate indicators. Need > {min_bars_needed} bars. Skipping check.")
            return

        # --- 4. Calculate Intraday Strategy Indicators (SMAs + RSI) ---
        logger.info(f"--- Calculating Intraday Strategy for {STRATEGY_SYMBOL} ---")
        try:
            intraday_df.ta.sma(length=INTRADAY_FAST_SMA, append=True)
            intraday_df.ta.sma(length=INTRADAY_SLOW_SMA, append=True)
            intraday_df.ta.rsi(length=RSI_PERIOD, append=True) # Calculate RSI
            intraday_df = intraday_df.dropna() # Drop rows with NaN from indicator calculations
        except Exception as e:
             logger.error(f"Error calculating intraday indicators: {e}")
             return

        if intraday_df.empty:
            logger.error("Error calculating intraday indicators (DataFrame became empty). Skipping check.")
            return

        latest_intraday_data = intraday_df.iloc[-1]
        latest_close_price = latest_intraday_data['close'] # Store for stop-loss calc
        intraday_fast_sma_col = f'SMA_{INTRADAY_FAST_SMA}'
        intraday_slow_sma_col = f'SMA_{INTRADAY_SLOW_SMA}'
        rsi_col = f'RSI_{RSI_PERIOD}' # Standard column name from pandas_ta

        # Check if all needed indicator columns exist
        required_cols = [intraday_fast_sma_col, intraday_slow_sma_col, rsi_col]
        missing_cols = [col for col in required_cols if col not in latest_intraday_data]
        if missing_cols:
             logger.error(f"Could not find Intraday indicator columns: {missing_cols}")
             logger.debug(f"Available intraday columns: {latest_intraday_data.index.to_list()}")
             return

        latest_intraday_fast = latest_intraday_data[intraday_fast_sma_col]
        latest_intraday_slow = latest_intraday_data[intraday_slow_sma_col]
        latest_rsi = latest_intraday_data[rsi_col]

        logger.info(f"Latest {INTRADAY_TIMEFRAME} Close Price: ${latest_close_price:.2f}")
        logger.info(f"Intraday SMA {INTRADAY_FAST_SMA}: {latest_intraday_fast:.2f}")
        logger.info(f"Intraday SMA {INTRADAY_SLOW_SMA}: {latest_intraday_slow:.2f}")
        logger.info(f"Intraday RSI {RSI_PERIOD}: {latest_rsi:.2f}")

        # --- 5. Get Current Position ---
        logger.info("--- Checking Current Position ---")
        have_position = False
        try:
            position = trading_client.get_open_position(STRATEGY_SYMBOL)
            have_position = True
            logger.info(f"Currently hold {position.qty} share(s) of {STRATEGY_SYMBOL}.")
        except Exception: # Alpaca throws exception if no position exists
            logger.info(f"No position found for {STRATEGY_SYMBOL}.")

        # --- 6. Execute Strategy & Place Order (Filtered by Daily Trend and RSI) ---
        logger.info("--- Executing Strategy ---")

        # BUY SIGNAL: Intraday cross UP + Daily Trend UP + No Position + RSI NOT Overbought
        if (latest_intraday_fast > latest_intraday_slow) and \
           (daily_trend == 'UP') and \
           (not have_position) and \
           (latest_rsi < RSI_OVERBOUGHT):
            
            # BUY SIGNAL: Submit as an OTO order (Market Buy + Stop Loss)
            logger.info(f"BUY SIGNAL detected: Intraday SMA crossed UP ({latest_intraday_fast:.2f} > {latest_intraday_slow:.2f}), Daily Trend is UP, AND RSI ({latest_rsi:.2f}) < {RSI_OVERBOUGHT}.")

            # Calculate stop price
            stop_price = round(latest_close_price * (1 - STOP_LOSS_PERCENT / 100), 2)
            logger.info(f"Preparing OTO Market BUY order for {ORDER_QTY} shares with stop-loss at ${stop_price:.2f}...")

            oto_market_order_data = MarketOrderRequest(
                                        symbol=STRATEGY_SYMBOL,
                                        qty=str(ORDER_QTY), # Keep as string
                                        side=OrderSide.BUY,
                                        time_in_force=TimeInForce.DAY,
                                        order_class=OrderClass.OTO, # Specify OTO order class
                                        stop_loss={'stop_price': stop_price} # Pass stop_loss params as dict
                                     )
            try:
                # Log the request data before submitting
                logger.debug(f"Submitting OTO MarketOrderRequest data: {oto_market_order_data}")
                oto_order = trading_client.submit_order(order_data=oto_market_order_data)
                logger.info(f"OTO Market BUY order submitted for {ORDER_QTY} share(s) of {STRATEGY_SYMBOL} with Stop Loss.")
                logger.info(f"  Order ID: {oto_order.id}, Status: {oto_order.status}")
                # Note: This submits the market order and the stop-loss order together.
            except Exception as e:
                logger.error(f"Error submitting OTO BUY order: {e}")
                logger.error(f"Failed OTO order data: {oto_market_order_data}")

        # SELL SIGNAL: Intraday cross DOWN + Daily Trend DOWN + Have Position + RSI NOT Oversold
        elif (latest_intraday_fast < latest_intraday_slow) and \
             (daily_trend == 'DOWN') and \
             (have_position) and \
             (latest_rsi > RSI_OVERSOLD):
            logger.info(f"SELL SIGNAL detected: Intraday SMA crossed DOWN ({latest_intraday_fast:.2f} < {latest_intraday_slow:.2f}), Daily Trend is DOWN, AND RSI ({latest_rsi:.2f}) > {RSI_OVERSOLD}.")

            # Cancel existing orders (like stop-loss) before closing position
            try:
                 logger.info(f"Attempting to cancel existing orders for {STRATEGY_SYMBOL} before selling...")
                 cancel_statuses = trading_client.cancel_orders(symbol=STRATEGY_SYMBOL)
                 logger.info(f"Cancelled {len(cancel_statuses)} order(s).")
            except Exception as cancel_e:
                 logger.error(f"Error cancelling orders for {STRATEGY_SYMBOL}: {cancel_e}")

            # Submit market order to close the position
            try:
                close_response = trading_client.close_position(STRATEGY_SYMBOL)
                logger.info(f"Market SELL order submitted to close position in {STRATEGY_SYMBOL}.")
                logger.info(f"  Close Order ID: {close_response.id}, Status: {close_response.status}") # Alpaca returns order details on close
            except Exception as e:
                logger.error(f"Error submitting SELL order to close position: {e}")

        # HOLD SIGNAL: Otherwise
        else:
            logger.info("HOLD SIGNAL: No valid signal based on MTFA + RSI rules.")
            # Add more detailed reasons for holding based on which condition failed
            if daily_trend == 'UP' and have_position:
                 logger.info("  Reason: Daily trend UP, holding position (no exit signal / RSI filter).")
            elif daily_trend == 'DOWN' and not have_position:
                 logger.info("  Reason: Daily trend DOWN, waiting for entry (trend reversal) / RSI filter.")
            elif latest_intraday_fast > latest_intraday_slow and daily_trend == 'UP' and not have_position and latest_rsi >= RSI_OVERBOUGHT:
                 logger.info(f"  Reason: Intraday BUY signal ignored, RSI ({latest_rsi:.2f}) >= {RSI_OVERBOUGHT} (Overbought).")
            elif latest_intraday_fast < latest_intraday_slow and daily_trend == 'DOWN' and have_position and latest_rsi <= RSI_OVERSOLD:
                 logger.info(f"  Reason: Intraday SELL signal ignored, RSI ({latest_rsi:.2f}) <= {RSI_OVERSOLD} (Oversold).")
            elif latest_intraday_fast > latest_intraday_slow and daily_trend == 'DOWN':
                 logger.info("  Reason: Intraday BUY signal ignored, Daily trend is DOWN.")
            elif latest_intraday_fast < latest_intraday_slow and daily_trend == 'UP':
                 logger.info("  Reason: Intraday SELL signal ignored (or waiting confirmation), Daily trend is UP.")


        # --- 7. Check on Our Orders (for verification) ---
        logger.info("--- Checking All Orders ---")
        try:
            # Only get open orders for the specific symbol for relevance
            orders_request = GetOrdersRequest(
                status=QueryOrderStatus.OPEN, # or ALL for everything
                symbols=[STRATEGY_SYMBOL]
            )
            orders = trading_client.get_orders(filter=orders_request)
            logger.info(f"Found {len(orders)} OPEN order(s) for {STRATEGY_SYMBOL}:")
            if orders:
                # Sort orders by submission time, newest first
                orders.sort(key=lambda o: o.submitted_at, reverse=True)
                for order in orders[:5]: # Log details of up to 5 most recent open orders
                    logger.info(f"  ID: {order.id}, Type: {order.order_type}, Side: {order.side}, Qty: {order.qty}, Status: {order.status}")
        except Exception as e:
            logger.error(f"Error fetching orders: {e}")


    except Exception as e:
        logger.exception("An error occurred during the main strategy check:") # Logs traceback
    finally:
        # This will now run right after the single check_strategy call
        logger.info("--- Alpaca Bot Finished (Single Run Mode) ---")

def run_bot():
    """Main function to run the trading bot logic."""
    logger.info("--- Alpaca Bot Started ---")
    logger.info("Checking for API keys...")
    if not API_KEY or not SECRET_KEY:
        logger.critical("CRITICAL: API_KEY or SECRET_KEY not found in .env file. Exiting.")
        sys.exit(1) # Use sys.exit for critical failures
    logger.info("API keys found.")

    try:
        trading_client = TradingClient(api_key=API_KEY, secret_key=SECRET_KEY, paper=True)
        logger.info("Trading Client initialized successfully.")
    except Exception as e:
        logger.critical(f"CRITICAL: Error initializing Trading Client: {e}. Exiting.")
        sys.exit(1)

    # --- FOR DEVELOPMENT: Run strategy check once ---
    logger.info("Running single strategy check for development...")
    check_strategy(trading_client)
    # --- END DEVELOPMENT BLOCK ---

    # --- TO ENABLE CONTINUOUS LOOP (UNCOMMENT BELOW) ---
    # logger.info("Starting continuous bot loop...")
    # Add LOOP_SLEEP_MINUTES back to Strategy Params if uncommenting
    # loop_sleep_minutes_actual = int(os.getenv('LOOP_SLEEP_MINUTES', 15)) # Example override via .env
    # while True:
    #     try:
    #         current_time_et = datetime.now(pytz.timezone('America/New_York'))
    #         logger.info(f"--- {current_time_et.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")

    #         if is_market_open():
    #             logger.info("Market is OPEN. Running strategy check...")
    #             check_strategy(trading_client)
    #             logger.info(f"Strategy check complete. Sleeping for {loop_sleep_minutes_actual} minutes...")
    #             sleep_duration = loop_sleep_minutes_actual * 60
    #         else:
    #             logger.info("Market is CLOSED. Determining sleep duration...")

    #             now_et = current_time_et
    #             next_open_time = dt_time(9, 30, tzinfo=now_et.tzinfo)
    #             # ... [rest of the sleep calculation code as before] ...
    #             if now_et.time() < next_open_time or now_et.weekday() >= 5:
    #                 days_to_add = 1
    #                 if now_et.weekday() == 5: days_to_add = 2
    #                 elif now_et.weekday() == 6: days_to_add = 1
    #                 next_market_day = (now_et + timedelta(days=days_to_add)).date()
    #                 target_open = datetime.combine(next_market_day, next_open_time.replace(tzinfo=None))
    #                 target_open = now_et.tzinfo.localize(target_open)
    #             else:
    #                 days_to_add = 1
    #                 if now_et.weekday() == 4: days_to_add = 3 # Friday -> Monday
    #                 next_market_day = (now_et + timedelta(days=days_to_add)).date()
    #                 target_open = datetime.combine(next_market_day, next_open_time.replace(tzinfo=None))
    #                 target_open = now_et.tzinfo.localize(target_open)

    #             sleep_duration = max(1, (target_open - now_et).total_seconds())
    #             sleep_duration = min(sleep_duration, 3600) # Sleep max 1 hour

    #             logger.info(f"Next market open approx: {target_open.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    #             logger.info(f"Sleeping for {sleep_duration / 60:.1f} minutes...")

    #         time.sleep(sleep_duration)

    #     except KeyboardInterrupt:
    #         logger.info("KeyboardInterrupt received. Shutting down bot.")
    #         break
    #     except Exception as e:
    #         logger.exception("An error occurred in the main loop:") # Logs traceback
    #         logger.info("Restarting check in 5 minutes...")
    #         time.sleep(300)
    # --- END CONTINUOUS LOOP BLOCK ---


if __name__ == "__main__":
    run_bot()

# ==============================================================================================================
# ==============================================================================================================