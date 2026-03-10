# Alpaca Trading Bot V5 - AI Hedge Fund Edition
# Features:
# - Multi-Agent System (Sentiment, Fundamental, Technical)
# - OpenAI / VADER Sentiment Analysis
# - Fundamental Quality Checks (P/E, Margins)
# - ATR-Based Trailing Stops (Volatility Adjusted)

import sys
import os
import time
import math
import logging
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import requests
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Alpaca Imports
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TrailingStopOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, QueryOrderStatus, OrderType, OrderClass

# AI / Sentiment Imports
try:
    import google.generativeai as genai
except ImportError:
    genai = None
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Import Notifications
from notifications import send_discord_alert

# --- LOGGING SETUP ---
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HedgeFund_V5")
logger.setLevel(logging.INFO)

if not logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)
    
    file_handler = logging.FileHandler("trading_bot_v5.log")
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

# --- CONFIGURATIONLOAD ---
load_dotenv()
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# --- STRATEGY CONSTANTS ---
SYMBOLS = ["AMD", "AAPL", "GOOGL", "NVDA", "IBM", "PLTR", "MU", "MDB", "AMZN", "META", "MSFT", "CSCO", "SOFI", "INTC", "SPY"]
RISK_PCT = 0.01
ATR_MULTIPLIER = 2.0  # ATR Multiplier for Stop Loss (2x ATR is standard)
TRAILING_STOP_PCT = 3.0 # Trailing Stop % (Locks in profit as price rises)

# =============================================================================
# AGENT 1: SENTIMENT AGENT ("The Analyst")
# =============================================================================
class SentimentAgent:
    def __init__(self, use_ai=True):
        self.use_ai = use_ai and (GEMINI_API_KEY is not None)
        self.vader = SentimentIntensityAnalyzer()
        
        if self.use_ai:
            genai.configure(api_key=GEMINI_API_KEY)
            # using gemini-flash-latest (Flash 2.5) for newest features/speed
            self.model = genai.GenerativeModel('gemini-flash-latest') 
            logger.info("SentimentAgent: Using Google Gemini (Flash Latest).")
        else:
            logger.info("SentimentAgent: Using VADER (Local Fallback).")

    def get_news(self, symbol):
        """Fetches recent news from Yahoo Finance (via yfinance)."""
        # Note: yfinance news is basic. Alpaca News API is better if available (paid).
        # We will try to fetch news titles from Ticker object.
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            headlines = []
            if news:
                for n in news[:5]:
                    # Safe parsing for varying yfinance news structures
                    if 'title' in n:
                        headlines.append(n['title'])
                    elif 'content' in n and 'title' in n['content']:
                        headlines.append(n['content']['title'])
            return headlines
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []

    def analyze(self, symbol):
        """Returns a score from -1.0 (Negative) to 1.0 (Positive)."""
        headlines = self.get_news(symbol)
        if not headlines:
            logger.info(f"No news found for {symbol}. Neutral score.")
            return 0.0

        text_block = "\n".join(headlines)
        
        # Method A: Google Gemini
        if self.use_ai:
            try:
                prompt = (
                    "You are a financial analyst. Analyze the sentiment of these headlines. "
                    "Return ONLY a single float number between -1.0 (Very Negative) and 1.0 (Very Positive).\n\n"
                    f"Headlines for {symbol}:\n{text_block}"
                )
                response = self.model.generate_content(prompt)
                score_str = response.text.strip()
                score = float(score_str)
                logger.info(f"Gemini Sentiment for {symbol}: {score}")
                return score
            except Exception as e:
                logger.error(f"Gemini Failed: {e}. Falling back to VADER.")
                # Fallthrough to VADER

        # Method B: VADER
        scores = [self.vader.polarity_scores(h)['compound'] for h in headlines]
        avg_score = sum(scores) / len(scores) if scores else 0
        logger.info(f"VADER Sentiment for {symbol}: {avg_score}")
        return avg_score

