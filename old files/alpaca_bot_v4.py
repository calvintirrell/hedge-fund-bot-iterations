# Alpaca Trading Bot V4
#
# Features:
# - Multi-Timeframe Analysis (Daily + 15m + 1h)
# - Indicators: SMA, RSI, VWAP
# - Filters: Daily Trend, Golden Cross (1h), RSI Overbought/Oversold, Price > VWAP
# - Risk Management: Dynamic Position Sizing (1% Risk)
# - Execution: OTO Entry (Buy + Fixed Stop) -> Upgraded to Trailing Stop
# - Multi-Symbol Support

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
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus, OrderType, OrderClass

# Import Notifications (Future Use)
from notifications import send_discord_alert

# --- Logging Configuration ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(log_formatter)
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    logger.addHandler(stream_handler)

file_handler = logging.FileHandler("trading_bot_v4.log")
file_handler.setFormatter(log_formatter)
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
     logger.addHandler(file_handler)
# ---------------------------

load_dotenv()

# --- CONFIGURATION ---
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL') # Add this to .env

# --- STRATEGY PARAMETERS ---
SYMBOLS = ["AMD", "AAPL", "GOOGL", "NVDA"] # Multi-Symbol List
RISK_PCT = 0.01               # 1% Risk per trade
STOP_LOSS_PERCENT = 2.5       # Stop-loss percentage

# Intraday Parameters
INTRADAY_TIMEFRAME = '15m'
INTRADAY_LOOKBACK_DAYS = 5
INTRADAY_FAST_SMA = 20
INTRADAY_SLOW_SMA = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Hourly Parameters (Golden Cross)
HOURLY_TIMEFRAME = '1h'
HOURLY_LOOKBACK_DAYS = 60 # Need ~30 trading days for 200 hours, setting 60 for safety
HOURLY_FAST_SMA = 50
HOURLY_SLOW_SMA = 200

# Daily Trend Filter Parameters
DAILY_LOOKBACK_DAYS = 365
DAILY_SMA_FAST = 50
DAILY_SMA_SLOW = 200

# ---------------------------

def fetch_and_prepare_data(symbol, start_date, interval, is_daily=False):
    """Fetches data from yfinance and prepares the DataFrame."""
    data_type = 'Daily' if is_daily else interval
    logger.info(f"Fetching {data_type} data for {symbol}...")
    try:
        bars_df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=True, progress=False)
    except Exception as e:
        logger.error(f"Error fetching {data_type} data for {symbol}: {e}")
        return None

    if bars_df.empty:
        logger.warning(f"No {data_type} data found for {symbol}.")
        return None

    if isinstance(bars_df.columns, pd.MultiIndex):
        bars_df.columns = bars_df.columns.get_level_values(0)

    bars_df.columns = bars_df.columns.str.lower()
    return bars_df

def calculate_qty(account_equity, price):
    """Calculates position size based on risk percentage."""
    risk_amount = account_equity * RISK_PCT
    stop_distance_per_share = price * (STOP_LOSS_PERCENT / 100)
    
    if stop_distance_per_share == 0: return 1 # Avoid division by zero
    
    qty = int(risk_amount / stop_distance_per_share)
    return max(1, qty) # Always buy at least 1 share

