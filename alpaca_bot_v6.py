# Alpaca Trading Bot V6 - AI Hedge Fund Edition
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
import concurrent.futures # Added for Multithreading
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import requests
import re # Added re import
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
logger = logging.getLogger("HedgeFund_V6")
logger.setLevel(logging.INFO)

if not logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)
    
    file_handler = logging.FileHandler("trading_bot_v6.log")
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

# --- CONFIGURATIONLOAD ---
load_dotenv()
API_KEY = os.getenv('API_KEY')
SECRET_KEY = os.getenv('SECRET_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL')

# --- STRATEGY CONSTANTS ---
SYMBOLS = ["AMD", "AAPL", "GOOGL", "NVDA", "IBM", "PLTR", "MU", "MDB", "AMZN", "META", "MSFT", "CSCO", "SOFI", "INTC", "SPY", "RIVN"]
RISK_PCT = 0.01
ATR_MULTIPLIER = 2.0  # ATR Multiplier for Stop Loss (2x ATR is standard)
TRAILING_STOP_PCT = 3.0 # Trailing Stop % (Locks in profit as price rises)

# --- V6 CONFIGURATION ---
ABOVE_25K = True # Set to False if < $25,000 to prevent PDT Lockout
SWING_ALLOCATION = 0.5 # 50% Capital for Swing
SCALP_ALLOCATION = 0.5 # 50% Capital for Scalping

# =============================================================================
# AGENT 1: SENTIMENT AGENT ("The Analyst")
# =============================================================================
class SentimentAgent:
    def __init__(self, use_ai=True):
        self.use_ai = use_ai and (GEMINI_API_KEY is not None)
        self.vader = SentimentIntensityAnalyzer()
        self.cache = {} # Format: {symbol: {'score': float, 'time': datetime}}
        self.cache_duration = timedelta(minutes=60) # Cache for 1 hour
        
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
        # 1. Check Cache
        now = datetime.now()
        if symbol in self.cache:
            last_run = self.cache[symbol]['time']
            if (now - last_run) < self.cache_duration:
                cached_score = self.cache[symbol]['score']
                logger.info(f"Using Cached Sentiment for {symbol}: {cached_score}")
                return {'score': cached_score}

        headlines = self.get_news(symbol)
        if not headlines:
            logger.info(f"No news found for {symbol}. Neutral score.")
            return {'score': 0.0}

        text_block = "\n".join(headlines)
        
        # Method A: Google Gemini
        if self.use_ai:
            try:
                # Basic sleep to respect Rate Limits (15 RPM)
                time.sleep(2) 
                
                prompt = (
                    "You are a financial analyst. Analyze the sentiment of these headlines. "
                    "Return ONLY a single float number between -1.0 (Very Negative) and 1.0 (Very Positive).\n\n"
                    f"Headlines for {symbol}:\n{text_block}"
                )
                response = self.model.generate_content(prompt)
                score_str = response.text.strip()
                score = float(score_str)
                logger.info(f"Gemini Sentiment for {symbol}: {score}")
                
                # Update Cache
                self.cache[symbol] = {'score': score, 'time': now}
                
                return {'score': score}
            except Exception as e:
                logger.error(f"Gemini Failed: {e}. Falling back to VADER.")
                # Fallthrough to VADER

        # Method B: VADER
        scores = [self.vader.polarity_scores(h)['compound'] for h in headlines]
        avg_score = sum(scores) / len(scores) if scores else 0
        logger.info(f"VADER Sentiment for {symbol}: {avg_score}")
        
        # Update Cache (even for VADER, to reduce news fetching spam)
        self.cache[symbol] = {'score': avg_score, 'time': now}
        
        return {'score': avg_score}

