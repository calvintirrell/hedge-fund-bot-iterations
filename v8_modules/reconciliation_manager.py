"""
Position Reconciliation Manager
Ensures internal state matches Alpaca's actual positions
"""

import logging
from datetime import datetime
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class ReconciliationManager:
    """
    Manages position reconciliation between internal tracking and Alpaca.
    Detects discrepancies and syncs state to match reality.
    """
    
    def __init__(self, config, trading_client, position_tracker):
        """
        Initialize ReconciliationManager.
        
        Args:
            config: TradingConfig instance
            trading_client: Alpaca TradingClient
            position_tracker: PositionTracker instance
        """
        self.config = config
        self.client = trading_client
        self.position_tracker = position_tracker
        self.last_reconciliation = None
        self.discrepancies_found = []
        
        logger.info("ReconciliationManager initialized")
    
    def fetch_alpaca_positions(self) -> Dict[str, float]:
        """
        Fetch all current positions from Alpaca.
        
        Returns:
            Dict mapping symbol to quantity
        """
        try:
            positions = self.client.get_all_positions()
            alpaca_positions = {}
            
            for pos in positions:
                alpaca_positions[pos.symbol] = float(pos.qty)
            
            logger.debug(f"Fetched {len(alpaca_positions)} positions from Alpaca")
            return alpaca_positions
            
        except Exception as e:
            logger.error(f"Failed to fetch Alpaca positions: {e}")
            return {}
    
    def compare_positions(self, internal: Dict[str, float], alpaca: Dict[str, float]) -> List[str]:
        """
        Compare internal positions with Alpaca positions.
        
        Args:
            internal: Internal position tracking {symbol: qty}
            alpaca: Alpaca positions {symbol: qty}
            
        Returns:
            List of discrepancy descriptions
        """
        discrepancies = []
        
        # Check for positions in internal but not in Alpaca
        for symbol, qty in internal.items():
            if symbol not in alpaca:
                discrepancies.append(f"Internal has {symbol} ({qty} shares) but Alpaca doesn't")
            elif abs(alpaca[symbol] - qty) > 0.01:
                discrepancies.append(
                    f"{symbol}: Internal={qty}, Alpaca={alpaca[symbol]}"
                )
        
        # Check for positions in Alpaca but not in internal
        for symbol, qty in alpaca.items():
            if symbol not in internal:
                discrepancies.append(f"Alpaca has {symbol} ({qty} shares) but internal doesn't")
        
        return discrepancies
    
    def sync_to_alpaca(self, discrepancies: List[str]):
        """
        Update internal state to match Alpaca.
        
        Args:
            discrepancies: List of discrepancy descriptions
        """
        if not discrepancies:
            return
        
        logger.warning(f"Syncing internal state to Alpaca ({len(discrepancies)} discrepancies)")
        
        # Fetch fresh Alpaca positions
        alpaca_positions = self.fetch_alpaca_positions()
        
        # Clear internal positions and rebuild from Alpaca
        # This is the safest approach - trust Alpaca as source of truth
        self.position_tracker.positions.clear()
        
        for symbol, qty in alpaca_positions.items():
            self.position_tracker.positions[symbol] = {
                'quantity': qty,
                'entry_price': 0.0,  # Will be updated on next price fetch
                'current_price': 0.0,
                'unrealized_pnl': 0.0,
                'last_updated': datetime.now()
            }
        
        logger.info(f"Internal state synced to Alpaca: {len(alpaca_positions)} positions")
    
    def reconcile_positions(self) -> dict:
        """
        Perform full position reconciliation.
        
        Returns:
            Reconciliation report dict
        """
        logger.info("Starting position reconciliation...")
        
        # Fetch positions from both sources
        alpaca_positions = self.fetch_alpaca_positions()
        internal_positions = {
            symbol: data['quantity'] 
            for symbol, data in self.position_tracker.positions.items()
        }
        
        # Compare
        discrepancies = self.compare_positions(internal_positions, alpaca_positions)
        
        # Sync if needed
        if discrepancies:
            logger.warning(f"Found {len(discrepancies)} discrepancies")
            for disc in discrepancies:
                logger.warning(f"  • {disc}")
            
            if self.config.alert_on_discrepancy:
                self.discrepancies_found.extend(discrepancies)
            
            # Sync internal state to match Alpaca
            self.sync_to_alpaca(discrepancies)
        else:
            logger.info("✓ Positions reconciled - no discrepancies found")
        
        # Update timestamp
        self.last_reconciliation = datetime.now()
        
        # Generate report
        report = {
            'timestamp': self.last_reconciliation,
            'alpaca_positions': len(alpaca_positions),
            'internal_positions': len(internal_positions),
            'discrepancies': discrepancies,
            'synced': len(discrepancies) > 0
        }
        
        return report
    
    def verify_order_status(self, order_id: str) -> dict:
        """
        Verify the status of a submitted order.
        
        Args:
            order_id: Alpaca order ID
            
        Returns:
            Order status dict
        """
        try:
            order = self.client.get_order_by_id(order_id)
            
            return {
                'found': True,
                'status': order.status,
                'filled_qty': float(order.filled_qty) if order.filled_qty else 0.0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else 0.0,
                'symbol': order.symbol
            }
            
        except Exception as e:
            logger.error(f"Failed to verify order {order_id}: {e}")
            return {
                'found': False,
                'error': str(e)
            }
