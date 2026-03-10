"""
Risk Manager Module
Provides portfolio-level risk management and protection mechanisms
"""

import json
import logging
from datetime import datetime, date
from typing import Tuple, Dict, Optional
import pandas as pd
import yfinance as yf

logger = logging.getLogger("HedgeFund_V8.RiskManager")


class RiskManager:
    """
    Portfolio-level risk management system.
    
    Features:
    - Daily drawdown monitoring and limits
    - Emergency stop mechanism
    - Position correlation analysis
    - Portfolio-wide P&L tracking
    """
    
    def __init__(self, config, trading_client):
        """
        Initialize Risk Manager.
        
        Args:
            config: TradingConfig instance
            trading_client: Alpaca TradingClient instance
        """
        self.config = config
        self.client = trading_client
        
        # State tracking
        self.daily_start_value = None
        self.daily_start_date = None
        self.emergency_stop_active = False
        self.emergency_stop_reason = None
        self.emergency_stop_time = None
        
        # Caching
        self._portfolio_value_cache = None
        self._portfolio_value_cache_time = None
        self._cache_ttl_seconds = 30
        
        # Correlation cache
        self._correlation_cache = {}  # {symbol: {'correlation': float, 'time': datetime}}
        self._correlation_cache_ttl = 3600  # 1 hour
        
        # State file
        self.state_file = 'risk_manager_state.json'
        
        # Load persisted state
        self._load_state()
        
        logger.info("RiskManager initialized")
    
    def _load_state(self):
        """Load persisted state from file."""
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                
            self.daily_start_value = state.get('daily_start_value')
            self.daily_start_date = state.get('date')
            self.emergency_stop_active = state.get('emergency_stop_active', False)
            self.emergency_stop_reason = state.get('emergency_stop_reason')
            self.emergency_stop_time = state.get('emergency_stop_time')
            
            logger.info(f"Loaded risk state: start_value=${self.daily_start_value}, "
                       f"date={self.daily_start_date}, emergency_stop={self.emergency_stop_active}")
                       
        except FileNotFoundError:
            logger.info("No existing risk state file found, will create new")
        except Exception as e:
            logger.error(f"Error loading risk state: {e}")
    
    def _save_state(self):
        """Persist state to file."""
        try:
            state = {
                'daily_start_value': self.daily_start_value,
                'date': self.daily_start_date,
                'emergency_stop_active': self.emergency_stop_active,
                'emergency_stop_reason': self.emergency_stop_reason,
                'emergency_stop_time': self.emergency_stop_time
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
                
            logger.debug("Risk state saved to file")
            
        except Exception as e:
            logger.error(f"Error saving risk state: {e}")

    
    def initialize_daily_value(self) -> float:
        """
        Initialize daily starting portfolio value.
        Should be called at market open or bot startup.
        
        Returns:
            Daily starting portfolio value
        """
        today = str(date.today())
        
        # Check if we already initialized today
        if self.daily_start_date == today and self.daily_start_value is not None:
            logger.info(f"Daily value already initialized: ${self.daily_start_value:,.2f}")
            return self.daily_start_value
        
        # Get current portfolio value
        current_value = self.get_current_portfolio_value()
        
        # Set as daily start
        self.daily_start_value = current_value
        self.daily_start_date = today
        
        # Persist to file
        self._save_state()
        
        logger.info(f"Initialized daily start value: ${self.daily_start_value:,.2f} for {today}")
        
        return self.daily_start_value
    
    def get_current_portfolio_value(self) -> float:
        """
        Get current total portfolio value (cash + positions).
        Uses 30-second cache to avoid excessive API calls.
        
        Returns:
            Current portfolio value in dollars
        """
        now = datetime.now()
        
        # Check cache
        if (self._portfolio_value_cache is not None and 
            self._portfolio_value_cache_time is not None):
            elapsed = (now - self._portfolio_value_cache_time).total_seconds()
            if elapsed < self._cache_ttl_seconds:
                logger.debug(f"Using cached portfolio value: ${self._portfolio_value_cache:,.2f}")
                return self._portfolio_value_cache
        
        # Fetch from Alpaca
        try:
            account = self.client.get_account()
            
            # Portfolio value = equity (cash + positions market value)
            portfolio_value = float(account.equity)
            
            # Update cache
            self._portfolio_value_cache = portfolio_value
            self._portfolio_value_cache_time = now
            
            logger.debug(f"Fetched portfolio value: ${portfolio_value:,.2f}")
            
            return portfolio_value
            
        except Exception as e:
            logger.error(f"Error fetching portfolio value: {e}")
            
            # Fallback to cached value if available
            if self._portfolio_value_cache is not None:
                logger.warning(f"Using last cached value: ${self._portfolio_value_cache:,.2f}")
                return self._portfolio_value_cache
            
            # Last resort: use config target value
            logger.warning(f"Using config target value: ${self.config.target_portfolio_value:,.2f}")
            return self.config.target_portfolio_value

    
    def calculate_daily_pnl(self) -> Dict[str, float]:
        """
        Calculate daily P&L in dollars and percentage.
        
        Returns:
            Dict with 'pnl_dollars' and 'pnl_pct' keys
        """
        if self.daily_start_value is None or self.daily_start_value == 0:
            logger.warning("Daily start value not initialized, cannot calculate P&L")
            return {'pnl_dollars': 0.0, 'pnl_pct': 0.0}
        
        current_value = self.get_current_portfolio_value()
        
        pnl_dollars = current_value - self.daily_start_value
        pnl_pct = (pnl_dollars / self.daily_start_value) * 100
        
        return {
            'pnl_dollars': pnl_dollars,
            'pnl_pct': pnl_pct,
            'current_value': current_value,
            'start_value': self.daily_start_value
        }
    
    def check_drawdown_limit(self) -> Tuple[bool, str]:
        """
        Check if portfolio has exceeded maximum daily drawdown limit.
        
        Returns:
            Tuple of (is_safe, reason)
            - is_safe: True if within limits, False if exceeded
            - reason: Explanation string
        """
        if not self.config.risk_check_enabled:
            return True, "Risk checks disabled"
        
        pnl = self.calculate_daily_pnl()
        
        # Check if we're in a loss
        if pnl['pnl_pct'] >= 0:
            return True, f"Portfolio up {pnl['pnl_pct']:.2f}%"
        
        # Check against limit (negative percentage)
        loss_pct = abs(pnl['pnl_pct'])
        
        if loss_pct >= self.config.max_daily_drawdown_pct:
            reason = (f"Daily drawdown limit exceeded: -{loss_pct:.2f}% "
                     f"(limit: {self.config.max_daily_drawdown_pct}%)")
            logger.critical(reason)
            return False, reason
        
        # Within limits
        reason = f"Drawdown: -{loss_pct:.2f}% (limit: {self.config.max_daily_drawdown_pct}%)"
        logger.debug(reason)
        return True, reason

    
    def calculate_position_correlation(self, new_symbol: str) -> float:
        """
        Calculate correlation between new symbol and existing positions.
        Returns average correlation with current holdings.
        
        Args:
            new_symbol: Symbol to check correlation for
            
        Returns:
            Average correlation coefficient (0.0 to 1.0)
        """
        try:
            # Get current positions
            positions = self.client.get_all_positions()
            
            if not positions:
                return 0.0  # No positions, no correlation
            
            # Check cache for this symbol
            cache_key = new_symbol
            if cache_key in self._correlation_cache:
                cached = self._correlation_cache[cache_key]
                age = (datetime.now() - cached['time']).total_seconds()
                if age < self._correlation_cache_ttl:
                    logger.debug(f"Using cached correlation for {new_symbol}: {cached['correlation']:.2f}")
                    return cached['correlation']
            
            # Fetch 30 days of price data for correlation
            symbols = [new_symbol] + [p.symbol for p in positions]
            
            # Download data
            data = yf.download(symbols, period='30d', progress=False)['Close']
            
            if data.empty or new_symbol not in data.columns:
                logger.warning(f"Could not fetch data for correlation analysis: {new_symbol}")
                return 0.0
            
            # Calculate returns
            returns = data.pct_change().dropna()
            
            # Calculate correlation with each position
            correlations = []
            for position in positions:
                if position.symbol in returns.columns and position.symbol != new_symbol:
                    corr = returns[new_symbol].corr(returns[position.symbol])
                    if not pd.isna(corr):
                        correlations.append(abs(corr))  # Use absolute value
            
            # Average correlation
            avg_corr = sum(correlations) / len(correlations) if correlations else 0.0
            
            # Cache result
            self._correlation_cache[cache_key] = {
                'correlation': avg_corr,
                'time': datetime.now()
            }
            
            logger.debug(f"Calculated correlation for {new_symbol}: {avg_corr:.2f}")
            
            return avg_corr
            
        except Exception as e:
            logger.error(f"Error calculating correlation for {new_symbol}: {e}")
            return 0.0  # Assume no correlation on error

    
    def validate_new_trade(self, symbol: str, quantity: int) -> Tuple[bool, str]:
        """
        Comprehensive pre-trade risk validation.
        Checks emergency stop, drawdown limit, and correlation.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            
        Returns:
            Tuple of (is_safe, reason)
        """
        if not self.config.risk_check_enabled:
            return True, "Risk checks disabled"
        
        # Check 1: Emergency stop
        if self.emergency_stop_active:
            return False, f"Emergency stop active: {self.emergency_stop_reason}"
        
        # Check 2: Drawdown limit
        is_safe, reason = self.check_drawdown_limit()
        if not is_safe:
            return False, f"Drawdown limit exceeded: {reason}"
        
        # Check 3: Correlation limit
        correlation = self.calculate_position_correlation(symbol)
        
        if correlation > self.config.correlation_threshold:
            # Check if we're already heavily exposed to correlated positions
            try:
                positions = self.client.get_all_positions()
                current_value = self.get_current_portfolio_value()
                
                # Calculate exposure to correlated positions
                correlated_value = 0.0
                for pos in positions:
                    pos_value = float(pos.market_value)
                    # Simple check: if correlation is high, count it
                    if correlation > self.config.correlation_threshold:
                        correlated_value += pos_value
                
                correlated_pct = correlated_value / current_value if current_value > 0 else 0
                
                if correlated_pct > self.config.max_correlated_exposure_pct:
                    return False, (f"Correlation limit: {symbol} corr={correlation:.2f}, "
                                 f"correlated exposure={correlated_pct*100:.1f}%")
                
            except Exception as e:
                logger.error(f"Error checking correlated exposure: {e}")
        
        # All checks passed
        return True, "All risk checks passed"

    
    def trigger_emergency_stop(self, reason: str):
        """
        Trigger emergency stop: close all positions, cancel orders, enter safe mode.
        
        Args:
            reason: Reason for emergency stop
        """
        if not self.config.enable_emergency_stop:
            logger.warning("Emergency stop disabled in config")
            return
        
        logger.critical(f"🚨 TRIGGERING EMERGENCY STOP: {reason}")
        
        try:
            # 1. Close all positions
            positions = self.client.get_all_positions()
            logger.info(f"Closing {len(positions)} positions...")
            
            for position in positions:
                try:
                    self.client.close_position(position.symbol)
                    logger.info(f"Closed position: {position.symbol}")
                except Exception as e:
                    logger.error(f"Failed to close {position.symbol}: {e}")
            
            # 2. Cancel all pending orders
            try:
                orders = self.client.get_orders()
                logger.info(f"Cancelling {len(orders)} pending orders...")
                
                for order in orders:
                    try:
                        self.client.cancel_order_by_id(order.id)
                        logger.info(f"Cancelled order: {order.id}")
                    except Exception as e:
                        logger.error(f"Failed to cancel order {order.id}: {e}")
                        
            except Exception as e:
                logger.error(f"Error cancelling orders: {e}")
            
            # 3. Set emergency stop flag
            self.emergency_stop_active = True
            self.emergency_stop_reason = reason
            self.emergency_stop_time = datetime.now().isoformat()
            
            # 4. Persist state
            self._save_state()
            
            logger.critical("🚨 EMERGENCY STOP COMPLETE - Bot in safe mode")
            
        except Exception as e:
            logger.critical(f"EMERGENCY STOP FAILED: {e}")
            # Still set the flag to prevent new trades
            self.emergency_stop_active = True
            self.emergency_stop_reason = f"Emergency stop error: {e}"
            self._save_state()
    
    def reset_emergency_stop(self):
        """
        Manually reset emergency stop after review.
        Should only be called after investigating the issue.
        """
        logger.warning("Resetting emergency stop - manual intervention")
        
        self.emergency_stop_active = False
        self.emergency_stop_reason = None
        self.emergency_stop_time = None
        
        self._save_state()
        
        logger.info("Emergency stop reset - bot can resume trading")
    
    def get_risk_summary(self) -> Dict:
        """
        Get comprehensive risk summary for logging/monitoring.
        
        Returns:
            Dict with risk metrics
        """
        pnl = self.calculate_daily_pnl()
        is_safe, drawdown_reason = self.check_drawdown_limit()
        
        return {
            'daily_pnl_dollars': pnl['pnl_dollars'],
            'daily_pnl_pct': pnl['pnl_pct'],
            'current_value': pnl['current_value'],
            'start_value': pnl['start_value'],
            'drawdown_safe': is_safe,
            'drawdown_reason': drawdown_reason,
            'emergency_stop_active': self.emergency_stop_active,
            'emergency_stop_reason': self.emergency_stop_reason
        }