# =============================================================================
# AGENT 2: FUNDAMENTAL AGENT ("The Warren Buffett")
# =============================================================================
class FundamentalAgent:
    def analyze(self, symbol):
        """Returns a Quality Score (0-10)."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # NoneType Check for info
            if info is None:
                logger.warning(f"FundamentalAgent: No info found for {symbol}")
                return {'score': 5, 'beta': None, 'days_to_earnings': 999}

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
            rec = info.get('recommendationKey', 'none')
            if rec:
                rec = rec.lower()
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
                # Wrap in try/except for specific property failure
                cal = None
                try:
                    cal = ticker.calendar
                except Exception:
                    cal = None

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
                
                # Fallback for DataFrame structure
                elif hasattr(cal, 'empty') and not cal.empty and 'Earnings Date' in cal.index:
                    next_earn = cal.loc['Earnings Date']
                    if len(next_earn) > 0:
                        next_earn = next_earn.iloc[0]
                        days_to_earnings = (next_earn - datetime.now(pytz.timezone('America/New_York'))).days
                        
            except Exception as e:
                logger.warning(f"Could not fetch earnings date for {symbol}: {e}")

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
            # SWITCH: Use Ticker.history (Thread-safe, cleaner) instead of download
            tick = yf.Ticker(symbol)
            df = tick.history(start=start_date, interval=interval, auto_adjust=True)
            
            if df.empty: return None
            
            # Flatten MultiIndex if present (Rare in history(), but possible)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Standardize Columns
            df.columns = df.columns.str.lower()
            
            # Remove Timezone info from index if causing issues (optional, but good practice)
            # df.index = df.index.tz_localize(None) 
            
            # Deduplicate columns (Fixes 'Cannot set DataFrame to multiple columns' error)
            df = df.loc[:, ~df.columns.duplicated()]
            
            # Validation
            if 'close' not in df.columns:
                logger.error(f"Data Fetch Error {symbol}: 'close' column missing. found: {df.columns.tolist()}")
                return None

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
        # Use .get() for safety
        sma_50 = latest_d.get('SMA_50')
        sma_200 = latest_d.get('SMA_200')
        
        if sma_50 is None or sma_200 is None:
             logger.warning(f"{symbol}: SMA data missing (Daily).")
             return {'signal': 'WAIT'}

        daily_up = sma_50 > sma_200
        
        if not daily_up:
            return {'signal': 'WAIT', 'reason': 'Daily Trend Down'}

        # 2. Hourly Trend (Golden Cross)
        start_h = datetime.now() - timedelta(days=self.hourly_lookback)
        df_h = self.fetch_data(symbol, start_h, '1h')
        if df_h is None or len(df_h) < 200: return {'signal': 'WAIT'}
        
        df_h.ta.sma(length=50, append=True)
        df_h.ta.sma(length=200, append=True)
        
        latest_h = df_h.iloc[-1]
        
        # Use .get() for safety
        sma_50_h = latest_h.get('SMA_50')
        sma_200_h = latest_h.get('SMA_200')

        if sma_50_h is None or sma_200_h is None:
             logger.warning(f"{symbol}: SMA data missing (Hourly).")
             return {'signal': 'WAIT'}

        hourly_up = sma_50_h > sma_200_h

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
        # Harden lookups with .get() to prevent crashes
        is_uptrend = latest.get('SMA_20', 0) > latest.get('SMA_50', 0)
        not_overbought = latest.get('RSI_14', 50) < 70
        price_above_vwap = latest.get('close', 0) > latest.get('VWAP_D', 0)
        
        # MACD Check: MACD > Signal (Bullish Momentum)
        macd_bullish = True
        if macd_col in latest and signal_col in latest:
            macd_bullish = latest[macd_col] > latest[signal_col]
        
        # Volume Check
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
# STRATEGY CONSTANTS (Moved for visibility)
# =============================================================================
TARGET_PORTFOLIO_VALUE = 100000.0 # 💰 MASTER VALUE: Controls all sizing!
                                  # Update this single value to scale the bot.

# Allocations (Percent of TARGET_PORTFOLIO_VALUE)
OPTIONS_ALLOC_PCT = 0.10          # 10% ($10,000)
SWING_ALLOC_PCT = 0.60            # 60% ($60,000)
SCALP_ALLOC_PCT = 0.30            # 30% ($30,000)

# Options Limits
OPTIONS_TOTAL_BUDGET = TARGET_PORTFOLIO_VALUE * OPTIONS_ALLOC_PCT
OPTIONS_TRADE_CAP = OPTIONS_TOTAL_BUDGET / 10.0 # Auto-size: 1/10th of budget

ABOVE_25K = True           # Set to True if Equity > $25,000 (PDT Rules)
ENABLE_OPTIONS = False     # ⚠️ CODE SWITCH: Master Control for Options Trading

# ... Note: Other constants are defined earlier in file or here. 
# For safety, ensure we don't duplicate. 
# Previously defined: SWING_ALLOCATION, SCALP_ALLOCATION at Strategy Level (dynamic?)
# Let's just restore the code flow.

# =============================================================================
# AGENT 3.5: DAY TRADING AGENT ("The Scalper")
# =============================================================================
class DayTradingAgent:
    """
    ⚡ THE SCALPER
    Focus: Intraday volatility (1m - 15m charts).
    Strategy: Mean Reversion (RSI) + Momentum (MACD - Fast).
    """
    def __init__(self):
        pass

    def analyze(self, symbol):
        try:
            # Switch to Ticker.history for consistency with TechnicalAgent
            # Notes: history(interval='5m') requires period='60d' max usually.
            # But recent yfinance updates allow start/end for intraday to some extent.
            # Safer to use period="5d" for 5m data.
            tick = yf.Ticker(symbol)
            df = tick.history(period="5d", interval="5m", auto_adjust=True)
            
            if df.empty or len(df) < 50:
                return {'signal': 'WAIT', 'reason': 'No Data'}
                
            # Flatten MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Standardize
            df.columns = df.columns.str.lower()
            
            # Deduplicate
            df = df.loc[:, ~df.columns.duplicated()]

            # Indicators
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.vwap(append=True) # Volume Weighted Average Price

            latest = df.iloc[-1]
            close = latest['close']

            # Fix: pandas_ta uses Uppercase by default (RSI_14)
            # We try both to be safe, or just use Upper.
            rsi = latest.get('RSI_14', latest.get('rsi_14', 50.0))
            
            # MACD Names: MACD_12_26_9, MACDs_12_26_9
            macd_col = 'MACD_12_26_9'
            signal_col = 'MACDs_12_26_9'
            
            macd_val = latest.get(macd_col, 0)
            signal_val = latest.get(signal_col, 0)
            
            # SCALPING LOGIC
            # 1. RSI Extremes (Mean Reversion / Momentum Start)
            # RSI < 30 is Oversold. If MACD is turning up, it's a sniper entry.
            if rsi < 30 and macd_val > signal_val: 
                return {
                    'signal': 'BUY', 
                    'reason': 'Scalp: RSI Oversold + MACD Cross', 
                    'price': close, 
                    'type': 'SCALP'
                }
                    
            return {'signal': 'WAIT', 'reason': f"RSI {rsi:.1f} / Neutral", 'price': close}

        except Exception as e:
            logger.error(f"DayTradingAgent Error {symbol}: {e}")
            return {'signal': 'ERROR', 'reason': str(e)}

# =============================================================================
# AGENT 3.8: OPTIONS AGENT ("The Quant")
# =============================================================================
class OptionsAgent:
    """
    🧬 THE QUANT
    Focus: Options Chain Analysis & Contract Selection.
    Strategy: 
      - Bullish -> Long Calls (Delta ~0.30-0.50)
      - Bearish -> Long Puts (Neg Delta ~0.30-0.50)
      - Liquidity Check: Open Interest > 500, Volume > 100.
      - Expiry: 30-45 Days (Swing) or >7 Days (Scalp/Gamma).
    """
    def __init__(self):
        pass

    def get_optimal_contract(self, symbol, sentiment_score, technical_signal):
        """
        Finds the best contract symbol based on analysis.
        Returns: {'contract': 'AMD230616C00120000', 'type': 'call', 'price': 1.50, ...}
        """
        try:
            tk = yf.Ticker(symbol)
            expirations = tk.options
            
            if not expirations:
                return None
            
            # 1. Select Expiration (Aim for ~30 days out for optimal Theta/Gamma balance)
            # We filter for dates roughly 20-45 days away.
            target_date = None
            today = datetime.now()
            
            for date_str in expirations:
                exp_date = datetime.strptime(date_str, "%Y-%m-%d")
                days_out = (exp_date - today).days
                if 20 <= days_out <= 50:
                    target_date = date_str
                    break
            
            if not target_date:
                # Fallback: Next available if no monthly in range
                target_date = expirations[1] if len(expirations) > 1 else expirations[0]
                
            logger.info(f"🧬 Options Analysis {symbol}: Target Expiry {target_date}")
            
            # 2. Get Chain
            chain = tk.option_chain(target_date)
            
            # 3. Determine Side
            is_bullish = (technical_signal == 'BUY') and (sentiment_score > 0.2)
            options_df = chain.calls if is_bullish else chain.puts
            side_label = "CALL" if is_bullish else "PUT"
            
            # 4. Filter for Liquidity & Strike
            # We want: 
            # - Volume > 50 (Ensure some trading)
            # - Open Interest > 100 (Ensure market depth)
            # - Slightly OTM (Out of The Money) for leverage, or ATM.
            
            hist = tk.history(period="1d")
            if hist.empty:
                logger.warning(f"🧬 No price history for {symbol}")
                return None
            current_price = hist['Close'].iloc[-1]
            
            # Add strict filtering
            liquid_opts = options_df[ (options_df['volume'] > 50) & (options_df['openInterest'] > 100) ].copy()
            
            if liquid_opts.empty:
                logger.warning(f"🧬 No liquid options found for {symbol} {side_label}")
                return None
                
            # Calculates Distance from Price
            liquid_opts['dist'] = abs(liquid_opts['strike'] - current_price)
            
            # Sort by distance (Find ATM/Near OTM)
            # If Bullish (Call), we usually want Strike >= Price (OTM) or Strike ~ Price (ATM)
            # If Bearish (Put), we want Strike <= Price (OTM) or Strike ~ Price (ATM)
            # For simplicity & Safety: Closest Strike to Current Price (ATM) has 0.5 Delta usually.
            
            liquid_opts.sort_values(by='dist', inplace=True)
            best_contract = liquid_opts.iloc[0]
            
            contract_symbol = best_contract['contractSymbol']
            strike = best_contract['strike']
            last_price = best_contract['lastPrice']
            iv = best_contract['impliedVolatility']
            
            logger.info(f"🧬 Selected {side_label}: {contract_symbol} (Strike: {strike}, IV: {iv:.2f}, Last: ${last_price})")
            
            return {
                'contract_symbol': contract_symbol,
                'type': 'call' if is_bullish else 'put',
                'strike': strike,
                'last_price': last_price,
                'expiry': target_date
            }

        except Exception as e:
            logger.error(f"Options Agent Error: {e}")
            return None

# =============================================================================
# AGENT 4: PORTFOLIO MANAGER ("The Boss")
# =============================================================================
class PortfolioManager:
    def __init__(self, trading_client):
        self.client = trading_client
        self.sentiment_agent = SentimentAgent()
        self.fundamental_agent = FundamentalAgent()
        self.technical_agent = TechnicalAgent()
        self.day_trading_agent = DayTradingAgent() # NEW
        self.options_agent = OptionsAgent() # NEW 3.8



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
                        
                        # --- Calculate PnL & Identify Strategy ---
                        pnl_msg = ""
                        strategy_label = "💰 **HEDGE FUND SELL**" # Default
                        
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
                                
                                # DETECT STRATEGY
                                # 1. Options Check (Symbol length > 6 and contains digits usually)
                                if len(symbol) > 6 and any(char.isdigit() for char in symbol):
                                    strategy_label = "🧬 **OPTION EXIT**"
                                # 2. Stock Check
                                elif last_buy.order_class == OrderClass.BRACKET:
                                    strategy_label = "⚡ **SCALP EXIT**"
                                elif last_buy.client_order_id and last_buy.client_order_id.startswith('scalp_'):
                                    strategy_label = "⚡ **SCALP EXIT**"
                                else:
                                    strategy_label = "💰 **HEDGE FUND SELL**"
                                
                                pnl = (price - buy_price) * qty
                                pnl_pct = (price - buy_price) / buy_price * 100
                                
                                emoji = "📈" if pnl >= 0 else "📉"
                                pnl_msg = f"\n{emoji} PnL: ${pnl:.2f} ({pnl_pct:.2f}%)"
                        except Exception as e:
                            logger.error(f"Error calculating PnL for {symbol}: {e}")

                        logger.info(f"Detected SELL FILL for {symbol}: {qty} @ ${price}")
                        
                        # Send Discord Alert
                        msg = (f"{strategy_label}: {symbol}\n"
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

    def safe_close_position(self, symbol):
        """
        Cancels all open orders for a symbol before closing the position.
        Prevents 'insufficient qty' errors if shares are locked in Trailing Stops.
        """
        try:
            logger.info(f"🛡️ Safe Close: Cancelling open orders for {symbol}...")
            # Fetch open orders for this symbol
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            orders = self.client.get_orders(filter=req)
            
            for o in orders:
                self.client.cancel_order_by_id(o.id)
                logger.info(f"   Cancelled Order {o.id} ({o.order_type})")
            
            if orders:
                time.sleep(0.5) # Wait for cancellation to propagate
            
            logger.info(f"🛡️ Safe Close: Closing Position {symbol}...")
            self.client.close_position(symbol)
        except Exception as e:
            logger.error(f"❌ Safe Close Failed for {symbol}: {e}")

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

    def get_position_counts(self):
        """
        Returns a dictionary with counts of 'scalp' and 'swing' positions.
        Identifies Scalps by checking if the associated Buy Order has 'scalp_' in client_order_id.
        """
        counts = {'scalp': 0, 'swing': 0}
        try:
            positions = self.client.get_all_positions()
            for p in positions:
                symbol = p.symbol
                # We need to find the OPENING buy order to check its ID
                # This is resource intensive if we have many positions, but reliable.
                # Optimization: We check 'filled' orders for this symbol.
                # Optimization: We check 'filled' orders for this symbol.
                req = GetOrdersRequest(
                    status=QueryOrderStatus.CLOSED,
                    symbols=[symbol],
                    side=OrderSide.BUY,
                    limit=1,
                    direction='desc'
                )
                orders = self.client.get_orders(filter=req)
                
                if orders:
                    last_buy = orders[0]
                    if last_buy.client_order_id and last_buy.client_order_id.startswith('scalp_'):
                        counts['scalp'] += 1
                    else:
                        counts['swing'] += 1
                else:
                    # Fallback if no order found (legacy position)
                    counts['swing'] += 1
                    
            logger.info(f"Position Counts: {counts}")
            return counts
        except Exception as e:
            logger.error(f"Error counting positions: {e}")
            return {'scalp': 10, 'swing': 10} # Conservative fallback (block trades)

    def manage_options_risk(self):
        """
        🛡️ OPTIONS RISK MANAGER (3-Layer Defense)
        1. Theta Guard: Close if held > 10 days (Time Decay).
        2. Smart Exit: Close if Underlying Stock Sentiment reversal.
        3. Bracket: Close if PnL < -30% (Stop) or > +50% (Take Profit).
        Only runs if ENABLE_OPTIONS is True.
        """
        if not ENABLE_OPTIONS:
            return

        try:
            positions = self.client.get_all_positions()
            for p in positions:
                # Identify Options (Asset Class check or Symbol check)
                # Alpaca Position object usually has asset_class='us_option'
                is_option = False
                if hasattr(p, 'asset_class') and p.asset_class == 'us_option':
                    is_option = True
                elif len(p.symbol) > 6 and any(c.isdigit() for c in p.symbol):
                    is_option = True
                
                if not is_option:
                    continue

                symbol = p.symbol
                qty = float(p.qty)
                avg_entry = float(p.avg_entry_price)
                current_price = float(p.current_price)
                unrealized_plpct = float(p.unrealized_plpc) # e.g. 0.05 for 5%
                
                # Parse Underlying (Naive Parser for standard OCC: ROOT + DATE + SIDE + STRIKE)
                # We need root. Usually non-digits at start.
                root_match = re.match(r'^([A-Z]+)', symbol)
                underlying = root_match.group(1) if root_match else None
                
                if not underlying: 
                    continue # Safety skip

                # LAYER 1: THETA GUARD (Time)
                # Check how long we've held it. Alpaca doesn't give 'filled_at' on Position easily, 
                # we assume 'created_at' logic or we check the Order.
                # Simplified: If we can't easily get age, we might skip Layer 1 for V1, 
                # but let's try to get the 'filled_at' of the open order.
                # Optimization: For now, we rely on PnL/Techs (Layer 2/3) mostly. 
                # To implement Theta Guard properly we need order history lookup.
                # Let's Skip Layer 1 implementation in this function to avoid API spam, 
                # considering usually Smart Exit catches it.
                
                # LAYER 3: BRACKET (Price) - Checked BEFORE Smart Exit for hard stops?
                # or AFTER? User said "no specific order". Let's check Hard Stops first.
                
                # Stop Loss (-30%)
                if unrealized_plpct <= -0.30:
                     logger.info(f"🛡️ Options Stop Loss Triggered for {symbol}: {unrealized_plpct*100:.2f}%")
                     self.client.close_position(symbol)
                     msg = f"🧬 **OPTION STOP LOSS**: {symbol}\n📉 PnL: {unrealized_plpct*100:.2f}% (Hit -30%)"
                     send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                     continue

                # Take Profit (+50%)
                if unrealized_plpct >= 0.50:
                     logger.info(f"🛡️ Options Take Profit Triggered for {symbol}: {unrealized_plpct*100:.2f}%")
                     self.client.close_position(symbol)
                     msg = f"🧬 **OPTION TAKE PROFIT**: {symbol}\n📈 PnL: {unrealized_plpct*100:.2f}% (Hit +50%)"
                     send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                     continue

                # LAYER 2: SMART EXIT (Technicals)
                # Analyze Underlying
                # Only check if we are NOT making huge profit/loss (middle ground)
                logger.info(f"🧬 Checking Smart Exit for {symbol} (Underlying: {underlying})...")
                tech_res = self.technical_agent.analyze(underlying)
                
                # Determine Option Side (Call vs Put)
                # Symbol Format: ROOT...C... or P...
                # Regex to find 'C' or 'P' after date?
                # Simple check: If 'C' in symbol and 'P' not in symbol? Risky.
                # Better: Parse the 7th-to-last char?
                # OCC: Last 8 chars are strike. 9th from last is Type (C/P).
                # Example: AMD230616C00120000 -> C is at index -9.
                type_char = symbol[-9] 
                
                should_close = False
                reason = ""
                
                if type_char == 'C': # CALL
                    # Close Call if Signal is SELL or MACD Bearish
                    if tech_res['signal'] == 'SELL' or tech_res.get('reason') == 'MACD Bearish':
                        should_close = True
                        reason = f"Call Invalidated: {tech_res.get('reason')}"
                elif type_char == 'P': # PUT
                    # Close Put if Signal is BUY or MACD Bullish
                    if tech_res['signal'] == 'BUY': # Tech Agent usually returns BUY for bullish
                        should_close = True
                        reason = f"Put Invalidated: Underlying Bullish ({tech_res.get('reason')})"
                
                if should_close:
                     logger.info(f"🧬 Smart Exit Triggered for {symbol}: {reason}")
                     self.client.close_position(symbol)
                     msg = (f"🧬 **OPTION SMART EXIT**: {symbol}\n"
                            f"📉 Reason: {reason}\n"
                            f"💵 PnL: {unrealized_plpct*100:.2f}%")
                     send_discord_alert(msg, DISCORD_WEBHOOK_URL)

        except Exception as e:
            logger.error(f"Error managing options risk: {e}")

    def execute_scalp_buy(self, symbol, price, budget):
        logger.info(f"⚡ SCALP SIGNAL for {symbol} @ ${price:.2f}")
        
        # Sizing Logic: Target 10% of Scalp Budget per trade
        target_val = budget / 10.0
        target_shares = int(target_val / price)
        
        # Safety Check: Do not exceed the Scalp Budget (Hard Cap)
        max_shares_budget = int(budget / price)
        
        qty = min(target_shares, max_shares_budget)
        qty = max(1, qty)
        
        # Calculate Stop Price (Initial Fixed Stop before Upgrade)
        # We set a distinct initial stop (e.g. 2% wide) to give it room before the Trailing Stop takes over
        stop_price = price * 0.98 
        
        logger.info(f"⚡ Scalp Entry: Buy {qty} @ ${price:.2f} (~${qty*price:.0f}) | Initial Stop: ${stop_price:.2f}")
        
        try:
            # UNIFIED STRATEGY: Use OTO (Buy + Fixed Stop)
            # We add a custom client_order_id to distinguish this as a Scalp for notifications.
            oid = f"scalp_{symbol}_{int(time.time())}"
            
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=str(qty),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.OTO,
                stop_loss={'stop_price': round(stop_price, 2)},
                client_order_id=oid
            )
            self.client.submit_order(order_data=order_data)
            
            msg = (f"⚡ **SCALP ENTRY**: {symbol}\n"
                   f"📊 Qty: {qty} @ ${price:.2f}\n"
                   f"🛑 Initial Stop: ${stop_price:.2f} (-2.0%)\n"
                   f"🛡️ Strategy: Will upgrade to Trailing Stop\n"
                   f"-----------------------------------------------------")
            send_discord_alert(msg, DISCORD_WEBHOOK_URL)
            
        except Exception as e:
            logger.error(f"Scalp Execution Failed: {e}")

    def execute_strategy(self, symbol, check_swing=True):
        # 0. Calculate Allocations based on TARGET_PORTFOLIO_VALUE
        # User defined: Options 10%, Swing 60%, Scalp 30% of TOTAL.
        swing_budget = TARGET_PORTFOLIO_VALUE * SWING_ALLOC_PCT
        scalp_budget = TARGET_PORTFOLIO_VALUE * SCALP_ALLOC_PCT
        
        logger.info(f"--- Analyzing {symbol} (Swing=${swing_budget:.0f}, Scalp=${scalp_budget:.0f}) ---")
        
        # Get Current Position Counts
        counts = self.get_position_counts()
        
        # 1. Check Existing Position
        position = None
        try:
            position = self.client.get_open_position(symbol)
        except Exception:
            position = None

        # --- 1. CONTINUOUS EXIT MONITORING (Always Run) ---
        # Checks for 10% TP and Smart Exit every cycle (1 min).
        tech_result = None
        if position:
            # Gather Technicals for Exit Analysis
            tech_result = self.technical_agent.analyze(symbol)
            
            if tech_result and 'close' in tech_result:
                price = tech_result['close']
                avg_entry = float(position.avg_entry_price)
                
                if price >= avg_entry:
                    # Calculate Unrealized PnL %
                    pnl_pct = (price - avg_entry) / avg_entry * 100
                    
                    # A) PRIORITY 1: HARD TAKE PROFIT (+10%)
                    if pnl_pct >= 10.0:
                        logger.info(f"💰 {symbol} hit +{pnl_pct:.2f}% Profit Target (>= 10%). TAKING PROFIT IMMEDIATELY.")
                        try:
                             qty_held = float(position.qty)
                             pnl_dollars = (price - avg_entry) * qty_held
                             
                             self.safe_close_position(symbol)
                             msg = (f"🚀 **MOONSHOT EXIT**: {symbol}\n"
                                    f"💰 Profit Target Hit (+10%)\n"
                                    f"💵 Price: ${price:.2f} (Entry: ${avg_entry:.2f})\n"
                                    f"💸 PnL: +${pnl_dollars:.2f} (+{pnl_pct:.2f}%)\n"
                                    f"-----------------------------------------------------")
                             send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                             return # Stop processing
                        except Exception as e:
                             logger.error(f"Failed to Take Profit {symbol}: {e}")
                             return

                    # B) PRIORITY 2: SMART EXIT LOGIC (TECHNICAL BREAKDOWN)
                    exit_reasons = ['MACD Bearish', 'Daily Trend Down', 'Hourly Trend Down']
                    tech_reason = tech_result.get('reason', '')
                    
                    if tech_result['signal'] == 'WAIT' and tech_reason in exit_reasons:
                          logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Higher. FOUND BEARISH SIGNAL: {tech_reason}. TAKING PROFIT. 💰")
                          try:
                              qty_held = float(position.qty)
                              pnl_dollars = (price - avg_entry) * qty_held
                              
                              self.client.close_position(symbol)
                              msg = (f"💰 **SMART EXIT**: {symbol}\n"
                                     f"📉 Reason: Technical Breakdown ({tech_reason})\n"
                                     f"💵 Price: ${price:.2f} (Entry: ${avg_entry:.2f})\n"
                                     f"💸 PnL: +${pnl_dollars:.2f} (+{pnl_pct:.2f}%)\n"
                                     f"-----------------------------------------------------")
                              send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                              return # Stop processing
                          except Exception as e:
                              logger.error(f"Failed to Smart Exit {symbol}: {e}")
                              return
                    
                    # If we are here, we are Profitable but Holding.
                    logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Higher (+{pnl_pct:.2f}%). No Exit Signal.")
                
                else:
                     logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Lower.")



        # --- BRANCH 1: SCALPING CHECK (Priority for Intra-day) ---
        # Only run if not holding, above 25k, and under the 10-position limit
        if not position and ABOVE_25K:
             if counts['scalp'] < 10:
                 scalp_res = self.day_trading_agent.analyze(symbol)
                 if scalp_res['signal'] == 'BUY':
                     # Pass Calculated Scalp Budget
                     self.execute_scalp_buy(symbol, scalp_res['price'], scalp_budget)
                     # Note: We return here to give Scalp the cycle priority. 
                     # Only one action per symbol per cycle.
                     return 
             else:
                 logger.info(f"Scalp Limit Reached ({counts['scalp']}/10). Skipping Scalp Check.")

        # If we are not checking swing this cycle, exit now
        if not check_swing:
            return

        # --- BRANCH 2: SWING STRATEGY (V5 Original) ---
        # Limit Check
        if counts['swing'] >= 10 and not position: 
             logger.info(f"Swing Limit Reached ({counts['swing']}/10). Skipping Swing Check for new positions.")
             if not position: return # Block new

        # 2. Gather Intelligence (Technical First - to get Price)
        tech_result = self.technical_agent.analyze(symbol)
        # Check signal later, AFTER we check for Smart Exit / Profit Taking
        # if tech_result['signal'] != 'BUY': ... (Moved down)

        if not tech_result or 'close' not in tech_result:
             return

        price = tech_result['close'] # Current Price

        # 3. POSITION LOGIC: Average Down Check
        # (Exit Logic moved to top of function)
        if position:
            avg_entry = float(position.avg_entry_price)
            if price >= avg_entry:
                 # We already checked for exits at top of loop. If we are here, we hold.
                 return
            else:
                logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Lower. EVALUATING TO ADD MORE 🚨")
                # We continue to Agents...

        # --- SIGNAL CHECK ---
        # Ensure we have a BUY signal before proceeding to Fundamental/Sentiment Analysis.
        if tech_result['signal'] != 'BUY':
             if not position:
                 logger.info(f"Technical Agent says WAIT ({tech_result.get('reason')}).")
             else:
                 logger.info(f"Technical Agent says WAIT ({tech_result.get('reason')}). Holding (Skipping Add).")
             return


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

        sent_result = self.sentiment_agent.analyze(symbol)
        sent_score = sent_result['score']
        
        # EARNINGS OVERRIDE CHECK
        if is_earnings_risk and sent_score <= 0.5:
             logger.info(f"❌ Earnings Risk ({days_to_earnings}d) + Weak Sentiment ({sent_score}). SKIP.")
             return
             
        if sent_score < 0: # Negative sentiment
            logger.info(f"Sentiment Agent rejects {symbol} (Score: {sent_score}).")
            return
        
        # DECISION 
        is_strong_buy = (fund_score >= 7) and (sent_score >= 0.2)
        
        if is_strong_buy:
             # >>> OPTIONS BRANCH (Feature Gated) <<<
             if ENABLE_OPTIONS and not position:
                 # Options Logic: If High conviction, maybe buy Call instead of Stock? 
                 # Or treat as "Swing" allocation.
                 logger.info(f"🧬 Checking Options for {symbol}...")
                 opt_res = self.options_agent.get_optimal_contract(symbol, sent_score, 'BUY')
                 


                 if opt_res:
                     # Calculate Sizing (Portfolio Constraint)
                     try:
                         # 1. Calculate Current Options Exposure
                         current_opt_exposure = 0.0
                         all_positions = self.client.get_all_positions()
                         for p in all_positions:
                             if hasattr(p, 'asset_class') and p.asset_class == 'us_option':
                                 current_opt_exposure += float(p.market_value)
                             elif len(p.symbol) > 6 and any(c.isdigit() for c in p.symbol): # Fallback
                                 current_opt_exposure += float(p.market_value)
                         
                         # 2. Determine Budget
                         available_budget = OPTIONS_TOTAL_BUDGET - current_opt_exposure
                         trade_amt = min(OPTIONS_TRADE_CAP, available_budget)
                         
                         contract_price = opt_res['last_price'] * 100 # x100 Multiplier
                         
                         # Need enough for at least 1 contract
                         if trade_amt >= contract_price and trade_amt >= 100: # Min $100 trade
                             num_contracts = int(trade_amt / contract_price)
                             num_contracts = max(1, num_contracts)
                             
                             total_cost = num_contracts * contract_price
                             
                             logger.info(f"🧬 EXECUTE OPTION: Buy {num_contracts}x {opt_res['contract_symbol']} @ ~${opt_res['last_price']} (Total: ${total_cost:.2f})")
                             
                             # NOTIFICATION (Simulation or Real)
                             msg = (f"🧬 **QUANT OPTION ENTRY**: {symbol}\n"
                                    f"🎫 Contract: {opt_res['contract_symbol']}\n"
                                    f"📊 Size: {num_contracts} contracts (~${total_cost:.0f})\n"
                                    f"💵 Price: ${opt_res['last_price']:.2f} (x100)\n"
                                    f"📅 Expiry: {opt_res['expiry']}\n"
                                    f"🧠 Reasoning: Sentiment {sent_score:.2f} + Strong Fundamentals\n"
                                    f"ℹ️ Budget: ${current_opt_exposure:.0f}/${OPTIONS_TOTAL_BUDGET:.0f} Used\n"
                                    f"-----------------------------------------------------")
                             
                             if ENABLE_OPTIONS:
                                 # TODO: self.client.submit_order(...)
                                 # order_data = MarketOrderRequest...
                                 send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                         else:
                             logger.info(f"🧬 Options Budget Full or Insufficient ({current_opt_exposure}/{OPTIONS_TOTAL_BUDGET}). Skipping.")

                     except Exception as e:
                         logger.error(f"Option Sizing Error: {e}")
             
             # >>> STOCK BUY EXECUTION <<<
             atr = tech_result['atr']
             stop_price = price - (atr * 2.0)
             
             # Sizing: Equal Weight (Budget / 10 Positions)
             target_pos = swing_budget / 10.0
             qty = int(target_pos / price)
             qty = max(1, qty)
             
             # Vol check
        
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

        # 5. SANITY CHECK (Crucial for Order Validation)
        # Ensure Stop Price is valid (Stop < Price for BUY)
        if stop_price >= price:
             logger.error(f"❌ Order Prep Failed: Stop Price ${stop_price:.2f} >= Entry ${price:.2f}. Volatility too high or Logic Error.")
             return
        
        # Ensure Not NaN
        if math.isnan(qty) or math.isnan(stop_price):
             logger.error("❌ Order Prep Failed: NaN value detected.")
             return

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
    logger.info("Initializing AI Hedge Fund V6...")
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
                
                # Run the 15-minute Cycle
                # We iterate 15 times (0 to 14).
                # Minute 0: Check Scalp AND Swing.
                # Minute 1-14: Check Scalp ONLY.
                for i in range(15):
                    check_swing = (i == 0)
                    
                    if i > 0: 
                        logger.info(f"--- Minute {i}/15: Scalp Scan Only (Parallel) ---")
                    else:
                        logger.info("--- Minute 0/15: Swing & Scalp Scan (Parallel) ---")

                    # PARALLEL EXECUTION
                    # We use max_workers=5 to respect API Rate Limits.
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        # Submit all strategy calls
                        futures = {executor.submit(manager.execute_strategy, symbol, check_swing): symbol for symbol in SYMBOLS}
                        
                        # Wait for completion (optional, blocking here ensures we finish before sleeping)
                        for future in concurrent.futures.as_completed(futures):
                            symbol = futures[future]
                            try:
                                future.result()
                            except Exception as exc:
                                logger.error(f"{symbol} generated an exception: {exc}")

                    # Sleep 60 seconds (approx)
                    # We ran in parallel, so execution should be fast (<5s).
                    logger.info("Cycle Complete. Waiting 60s...")
                    time.sleep(60)
                    
                    # Maintain Stops & Fills constantly
                    last_fill_check_time = manager.check_fills_and_notify(last_fill_check_time)
                    manager.upgrade_stops()
                    manager.manage_options_risk() # NEW: Options Defense Layer
            
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
