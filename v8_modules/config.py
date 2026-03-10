"""
Trading Configuration Module
Centralized configuration for all trading parameters
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class TradingConfig:
    """
    Centralized trading configuration.
    All trading parameters in one place for easy tuning.
    """
    
    # ==================== API CREDENTIALS ====================
    api_key: str = field(default_factory=lambda: os.getenv('API_KEY', ''))
    secret_key: str = field(default_factory=lambda: os.getenv('SECRET_KEY', ''))
    gemini_api_key: str = field(default_factory=lambda: os.getenv('GEMINI_API_KEY', ''))
    discord_webhook_url: str = field(default_factory=lambda: os.getenv('DISCORD_WEBHOOK_URL', ''))
    
    # ==================== TRADING SYMBOLS ====================
    symbols: List[str] = field(default_factory=lambda: [
        "AMD", "AAPL", "GOOGL", "NVDA", "IBM", "PLTR", 
        "MU", "MDB", "AMZN", "META", "MSFT", "CSCO", 
        "SOFI", "INTC", "SPY", "RIVN"
    ])
    
    # ==================== PORTFOLIO ALLOCATION ====================
    target_portfolio_value: float = 100000.0  # Master value for sizing
    swing_alloc_pct: float = 0.50  # 50% for swing trading ($50k)
    scalp_alloc_pct: float = 0.40  # 40% for scalping ($40k)
    options_alloc_pct: float = 0.10  # 10% for options ($10k)
    
    # ==================== POSITION LIMITS ====================
    max_swing_positions: int = 5  # Fewer, larger positions ($10k each)
    max_scalp_positions: int = 8  # Fewer, larger positions ($5k each)
    above_25k: bool = True  # PDT rule compliance
    
    # ==================== RISK MANAGEMENT ====================
    risk_pct: float = 0.01  # 1% risk per trade
    atr_multiplier: float = 2.0  # Stop loss distance (2x ATR)
    trailing_stop_pct: float = 3.0  # Trailing stop percentage
    
    # ==================== COMMISSION SIMULATION ====================
    # Alpaca commission structure (for paper trading simulation)
    enable_commission_simulation: bool = True  # Simulate commissions in P&L
    commission_per_share: float = 0.0  # $0 per share for stocks (Alpaca is commission-free)
    options_commission_per_contract: float = 0.65  # $0.65 per options contract
    sec_fee_per_dollar: float = 0.0000278  # SEC fee: $27.80 per $1M sold
    finra_taf_per_share: float = 0.000166  # FINRA TAF: $0.000166 per share (max $8.30)
    
    # Portfolio-level risk controls
    max_daily_drawdown_pct: float = 5.0  # Maximum daily loss percentage
    correlation_threshold: float = 0.7  # Max correlation between positions
    max_correlated_exposure_pct: float = 0.3  # Max % in correlated positions
    enable_emergency_stop: bool = True  # Enable emergency stop mechanism
    risk_check_enabled: bool = True  # Master switch for risk checks
    
    # ==================== DATA QUALITY ====================
    max_data_age_seconds: int = 300  # 5 minutes - max age for price data
    max_price_change_pct: float = 20.0  # Max reasonable price change percentage
    enable_alpaca_failover: bool = False  # Failover to Alpaca if Yahoo fails (requires Alpaca data subscription)
    data_validation_enabled: bool = True  # Master switch for data validation
    log_data_metrics_interval: int = 3600  # Log metrics every hour (seconds)
    
    # ==================== RECONCILIATION ====================
    reconciliation_interval_minutes: int = 15  # How often to reconcile positions
    order_verification_enabled: bool = True  # Verify order fills
    max_order_wait_seconds: int = 60  # Max time to wait for order fill
    enable_startup_reconciliation: bool = True  # Reconcile on startup
    alert_on_discrepancy: bool = True  # Send Discord alert for discrepancies
    
    # ==================== FEATURE FLAGS ====================
    enable_options: bool = False  # Master control for swing options
    enable_options_scalp: bool = True  # Master control for scalp options (0-5 DTE)
    
    # ==================== TECHNICAL ANALYSIS ====================
    # Lookback periods
    daily_lookback_days: int = 365
    hourly_lookback_days: int = 60
    intraday_lookback_days: int = 5
    intraday_timeframe: str = '15m'
    
    # ==================== CACHING ====================
    data_cache_ttl: int = 60  # seconds
    indicator_cache_ttl: int = 60  # seconds
    sentiment_cache_duration: int = 0  # DISABLED - sentiment refreshes every cycle for real-time trading
    
    # ==================== AGENT SETTINGS ====================
    agent_memory_size: int = 100  # Number of analyses to remember
    use_gemini_sentiment: bool = True  # Use Gemini AI for sentiment
    
    # ==================== AGENT COORDINATION ====================
    enable_agent_coordination: bool = True  # Use coordination layer
    consensus_threshold: float = 0.6  # Minimum score to trigger BUY
    agent_base_weights: dict = field(default_factory=lambda: {
        'sentiment': 1.0,
        'fundamental': 1.0,
        'technical': 1.0
    })
    performance_window: int = 20  # Recent trades for accuracy calculation
    min_trades_for_learning: int = 10  # Min trades before adjusting weights
    weight_adjustment_rate: float = 0.1  # How fast to adapt (0.0-1.0)
    enable_market_regime_modifier: bool = True  # Use market regime in weighting
    performance_file: str = 'agent_performance_history.json'  # Performance data file
    
    # ==================== OPTIONS TRADING ====================
    options_total_budget: float = field(init=False)
    options_trade_cap: float = field(init=False)
    
    def __post_init__(self):
        """Calculate derived values"""
        self.options_total_budget = self.target_portfolio_value * self.options_alloc_pct
        self.options_trade_cap = self.options_total_budget / 10.0
        
        # Load symbols from environment if provided
        env_symbols = os.getenv('SYMBOLS')
        if env_symbols:
            self.symbols = [s.strip() for s in env_symbols.split(',')]
    
    @property
    def swing_budget(self) -> float:
        """Calculate swing trading budget"""
        return self.target_portfolio_value * self.swing_alloc_pct
    
    @property
    def scalp_budget(self) -> float:
        """Calculate scalping budget"""
        return self.target_portfolio_value * self.scalp_alloc_pct
    
    def validate(self) -> bool:
        """
        Validate configuration.
        
        Returns:
            True if valid, raises ValueError if invalid
        """
        # Check API keys
        if not self.api_key or not self.secret_key:
            raise ValueError("API_KEY and SECRET_KEY must be set in .env file")
        
        # Check allocations sum to 1.0
        total_alloc = self.swing_alloc_pct + self.scalp_alloc_pct + self.options_alloc_pct
        if abs(total_alloc - 1.0) > 0.01:
            raise ValueError(f"Allocations must sum to 1.0, got {total_alloc}")
        
        # Check symbols list
        if not self.symbols:
            raise ValueError("Must have at least one symbol to trade")
        
        # Check position limits
        if self.max_swing_positions < 1 or self.max_scalp_positions < 1:
            raise ValueError("Position limits must be at least 1")
        
        return True
    
    def summary(self) -> str:
        """
        Generate configuration summary for logging.
        
        Returns:
            Formatted configuration summary
        """
        return f"""
