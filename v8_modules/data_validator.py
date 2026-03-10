"""
Data Validator Module
Validates data quality and freshness for trading decisions
"""

import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict, Optional

logger = logging.getLogger("HedgeFund_V8.DataValidator")


class DataValidator:
    """
    Data quality validation system.
    
    Features:
    - Validates data freshness (timestamp checks)
    - Validates price reasonableness (change limits)
    - Tracks last valid prices for comparison
    - Maintains data quality metrics
    """
    
    def __init__(self, config):
        """
        Initialize Data Validator.
        
        Args:
            config: TradingConfig instance
        """
        self.config = config
        
        # Last valid prices for comparison
        # Format: {symbol: {'price': float, 'time': datetime}}
        self.last_valid_prices = {}
        
        # Data quality metrics
        self.metrics = {
            'stale_data_count': 0,
            'bad_data_count': 0,
            'yahoo_failures': 0,
            'alpaca_fallbacks': 0,
            'total_validations': 0,
            'successful_validations': 0
        }
        
        # Last metrics log time
        self.last_metrics_log = datetime.now()
        
        logger.info("DataValidator initialized")
    
    def is_data_stale(self, timestamp: datetime) -> bool:
        """
        Check if data timestamp is too old.
        
        Args:
            timestamp: Data timestamp to check
            
        Returns:
            True if data is stale (older than max_data_age_seconds)
        """
        if timestamp is None:
            return True
        
        now = datetime.now()
        
        # Handle timezone-aware timestamps
        if timestamp.tzinfo is not None and now.tzinfo is None:
            import pytz
            now = pytz.utc.localize(now)
        elif timestamp.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        
        age_seconds = (now - timestamp).total_seconds()
        
        is_stale = age_seconds > self.config.max_data_age_seconds
        
        if is_stale:
            logger.debug(f"Data is stale: {age_seconds:.0f}s old (limit: {self.config.max_data_age_seconds}s)")
        
        return is_stale
    
    def is_price_reasonable(self, symbol: str, new_price: float) -> bool:
        """
        Check if price change is reasonable compared to last valid price.
        
        Args:
            symbol: Stock symbol
            new_price: New price to validate
            
        Returns:
            True if price change is reasonable or no comparison available
        """
        if new_price <= 0:
            logger.warning(f"Invalid price for {symbol}: {new_price}")
            return False
        
        # If no previous price, accept this one
        if symbol not in self.last_valid_prices:
            return True
        
        last_price = self.last_valid_prices[symbol]['price']
        
        # Calculate percentage change
        price_change_pct = abs((new_price - last_price) / last_price) * 100
        
        # Check against threshold
        is_reasonable = price_change_pct <= self.config.max_price_change_pct
        
        if not is_reasonable:
            logger.warning(
                f"Unreasonable price change for {symbol}: "
                f"${last_price:.2f} -> ${new_price:.2f} ({price_change_pct:.1f}%)"
            )
        
        return is_reasonable
    
    def validate_price_data(
        self, 
        symbol: str, 
        price: float, 
        timestamp: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Comprehensive price data validation.
        
        Args:
            symbol: Stock symbol
            price: Price to validate
            timestamp: Data timestamp (optional, defaults to now)
            
        Returns:
            Tuple of (is_valid, reason)
        """
        self.metrics['total_validations'] += 1
        
        if not self.config.data_validation_enabled:
            self.metrics['successful_validations'] += 1
            return True, "Validation disabled"
        
        # Default timestamp to now if not provided
        if timestamp is None:
            timestamp = datetime.now()
        
        # Check 1: Data freshness
        if self.is_data_stale(timestamp):
            self.metrics['stale_data_count'] += 1
            return False, f"Data is stale (>{self.config.max_data_age_seconds}s old)"
        
        # Check 2: Price reasonableness
        if not self.is_price_reasonable(symbol, price):
            self.metrics['bad_data_count'] += 1
            return False, f"Price change exceeds {self.config.max_price_change_pct}%"
        
        # All checks passed
        self.metrics['successful_validations'] += 1
        return True, "Data valid"
    
    def update_last_valid_price(self, symbol: str, price: float):
        """
        Store last known good price for future comparisons.
        
        Args:
            symbol: Stock symbol
            price: Valid price to store
        """
        self.last_valid_prices[symbol] = {
            'price': price,
            'time': datetime.now()
        }
        
        logger.debug(f"Updated last valid price for {symbol}: ${price:.2f}")
    
    def get_metrics_summary(self) -> Dict:
        """
        Get data quality metrics summary.
        
        Returns:
            Dictionary with all metrics
        """
        success_rate = 0.0
        if self.metrics['total_validations'] > 0:
            success_rate = (self.metrics['successful_validations'] / 
                          self.metrics['total_validations']) * 100
        
        return {
            **self.metrics,
            'success_rate_pct': success_rate
        }
    
    def log_metrics_if_needed(self):
        """
        Log metrics if enough time has passed since last log.
        Logs every log_data_metrics_interval seconds.
        """
        now = datetime.now()
        elapsed = (now - self.last_metrics_log).total_seconds()
        
        if elapsed >= self.config.log_data_metrics_interval:
            metrics = self.get_metrics_summary()
            
            logger.info(
                f"📊 Data Quality Metrics: "
                f"Success: {metrics['success_rate_pct']:.1f}% "
                f"({metrics['successful_validations']}/{metrics['total_validations']}), "
                f"Stale: {metrics['stale_data_count']}, "
                f"Bad: {metrics['bad_data_count']}, "
                f"Alpaca Fallbacks: {metrics['alpaca_fallbacks']}"
            )
            
            self.last_metrics_log = now
    
    def reset_metrics(self):
        """Reset all metrics counters."""
        self.metrics = {
            'stale_data_count': 0,
            'bad_data_count': 0,
            'yahoo_failures': 0,
            'alpaca_fallbacks': 0,
            'total_validations': 0,
            'successful_validations': 0
        }
        logger.info("Data quality metrics reset")
