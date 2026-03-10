"""
Analysis Optimizer Module
Intelligently skips unnecessary symbol analysis to reduce computational load
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AnalysisRecord:
    """Record of a previous analysis"""
    symbol: str
    timestamp: datetime
    signal: str  # 'BUY', 'WAIT', 'SELL'
    price: float
    confidence: float
    analysis_type: str  # 'swing' or 'scalp'


class AnalysisOptimizer:
    """
    Optimizes analysis by skipping unnecessary symbol checks.
    
    Skip Conditions:
    1. Already at max positions for that type (scalp/swing)
    2. Symbol analyzed recently with WAIT signal and price hasn't moved significantly
    3. Already have position in symbol (monitor only, don't re-analyze for entry)
    """
    
    def __init__(
        self,
        wait_signal_cache_minutes: int = 5,
        price_change_threshold: float = 0.01  # 1% price change
    ):
        """
        Initialize AnalysisOptimizer.
        
        Args:
            wait_signal_cache_minutes: How long to cache WAIT signals
            price_change_threshold: Minimum price change to re-analyze (e.g., 0.01 = 1%)
        """
        self.wait_signal_cache_minutes = wait_signal_cache_minutes
        self.price_change_threshold = price_change_threshold
        self.analysis_history: Dict[str, AnalysisRecord] = {}
        
        # Statistics
        self.total_checks = 0
        self.skipped_max_positions = 0
        self.skipped_recent_wait = 0
        self.skipped_has_position = 0
        self.analyses_performed = 0
        
        logger.info(f"AnalysisOptimizer initialized (cache: {wait_signal_cache_minutes}min, threshold: {price_change_threshold*100}%)")
    
    def should_analyze(
        self,
        symbol: str,
        analysis_type: str,
        current_price: float,
        position_counts: Dict[str, int],
        max_positions: Dict[str, int],
        has_position: bool
    ) -> tuple[bool, str]:
        """
        Determine if symbol should be analyzed.
        
        Args:
            symbol: Stock symbol
            analysis_type: 'swing' or 'scalp'
            current_price: Current price of the symbol
            position_counts: Current position counts {'scalp': X, 'swing': Y}
            max_positions: Max allowed positions {'scalp': X, 'swing': Y}
            has_position: Whether we already have a position in this symbol
            
        Returns:
            Tuple of (should_analyze: bool, reason: str)
        """
        self.total_checks += 1
        
        # Rule 1: Already have position - skip entry analysis
        if has_position:
            self.skipped_has_position += 1
            return False, f"Already have position in {symbol}"
        
        # Rule 2: At max positions for this type - skip
        if position_counts.get(analysis_type, 0) >= max_positions.get(analysis_type, 10):
            self.skipped_max_positions += 1
            return False, f"At max {analysis_type} positions ({position_counts[analysis_type]}/{max_positions[analysis_type]})"
        
        # Rule 3: Recently analyzed with WAIT signal and price hasn't moved much
        if symbol in self.analysis_history:
            record = self.analysis_history[symbol]
            
            # Check if record is recent
            time_since_analysis = datetime.now() - record.timestamp
            if time_since_analysis < timedelta(minutes=self.wait_signal_cache_minutes):
                
                # Check if it was a WAIT signal
                if record.signal == 'WAIT' and record.analysis_type == analysis_type:
                    
                    # Check if price has moved significantly
                    price_change = abs(current_price - record.price) / record.price
                    
                    if price_change < self.price_change_threshold:
                        self.skipped_recent_wait += 1
                        minutes_ago = time_since_analysis.total_seconds() / 60
                        return False, f"Recent WAIT signal ({minutes_ago:.1f}min ago, price change: {price_change*100:.2f}%)"
        
        # Should analyze
        self.analyses_performed += 1
        return True, "Analysis needed"
    
    def record_analysis(
        self,
        symbol: str,
        signal: str,
        price: float,
        confidence: float,
        analysis_type: str
    ):
        """
        Record an analysis result for future optimization.
        
        Args:
            symbol: Stock symbol
            signal: Analysis signal ('BUY', 'WAIT', 'SELL')
            price: Price at time of analysis
            confidence: Confidence score
            analysis_type: 'swing' or 'scalp'
        """
        self.analysis_history[symbol] = AnalysisRecord(
            symbol=symbol,
            timestamp=datetime.now(),
            signal=signal,
            price=price,
            confidence=confidence,
            analysis_type=analysis_type
        )
        
        logger.debug(f"Recorded {analysis_type} analysis: {symbol} = {signal} @ ${price:.2f}")
    
    def clear_symbol_history(self, symbol: str):
        """Clear analysis history for a symbol (e.g., after taking a position)"""
        if symbol in self.analysis_history:
            del self.analysis_history[symbol]
            logger.debug(f"Cleared analysis history for {symbol}")
    
    def get_statistics(self) -> Dict[str, any]:
        """
        Get optimization statistics.
        
        Returns:
            Dictionary with statistics
        """
        total_skipped = (self.skipped_max_positions + 
                        self.skipped_recent_wait + 
                        self.skipped_has_position)
        
        skip_rate = (total_skipped / self.total_checks * 100) if self.total_checks > 0 else 0
        
        return {
            'total_checks': self.total_checks,
            'analyses_performed': self.analyses_performed,
            'total_skipped': total_skipped,
            'skip_rate': skip_rate,
            'skipped_max_positions': self.skipped_max_positions,
            'skipped_recent_wait': self.skipped_recent_wait,
            'skipped_has_position': self.skipped_has_position
        }
    
    def summary(self) -> str:
        """Generate statistics summary."""
        stats = self.get_statistics()
        
        summary = f"\n{'='*60}\n"
        summary += "ANALYSIS OPTIMIZER STATISTICS\n"
        summary += f"{'='*60}\n"
        summary += f"Total Checks: {stats['total_checks']}\n"
        summary += f"Analyses Performed: {stats['analyses_performed']}\n"
        summary += f"Total Skipped: {stats['total_skipped']} ({stats['skip_rate']:.1f}%)\n"
        summary += f"\nSkip Breakdown:\n"
        summary += f"  • Max Positions: {stats['skipped_max_positions']}\n"
        summary += f"  • Recent WAIT: {stats['skipped_recent_wait']}\n"
        summary += f"  • Has Position: {stats['skipped_has_position']}\n"
        summary += f"{'='*60}\n"
        
        return summary
    
    def reset_statistics(self):
        """Reset statistics counters."""
        self.total_checks = 0
        self.skipped_max_positions = 0
        self.skipped_recent_wait = 0
        self.skipped_has_position = 0
        self.analyses_performed = 0
        logger.info("Statistics reset")
