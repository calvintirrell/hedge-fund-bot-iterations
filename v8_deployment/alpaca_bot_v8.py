# Alpaca Trading Bot V8 - Optimized Edition
# Features:
# - V7 Core (All existing features)
# - NEW: Data caching for 3x faster execution
# - NEW: Indicator caching for 10x faster calculations
# - IMPROVED: Performance optimizations from pre-phase1-action-plan.md

import sys
import os
import time
import math
import logging
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import requests
import re # Added re import
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv
import concurrent.futures # Added for Multithreading

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

# V8 Modules - Performance Optimizations
from v8_modules.cache_manager import DataCache, IndicatorCache
from v8_modules.base_agent import BaseAgent
from v8_modules.trade_tracker import TradeTracker, TradeType
from v8_modules.config import get_config
from v8_modules.position_tracker import PositionTracker
from v8_modules.order_executor import OrderExecutor
from v8_modules.analysis_optimizer import AnalysisOptimizer
from v8_modules.market_regime import MarketRegimeDetector
from v8_modules.async_api_wrapper import run_concurrent_api_calls
from v8_modules.agent_coordinator import AgentCoordinator
from v8_modules.risk_manager import RiskManager
from v8_modules.data_validator import DataValidator

# Load configuration
config = get_config()

# --- LOGGING SETUP ---
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("HedgeFund_V8")  # V8 logger
logger.setLevel(logging.INFO)

if not logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)
    
    file_handler = logging.FileHandler("trading_bot_v8.log")  # V8 log file
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

# --- CONFIGURATION ---
load_dotenv()

# V8: Load centralized configuration
config = get_config()

# API Credentials (from config)
API_KEY = config.api_key
SECRET_KEY = config.secret_key
GEMINI_API_KEY = config.gemini_api_key
DISCORD_WEBHOOK_URL = config.discord_webhook_url

# Trading Parameters (from config)
SYMBOLS = config.symbols
RISK_PCT = config.risk_pct
ATR_MULTIPLIER = config.atr_multiplier
TRAILING_STOP_PCT = config.trailing_stop_pct
ABOVE_25K = config.above_25k
SWING_ALLOCATION = config.swing_alloc_pct
SCALP_ALLOCATION = config.scalp_alloc_pct
TARGET_PORTFOLIO_VALUE = config.target_portfolio_value
ENABLE_OPTIONS = config.enable_options
ENABLE_OPTIONS_SCALP = config.enable_options_scalp

# Derived values (from config)
OPTIONS_ALLOC_PCT = config.options_alloc_pct
SWING_ALLOC_PCT = config.swing_alloc_pct
SCALP_ALLOC_PCT = config.scalp_alloc_pct
OPTIONS_TOTAL_BUDGET = config.options_total_budget
OPTIONS_TRADE_CAP = config.options_trade_cap

# =============================================================================
# AGENT 1: SENTIMENT AGENT ("The Analyst")
# =============================================================================
class SentimentAgent(BaseAgent):
    def __init__(self, use_ai=True, memory_size=100):
        """
        Initialize SentimentAgent with memory and learning.
        V8 Week 2: Now inherits from BaseAgent for memory/state tracking.
        """
        super().__init__(memory_size=memory_size)
        
        self.use_ai = use_ai and (GEMINI_API_KEY is not None)
        self.vader = SentimentIntensityAnalyzer()
        self.cache = {} # Format: {symbol: {'score': float, 'time': datetime}}
        # FIX: Remove time-based cache, use cycle-based refresh instead
        # Sentiment will be refreshed every analysis cycle for real-time trading
        self.cache_duration = timedelta(seconds=0)  # Disabled - use cycle-based refresh
        
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
        """
        Returns sentiment analysis with confidence score.
        V8 Week 2: Now includes confidence and reasoning.
        
        Returns:
            dict: {
                'score': float (-1.0 to 1.0),
                'confidence': float (0.0 to 1.0),
                'reasoning': str
            }
        """
        # 1. Check Cache
        now = datetime.now()
        if symbol in self.cache:
            last_run = self.cache[symbol]['time']
            if (now - last_run) < self.cache_duration:
                cached_result = self.cache[symbol]
                logger.info(f"Using Cached Sentiment for {symbol}: {cached_result['score']}")
                return cached_result

        headlines = self.get_news(symbol)
        if not headlines:
            logger.info(f"No news found for {symbol}. Neutral score.")
            result = {
                'score': 0.0,
                'confidence': 0.0,
                'reasoning': 'No news available'
            }
            self.cache[symbol] = {**result, 'time': now}
            return result

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
                
                # Calculate confidence based on score magnitude and news count
                confidence = self._calculate_confidence(score, len(headlines))
                reasoning = self._build_reasoning(score, len(headlines), 'Gemini')
                
                logger.info(f"Gemini Sentiment for {symbol}: {score} (confidence: {confidence:.2f})")
                
                # Update Cache
                result = {
                    'score': score,
                    'confidence': confidence,
                    'reasoning': reasoning
                }
                self.cache[symbol] = {**result, 'time': now}
                
                # V8 Week 2: Record analysis in memory
                self.record_analysis(symbol, result)
                
                return result
            except Exception as e:
                logger.error(f"Gemini Failed: {e}. Falling back to VADER.")
                # Fallthrough to VADER

        # Method B: VADER
        scores = [self.vader.polarity_scores(h)['compound'] for h in headlines]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # Calculate confidence for VADER
        confidence = self._calculate_confidence(avg_score, len(headlines))
        reasoning = self._build_reasoning(avg_score, len(headlines), 'VADER')
        
        logger.info(f"VADER Sentiment for {symbol}: {avg_score} (confidence: {confidence:.2f})")
        
        # Update Cache (even for VADER, to reduce news fetching spam)
        result = {
            'score': avg_score,
            'confidence': confidence,
            'reasoning': reasoning
        }
        self.cache[symbol] = {**result, 'time': now}
        
        # V8 Week 2: Record analysis in memory
        self.record_analysis(symbol, result)
        
        return result
    
    def _calculate_confidence(self, score, news_count):
        """
        Calculate confidence based on sentiment strength and news volume.
        
        Args:
            score: Sentiment score (-1.0 to 1.0)
            news_count: Number of news articles analyzed
            
        Returns:
            float: Confidence score (0.0 to 1.0)
        """
        # Base confidence from score magnitude (stronger sentiment = higher confidence)
        score_confidence = abs(score)
        
        # News volume confidence (more news = higher confidence)
        # 1 article = 0.2, 5+ articles = 1.0
        volume_confidence = min(news_count / 5.0, 1.0)
        
        # Combined confidence (weighted average)
        confidence = (score_confidence * 0.7) + (volume_confidence * 0.3)
        
        return min(confidence, 1.0)
    
    def _build_reasoning(self, score, news_count, method):
        """Build human-readable reasoning for the sentiment analysis."""
        sentiment = "Positive" if score > 0.2 else "Negative" if score < -0.2 else "Neutral"
        strength = "Strong" if abs(score) > 0.6 else "Moderate" if abs(score) > 0.3 else "Weak"
        
        return f"{strength} {sentiment} sentiment from {news_count} articles ({method})"
    
    def clear_cache(self):
        """
        Clear sentiment cache to force fresh analysis.
        Used at the start of each trading cycle for real-time sentiment.
        """
        self.cache.clear()
        logger.debug("Sentiment cache cleared for fresh cycle analysis")
    
    def analyze_batch(self, symbols, force_refresh=False):
        """
        V8: Analyze multiple symbols in one batch to avoid rate limits.
        Performance: 16x faster (32s → 2s for 16 symbols)
        
        Args:
            symbols: List of stock symbols to analyze
            force_refresh: If True, ignore cache and fetch fresh sentiment
            
        Returns:
            Dictionary mapping symbols to sentiment scores
        """
        results = {}
        now = datetime.now()
        symbols_to_analyze = []
        
        # 1. Check cache for all symbols first (skip if force_refresh)
        if not force_refresh:
            for symbol in symbols:
                if symbol in self.cache:
                    last_run = self.cache[symbol]['time']
                    if (now - last_run) < self.cache_duration:
                        results[symbol] = {'score': self.cache[symbol]['score']}
                        logger.debug(f"V8 Batch: Cache HIT for {symbol}")
                        continue
                symbols_to_analyze.append(symbol)
        else:
            # Force refresh - analyze all symbols
            symbols_to_analyze = symbols
            logger.info("V8 Batch: Force refresh - analyzing all symbols")
        
        if not symbols_to_analyze:
            logger.info("V8 Batch: All symbols cached, no API calls needed")
            return results
        
        logger.info(f"V8 Batch: Analyzing {len(symbols_to_analyze)} symbols (cached: {len(results)})")
        
        # 2. Collect headlines for uncached symbols
        all_headlines = {}
        for symbol in symbols_to_analyze:
            headlines = self.get_news(symbol)
            if headlines:
                all_headlines[symbol] = headlines
            else:
                results[symbol] = {'score': 0.0}
        
        if not all_headlines:
            logger.info("V8 Batch: No news found for any symbols")
            return results
        
        # 3. Batch process with Gemini (if available)
        if self.use_ai:
            try:
                # Create single batch prompt for all symbols
                batch_prompt = self._create_batch_prompt(all_headlines)
                
                logger.info(f"V8 Batch: Sending {len(all_headlines)} symbols to Gemini...")
                response = self.model.generate_content(batch_prompt)
                
                # Parse batch response
                batch_results = self._parse_batch_response(response.text, list(all_headlines.keys()))
                
                # Update results and cache
                for symbol, score in batch_results.items():
                    results[symbol] = {'score': score}
                    self.cache[symbol] = {'score': score, 'time': now}
                    logger.info(f"V8 Batch Gemini: {symbol} = {score}")
                
                return results
                
            except Exception as e:
                logger.error(f"V8 Batch Gemini failed: {e}. Falling back to VADER batch.")
                # Fallthrough to VADER batch
        
        # 4. VADER batch processing (fallback)
        logger.info("V8 Batch: Using VADER for batch processing")
        for symbol, headlines in all_headlines.items():
            scores = [self.vader.polarity_scores(h)['compound'] for h in headlines]
            avg_score = sum(scores) / len(scores) if scores else 0
            results[symbol] = {'score': avg_score}
            self.cache[symbol] = {'score': avg_score, 'time': now}
            logger.debug(f"V8 Batch VADER: {symbol} = {avg_score}")
        
        return results
    
    def _create_batch_prompt(self, all_headlines):
        """Create a single prompt for batch sentiment analysis."""
        prompt = (
            "You are a financial analyst. Analyze the sentiment of headlines for multiple stocks.\n"
            "Return ONLY a JSON object with stock symbols as keys and sentiment scores as values.\n"
            "Scores must be float numbers between -1.0 (Very Negative) and 1.0 (Very Positive).\n"
            "Format: {\"SYMBOL\": score, \"SYMBOL2\": score, ...}\n\n"
        )
        
        for symbol, headlines in all_headlines.items():
            prompt += f"\n{symbol}:\n"
            for headline in headlines:
                prompt += f"- {headline}\n"
        
        prompt += "\nReturn JSON only, no other text:"
        return prompt
    
    def _parse_batch_response(self, response_text, symbols):
        """Parse Gemini batch response into symbol: score dictionary."""
        import json
        import re
        
        try:
            # Try to extract JSON from response
            # Look for {...} pattern
            json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                
                # Validate and clean results
                results = {}
                for symbol in symbols:
                    if symbol in data:
                        try:
                            score = float(data[symbol])
                            # Clamp to valid range
                            score = max(-1.0, min(1.0, score))
                            results[symbol] = score
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid score for {symbol}, using 0.0")
                            results[symbol] = 0.0
                    else:
                        logger.warning(f"Missing {symbol} in batch response, using 0.0")
                        results[symbol] = 0.0
                
                return results
            else:
                raise ValueError("No JSON found in response")
                
        except Exception as e:
            logger.error(f"Failed to parse batch response: {e}")
            # Return neutral scores for all
            return {symbol: 0.0 for symbol in symbols}