def check_strategy(trading_client, symbol):
    """
    Runs strategy check for a SINGLE symbol.
    """
    logger.info(f"=== Checking Strategy for {symbol} ===")
    
    try:
        # --- 1. Get Account Info & Equity ---
        account = trading_client.get_account()
        if account.trading_blocked:
            logger.warning("Account is blocked.")
            return
        equity = float(account.equity)

        # --- 2. Determine Daily Trend ---
        daily_start = datetime.now() - timedelta(days=DAILY_LOOKBACK_DAYS)
        daily_df = fetch_and_prepare_data(symbol, daily_start, '1d', is_daily=True)
        
        if daily_df is None or len(daily_df) < DAILY_SMA_SLOW:
            logger.warning(f"Not enough daily data for {symbol}.")
            return

        daily_df.ta.sma(length=DAILY_SMA_FAST, append=True)
        daily_df.ta.sma(length=DAILY_SMA_SLOW, append=True)
        
        latest_daily = daily_df.iloc[-1]
        daily_fast = latest_daily[f'SMA_{DAILY_SMA_FAST}']
        daily_slow = latest_daily[f'SMA_{DAILY_SMA_SLOW}']
        
        daily_trend = 'UP' if daily_fast > daily_slow else 'DOWN'
        logger.info(f"Daily Trend ({symbol}): {daily_trend}")

        if daily_trend != 'UP':
            logger.info(f"Skipping {symbol}: Daily trend is not UP.")
            # Note: We might still want to process exits even if trend is down, 
            # but for now we stick to the original logic flow.
            # To be safe, let's check for exits even if trend is down? 
            # The original logic filtered EVERYTHING by trend. We will keep it consistent.
            # BUT, we need to manage existing positions (Trailing Stop Upgrade) regardless of trend.
            pass 

        # --- 3. Manage Existing Position (Trailing Stop Upgrade) ---
        # We check this BEFORE entry logic so we can upgrade stops on existing holds
        have_position = False
        try:
            position = trading_client.get_open_position(symbol)
            have_position = True
            logger.info(f"Holding {position.qty} {symbol}. Checking for Stop Loss upgrade...")
            
            # Check open orders
            orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
            
            fixed_stop_order = None
            trailing_stop_order = None
            
            for o in orders:
                if o.order_type == OrderType.STOP:
                    fixed_stop_order = o
                elif o.order_type == OrderType.TRAILING_STOP:
                    trailing_stop_order = o
            
            if trailing_stop_order:
                logger.info(f"Trailing Stop already active for {symbol}.")
            elif fixed_stop_order:
                logger.info(f"Found Fixed Stop for {symbol}. Upgrading to Trailing Stop...")
                trading_client.cancel_order_by_id(fixed_stop_order.id)
                
                # Submit Trailing Stop
                # Note: We sell the entire position size
                trailing_data = TrailingStopOrderRequest(
                    symbol=symbol,
                    qty=position.qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    trail_percent=STOP_LOSS_PERCENT
                )
                trading_client.submit_order(order_data=trailing_data)
                logger.info(f"Upgraded to Trailing Stop ({STOP_LOSS_PERCENT}%) for {symbol}.")
                
        except Exception:
            logger.info(f"No position for {symbol}.")

        # If we have a position, we generally don't buy more (simple logic)
        if have_position:
            logger.info(f"Already holding {symbol}. Skipping entry check.")
            return

        # --- 4. Golden Cross Confirmation (Hourly) ---
        hourly_start = datetime.now() - timedelta(days=HOURLY_LOOKBACK_DAYS) 
        hourly_df = fetch_and_prepare_data(symbol, hourly_start, HOURLY_TIMEFRAME)
        
        if hourly_df is None or len(hourly_df) < HOURLY_SLOW_SMA:
            logger.warning(f"Not enough hourly data for {symbol}.")
            return

        hourly_df.ta.sma(length=HOURLY_FAST_SMA, append=True)
        hourly_df.ta.sma(length=HOURLY_SLOW_SMA, append=True)
        
        latest_hourly = hourly_df.iloc[-1]
        hourly_fast = latest_hourly[f'SMA_{HOURLY_FAST_SMA}']
        hourly_slow = latest_hourly[f'SMA_{HOURLY_SLOW_SMA}']
        
        hourly_trend = 'UP' if hourly_fast > hourly_slow else 'DOWN'
        logger.info(f"Hourly Trend (Golden Cross Check): {hourly_trend}")

        if hourly_trend != 'UP':
            logger.info(f"Skipping {symbol}: Hourly Golden Cross not confirmed.")
            return

        # --- 5. Intraday Analysis (15m) ---
        intraday_start = datetime.now() - timedelta(days=INTRADAY_LOOKBACK_DAYS)
        intraday_df = fetch_and_prepare_data(symbol, intraday_start, INTRADAY_TIMEFRAME)
        
        if intraday_df is None or len(intraday_df) < INTRADAY_SLOW_SMA:
            return

        intraday_df.ta.sma(length=INTRADAY_FAST_SMA, append=True)
        intraday_df.ta.sma(length=INTRADAY_SLOW_SMA, append=True)
        intraday_df.ta.rsi(length=RSI_PERIOD, append=True)
        intraday_df.ta.vwap(append=True)
        intraday_df = intraday_df.dropna()

        if intraday_df.empty: return

        latest = intraday_df.iloc[-1]
        close = latest['close']
        fast = latest[f'SMA_{INTRADAY_FAST_SMA}']
        slow = latest[f'SMA_{INTRADAY_SLOW_SMA}']
        rsi = latest[f'RSI_{RSI_PERIOD}']
        vwap = latest['VWAP_D']

        logger.info(f"{symbol} Intraday: Close=${close:.2f}, SMA{INTRADAY_FAST_SMA}={fast:.2f}, SMA{INTRADAY_SLOW_SMA}={slow:.2f}, RSI={rsi:.2f}, VWAP={vwap:.2f}")

        # --- 6. Entry Logic ---
        # BUY SIGNAL: 
        # 1. Intraday SMA Cross UP
        # 2. Daily Trend UP (Checked above)
        # 3. Hourly Trend UP (Checked above)
        # 4. RSI < Overbought
        # 5. Price > VWAP
        
        if (fast > slow) and (daily_trend == 'UP') and (rsi < RSI_OVERBOUGHT) and (close > vwap):
            logger.info(f"BUY SIGNAL for {symbol}!")
            
            # Calculate Quantity
            qty = calculate_qty(equity, close)
            stop_price = round(close * (1 - STOP_LOSS_PERCENT / 100), 2)
            
            logger.info(f"Buying {qty} shares of {symbol} at Market. Stop Loss: ${stop_price}")
            
            # Submit OTO Order (Buy + Fixed Stop)
            # We use Fixed Stop initially for safety. The NEXT loop will upgrade it to Trailing.
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=str(qty),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.OTO,
                stop_loss={'stop_price': stop_price}
            )
            
            try:
                trading_client.submit_order(order_data=order_data)
                logger.info(f"Order submitted for {symbol}.")
                # Send Discord Notification
                send_discord_alert(f"🚀 BUY {symbol}: {qty} shares @ ${close:.2f} (approx). Stop: ${stop_price}", DISCORD_WEBHOOK_URL)
            except Exception as e:
                logger.error(f"Failed to submit order for {symbol}: {e}")

        else:
            logger.info(f"No entry signal for {symbol}.")

    except Exception as e:
        logger.exception(f"Error checking {symbol}: {e}")