╔══════════════════════════════════════════════════════════════╗
║                  TRADING CONFIGURATION V8                     ║
╚══════════════════════════════════════════════════════════════╝

📊 PORTFOLIO:
   • Target Value: ${self.target_portfolio_value:,.0f}
   • Swing Budget: ${self.swing_budget:,.0f} ({self.swing_alloc_pct*100:.0f}%)
   • Scalp Budget: ${self.scalp_budget:,.0f} ({self.scalp_alloc_pct*100:.0f}%)
   • Options Budget: ${self.options_total_budget:,.0f} ({self.options_alloc_pct*100:.0f}%)

📈 SYMBOLS ({len(self.symbols)}):
   {', '.join(self.symbols)}

🎯 POSITION LIMITS:
   • Max Swing: {self.max_swing_positions}
   • Max Scalp: {self.max_scalp_positions}
   • PDT Compliant: {'Yes' if self.above_25k else 'No'}

🛡️ RISK MANAGEMENT:
   • Risk per Trade: {self.risk_pct*100:.1f}%
   • ATR Multiplier: {self.atr_multiplier}x
   • Trailing Stop: {self.trailing_stop_pct:.1f}%

⚙️ FEATURES:
   • Swing Options: {'Enabled' if self.enable_options else 'Disabled'}
   • Scalp Options: {'Enabled' if self.enable_options_scalp else 'Disabled'}
   • Gemini Sentiment: {'Enabled' if self.use_gemini_sentiment else 'Disabled'}
   • Agent Coordination: {'Enabled' if self.enable_agent_coordination else 'Disabled'}

🤖 AGENT COORDINATION:
   • Consensus Threshold: {self.consensus_threshold:.2f}
   • Performance Window: {self.performance_window} trades
   • Min Trades for Learning: {self.min_trades_for_learning}
   • Weight Adjustment Rate: {self.weight_adjustment_rate:.1%}
   • Market Regime Modifier: {'Enabled' if self.enable_market_regime_modifier else 'Disabled'}

💾 CACHING:
   • Data Cache: {self.data_cache_ttl}s
   • Indicator Cache: {self.indicator_cache_ttl}s
   • Sentiment Cache: Real-time (refreshes every cycle)

╚══════════════════════════════════════════════════════════════╝
"""


# Global configuration instance
_config = None


def get_config() -> TradingConfig:
    """
    Get the global configuration instance.
    Creates it if it doesn't exist.
    
    Returns:
        TradingConfig instance
    """
    global _config
    if _config is None:
        _config = TradingConfig()
        _config.validate()
    return _config


def reload_config() -> TradingConfig:
    """
    Reload configuration from environment.
    Useful for testing or runtime config changes.
    
    Returns:
        New TradingConfig instance
    """
    global _config
    load_dotenv(override=True)
    _config = TradingConfig()
    _config.validate()
    return _config