# =============================================================================
# AGENT 2: FUNDAMENTAL AGENT ("The Warren Buffett")
# =============================================================================
class FundamentalAgent:
    def analyze(self, symbol):
        """Returns a Quality Score (0-10)."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            score = 5 # Start neutral
            
            # 1. P/E Ratio (Value)
            pe = info.get('trailingPE')
            if pe:
                if 0 < pe < 25: score += 1 # Good value
                elif pe > 50: score -= 1   # Overvalued
            
            # 2. Profit Margins (Profitability)
            margins = info.get('profitMargins')
            if margins and margins > 0.15: score += 2 # Strong margins (>15%)
            
            # 3. Revenue Growth
            growth = info.get('revenueGrowth')
            if growth and growth > 0.10: score += 2 # Strong growth (>10%)
            
            # 4. Analyst Recommendation (New)
            rec = info.get('recommendationKey', 'none').lower()
            if rec in ['buy', 'strong_buy']:
                score += 2
                logger.info(f"Analyst Rating: {rec} (+2)")
            elif rec in ['underperform', 'sell']:
                score -= 2
                logger.info(f"Analyst Rating: {rec} (-2)")
            
            # 5. Beta (Volatility Warning)
            beta = info.get('beta')
            
            # 6. Earnings Date Check
            days_to_earnings = 999
            try:
                # yfinance often stores next earnings in 'calendar'
                cal = ticker.calendar
                if isinstance(cal, dict) and 'Earnings Date' in cal:
                    dates = cal['Earnings Date']
                    if dates:
                        next_earn = dates[0] # date object or timestamp
                        # Ensure datetime
                        if not isinstance(next_earn, datetime):
                            next_earn = pd.to_datetime(next_earn)
                        
                        # Make timezone aware if needed (assume NY)
                        if next_earn.tzinfo is None:
                            next_earn = pytz.timezone('America/New_York').localize(next_earn)
                            
                        days_to_earnings = (next_earn - datetime.now(pytz.timezone('America/New_York'))).days
                # Fallback for old dataframe structure (just in case)
                elif hasattr(cal, 'empty') and not cal.empty and 'Earnings Date' in cal.index:
                    next_earn = cal.loc['Earnings Date']
                    if len(next_earn) > 0:
                        next_earn = next_earn.iloc[0]
                        days_to_earnings = (next_earn - datetime.now(pytz.timezone('America/New_York'))).days
            except Exception as e:
                logger.warning(f"Could not fetch earnings date: {e}")

            logger.info(f"Fundamental Score for {symbol}: {score}/10 (Beta: {beta})")
            return {'score': min(10, max(0, score)), 'beta': beta, 'days_to_earnings': days_to_earnings} 
            
        except Exception as e:
            logger.error(f"Fundamental Analysis Error for {symbol}: {e}")
            return {'score': 5, 'beta': None, 'days_to_earnings': 999}

# =============================================================================
# AGENT 3: TECHNICAL AGENT ("The Chartist")
# =============================================================================
class TechnicalAgent:
    def __init__(self):
        self.hourly_lookback = 60
        self.daily_lookback = 365
        self.intraday_timeframe = '15m'

    def fetch_data(self, symbol, start_date, interval):
        try:
            df = yf.download(symbol, start=start_date, interval=interval, auto_adjust=True, progress=False)
            if df.empty: return None
            # Fix MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = df.columns.str.lower()
            return df
        except Exception as e:
            logger.error(f"Data Fetch Error {symbol} {interval}: {e}")
            return None

    def analyze(self, symbol):
        """
        Returns dictionary: {'signal': 'BUY'/'WAIT', 'atr': float, 'close': float}
        """
        # 1. Daily Trend
        start_d = datetime.now() - timedelta(days=self.daily_lookback)
        df_d = self.fetch_data(symbol, start_d, '1d')
        if df_d is None or len(df_d) < 200: return {'signal': 'WAIT'}
        
        df_d.ta.sma(length=50, append=True)
        df_d.ta.sma(length=200, append=True)
        
        # Check Trend
        latest_d = df_d.iloc[-1]
        daily_up = latest_d['SMA_50'] > latest_d['SMA_200']
        
        if not daily_up:
            return {'signal': 'WAIT', 'reason': 'Daily Trend Down'}

        # 2. Hourly Trend (Golden Cross)
        start_h = datetime.now() - timedelta(days=self.hourly_lookback)
        df_h = self.fetch_data(symbol, start_h, '1h')
        if df_h is None or len(df_h) < 200: return {'signal': 'WAIT'}
        
        df_h.ta.sma(length=50, append=True)
        df_h.ta.sma(length=200, append=True)
        
        latest_h = df_h.iloc[-1]
        hourly_up = latest_h['SMA_50'] > latest_h['SMA_200']

        if not hourly_up:
            return {'signal': 'WAIT', 'reason': 'Hourly Trend Down'}

        # 3. Intraday (Entry Trigger) + ATR
        start_i = datetime.now() - timedelta(days=5)
        df_i = self.fetch_data(symbol, start_i, self.intraday_timeframe)
        if df_i is None or len(df_i) < 50: return {'signal': 'WAIT'}
        
        df_i.ta.sma(length=20, append=True) # Fast
        df_i.ta.sma(length=50, append=True) # Slow
        df_i.ta.rsi(length=14, append=True)
        df_i.ta.vwap(append=True)
        df_i.ta.atr(length=14, append=True) # Check ATR
        df_i.ta.macd(append=True) # MACD
        df_i['VOL_SMA_20'] = df_i['volume'].rolling(20).mean()
        
        latest = df_i.iloc[-1]
        
        # MACD Column Names (usually MACD_12_26_9, MACDh_..., MACDs_...)
        # pandas_ta auto-names them. We need to be dynamic or check standard names.
        # Standard: MACD_12_26_9, MACDs_12_26_9 (Signal), MACDh_12_26_9 (Hist)
        macd_col = 'MACD_12_26_9'
        signal_col = 'MACDs_12_26_9'
        
        # Conditions
        is_uptrend = latest['SMA_20'] > latest['SMA_50']
        not_overbought = latest['RSI_14'] < 70
        price_above_vwap = latest['close'] > latest['VWAP_D']
        
        # MACD Check: MACD > Signal (Bullish Momentum)
        # Note: We check if it exists first
        macd_bullish = True
        if macd_col in latest and signal_col in latest:
            macd_bullish = latest[macd_col] > latest[signal_col]
        
        # Volume Check (Information Only)
        vol_confirmed = latest['volume'] > latest['VOL_SMA_20']
        
        if is_uptrend and not_overbought and price_above_vwap and macd_bullish:
            return {
                'signal': 'BUY',
                'close': latest['close'],
                'atr': latest['ATRr_14'],
                'vol_confirmed': vol_confirmed
            }
        
        if not macd_bullish:
            return {'signal': 'WAIT', 'reason': 'MACD Bearish'}
        
        return {'signal': 'WAIT', 'reason': 'Intraday Conditions Met'}

# =============================================================================
# AGENT 4: PORTFOLIO MANAGER ("The Boss")
# =============================================================================
class PortfolioManager:
    def __init__(self, trading_client):
        self.client = trading_client
        self.sentiment_agent = SentimentAgent()
        self.fundamental_agent = FundamentalAgent()
        self.technical_agent = TechnicalAgent()

    def check_fills_and_notify(self, last_check_time):
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
            orders = self.client.get_orders(filter=filter_request)
            
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
                            buy_orders = self.client.get_orders(filter=buy_filter)
                            
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
                        msg = (f"💰 **HEDGE FUND SELL**: {symbol}\n"
                               f"📉 Sold {qty} shares @ ${price:.2f}\n"
                               f"💵 Total: ${total_val:.2f}"
                               f"{pnl_msg}\n"
                               f"-----------------------------------------------------")
                        send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                        
                        # Update high water mark if this fill is newer
                        if filled_at > new_last_check_time:
                            new_last_check_time = filled_at
            
            return new_last_check_time

        except Exception as e:
            logger.error(f"Error checking fills: {e}")
            return last_check_time

    def upgrade_stops(self):
        """
        Scans ALL open positions and upgrades Fixed Stops to Trailing Stops.
        Run this frequently (e.g. every minute).
        """
        try:
            positions = self.client.get_all_positions()
            for p in positions:
                symbol = p.symbol
                qty = float(p.qty)
                
                # Check Orders for this symbol
                orders = self.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
                
                fixed_stop = None
                trailing_stop = None
                
                for o in orders:
                    if o.order_type in [OrderType.STOP, OrderType.STOP_LIMIT]:
                        fixed_stop = o
                    elif o.order_type == OrderType.TRAILING_STOP:
                        trailing_stop = o
                
                # Upgrade Logic
                if fixed_stop and not trailing_stop:
                    logger.info(f"⚡ Fast Upgrade: Found Fixed Stop for {symbol}. Upgrading to Trailing Stop ({TRAILING_STOP_PCT}%)...")
                    try:
                        self.client.cancel_order_by_id(fixed_stop.id)
                        time.sleep(0.5) 
                        
                        trail_data = TrailingStopOrderRequest(
                            symbol=symbol,
                            qty=qty,
                            side=OrderSide.SELL,
                            time_in_force=TimeInForce.GTC,
                            trail_percent=TRAILING_STOP_PCT
                        )
                        self.client.submit_order(order_data=trail_data)
                        logger.info(f"✅ Fast Upgrade: {symbol} Trailing Stop Set.")
                        
                        # Notify User
                        msg = (f"🔄 **POSITION UPGRADE**: {symbol}\n"
                               f"✅ Fixed Stop Cancelled.\n"
                               f"🛡️ Trailing Stop Set: {TRAILING_STOP_PCT}%\n"
                               f"📈 Profit Locked In.\n"
                               f"-----------------------------------------------------")
                        send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                        
                    except Exception as e:
                        logger.error(f"Failed to fast-upgrade {symbol}: {e}")

        except Exception as e:
            logger.error(f"Error in upgrade_stops: {e}")

    def execute_strategy(self, symbol):
        logger.info(f"--- Analyzing {symbol} ---")
        
        # 1. Check Existing Position
        position = None
        try:
            position = self.client.get_open_position(symbol)
        except Exception:
            position = None

        # 2. Gather Intelligence (Technical First - to get Price)
        tech_result = self.technical_agent.analyze(symbol)
        if tech_result['signal'] != 'BUY':
             logger.info(f"Technical Agent says WAIT ({tech_result.get('reason')}).")
             return

        price = tech_result['close'] # Current Price

        # 3. POSITION LOGIC: Average Down vs. Skip
        if position:
            avg_entry = float(position.avg_entry_price)
            if price >= avg_entry:
                logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Higher. Skipping Add.")
                return
            else:
                logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Lower. EVALUATING TO ADD MORE 🚨")
                # We continue to Agents...

        # 4. Fundamental & Sentiment Analysis
        # (Only run if we passed the checks above)

        fund_result = self.fundamental_agent.analyze(symbol)
        fund_score = fund_result['score']
        beta = fund_result['beta']
        days_to_earnings = fund_result.get('days_to_earnings', 999)
        
        # EARNINGS LOGIC:
        # If Earnings are within 2 days, we enter "Blackout Mode".
        # We ONLY buy if Sentiment is > 0.5 (Betting on the pop).
        is_earnings_risk = days_to_earnings is not None and days_to_earnings <= 2 and days_to_earnings >= 0
        if is_earnings_risk:
            logger.warning(f"⚠️ {symbol} Earnings in {days_to_earnings} days! High Risk.")
        
        if fund_score < 5:
            logger.info(f"Fundamental Agent rejects {symbol} (Score: {fund_score}/10).")
            return

        sent_score = self.sentiment_agent.analyze(symbol)
        
        # EARNINGS OVERRIDE CHECK
        if is_earnings_risk and sent_score <= 0.5:
             logger.info(f"❌ Earnings Risk ({days_to_earnings}d) + Weak Sentiment ({sent_score}). SKIP.")
             return
             
        if sent_score < 0: # Negative sentiment
            logger.info(f"Sentiment Agent rejects {symbol} (Score: {sent_score}).")
            return
        
        # 3. Final Decision: BUY
        price = tech_result['close']
        atr = tech_result['atr']

        stop_dist = atr * ATR_MULTIPLIER
        stop_price = price - stop_dist
        
        account = self.client.get_account()
        equity = float(account.equity)
        risk_amt = equity * RISK_PCT
        qty = int(risk_amt / stop_dist)
        
        # 4. SAFETY: Cap Qty by Buying Power OR Fixed $10k Target
        buying_power = float(account.buying_power)
        
        # USER REQUEST: Target ~$10,000 per trade (Closest Number of Shares)
        target_val = 10000.0
        target_shares = round(target_val / price)
        
        # If Risk Model suggests MORE than the Target, clamp it down to the Target
        # (We treat $10k as a 'Soft Cap' / 'Ideal Size')
        if qty > target_shares:
             logger.warning(f"⚠️ Risk Sizing ({qty}) exceeds Target ({target_shares}). Adjusting to ~$10k.")
             qty = int(target_shares)

        # FINAL CHECK: Absolute Hard Cap by Actual Buying Power
        # We can't spend money we don't have.
        hard_max = int((buying_power * 0.95) / price)
        if qty > hard_max:
             qty = hard_max

        qty = max(1, qty)
        
        # Prepare Info Strings
        beta_str = f" | ⚡ Beta: {beta}" if beta else ""
        vol_str = " | 🔊 Vol High" if tech_result.get('vol_confirmed') else " | 🔇 Vol Low"
        earn_str = f" | 📅 Earn {days_to_earnings}d" if is_earnings_risk else ""
        
        logger.info(f"✅ AGENTS AGREE: BUY {symbol}!")
        logger.info(f"Sentiment: {sent_score}, Fundamental: {fund_score}/10{beta_str}{vol_str}{earn_str}")
        logger.info(f"ATR: {atr:.2f}, Stop Price: {stop_price:.2f}")

        # Execute
        try:
            # Submit OTO (Buy + Stop Limit or Stop Market)
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=str(qty),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.OTO,
                stop_loss={'stop_price': round(stop_price, 2)}
            )
            self.client.submit_order(order_data=order_data)
            
            msg = (f"🚀 **HEDGE FUND BUY**: {symbol}\n"
                   f"📊 Quant: {qty} shares @ ${price:.2f}\n"
                   f"🛡️ ATR Stop: ${stop_price:.2f}\n"
                   f"🧠 Sentiment: {sent_score:.2f} | 🏢 Fundamentals: {fund_score}/10\n"
                   f"ℹ️ {beta_str}{vol_str}{earn_str}\n"
                   f"-----------------------------------------------------")
            send_discord_alert(msg, DISCORD_WEBHOOK_URL)
            
        except Exception as e:
            logger.error(f"Order Failed: {e}")

# =============================================================================
# MAIN ORCHESTRATOR
# =============================================================================
def run_hedge_fund():
    logger.info("Initializing AI Hedge Fund V5...")
    if not API_KEY or not SECRET_KEY:
        logger.critical("Missing Keys.")
        return

    trading_client = TradingClient(api_key=API_KEY, secret_key=SECRET_KEY, paper=True)
    manager = PortfolioManager(trading_client)
    
    # Initialize Fill Check Time
    last_fill_check_time = datetime.now(pytz.utc)

    # Simple Loop Strategy
    while True:
        try:
            clock = trading_client.get_clock()
            now = clock.timestamp
            
            # Check Fills AND Upgrades Every Loop
            last_fill_check_time = manager.check_fills_and_notify(last_fill_check_time)
            manager.upgrade_stops()
            
            if clock.is_open:
                logger.info("Market Open. Agents active.")
                for symbol in SYMBOLS:
                    manager.execute_strategy(symbol)
                
                logger.info("Cycle complete. Waiting 15m (checking fills every 1m)...")
                
                # Smart Sleep (15 mins)
                for _ in range(15):
                    time.sleep(60)
                    last_fill_check_time = manager.check_fills_and_notify(last_fill_check_time)
                    manager.upgrade_stops()
            
            else:
                logger.info("Market Closed.")
                sleep_sec = (clock.next_open - now).total_seconds() + 10
                logger.info(f"Sleeping {sleep_sec/3600:.2f} hours until open.")
                time.sleep(sleep_sec)
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_hedge_fund()