def check_for_fills(trading_client, last_check_time):
    """
    Checks for recently filled SELL orders and sends Discord alerts.
    Returns the updated last_check_time.
    """
    try:
        # Get closed orders filled after the last check
        # Note: Alpaca 'after' filter works on submission time, not fill time for some endpoints,
        # but for 'closed' orders, we can filter manually.
        # We fetch the last 50 closed orders to be safe.
        filter_request = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=50, direction='desc')
        orders = trading_client.get_orders(filter=filter_request)
        
        new_last_check_time = last_check_time
        
        for order in orders:
            # We only care about FILLED SELL orders
            if order.side == OrderSide.SELL and order.filled_at:
                filled_at = order.filled_at
                
                # Check if this fill is new (after our last check)
                if filled_at > last_check_time:
                    symbol = order.symbol
                    qty = float(order.filled_qty)
                    price = float(order.filled_avg_price)
                    # Calculate Total Value
                    total_val = qty * price
                    
                    # --- Calculate PnL ---
                    pnl_msg = ""
                    try:
                        # Fetch the last CLOSED BUY order for this symbol
                        buy_filter = GetOrdersRequest(
                            status=QueryOrderStatus.CLOSED, 
                            symbols=[symbol], 
                            side=OrderSide.BUY, 
                            limit=1,
                            direction='desc'
                        )
                        buy_orders = trading_client.get_orders(filter=buy_filter)
                        
                        if buy_orders:
                            last_buy = buy_orders[0]
                            buy_price = float(last_buy.filled_avg_price)
                            
                            pnl = (price - buy_price) * qty
                            pnl_pct = (price - buy_price) / buy_price * 100
                            
                            emoji = "📈" if pnl >= 0 else "📉"
                            pnl_msg = f"\n{emoji} Profit: ${pnl:.2f} ({pnl_pct:.2f}%)"
                    except Exception as e:
                        logger.error(f"Error calculating PnL for {symbol}: {e}")

                    logger.info(f"Detected SELL FILL for {symbol}: {qty} @ ${price}")
                    
                    # Send Discord Alert
                    msg = (f"💰 SOLD {symbol}: {qty} shares @ ${price:.2f}\n"
                           f"💵 Total Value: ${total_val:.2f}"
                           f"{pnl_msg}")
                    send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                    
                    # Update high water mark if this fill is newer
                    if filled_at > new_last_check_time:
                        new_last_check_time = filled_at
        
        return new_last_check_time

    except Exception as e:
        logger.error(f"Error checking fills: {e}")
        return last_check_time

def run_bot():
    logger.info("--- Alpaca Bot V4 Started ---")
    if not API_KEY or not SECRET_KEY:
        logger.critical("Missing API Keys.")
        sys.exit(1)
        
    trading_client = TradingClient(api_key=API_KEY, secret_key=SECRET_KEY, paper=True)
    
    # Continuous Loop
    # Initialize Fill Check Time (Start from NOW to avoid spamming old fills)
    last_fill_check_time = datetime.now(pytz.utc)
    
    # Continuous Loop
    while True:
        try:
            clock = trading_client.get_clock()
            now = clock.timestamp
            logger.info(f"--- {now.strftime('%Y-%m-%d %H:%M:%S %Z')} ---")
            
            # --- 1. Check for Fills (Every Loop) ---
            last_fill_check_time = check_for_fills(trading_client, last_fill_check_time)
            
            if clock.is_open:
                logger.info("Market Open. Checking Strategy...")
                for symbol in SYMBOLS:
                    check_strategy(trading_client, symbol)
                
                logger.info("Strategy Cycle complete. Entering Wait Loop...")
                
                # --- Smart Sleep Loop (15 mins total, check fills every 1 min) ---
                # 15 mins = 900 seconds. 
                # We loop 15 times, sleeping 60s each.
                for _ in range(15):
                    time.sleep(60)
                    last_fill_check_time = check_for_fills(trading_client, last_fill_check_time)
                    
            else:
                logger.info("Market Closed.")
                sleep_sec = (clock.next_open - now).total_seconds() + 60
                logger.info(f"Sleeping {sleep_sec/3600:.2f} hours until open.")
                
                # For long sleeps, we can just sleep. 
                # But if you want to catch fills that happened right at close, 
                # we should check once more before the big sleep.
                last_fill_check_time = check_for_fills(trading_client, last_fill_check_time)
                
                time.sleep(sleep_sec)
                
        except KeyboardInterrupt:
            logger.info("Stopping Bot.")
            break
        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_bot()
