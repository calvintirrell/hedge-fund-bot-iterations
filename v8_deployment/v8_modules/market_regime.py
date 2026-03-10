"""
Market Regime Detection Module
Analyzes overall market conditions (SPY/QQQ) to inform trading decisions
"""

import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classifications"""
    STRONG_BULL = "strong_bull"      # Both SPY and QQQ bullish, strong momentum
    BULL = "bull"                     # Both bullish
    NEUTRAL = "neutral"               # Mixed signals
    BEAR = "bear"                     # Both bearish
    STRONG_BEAR = "strong_bear"       # Both bearish, strong momentum
    UNKNOWN = "unknown"               # Unable to determine


@dataclass
class MarketConditions:
    """Market conditions data"""
    regime: MarketRegime
    spy_trend: str  # 'up', 'down', 'neutral'
    qqq_trend: str  # 'up', 'down', 'neutral'
    spy_strength: float  # 0.0 to 1.0
    qqq_strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    timestamp: datetime
    reasoning: str


class MarketRegimeDetector:
    """
    Detects overall market regime by analyzing SPY and QQQ.
    
    Features:
    - Analyzes major indices (SPY, QQQ)
    - Determines trend direction and strength
    - Classifies market regime
    - Caches results to avoid redundant analysis
    """
    
    def __init__(self, cache_duration_minutes: int = 15):
        """
        Initialize MarketRegimeDetector.
        
        Args:
            cache_duration_minutes: How long to cache market regime (default: 15 min)
        """
        self.cache_duration_minutes = cache_duration_minutes
        self.cached_conditions: Optional[MarketConditions] = None
        self.last_analysis_time: Optional[datetime] = None
        
        logger.info(f"MarketRegimeDetector initialized (cache: {cache_duration_minutes} min)")
    
    def get_market_conditions(self, force_refresh: bool = False) -> MarketConditions:
        """
        Get current market conditions.
        
        Args:
            force_refresh: Force re-analysis even if cache is valid
            
        Returns:
            MarketConditions object
        """
        # Check cache
        if not force_refresh and self._is_cache_valid():
            logger.debug("Market regime: Using cached conditions")
            return self.cached_conditions
        
        # Analyze market
        logger.info("Market regime: Analyzing SPY and QQQ...")
        conditions = self._analyze_market()
        
        # Update cache
        self.cached_conditions = conditions
        self.last_analysis_time = datetime.now()
        
        logger.info(f"Market regime: {conditions.regime.value} (confidence: {conditions.confidence:.2f})")
        logger.info(f"  SPY: {conditions.spy_trend} (strength: {conditions.spy_strength:.2f})")
        logger.info(f"  QQQ: {conditions.qqq_trend} (strength: {conditions.qqq_strength:.2f})")
        
        return conditions
    
    def _is_cache_valid(self) -> bool:
        """Check if cached conditions are still valid"""
        if self.cached_conditions is None or self.last_analysis_time is None:
            return False
        
        elapsed = datetime.now() - self.last_analysis_time
        return elapsed.total_seconds() < (self.cache_duration_minutes * 60)
    
    def _analyze_market(self) -> MarketConditions:
        """Analyze SPY and QQQ to determine market regime"""
        try:
            # Analyze SPY
            spy_trend, spy_strength = self._analyze_index('SPY')
            
            # Analyze QQQ
            qqq_trend, qqq_strength = self._analyze_index('QQQ')
            
            # Determine regime
            regime, confidence, reasoning = self._classify_regime(
                spy_trend, spy_strength,
                qqq_trend, qqq_strength
            )
            
            return MarketConditions(
                regime=regime,
                spy_trend=spy_trend,
                qqq_trend=qqq_trend,
                spy_strength=spy_strength,
                qqq_strength=qqq_strength,
                confidence=confidence,
                timestamp=datetime.now(),
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Market regime analysis failed: {e}")
            return MarketConditions(
                regime=MarketRegime.UNKNOWN,
                spy_trend='neutral',
                qqq_trend='neutral',
                spy_strength=0.5,
                qqq_strength=0.5,
                confidence=0.0,
                timestamp=datetime.now(),
                reasoning=f"Analysis error: {str(e)}"
            )
    
    def _analyze_index(self, symbol: str) -> tuple[str, float]:
        """
        Analyze a single index (SPY or QQQ).
        
        Returns:
            Tuple of (trend: str, strength: float)
            trend: 'up', 'down', or 'neutral'
            strength: 0.0 to 1.0
        """
        try:
            # Fetch recent data (20 days for SMA calculations)
            ticker = yf.Ticker(symbol)
            df = ticker.history(period='1mo', interval='1d')
            
            if df.empty or len(df) < 20:
                logger.warning(f"Insufficient data for {symbol}")
                return 'neutral', 0.5
            
            # Calculate SMAs
            df['SMA_10'] = df['Close'].rolling(window=10).mean()
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            
            latest = df.iloc[-1]
            close = latest['Close']
            sma_10 = latest['SMA_10']
            sma_20 = latest['SMA_20']
            
            # Determine trend
            if pd.isna(sma_10) or pd.isna(sma_20):
                return 'neutral', 0.5
            
            # Trend direction
            if close > sma_10 > sma_20:
                trend = 'up'
                # Strength based on distance from SMAs
                strength = min(1.0, (close - sma_20) / sma_20 * 20)  # Normalize
            elif close < sma_10 < sma_20:
                trend = 'down'
                strength = min(1.0, (sma_20 - close) / sma_20 * 20)
            else:
                trend = 'neutral'
                strength = 0.5
            
            # Ensure strength is in valid range
            strength = max(0.0, min(1.0, strength))
            
            return trend, strength
            
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return 'neutral', 0.5
    
    def _classify_regime(
        self,
        spy_trend: str,
        spy_strength: float,
        qqq_trend: str,
        qqq_strength: float
    ) -> tuple[MarketRegime, float, str]:
        """
        Classify market regime based on SPY and QQQ analysis.
        
        Returns:
            Tuple of (regime, confidence, reasoning)
        """
        # Both bullish
        if spy_trend == 'up' and qqq_trend == 'up':
            avg_strength = (spy_strength + qqq_strength) / 2
            
            if avg_strength > 0.7:
                return (
                    MarketRegime.STRONG_BULL,
                    avg_strength,
                    f"Strong bull market: SPY and QQQ both trending up strongly"
                )
            else:
                return (
                    MarketRegime.BULL,
                    avg_strength,
                    f"Bull market: SPY and QQQ both trending up"
                )
        
        # Both bearish
        elif spy_trend == 'down' and qqq_trend == 'down':
            avg_strength = (spy_strength + qqq_strength) / 2
            
            if avg_strength > 0.7:
                return (
                    MarketRegime.STRONG_BEAR,
                    avg_strength,
                    f"Strong bear market: SPY and QQQ both trending down strongly"
                )
            else:
                return (
                    MarketRegime.BEAR,
                    avg_strength,
                    f"Bear market: SPY and QQQ both trending down"
                )
        
        # Mixed signals
        else:
            # Calculate confidence based on how neutral it is
            confidence = 0.5
            
            if spy_trend == 'neutral' and qqq_trend == 'neutral':
                reasoning = "Neutral market: Both SPY and QQQ showing no clear trend"
            elif spy_trend == 'up' and qqq_trend == 'down':
                reasoning = "Neutral market: SPY up but QQQ down (mixed signals)"
            elif spy_trend == 'down' and qqq_trend == 'up':
                reasoning = "Neutral market: SPY down but QQQ up (mixed signals)"
            else:
                reasoning = f"Neutral market: SPY {spy_trend}, QQQ {qqq_trend}"
            
            return MarketRegime.NEUTRAL, confidence, reasoning
    
    def should_trade_long(self, min_confidence: float = 0.5) -> bool:
        """
        Determine if conditions are favorable for long positions.
        
        Args:
            min_confidence: Minimum confidence required
            
        Returns:
            True if favorable for longs, False otherwise
        """
        conditions = self.get_market_conditions()
        
        if conditions.regime in [MarketRegime.STRONG_BULL, MarketRegime.BULL]:
            return conditions.confidence >= min_confidence
        
        return False
    
    def should_be_cautious(self) -> bool:
        """
        Determine if we should be cautious (reduce position sizes, tighter stops).
        
        Returns:
            True if caution is warranted
        """
        conditions = self.get_market_conditions()
        
        return conditions.regime in [MarketRegime.BEAR, MarketRegime.STRONG_BEAR, MarketRegime.UNKNOWN]
    
    def get_regime_multiplier(self) -> float:
        """
        Get a position size multiplier based on market regime.
        
        Returns:
            Multiplier (0.5 to 1.5)
            - Strong bull: 1.5x (increase size)
            - Bull: 1.2x
            - Neutral: 1.0x (normal)
            - Bear: 0.7x (reduce size)
            - Strong bear: 0.5x (significantly reduce)
        """
        conditions = self.get_market_conditions()
        
        multipliers = {
            MarketRegime.STRONG_BULL: 1.5,
            MarketRegime.BULL: 1.2,
            MarketRegime.NEUTRAL: 1.0,
            MarketRegime.BEAR: 0.7,
            MarketRegime.STRONG_BEAR: 0.5,
            MarketRegime.UNKNOWN: 0.8
        }
        
        return multipliers.get(conditions.regime, 1.0)
    
    def summary(self) -> str:
        """Generate market conditions summary"""
        if self.cached_conditions is None:
            return "Market conditions: Not analyzed yet"
        
        conditions = self.cached_conditions
        
        summary = f"\n{'='*60}\n"
        summary += "MARKET REGIME ANALYSIS\n"
        summary += f"{'='*60}\n"
        summary += f"Regime: {conditions.regime.value.upper()}\n"
        summary += f"Confidence: {conditions.confidence:.2f}\n"
        summary += f"\nIndices:\n"
        summary += f"  SPY: {conditions.spy_trend.upper()} (strength: {conditions.spy_strength:.2f})\n"
        summary += f"  QQQ: {conditions.qqq_trend.upper()} (strength: {conditions.qqq_strength:.2f})\n"
        summary += f"\nRecommendations:\n"
        summary += f"  Position Size Multiplier: {self.get_regime_multiplier():.2f}x\n"
        summary += f"  Favorable for Longs: {'Yes' if self.should_trade_long() else 'No'}\n"
        summary += f"  Caution Warranted: {'Yes' if self.should_be_cautious() else 'No'}\n"
        summary += f"\nReasoning: {conditions.reasoning}\n"
        summary += f"{'='*60}\n"
        
        return summary
