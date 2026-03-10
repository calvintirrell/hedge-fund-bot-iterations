"""
Position Tracker Module
Tracks open positions and their types (scalp vs swing)
"""

import logging
from typing import Dict, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PositionInfo:
    """Information about an open position"""
    symbol: str
    position_type: str  # 'scalp' or 'swing'
    entry_price: float
    quantity: int
    entry_time: datetime
    trade_id: Optional[str] = None


class PositionTracker:
    """
    Tracks open positions and their types.
    
    Features:
    - In-memory tracking (no API calls)
    - Position type classification (scalp vs swing)
    - Fast position count queries
    - Position lookup by symbol
    """
    
    def __init__(self):
        """Initialize position tracker"""
        self.positions: Dict[str, PositionInfo] = {}
        logger.info("PositionTracker initialized")
    
    def add_position(
        self,
        symbol: str,
        position_type: str,
        entry_price: float,
        quantity: int,
        trade_id: Optional[str] = None
    ):
        """
        Add a new position to tracking.
        
        Args:
            symbol: Stock symbol
            position_type: 'scalp' or 'swing'
            entry_price: Entry price per share
            quantity: Number of shares
            trade_id: Optional trade ID from TradeTracker
        """
        if position_type not in ['scalp', 'swing']:
            raise ValueError(f"Invalid position_type: {position_type}. Must be 'scalp' or 'swing'")
        
        self.positions[symbol] = PositionInfo(
            symbol=symbol,
            position_type=position_type,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(),
            trade_id=trade_id
        )
        
        logger.info(f"Position added: {symbol} ({position_type}) - {quantity} shares @ ${entry_price:.2f}")
    
    def remove_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        Remove a position from tracking.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            PositionInfo if found, None otherwise
        """
        if symbol in self.positions:
            position = self.positions.pop(symbol)
            logger.info(f"Position removed: {symbol} ({position.position_type})")
            return position
        
        logger.warning(f"Attempted to remove non-existent position: {symbol}")
        return None
    
    def get_position(self, symbol: str) -> Optional[PositionInfo]:
        """
        Get position info for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            PositionInfo if found, None otherwise
        """
        return self.positions.get(symbol)
    
    def get_position_type(self, symbol: str) -> Optional[str]:
        """
        Get position type for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            'scalp', 'swing', or None if not found
        """
        position = self.positions.get(symbol)
        return position.position_type if position else None
    
    def get_position_counts(self) -> Dict[str, int]:
        """
        Get count of positions by type.
        
        Returns:
            Dictionary with 'scalp' and 'swing' counts
        """
        counts = {'scalp': 0, 'swing': 0}
        
        for position in self.positions.values():
            counts[position.position_type] += 1
        
        return counts
    
    def get_all_positions(self) -> Dict[str, PositionInfo]:
        """
        Get all tracked positions.
        
        Returns:
            Dictionary of symbol -> PositionInfo
        """
        return self.positions.copy()
    
    def get_positions_by_type(self, position_type: str) -> Dict[str, PositionInfo]:
        """
        Get all positions of a specific type.
        
        Args:
            position_type: 'scalp' or 'swing'
            
        Returns:
            Dictionary of symbol -> PositionInfo for matching type
        """
        return {
            symbol: pos for symbol, pos in self.positions.items()
            if pos.position_type == position_type
        }
    
    def has_position(self, symbol: str) -> bool:
        """
        Check if a position exists for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            True if position exists, False otherwise
        """
        return symbol in self.positions
    
    def clear(self):
        """Clear all tracked positions"""
        count = len(self.positions)
        self.positions.clear()
        logger.info(f"Cleared {count} tracked positions")
    
    def summary(self) -> str:
        """
        Generate position summary.
        
        Returns:
            Formatted summary string
        """
        counts = self.get_position_counts()
        total = sum(counts.values())
        
        summary = f"\n{'='*60}\n"
        summary += "POSITION TRACKER SUMMARY\n"
        summary += f"{'='*60}\n"
        summary += f"Total Positions: {total}\n"
        summary += f"  • Scalp: {counts['scalp']}\n"
        summary += f"  • Swing: {counts['swing']}\n"
        
        if self.positions:
            summary += f"\nOpen Positions:\n"
            for symbol, pos in self.positions.items():
                summary += f"  • {symbol}: {pos.position_type.upper()} - {pos.quantity} shares @ ${pos.entry_price:.2f}\n"
        
        summary += f"{'='*60}\n"
        
        return summary
