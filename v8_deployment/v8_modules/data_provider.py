"""
Data Provider Module
Abstract interface for market data with Yahoo Finance implementation
"""

import logging
import pandas as pd
import yfinance as yf
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from v8_modules.cache_manager import DataCache

logger = logging.getLogger(__name__)


class DataProvider(ABC):
    """
    Abstract interface for market data.
    Allows swapping data sources without changing agent code.
    """
    
    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        start_date: datetime,
        interval: str
    ) -> Optional[pd.DataFrame]:
        """
        Get historical price bars.
        
        Args:
            symbol: Stock symbol
            start_date: Start date for historical data
            interval: Time interval ('1d', '1h', '15m', etc.)
            
        Returns:
            DataFrame with OHLCV data, or None if error
        """
        pass
    
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental data for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with fundamental data, or None if error
        """
        pass
    
    @abstractmethod
    def get_news(self, symbol: str, limit: int = 5) -> List[str]:
        """
        Get recent news headlines for a symbol.
        
        Args:
            symbol: Stock symbol
            limit: Maximum number of headlines
            
        Returns:
            List of news headlines
        """
        pass
    
    @abstractmethod
    def get_calendar(self, symbol: str) -> Optional[Any]:
        """
        Get earnings calendar for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Calendar data, or None if error
        """
        pass


class YahooDataProvider(DataProvider):
    """
    Yahoo Finance implementation of DataProvider.
    Includes caching for performance.
    """
    
    def __init__(self, cache: Optional[DataCache] = None):
        """
        Initialize Yahoo Finance data provider.
        
        Args:
            cache: Optional DataCache instance for caching
        """
        self.cache = cache if cache else DataCache(ttl_seconds=60)
        logger.info("YahooDataProvider initialized with caching")
    
    def get_bars(
        self,
        symbol: str,
        start_date: datetime,
        interval: str
    ) -> Optional[pd.DataFrame]:
        """
        Get historical price bars from Yahoo Finance.
        
        Args:
            symbol: Stock symbol
            start_date: Start date for historical data
            interval: Time interval ('1d', '1h', '15m', etc.)
            
        Returns:
            DataFrame with OHLCV data, or None if error
        """
        try:
            # Calculate lookback days for cache key
            lookback_days = (datetime.now() - start_date).days
            
            # Check cache first
            cached_data = self.cache.get(symbol, interval, lookback_days)
            if cached_data is not None:
                logger.debug(f"Cache HIT: {symbol} {interval}")
                return cached_data
            
            # Cache miss - fetch from Yahoo Finance
            logger.debug(f"Cache MISS: {symbol} {interval} - fetching from API")
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start_date, interval=interval, auto_adjust=True)
            
            if df.empty:
                logger.warning(f"No data returned for {symbol} {interval}")
                return None
            
            # Flatten MultiIndex if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            # Standardize column names
            df.columns = df.columns.str.lower()
            
            # Deduplicate columns
            df = df.loc[:, ~df.columns.duplicated()]
            
            # Validation
            if 'close' not in df.columns:
                logger.error(f"Data missing 'close' column for {symbol}. Columns: {df.columns.tolist()}")
                return None
            
            # Cache the result
            self.cache.set(symbol, interval, lookback_days, df)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching bars for {symbol} {interval}: {e}")
            return None
    
    def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get fundamental data from Yahoo Finance.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dictionary with fundamental data, or None if error
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            if info is None:
                logger.warning(f"No fundamental data for {symbol}")
                return None
            
            return info
            
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {symbol}: {e}")
            return None
    
    def get_news(self, symbol: str, limit: int = 5) -> List[str]:
        """
        Get recent news headlines from Yahoo Finance.
        
        Args:
            symbol: Stock symbol
            limit: Maximum number of headlines
            
        Returns:
            List of news headlines
        """
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            headlines = []
            
            if news:
                for n in news[:limit]:
                    # Safe parsing for varying yfinance news structures
                    if 'title' in n:
                        headlines.append(n['title'])
                    elif 'content' in n and 'title' in n['content']:
                        headlines.append(n['content']['title'])
            
            return headlines
            
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return []
    
    def get_calendar(self, symbol: str) -> Optional[Any]:
        """
        Get earnings calendar from Yahoo Finance.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Calendar data, or None if error
        """
        try:
            ticker = yf.Ticker(symbol)
            calendar = ticker.calendar
            return calendar
            
        except Exception as e:
            logger.error(f"Error fetching calendar for {symbol}: {e}")
            return None
    
    def invalidate_cache(self, symbol: Optional[str] = None):
        """
        Invalidate cache for a symbol or all symbols.
        
        Args:
            symbol: Optional symbol to invalidate, or None for all
        """
        self.cache.invalidate(symbol)
        if symbol:
            logger.info(f"Cache invalidated for {symbol}")
        else:
            logger.info("Cache invalidated for all symbols")


class AlpacaDataProvider(DataProvider):
    """
    Alpaca data provider (placeholder for future implementation).
    Could be used for real-time data or as primary data source.
    """
    
    def __init__(self, api_key: str, secret_key: str):
        """
        Initialize Alpaca data provider.
        
        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
        """
        self.api_key = api_key
        self.secret_key = secret_key
        logger.info("AlpacaDataProvider initialized (not yet implemented)")
    
    def get_bars(
        self,
        symbol: str,
        start_date: datetime,
        interval: str
    ) -> Optional[pd.DataFrame]:
        """Not yet implemented"""
        raise NotImplementedError("Alpaca data provider not yet implemented")
    
    def get_fundamentals(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Not yet implemented"""
        raise NotImplementedError("Alpaca data provider not yet implemented")
    
    def get_news(self, symbol: str, limit: int = 5) -> List[str]:
        """Not yet implemented"""
        raise NotImplementedError("Alpaca data provider not yet implemented")
    
    def get_calendar(self, symbol: str) -> Optional[Any]:
        """Not yet implemented"""
        raise NotImplementedError("Alpaca data provider not yet implemented")


def create_data_provider(
    provider_type: str = 'yahoo',
    cache: Optional[DataCache] = None,
    **kwargs
) -> DataProvider:
    """
    Factory function to create data providers.
    
    Args:
        provider_type: Type of provider ('yahoo', 'alpaca')
        cache: Optional cache instance
        **kwargs: Additional provider-specific arguments
        
    Returns:
        DataProvider instance
        
    Raises:
        ValueError: If provider_type is unknown
    """
    if provider_type.lower() == 'yahoo':
        return YahooDataProvider(cache=cache)
    elif provider_type.lower() == 'alpaca':
        api_key = kwargs.get('api_key')
        secret_key = kwargs.get('secret_key')
        if not api_key or not secret_key:
            raise ValueError("Alpaca provider requires api_key and secret_key")
        return AlpacaDataProvider(api_key=api_key, secret_key=secret_key)
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