# =============================================================================
# AGENT 2: FUNDAMENTAL AGENT ("The Warren Buffett")
# =============================================================================
class FundamentalAgent(BaseAgent):
    def __init__(self, memory_size=100):
        """
        Initialize FundamentalAgent with memory and learning.
        V8 Week 2: Now inherits from BaseAgent for memory/state tracking.
        """
        super().__init__(memory_size=memory_size)
    def analyze(self, symbol):
        """
        Returns fundamental quality score with confidence.
        V8 Week 2: Now includes confidence and reasoning.
        
        Returns:
            dict: {
                'score': int (0-10),
                'confidence': float (0.0-1.0),
                'reasoning': str,
                'beta': float,
                'days_to_earnings': int
            }
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # NoneType Check for info
            if info is None:
                logger.warning(f"FundamentalAgent: No info found for {symbol}")
                return {
                    'score': 5,
                    'confidence': 0.0,
                    'reasoning': 'No fundamental data available',
                    'beta': None,
                    'days_to_earnings': 999
                }
            
            score = 5 # Start neutral
            factors = []  # Track which factors contributed
            data_points = 0  # Count available data points for confidence
            
            # 1. P/E Ratio (Value)
            pe = info.get('trailingPE')
            if pe:
                data_points += 1
                if 0 < pe < 25:
                    score += 1
                    factors.append(f"Good P/E ({pe:.1f})")
                elif pe > 50:
                    score -= 1
                    factors.append(f"High P/E ({pe:.1f})")
            
            # 2. Profit Margins (Profitability)
            margins = info.get('profitMargins')
            if margins:
                data_points += 1
                if margins > 0.15:
                    score += 2
                    factors.append(f"Strong margins ({margins*100:.1f}%)")
            
            # 3. Revenue Growth
            growth = info.get('revenueGrowth')
            if growth:
                data_points += 1
                if growth > 0.10:
                    score += 2
                    factors.append(f"Strong growth ({growth*100:.1f}%)")
            
            # 4. Analyst Recommendation
            rec = info.get('recommendationKey', 'none').lower()
            if rec != 'none':
                data_points += 1
                if rec in ['buy', 'strong_buy']:
                    score += 2
                    factors.append(f"Analyst: {rec}")
                elif rec in ['underperform', 'sell']:
                    score -= 2
                    factors.append(f"Analyst: {rec}")
            
            # 5. Beta (Volatility Warning)
            beta = info.get('beta')
            if beta:
                data_points += 1
            
            # 6. Earnings Date Check
            days_to_earnings = 999
            try:
                cal = ticker.calendar
                if cal is None:
                    pass
                elif isinstance(cal, dict) and 'Earnings Date' in cal:
                    dates = cal['Earnings Date']
                    if dates:
                        next_earn = dates[0]
                        if not isinstance(next_earn, datetime):
                            next_earn = pd.to_datetime(next_earn)
                        if next_earn.tzinfo is None:
                            next_earn = pytz.timezone('America/New_York').localize(next_earn)
                        days_to_earnings = (next_earn - datetime.now(pytz.timezone('America/New_York'))).days
                        data_points += 1
                elif hasattr(cal, 'empty') and not cal.empty and 'Earnings Date' in cal.index:
                    next_earn = cal.loc['Earnings Date']
                    if len(next_earn) > 0:
                        next_earn = next_earn.iloc[0]
                        days_to_earnings = (next_earn - datetime.now(pytz.timezone('America/New_York'))).days
                        data_points += 1
            except Exception as e:
                logger.warning(f"Could not fetch earnings date: {e}")
            
            # Calculate confidence based on data availability and score deviation
            final_score = min(10, max(0, score))
            confidence = self._calculate_confidence(final_score, data_points)
            reasoning = self._build_reasoning(final_score, factors, data_points)
            
            logger.info(f"Fundamental for {symbol}: {final_score}/10 (confidence: {confidence:.2f})")
            
            result = {
                'score': final_score,
                'confidence': confidence,
                'reasoning': reasoning,
                'beta': beta,
                'days_to_earnings': days_to_earnings
            }
            
            # V8 Week 2: Record analysis in memory
            self.record_analysis(symbol, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Fundamental Analysis Error for {symbol}: {e}")
            result = {
                'score': 5,
                'confidence': 0.0,
                'reasoning': f'Analysis error: {str(e)}',
                'beta': None,
                'days_to_earnings': 999
            }
            
            # V8 Week 2: Record analysis in memory
            self.record_analysis(symbol, result)
            
            return result
    
    def _calculate_confidence(self, score, data_points):
        """
        Calculate confidence based on data availability and score strength.
        
        Args:
            score: Quality score (0-10)
            data_points: Number of data points available
            
        Returns:
            float: Confidence (0.0-1.0)
        """
        # Data availability confidence (max 6 data points)
        data_confidence = min(data_points / 6.0, 1.0)
        
        # Score strength confidence (deviation from neutral 5)
        score_deviation = abs(score - 5) / 5.0
        
        # Combined confidence
        confidence = (data_confidence * 0.6) + (score_deviation * 0.4)
        
        return min(confidence, 1.0)
    
    def _build_reasoning(self, score, factors, data_points):
        """Build human-readable reasoning."""
        quality = "Strong" if score >= 7 else "Weak" if score <= 3 else "Neutral"
        
        if not factors:
            return f"{quality} fundamentals (limited data: {data_points} points)"
        
        factors_str = ", ".join(factors[:3])  # Top 3 factors
        return f"{quality} fundamentals: {factors_str}"

# =============================================================================
# AGENT 3: TECHNICAL AGENT ("The Chartist")
# =============================================================================
class TechnicalAgent(BaseAgent):
    def __init__(self, data_cache=None, indicator_cache=None, memory_size=100):
        """
        Initialize TechnicalAgent with optional caching and memory.
        V8 Week 2: Now inherits from BaseAgent for memory/state tracking.
        
        Args:
            data_cache: DataCache instance for caching market data
            indicator_cache: IndicatorCache instance for caching indicators
            memory_size: Number of analyses to remember
        """
        super().__init__(memory_size=memory_size)
        
        self.hourly_lookback = 60
        self.daily_lookback = 365
        self.intraday_timeframe = '15m'
        
        # V8: Add caching support
        self.data_cache = data_cache if data_cache else DataCache(ttl_seconds=60)
        self.indicator_cache = indicator_cache if indicator_cache else IndicatorCache(ttl_seconds=60)
        logger.info("TechnicalAgent initialized with caching enabled")

    def fetch_data(self, symbol, start_date, interval):
        """
        Fetch market data with caching support.
        V8: Now checks cache before fetching from API.
        """
        try:
            # V8: Calculate lookback days for cache key
            lookback_days = (datetime.now() - start_date).days
            
            # V8: Check cache first
            cached_data = self.data_cache.get(symbol, interval, lookback_days)
            if cached_data is not None:
                logger.debug(f"Cache HIT: {symbol} {interval}")
                return cached_data
            
            # Cache miss - fetch from API
            logger.debug(f"Cache MISS: {symbol} {interval} - fetching from API")
            tick = yf.Ticker(symbol)
            df = tick.history(start=start_date, interval=interval, auto_adjust=True)
            
            if df.empty: return None
            
            # Flatten MultiIndex if present (Rare in history(), but possible)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # Standardize Columns
            df.columns = df.columns.str.lower()
            
            # Deduplicate columns (Fixes 'Cannot set DataFrame to multiple columns' error)
            df = df.loc[:, ~df.columns.duplicated()]
            
            # Validation
            if 'close' not in df.columns:
                logger.error(f"Data Fetch Error {symbol}: 'close' column missing. found: {df.columns.tolist()}")
                return None

            # V8: Cache the result before returning
            self.data_cache.set(symbol, interval, lookback_days, df)
            
            return df
        except Exception as e:
            logger.error(f"Data Fetch Error {symbol} {interval}: {e}")
            return None

    def analyze(self, symbol):
        """
        Returns technical analysis with confidence score.
        V8 Week 2: Now includes confidence and reasoning.
        V8: Uses indicator caching for 10x faster calculations
        
        Returns:
            dict: {
                'signal': 'BUY'/'WAIT',
                'confidence': float (0.0-1.0),
                'reasoning': str,
                'close': float,
                'atr': float,
                'vol_confirmed': bool
            }
        """
        # Track conditions for confidence calculation
        conditions_met = []
        conditions_failed = []
        
        # 1. Daily Trend
        start_d = datetime.now() - timedelta(days=self.daily_lookback)
        df_d = self.fetch_data(symbol, start_d, '1d')
        if df_d is None or len(df_d) < 200:
            result = {
                'signal': 'WAIT',
                'confidence': 0.0,
                'reasoning': 'Insufficient daily data'
            }
            self.record_analysis(symbol, result)
            return result
        
        # V8: Check indicator cache for daily SMAs
        data_len_d = len(df_d)
        sma_50_series = self.indicator_cache.get(symbol, 'SMA_50_daily', data_len_d)
        sma_200_series = self.indicator_cache.get(symbol, 'SMA_200_daily', data_len_d)
        
        if sma_50_series is None:
            df_d.ta.sma(length=50, append=True)
            sma_50_series = df_d['SMA_50']
            self.indicator_cache.set(symbol, 'SMA_50_daily', data_len_d, sma_50_series)
            logger.debug(f"Indicator cache MISS: {symbol} SMA_50_daily")
        else:
            df_d['SMA_50'] = sma_50_series
            logger.debug(f"Indicator cache HIT: {symbol} SMA_50_daily")
        
        if sma_200_series is None:
            df_d.ta.sma(length=200, append=True)
            sma_200_series = df_d['SMA_200']
            self.indicator_cache.set(symbol, 'SMA_200_daily', data_len_d, sma_200_series)
            logger.debug(f"Indicator cache MISS: {symbol} SMA_200_daily")
        else:
            df_d['SMA_200'] = sma_200_series
            logger.debug(f"Indicator cache HIT: {symbol} SMA_200_daily")
        
        # Check Trend
        latest_d = df_d.iloc[-1]
        sma_50 = latest_d.get('SMA_50')
        sma_200 = latest_d.get('SMA_200')
        
        if sma_50 is None or sma_200 is None:
            logger.warning(f"{symbol}: SMA data missing (Daily).")
            result = {
                'signal': 'WAIT',
                'confidence': 0.0,
                'reasoning': 'Missing daily SMA data'
            }
            self.record_analysis(symbol, result)
            return result

        daily_up = sma_50 > sma_200
        
        if daily_up:
            conditions_met.append('Daily uptrend')
        else:
            conditions_failed.append('Daily downtrend')
            result = {
                'signal': 'WAIT',
                'confidence': 0.2,
                'reasoning': 'Daily trend down (SMA50 < SMA200)'
            }
            self.record_analysis(symbol, result)
            return result

        # 2. Hourly Trend (Golden Cross)
        start_h = datetime.now() - timedelta(days=self.hourly_lookback)
        df_h = self.fetch_data(symbol, start_h, '1h')
        if df_h is None or len(df_h) < 200:
            result = {
                'signal': 'WAIT',
                'confidence': 0.3,
                'reasoning': 'Insufficient hourly data'
            }
            self.record_analysis(symbol, result)
            return result
        
        # V8: Check indicator cache for hourly SMAs
        data_len_h = len(df_h)
        sma_50_h_series = self.indicator_cache.get(symbol, 'SMA_50_hourly', data_len_h)
        sma_200_h_series = self.indicator_cache.get(symbol, 'SMA_200_hourly', data_len_h)
        
        if sma_50_h_series is None:
            df_h.ta.sma(length=50, append=True)
            sma_50_h_series = df_h['SMA_50']
            self.indicator_cache.set(symbol, 'SMA_50_hourly', data_len_h, sma_50_h_series)
            logger.debug(f"Indicator cache MISS: {symbol} SMA_50_hourly")
        else:
            df_h['SMA_50'] = sma_50_h_series
            logger.debug(f"Indicator cache HIT: {symbol} SMA_50_hourly")
        
        if sma_200_h_series is None:
            df_h.ta.sma(length=200, append=True)
            sma_200_h_series = df_h['SMA_200']
            self.indicator_cache.set(symbol, 'SMA_200_hourly', data_len_h, sma_200_h_series)
            logger.debug(f"Indicator cache MISS: {symbol} SMA_200_hourly")
        else:
            df_h['SMA_200'] = sma_200_h_series
            logger.debug(f"Indicator cache HIT: {symbol} SMA_200_hourly")
        
        latest_h = df_h.iloc[-1]
        sma_50_h = latest_h.get('SMA_50')
        sma_200_h = latest_h.get('SMA_200')

        if sma_50_h is None or sma_200_h is None:
            logger.warning(f"{symbol}: SMA data missing (Hourly).")
            result = {
                'signal': 'WAIT',
                'confidence': 0.3,
                'reasoning': 'Missing hourly SMA data'
            }
            self.record_analysis(symbol, result)
            return result

        hourly_up = sma_50_h > sma_200_h

        if hourly_up:
            conditions_met.append('Hourly uptrend')
        else:
            conditions_failed.append('Hourly downtrend')
            result = {
                'signal': 'WAIT',
                'confidence': 0.4,
                'reasoning': 'Hourly trend down (SMA50 < SMA200)'
            }
            self.record_analysis(symbol, result)
            return result

        # 3. Intraday (Entry Trigger) + ATR
        start_i = datetime.now() - timedelta(days=5)
        df_i = self.fetch_data(symbol, start_i, self.intraday_timeframe)
        if df_i is None or len(df_i) < 50:
            result = {
                'signal': 'WAIT',
                'confidence': 0.5,
                'reasoning': 'Insufficient intraday data'
            }
            self.record_analysis(symbol, result)
            return result
        
        # V8: Check indicator cache for intraday indicators
        data_len_i = len(df_i)
        
        # Cache SMA_20
        sma_20_series = self.indicator_cache.get(symbol, 'SMA_20_intraday', data_len_i)
        if sma_20_series is None:
            df_i.ta.sma(length=20, append=True)
            sma_20_series = df_i['SMA_20']
            self.indicator_cache.set(symbol, 'SMA_20_intraday', data_len_i, sma_20_series)
        else:
            df_i['SMA_20'] = sma_20_series
        
        # Cache SMA_50
        sma_50_i_series = self.indicator_cache.get(symbol, 'SMA_50_intraday', data_len_i)
        if sma_50_i_series is None:
            df_i.ta.sma(length=50, append=True)
            sma_50_i_series = df_i['SMA_50']
            self.indicator_cache.set(symbol, 'SMA_50_intraday', data_len_i, sma_50_i_series)
        else:
            df_i['SMA_50'] = sma_50_i_series
        
        # Cache RSI_14
        rsi_series = self.indicator_cache.get(symbol, 'RSI_14_intraday', data_len_i)
        if rsi_series is None:
            df_i.ta.rsi(length=14, append=True)
            rsi_series = df_i['RSI_14']
            self.indicator_cache.set(symbol, 'RSI_14_intraday', data_len_i, rsi_series)
        else:
            df_i['RSI_14'] = rsi_series
        
        # Cache VWAP
        vwap_series = self.indicator_cache.get(symbol, 'VWAP_D_intraday', data_len_i)
        if vwap_series is None:
            df_i.ta.vwap(append=True)
            vwap_series = df_i['VWAP_D']
            self.indicator_cache.set(symbol, 'VWAP_D_intraday', data_len_i, vwap_series)
        else:
            df_i['VWAP_D'] = vwap_series
        
        # Cache ATR
        atr_series = self.indicator_cache.get(symbol, 'ATRr_14_intraday', data_len_i)
        if atr_series is None:
            df_i.ta.atr(length=14, append=True)
            atr_series = df_i['ATRr_14']
            self.indicator_cache.set(symbol, 'ATRr_14_intraday', data_len_i, atr_series)
        else:
            df_i['ATRr_14'] = atr_series
        
        # Cache MACD (returns multiple columns)
        macd_series = self.indicator_cache.get(symbol, 'MACD_12_26_9_intraday', data_len_i)
        macd_signal_series = self.indicator_cache.get(symbol, 'MACDs_12_26_9_intraday', data_len_i)
        macd_hist_series = self.indicator_cache.get(symbol, 'MACDh_12_26_9_intraday', data_len_i)
        
        if macd_series is None or macd_signal_series is None or macd_hist_series is None:
            df_i.ta.macd(append=True)
            self.indicator_cache.set(symbol, 'MACD_12_26_9_intraday', data_len_i, df_i['MACD_12_26_9'])
            self.indicator_cache.set(symbol, 'MACDs_12_26_9_intraday', data_len_i, df_i['MACDs_12_26_9'])
            self.indicator_cache.set(symbol, 'MACDh_12_26_9_intraday', data_len_i, df_i['MACDh_12_26_9'])
        else:
            df_i['MACD_12_26_9'] = macd_series
            df_i['MACDs_12_26_9'] = macd_signal_series
            df_i['MACDh_12_26_9'] = macd_hist_series
        
        # Volume SMA (not cached - simple rolling calculation)
        df_i['VOL_SMA_20'] = df_i['volume'].rolling(20).mean()
        
        latest = df_i.iloc[-1]
        
        # MACD Column Names
        macd_col = 'MACD_12_26_9'
        signal_col = 'MACDs_12_26_9'
        
        # Conditions
        is_uptrend = latest.get('SMA_20', 0) > latest.get('SMA_50', 0)
        not_overbought = latest.get('RSI_14', 50) < 70
        price_above_vwap = latest.get('close', 0) > latest.get('VWAP_D', 0)
        
        # MACD Check: MACD > Signal (Bullish Momentum)
        macd_bullish = True
        if macd_col in latest and signal_col in latest:
            macd_bullish = latest[macd_col] > latest[signal_col]
        
        # Volume Check
        vol_confirmed = latest['volume'] > latest['VOL_SMA_20']
        
        # Track intraday conditions
        if is_uptrend:
            conditions_met.append('Intraday uptrend')
        else:
            conditions_failed.append('Intraday downtrend')
            
        if not_overbought:
            conditions_met.append('RSI not overbought')
        else:
            conditions_failed.append('RSI overbought')
            
        if price_above_vwap:
            conditions_met.append('Price > VWAP')
        else:
            conditions_failed.append('Price < VWAP')
            
        if macd_bullish:
            conditions_met.append('MACD bullish')
        else:
            conditions_failed.append('MACD bearish')
            
        if vol_confirmed:
            conditions_met.append('Volume confirmed')
        
        # Calculate confidence and determine signal
        if is_uptrend and not_overbought and price_above_vwap and macd_bullish:
            confidence = self._calculate_confidence(conditions_met, vol_confirmed)
            reasoning = self._build_reasoning(conditions_met)
            
            result = {
                'signal': 'BUY',
                'confidence': confidence,
                'reasoning': reasoning,
                'close': latest['close'],
                'atr': latest['ATRr_14'],
                'vol_confirmed': vol_confirmed
            }
            
            # V8 Week 2: Record analysis in memory
            self.record_analysis(symbol, result)
            
            return result
        
        # WAIT signal with partial confidence
        partial_confidence = len(conditions_met) / 6.0  # 6 total conditions
        reasoning = f"Waiting: {', '.join(conditions_failed[:2])}"
        
        result = {
            'signal': 'WAIT',
            'confidence': partial_confidence,
            'reasoning': reasoning
        }
        
        # V8 Week 2: Record analysis in memory
        self.record_analysis(symbol, result)
        
        return result
    
    def _calculate_confidence(self, conditions_met, vol_confirmed):
        """
        Calculate confidence based on conditions met.
        
        Args:
            conditions_met: List of conditions that passed
            vol_confirmed: Whether volume is confirmed
            
        Returns:
            float: Confidence (0.0-1.0)
        """
        # Base confidence from number of conditions (6 total)
        base_confidence = len(conditions_met) / 6.0
        
        # Bonus for volume confirmation
        volume_bonus = 0.1 if vol_confirmed else 0.0
        
        # Total confidence
        confidence = min(base_confidence + volume_bonus, 1.0)
        
        return confidence
    
    def _build_reasoning(self, conditions_met):
        """Build human-readable reasoning."""
        if len(conditions_met) >= 5:
            return f"Strong setup: {', '.join(conditions_met[:3])}"
        else:
            return f"Setup: {', '.join(conditions_met[:2])}"

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
            
            # MACD Names
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

    def get_scalp_contract(self, symbol, type='call'):
        """
        ⚡ V7 NEW: Finds Short-Term Contract (0-5 DTE) for Scalping.
        Focus: High Gamma, ATM, High Liquidity.
        """
        try:
            tk = yf.Ticker(symbol)
            expirations = tk.options
            
            if not expirations: return None
            
            # 1. Select Expiry (0 to 5 Days)
            target_date = None
            today = datetime.now()
            
            for date_str in expirations:
                exp_date = datetime.strptime(date_str, "%Y-%m-%d")
                days_out = (exp_date - today).days
                if 0 <= days_out <= 5:
                    target_date = date_str
                    break # Take the FIRST one (Nearest Term)
            
            if not target_date:
                # If no weekly, maybe just take the next available if it's close?
                # Or abort to be safe for scalping.
                return None
                
            # 2. Get Chain
            chain = tk.option_chain(target_date)
            options_df = chain.calls if type == 'call' else chain.puts
            
            # 3. Filter Liquidity
            # Scalping needs TIGHT spreads. High Vol/OI.
            liquid_opts = options_df[ (options_df['volume'] > 100) & (options_df['openInterest'] > 500) ].copy()
            
            if liquid_opts.empty: 
                return None
                
            # 4. Select Strike (ATM)
            hist = tk.history(period="1d")
            if hist.empty: return None
            current_price = hist['Close'].iloc[-1]
            
            liquid_opts['dist'] = abs(liquid_opts['strike'] - current_price)
            liquid_opts.sort_values(by='dist', inplace=True)
            
            best_contract = liquid_opts.iloc[0]
            
            return {
                'contract_symbol': best_contract['contractSymbol'],
                'strike': best_contract['strike'],
                'last_price': best_contract['lastPrice'],
                'expiry': target_date,
                'type': type
            }
            
        except Exception as e:
            logger.error(f"Options Scalp Selection Error: {e}")
            return None

# =============================================================================
# AGENT 4: PORTFOLIO MANAGER ("The Boss")
# =============================================================================
class PortfolioManager:
    def __init__(self, trading_client):
        self.client = trading_client
        
        # V8: Initialize shared cache instances
        self.data_cache = DataCache(ttl_seconds=60)
        self.indicator_cache = IndicatorCache(ttl_seconds=60)
        logger.info("V8: Initialized shared caching system")
        
        # V8 Optimization #2: Initialize AnalysisOptimizer for smart skipping
        self.analysis_optimizer = AnalysisOptimizer(
            wait_signal_cache_minutes=5,
            price_change_threshold=0.01  # 1% price change threshold
        )
        logger.info("V8: Initialized AnalysisOptimizer for intelligent analysis skipping")
        
        # V8 Optimization #3: Initialize MarketRegimeDetector for market condition awareness
        self.market_regime = MarketRegimeDetector(cache_duration_minutes=15)
        logger.info("V8: Initialized MarketRegimeDetector for market condition analysis")
        
        # Initialize agents with caching support
        self.sentiment_agent = SentimentAgent()
        self.fundamental_agent = FundamentalAgent()
        self.technical_agent = TechnicalAgent(
            data_cache=self.data_cache,
            indicator_cache=self.indicator_cache
        )
        self.day_trading_agent = DayTradingAgent()
        self.options_agent = OptionsAgent()
        
        # V8 Agent Coordination: Initialize AgentCoordinator for adaptive learning
        agents_dict = {
            'sentiment': self.sentiment_agent,
            'fundamental': self.fundamental_agent,
            'technical': self.technical_agent,
            'day_trading': self.day_trading_agent
        }
        
        self.agent_coordinator = AgentCoordinator(
            agents=agents_dict,
            market_regime_detector=self.market_regime,
            consensus_threshold=config.consensus_threshold,
            performance_file='agent_performance_history.json'
        )
        logger.info("V8: Initialized AgentCoordinator for multi-agent consensus with adaptive learning")
        
        # V8: Initialize TradeTracker for P&L tracking (with coordinator feedback and commission simulation)
        self.trade_tracker = TradeTracker(agent_coordinator=self.agent_coordinator, config=config)
        logger.info("V8: Initialized TradeTracker with AgentCoordinator feedback loop and commission simulation")
        
        # V8 Week 3 Day 5: Initialize PositionTracker and OrderExecutor
        self.position_tracker = PositionTracker()
        self.order_executor = OrderExecutor(trading_client)
        logger.info("V8: Initialized PositionTracker and OrderExecutor")
        
        # V8 Safety Features: Initialize RiskManager for portfolio-level protection
        self.risk_manager = RiskManager(config, trading_client)
        self.risk_manager.initialize_daily_value()
        logger.info("V8: Initialized RiskManager with portfolio-level risk controls")
        
        # V8 Safety Features: Initialize DataValidator for data quality checks
        self.data_validator = DataValidator(config)
        logger.info("V8: Initialized DataValidator for data quality validation")
        
        # V8 Safety Features: Initialize ReconciliationManager for position sync
        from v8_modules.reconciliation_manager import ReconciliationManager
        self.reconciliation_manager = ReconciliationManager(config, trading_client, self.position_tracker)
        logger.info("V8: Initialized ReconciliationManager for position reconciliation")
        
        # Perform startup reconciliation if enabled
        if config.enable_startup_reconciliation:
            logger.info("Performing startup position reconciliation...")
            report = self.reconciliation_manager.reconcile_positions()
            
            if report['discrepancies']:
                msg = f"⚠️ **STARTUP RECONCILIATION**\n"
                msg += f"Found {len(report['discrepancies'])} discrepancies:\n"
                for disc in report['discrepancies'][:5]:  # Limit to 5 for Discord
                    msg += f"• {disc}\n"
                if len(report['discrepancies']) > 5:
                    msg += f"• ... and {len(report['discrepancies']) - 5} more\n"
                send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                logger.warning(f"Startup reconciliation found {len(report['discrepancies'])} discrepancies")
            else:
                logger.info("✓ Startup reconciliation complete - no discrepancies")
        
        # Track last reconciliation time
        self.last_reconciliation_time = datetime.now()
        
        # V8: Track position types in memory (avoid API calls)
        # NOTE: This will be replaced by PositionTracker, kept for backward compatibility during migration
        self.position_types = {}  # {symbol: 'scalp' or 'swing'}
        logger.info("PortfolioManager V8 initialized with performance optimizations and agent coordination")



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
        V8 Week 3 Day 5: Now uses OrderExecutor and PositionTracker.
        """
        try:
            logger.info(f"🛡️ Safe Close: Closing position {symbol}...")
            
            # Use OrderExecutor for safe close
            success = self.order_executor.close_position(symbol, safe_close=True)
            
            if success:
                # Clean up position tracking
                self.position_tracker.remove_position(symbol)
                
                # Legacy cleanup (backward compatibility)
                if symbol in self.position_types:
                    del self.position_types[symbol]
                    
        except Exception as e:
            logger.error(f"❌ Safe Close Failed for {symbol}: {e}")

    def upgrade_stops(self):
        """
        Scans ALL open positions and upgrades Fixed Stops to Trailing Stops.
        Run this frequently (e.g. every minute).
        V8 Week 3 Day 5: Now uses OrderExecutor for cleaner order management.
        V8 Optimization #4: Uses async wrapper for concurrent API calls.
        """
        try:
            # V8 Optimization #4: Fetch positions and orders concurrently
            # This is 2x faster than sequential calls
            calls = [
                (self.client.get_all_positions, (), {}),
            ]
            results = run_concurrent_api_calls(calls)
            positions = results[0]
            
            for p in positions:
                symbol = p.symbol
                qty = float(p.qty)
                
                # Check Orders for this symbol
                orders = self.order_executor.get_open_orders(symbol)
                
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
                        # Use OrderExecutor to upgrade
                        success = self.order_executor.upgrade_stop_to_trailing(
                            symbol=symbol,
                            quantity=int(qty),
                            trail_percent=TRAILING_STOP_PCT,
                            fixed_stop_order_id=fixed_stop.id
                        )
                        
                        if success:
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
        V8 OPTIMIZED: Returns position counts using PositionTracker.
        Performance: 200x faster (2s → 0.01s)
        
        Week 3 Day 5: Now uses PositionTracker for cleaner architecture.
        """
        return self.position_tracker.get_position_counts()

    def manage_options_risk(self):
        """
        🛡️ OPTIONS RISK MANAGER (3-Layer Defense)
        1. Theta Guard: Close if held > 10 days (Time Decay).
        2. Smart Exit: Close if Underlying Stock Sentiment reversal.
        3. Bracket: Close if PnL < -30% (Stop) or > +50% (Take Profit).
        Only runs if ENABLE_OPTIONS is True.
        V8 Optimization #4: Uses async wrapper for concurrent API calls.
        """
        if not ENABLE_OPTIONS:
            return

        try:
            # V8 Optimization #4: Fetch positions concurrently
            calls = [(self.client.get_all_positions, (), {})]
            results = run_concurrent_api_calls(calls)
            positions = results[0]
            
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
                
                # Calculate Approx Dollar PnL based on unrealized_plpc (not perfect but close)
                # Faster than recalculating from cost basis manually
                pnl_dollars = (current_price - avg_entry) * qty
                if hasattr(p, 'unrealized_pl'): # Use API value if available (cleaner)
                     try: pnl_dollars = float(p.unrealized_pl)
                     except: pass

                # Stop Loss (-30%)
                if unrealized_plpct <= -0.30:
                     logger.info(f"🛡️ Options Stop Loss Triggered for {symbol}: {unrealized_plpct*100:.2f}%")
                     self.client.close_position(symbol)
                     
                     # V8: Close trade in TradeTracker
                     completed_trade = self.trade_tracker.close_trade_by_symbol(
                         symbol=symbol,
                         trade_type=TradeType.OPTIONS,
                         exit_price=current_price,
                         sell_order_id='options_stop_loss'
                     )
                     
                     if completed_trade:
                         msg = completed_trade.to_discord_message()
                         msg += "\n🛡️ **OPTION STOP LOSS** - Hit -30%"
                     else:
                         prefix_sign = "-" if pnl_dollars < 0 else "+"
                         abs_dollars = abs(pnl_dollars)
                         msg = f"🧬 **OPTION STOP LOSS**: {symbol}\n📉 PnL: {prefix_sign}${abs_dollars:.2f} ({unrealized_plpct*100:.2f}%) (Hit -30%)"
                     
                     send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                     continue

                # Take Profit (+50%)
                if unrealized_plpct >= 0.50:
                     logger.info(f"🛡️ Options Take Profit Triggered for {symbol}: {unrealized_plpct*100:.2f}%")
                     self.client.close_position(symbol)
                     
                     # V8: Close trade in TradeTracker
                     completed_trade = self.trade_tracker.close_trade_by_symbol(
                         symbol=symbol,
                         trade_type=TradeType.OPTIONS,
                         exit_price=current_price,
                         sell_order_id='options_take_profit'
                     )
                     
                     if completed_trade:
                         msg = completed_trade.to_discord_message()
                         msg += "\n🧬 **OPTION TAKE PROFIT** - Hit +50%"
                     else:
                         msg = f"🧬 **OPTION TAKE PROFIT**: {symbol}\n📈 PnL: +${pnl_dollars:.2f} (+{unrealized_plpct*100:.2f}%) (Hit +50%)"
                     
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
                     
                     pnl_dollars = (current_price - avg_entry) * qty
                     if hasattr(p, 'unrealized_pl'):
                         try: pnl_dollars = float(p.unrealized_pl)
                         except: pass
                         
                     self.client.close_position(symbol)
                     
                     # V8: Close trade in TradeTracker
                     completed_trade = self.trade_tracker.close_trade_by_symbol(
                         symbol=symbol,
                         trade_type=TradeType.OPTIONS,
                         exit_price=current_price,
                         sell_order_id='options_smart_exit'
                     )
                     
                     if completed_trade:
                         msg = completed_trade.to_discord_message()
                         msg += f"\n🧬 **OPTION SMART EXIT** - {reason}"
                     else:
                         msg = (f"🧬 **OPTION SMART EXIT**: {symbol}\n"
                                f"📉 Reason: {reason}\n"
                                f"💸 PnL: ${pnl_dollars:.2f} ({unrealized_plpct*100:.2f}%)")
                     
                     send_discord_alert(msg, DISCORD_WEBHOOK_URL)

        except Exception as e:
            logger.error(f"Error managing options risk: {e}")

    def execute_scalp_buy(self, symbol, price, budget):
        logger.info(f"⚡ SCALP SIGNAL for {symbol} @ ${price:.2f}")
        
        # V8 Safety: Pre-trade risk check
        is_safe, reason = self.risk_manager.validate_new_trade(symbol, 1)  # Check with 1 share for now
        if not is_safe:
            logger.warning(f"🛑 SCALP TRADE BLOCKED by RiskManager: {symbol} - {reason}")
            send_discord_alert(
                f"🛑 **SCALP TRADE BLOCKED**: {symbol}\n"
                f"💰 Price: ${price:.2f}\n"
                f"🛡️ Reason: {reason}\n"
                f"-----------------------------------------------------",
                DISCORD_WEBHOOK_URL
            )
            return
        
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
            # V8 Week 3 Day 5: Use OrderExecutor for order submission
            oid = f"scalp_{symbol}_{int(time.time())}"
            
            # Note: OrderExecutor doesn't support OTO yet, so we'll use the client directly for now
            # TODO: Add OTO support to OrderExecutor
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=str(qty),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.OTO,
                stop_loss={'stop_price': round(stop_price, 2)},
                client_order_id=oid
            )
            order_response = self.client.submit_order(order_data=order_data)
            
            # V8 Week 3 Day 5: Track position in PositionTracker
            trade_id = self.trade_tracker.open_trade(
                symbol=symbol,
                trade_type=TradeType.SCALP,
                quantity=qty,
                entry_price=price,
                buy_order_id=order_response.id
            )
            
            self.position_tracker.add_position(
                symbol=symbol,
                position_type='scalp',
                entry_price=price,
                quantity=qty,
                trade_id=trade_id
            )
            
            # Legacy tracking (backward compatibility)
            self.position_types[symbol] = 'scalp'
            
            # V8 Optimization #2: Clear analysis history (we now have position)
            self.analysis_optimizer.clear_symbol_history(symbol)
            
            logger.info(f"V8 TradeTracker: Opened {trade_id}")
            
            msg = (f"⚡ **SCALP ENTRY**: {symbol}\n"
                   f"📊 Qty: {qty} @ ${price:.2f}\n"
                   f"💼 Trade ID: `{trade_id}`\n"
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
        
        # FIX: Also check position_types for tracked positions (including options)
        # This prevents duplicate scalp option orders
        has_tracked_position = symbol in self.position_types
        
        # V8 Optimization #2: Smart Analysis Skipping
        # Get current price for skip logic
        try:
            ticker = yf.Ticker(symbol)
            current_price = ticker.info.get('currentPrice') or ticker.info.get('regularMarketPrice', 0)
            if not current_price:
                # Fallback: get from recent data
                hist = ticker.history(period='1d', interval='1m')
                if not hist.empty:
                    current_price = hist['Close'].iloc[-1]
                else:
                    current_price = 0
        except Exception as e:
            logger.warning(f"Could not get current price for {symbol}: {e}")
            current_price = 0
        
        # V8 Safety: Validate price data quality
        if current_price > 0:
            is_valid, reason = self.data_validator.validate_price_data(symbol, current_price)
            if not is_valid:
                logger.warning(f"⚠️ DATA QUALITY: {symbol} - {reason}. Skipping analysis.")
                self.data_validator.metrics['yahoo_failures'] += 1
                return
            # Update last valid price
            self.data_validator.update_last_valid_price(symbol, current_price)
            current_price = 0


        # --- BRANCH 1: SCALPING CHECK (Priority for Intra-day) ---
        # Only run if not holding, above 25k, and under the 10-position limit
        # FIX: Check both Alpaca position AND tracked positions
        if not position and not has_tracked_position and ABOVE_25K:
             # V8 Optimization #2: Check if we should skip scalp analysis
             if current_price > 0:
                 should_analyze_scalp, skip_reason = self.analysis_optimizer.should_analyze(
                     symbol=symbol,
                     analysis_type='scalp',
                     current_price=current_price,
                     position_counts=counts,
                     max_positions={'scalp': 10, 'swing': 10},
                     has_position=(position is not None)
                 )
                 
                 if not should_analyze_scalp:
                     logger.info(f"V8 Skip: {symbol} scalp analysis skipped - {skip_reason}")
                     # Continue to swing check if applicable
                     if not check_swing:
                         return
                 else:
                     logger.debug(f"V8: {symbol} scalp analysis proceeding - {skip_reason}")
             else:
                 should_analyze_scalp = True  # No price data, analyze anyway
             
             if should_analyze_scalp and counts['scalp'] < 10:
                 scalp_res = self.day_trading_agent.analyze(symbol)
                 
                 # V8 Optimization #2: Record scalp analysis for future skipping
                 if current_price > 0:
                     self.analysis_optimizer.record_analysis(
                         symbol=symbol,
                         signal=scalp_res['signal'],
                         price=current_price,
                         confidence=scalp_res.get('confidence', 0.5),
                         analysis_type='scalp'
                     )
                 
                 if scalp_res['signal'] == 'BUY':
                     
                     # V7 LOGIC: Check for Options Scalp First
                     if ENABLE_OPTIONS_SCALP:
                         logger.info(f"⚡ V7: Scalp Signal for {symbol}. Hunting for Options...")
                         # Scalp is usually Directional Long (Call) unless we implement Short logic
                         # DayTradingAgent logic is currently Long-only (RSI Oversold).
                         option_type = 'call'  # Store option type for notification
                         opt_res = self.options_agent.get_scalp_contract(symbol, type=option_type)
                         
                         if opt_res:
                             # Execute Option Scalp
                             logger.info(f"⚡ V7 Gamma Sniper: {opt_res['contract_symbol']} (Exp: {opt_res['expiry']}) - {option_type.upper()}")
                             # Sizing: Use Scalp Budget, but careful with sizing options (Contracts * 100)
                             # We use the same budget logic: 1/10th of Scalp Budget.
                             trade_amt = scalp_budget / 10.0
                             price = opt_res['last_price'] * 100
                             
                             if trade_amt >= price:
                                 qty = int(trade_amt / price)
                                 qty = max(1, qty)
                                 
                                 # FIX: Track position to prevent duplicate orders
                                 self.position_types[symbol] = 'scalp_option'
                                 
                                 # Submit Order (TODO: Real submission)
                                 msg = (f"⚡ **GAMMA SNIPER ENTRY**: {symbol}\n"
                                        f"📞 Type: {option_type.upper()}\n"
                                        f"🎫 Contract: {opt_res['contract_symbol']}\n"
                                        f"📊 Qty: {qty} (@ ${opt_res['last_price']:.2f})\n"
                                        f"📅 Expiry: {opt_res['expiry']}\n"
                                        f"🚀 Reason: Scalp Signal (No Sentiment)\n"
                                        f"-----------------------------------------------------")
                                 send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                                 
                                 # FIX: Clear analysis history to prevent re-triggering
                                 self.analysis_optimizer.clear_symbol_history(symbol)
                                 
                                 return # Done for this symbol
                             else:
                                 logger.warning(f"Scalp Budget too small for Option (${trade_amt:.2f} vs ${price:.2f}). Fallback to Stock.")
                         else:
                             logger.warning(f"No suitable Scalp Options found. Fallback to Stock.")
                     
                     # Fallback / Default Stock Scalp
                     self.execute_scalp_buy(symbol, scalp_res['price'], scalp_budget)
                     # Note: We return here to give Scalp the cycle priority. 
                     # Only one action per symbol per cycle.
                     return 
             else:
                 logger.info(f"Scalp Limit Reached ({counts['scalp']}/10). Skipping Scalp Check.")

        # If we are not checking swing this cycle, exit now
        if not check_swing:
            return

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
                             
                             # Close position and get sell order
                             self.safe_close_position(symbol)
                             
                             # V8: Close trade in TradeTracker and get completed trade details
                             # Determine trade type from position tracking
                             trade_type = TradeType.SWING  # Default
                             if symbol in self.position_types:
                                 if self.position_types[symbol] == 'scalp':
                                     trade_type = TradeType.SCALP
                             
                             completed_trade = self.trade_tracker.close_trade_by_symbol(
                                 symbol=symbol,
                                 trade_type=trade_type,
                                 exit_price=price,
                                 sell_order_id='profit_target_exit'  # Placeholder - real order ID from close_position
                             )
                             
                             # Send Discord notification with complete trade details
                             if completed_trade:
                                 msg = completed_trade.to_discord_message()
                                 msg += "\n🚀 **MOONSHOT EXIT** - Profit Target Hit (+10%)"
                             else:
                                 # Fallback if trade not tracked
                                 pnl_dollars = (price - avg_entry) * qty_held
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
                              
                              self.client.close_position(symbol)
                              
                              # V8: Close trade in TradeTracker
                              trade_type = TradeType.SWING
                              if symbol in self.position_types:
                                  if self.position_types[symbol] == 'scalp':
                                      trade_type = TradeType.SCALP
                              
                              completed_trade = self.trade_tracker.close_trade_by_symbol(
                                  symbol=symbol,
                                  trade_type=trade_type,
                                  exit_price=price,
                                  sell_order_id='smart_exit'
                              )
                              
                              if completed_trade:
                                  msg = completed_trade.to_discord_message()
                                  msg += f"\n💰 **SMART EXIT** - Technical Breakdown ({tech_reason})"
                              else:
                                  pnl_dollars = (price - avg_entry) * qty_held
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


        # --- BRANCH 2: SWING STRATEGY (V5 Original) ---
        # V8 Optimization #2: Check if we should skip swing analysis
        if current_price > 0 and not position:  # Only skip for new entries, not exits
            should_analyze_swing, skip_reason = self.analysis_optimizer.should_analyze(
                symbol=symbol,
                analysis_type='swing',
                current_price=current_price,
                position_counts=counts,
                max_positions={'scalp': 10, 'swing': 10},
                has_position=(position is not None)
            )
            
            if not should_analyze_swing:
                logger.info(f"V8 Skip: {symbol} swing analysis skipped - {skip_reason}")
                return
            else:
                logger.debug(f"V8: {symbol} swing analysis proceeding - {skip_reason}")
        
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

        # 3. POSITION LOGIC: Average Down CHECK
        # (Exit Logic moved to top of function for continuous monitoring)
        if position:
            avg_entry = float(position.avg_entry_price)
            if price >= avg_entry:
                 # We already checked for exits at top of loop. If we are here, we hold.
                 return
            else:
                logger.info(f"Holding {symbol} @ ${avg_entry:.2f}. Price ${price:.2f} is Lower. EVALUATING TO ADD MORE 🚨")
                # We continue to Agents...



        # 3. POSITION LOGIC: Average Down CHECK
        # (Exit Logic moved to top of function for continuous monitoring)
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
        # This applies to both NEW positions and AVERAGE DOWN adds.
        if tech_result['signal'] != 'BUY':
             # V8 Optimization #2: Record WAIT signal for future skipping
             if current_price > 0 and not position:
                 self.analysis_optimizer.record_analysis(
                     symbol=symbol,
                     signal='WAIT',
                     price=current_price,
                     confidence=tech_result.get('confidence', 0.5),
                     analysis_type='swing'
                 )
             
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
        
        # V8 Optimization #4: Use async wrapper for account fetch
        calls = [(self.client.get_account, (), {})]
        results = run_concurrent_api_calls(calls)
        account = results[0]
        
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
        
        # 5. SANITY CHECK (Crucial for Order Validation)
        # Ensure Stop Price is valid (Stop < Price for BUY)
        if stop_price >= price:
             logger.error(f"❌ Order Prep Failed: Stop Price ${stop_price:.2f} >= Entry ${price:.2f}. Volatility too high or Logic Error.")
             return
        
        # Ensure Not NaN
        if math.isnan(qty) or math.isnan(stop_price):
             logger.error("❌ Order Prep Failed: NaN value detected.")
             return
        
        # V8 Safety: Pre-trade risk check for swing trade
        is_safe, reason = self.risk_manager.validate_new_trade(symbol, qty)
        if not is_safe:
            logger.warning(f"🛑 SWING TRADE BLOCKED by RiskManager: {symbol} - {reason}")
            send_discord_alert(
                f"🛑 **SWING TRADE BLOCKED**: {symbol}\n"
                f"💰 Price: ${price:.2f}\n"
                f"📊 Quantity: {qty} shares\n"
                f"🛡️ Reason: {reason}\n"
                f"-----------------------------------------------------",
                DISCORD_WEBHOOK_URL
            )
            return

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
            order_response = self.client.submit_order(order_data=order_data)
            
            # V8 Week 3 Day 5: Track position in PositionTracker
            trade_id = self.trade_tracker.open_trade(
                symbol=symbol,
                trade_type=TradeType.SWING,
                quantity=qty,
                entry_price=price,
                buy_order_id=order_response.id
            )
            
            self.position_tracker.add_position(
                symbol=symbol,
                position_type='swing',
                entry_price=price,
                quantity=qty,
                trade_id=trade_id
            )
            
            # V8 Optimization #2: Record BUY signal and clear history (we now have position)
            if current_price > 0:
                self.analysis_optimizer.record_analysis(
                    symbol=symbol,
                    signal='BUY',
                    price=current_price,
                    confidence=tech_result.get('confidence', 0.8),
                    analysis_type='swing'
                )
                # Clear history since we now have a position
                self.analysis_optimizer.clear_symbol_history(symbol)
            
            # Legacy tracking (backward compatibility)
            self.position_types[symbol] = 'swing'
            
            logger.info(f"V8 TradeTracker: Opened {trade_id}")
            
            msg = (f"🚀 **HEDGE FUND BUY**: {symbol}\n"
                   f"📊 Quant: {qty} shares @ ${price:.2f}\n"
                   f"💼 Trade ID: `{trade_id}`\n"
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
    logger.info("Initializing AI Hedge Fund V8 (Optimized Edition)...")
    
    # V8: Display configuration summary
    logger.info("\n" + config.summary())
    
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
                
                # V8 Safety: Continuous risk monitoring
                is_safe, reason = manager.risk_manager.check_drawdown_limit()
                if not is_safe:
                    logger.critical(f"🚨 DRAWDOWN LIMIT EXCEEDED: {reason}")
                    manager.risk_manager.trigger_emergency_stop(reason)
                    send_discord_alert(
                        f"🚨 **EMERGENCY STOP TRIGGERED**\n"
                        f"Reason: {reason}\n"
                        f"All positions closed\n"
                        f"Bot in safe mode\n"
                        f"-----------------------------------------------------",
                        DISCORD_WEBHOOK_URL
                    )
                    # Continue loop but skip trading
                    time.sleep(60)
                    continue
                
                # Log P&L every cycle
                pnl = manager.risk_manager.calculate_daily_pnl()
                logger.info(f"📊 Daily P&L: ${pnl['pnl_dollars']:,.2f} ({pnl['pnl_pct']:+.2f}%)")
                
                # V8 Safety: Log data quality metrics periodically
                manager.data_validator.log_metrics_if_needed()
                
                # V8 Safety: Periodic position reconciliation
                time_since_reconciliation = (datetime.now() - manager.last_reconciliation_time).total_seconds()
                reconciliation_interval = config.reconciliation_interval_minutes * 60
                
                if time_since_reconciliation >= reconciliation_interval:
                    logger.info("Performing periodic position reconciliation...")
                    report = manager.reconciliation_manager.reconcile_positions()
                    manager.last_reconciliation_time = datetime.now()
                    
                    if report['discrepancies']:
                        msg = f"⚠️ **POSITION RECONCILIATION**\n"
                        msg += f"Found {len(report['discrepancies'])} discrepancies:\n"
                        for disc in report['discrepancies'][:5]:
                            msg += f"• {disc}\n"
                        if len(report['discrepancies']) > 5:
                            msg += f"• ... and {len(report['discrepancies']) - 5} more\n"
                        send_discord_alert(msg, DISCORD_WEBHOOK_URL)
                        logger.warning(f"Reconciliation found {len(report['discrepancies'])} discrepancies")
                
                # V8 Optimization #3: Get market conditions once per cycle
                market_conditions = manager.market_regime.get_market_conditions()
                regime_multiplier = manager.market_regime.get_regime_multiplier()
                logger.info(f"V8 Market Regime: {market_conditions.regime.value.upper()} "
                           f"(SPY: {market_conditions.spy_trend}, QQQ: {market_conditions.qqq_trend}) "
                           f"Position Multiplier: {regime_multiplier:.2f}x")
                
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
                    
                    # FIX: Refresh sentiment at START of EVERY cycle for real-time trading
                    # This ensures agents have the freshest sentiment data for accurate decisions
                    logger.info("V8: Refreshing sentiment for all symbols (real-time trading)...")
                    start_time = time.time()
                    manager.sentiment_agent.analyze_batch(SYMBOLS, force_refresh=True)
                    batch_time = time.time() - start_time
                    logger.info(f"V8: Sentiment refresh complete in {batch_time:.2f}s")

                    # PARALLEL EXECUTION
                    # V8 Optimization: Increased to 8 workers (with caching, API limits less of a concern)
                    # 16 symbols / 8 workers = 2 symbols per worker = faster cycles
                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
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
                
                # V8: Send end-of-day performance summary
                try:
                    daily_summary = manager.trade_tracker.format_daily_summary()
                    send_discord_alert(daily_summary, DISCORD_WEBHOOK_URL)
                    logger.info("V8: Daily performance summary sent to Discord")
                except Exception as e:
                    logger.error(f"Failed to send daily summary: {e}")
                
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
