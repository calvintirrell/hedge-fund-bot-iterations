"""
Trade Tracker - Position and P&L Tracking
Links buy orders to sell orders with complete trade lifecycle tracking

Features:
- Unique trade IDs linking entry to exit
- Entry/exit price and quantity tracking
- P&L calculation (per share, total, percentage)
- Hold duration tracking
- Trade type classification (scalp, swing, options)
- Discord-ready formatted output
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TradeType(Enum):
    """Trade type classification"""
    SCALP = "scalp"
    SWING = "swing"
    OPTIONS = "options"


class TradeStatus(Enum):
    """Trade lifecycle status"""
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"  # Partially closed


@dataclass
class TradeEntry:
    """Entry details for a trade"""
    trade_id: str
    symbol: str
    trade_type: TradeType
    quantity: int
    entry_price: float
    entry_time: datetime
    buy_order_id: str
    total_cost: float = field(init=False)
    
    def __post_init__(self):
        self.total_cost = self.quantity * self.entry_price


@dataclass
class TradeExit:
    """Exit details for a trade"""
    exit_price: float
    exit_time: datetime
    sell_order_id: str
    quantity_sold: int
    total_proceeds: float = field(init=False)
    
    def __post_init__(self):
        self.total_proceeds = self.quantity_sold * self.exit_price


@dataclass
class CompletedTrade:
    """Complete trade with entry, exit, and P&L (including commissions)"""
    entry: TradeEntry
    exit: TradeExit
    commission_buy: float = 0.0  # Commission paid on entry
    commission_sell: float = 0.0  # Commission paid on exit
    gain_per_share: float = field(init=False)
    total_gain: float = field(init=False)
    total_gain_after_fees: float = field(init=False)
    gain_percentage: float = field(init=False)
    gain_percentage_after_fees: float = field(init=False)
    hold_duration_days: float = field(init=False)
    status: TradeStatus = field(init=False)
    
    def __post_init__(self):
        self.gain_per_share = self.exit.exit_price - self.entry.entry_price
        self.total_gain = self.exit.total_proceeds - self.entry.total_cost
        self.total_gain_after_fees = self.total_gain - self.commission_buy - self.commission_sell
        self.gain_percentage = (self.total_gain / self.entry.total_cost) * 100
        self.gain_percentage_after_fees = (self.total_gain_after_fees / self.entry.total_cost) * 100
        
        # Calculate hold duration
        duration = self.exit.exit_time - self.entry.entry_time
        self.hold_duration_days = duration.total_seconds() / 86400  # Convert to days
        
        # Determine status
        if self.exit.quantity_sold == self.entry.quantity:
            self.status = TradeStatus.CLOSED
        else:
            self.status = TradeStatus.PARTIAL
    
    def to_discord_message(self) -> str:
        """
        Format trade for Discord notification with commission breakdown.
        
        Returns:
            Formatted string ready for Discord webhook
        """
        # Emoji based on profit/loss (after fees)
        emoji = "🟢" if self.total_gain_after_fees > 0 else "🔴" if self.total_gain_after_fees < 0 else "⚪"
        
        # Trade type badge
        type_badge = {
            TradeType.SCALP: "⚡ SCALP",
            TradeType.SWING: "📈 SWING",
            TradeType.OPTIONS: "🎯 OPTIONS"
        }.get(self.entry.trade_type, "📊 TRADE")
        
        # Format hold duration
        if self.hold_duration_days < 1:
            hold_str = f"{self.hold_duration_days * 24:.1f} hours"
        else:
            hold_str = f"{self.hold_duration_days:.1f} days"
        
        # Calculate total fees
        total_fees = self.commission_buy + self.commission_sell
        
        # Build message
        message = f"""
{emoji} **{type_badge} CLOSED** - {self.entry.symbol}

**Entry:**
• Buy Order ID: `{self.entry.buy_order_id}`
• Quantity: {self.entry.quantity} shares
• Entry Price: ${self.entry.entry_price:.2f}
• Total Cost: ${self.entry.total_cost:.2f}
• Entry Time: {self.entry.entry_time.strftime('%Y-%m-%d %H:%M:%S')}

**Exit:**
• Sell Order ID: `{self.exit.sell_order_id}`
• Quantity Sold: {self.exit.quantity_sold} shares
• Exit Price: ${self.exit.exit_price:.2f}
• Total Proceeds: ${self.exit.total_proceeds:.2f}
• Exit Time: {self.exit.exit_time.strftime('%Y-%m-%d %H:%M:%S')}

**Performance:**
• Gain/Loss per Share: ${self.gain_per_share:+.2f}
• Total Gain/Loss (Before Fees): ${self.total_gain:+.2f} ({self.gain_percentage:+.2f}%)
• Commission & Fees: ${total_fees:.2f}
• Total Gain/Loss (After Fees): ${self.total_gain_after_fees:+.2f} ({self.gain_percentage_after_fees:+.2f}%)
• Hold Duration: {hold_str}
"""
        return message.strip()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage"""
        return {
            'trade_id': self.entry.trade_id,
            'symbol': self.entry.symbol,
            'trade_type': self.entry.trade_type.value,
            'status': self.status.value,
            'entry': {
                'quantity': self.entry.quantity,
                'price': self.entry.entry_price,
                'time': self.entry.entry_time.isoformat(),
                'order_id': self.entry.buy_order_id,
                'total_cost': self.entry.total_cost
            },
            'exit': {
                'quantity': self.exit.quantity_sold,
                'price': self.exit.exit_price,
                'time': self.exit.exit_time.isoformat(),
                'order_id': self.exit.sell_order_id,
                'total_proceeds': self.exit.total_proceeds
            },
            'performance': {
                'gain_per_share': self.gain_per_share,
                'total_gain': self.total_gain,
                'gain_percentage': self.gain_percentage,
                'hold_duration_days': self.hold_duration_days
            }
        }


class TradeTracker:
    """
    Tracks open and closed trades with complete lifecycle.
    
    Features:
    - Links buy orders to sell orders
    - Calculates P&L automatically (with commission simulation)
    - Generates Discord notifications
    - Maintains trade history
    - Provides feedback to AgentCoordinator for adaptive learning
    """
    
    def __init__(self, agent_coordinator=None, config=None):
        """
        Initialize trade tracker.
        
        Args:
            agent_coordinator: Optional AgentCoordinator instance for feedback loop
            config: Optional TradingConfig for commission simulation
        """
        self.open_trades: Dict[str, TradeEntry] = {}  # trade_id -> TradeEntry
        self.closed_trades: List[CompletedTrade] = []
        self.trade_counter = 0
        self.agent_coordinator = agent_coordinator
        self.config = config
        logger.info("TradeTracker initialized")
    
    def calculate_commission(self, trade_type: TradeType, quantity: int, price: float, is_buy: bool) -> float:
        """
        Calculate commission for a trade based on Alpaca's fee structure.
        
        Args:
            trade_type: Type of trade (SCALP, SWING, OPTIONS)
            quantity: Number of shares/contracts
            price: Price per share/contract
            is_buy: True for buy orders, False for sell orders
            
        Returns:
            Total commission in dollars
        """
        if not self.config or not self.config.enable_commission_simulation:
            return 0.0
        
        total_commission = 0.0
        
        if trade_type == TradeType.OPTIONS:
            # Options: $0.65 per contract
            total_commission += quantity * self.config.options_commission_per_contract
        else:
            # Stocks: Commission-free on Alpaca, but regulatory fees apply
            total_value = quantity * price
            
            # SEC fee (only on sells): $27.80 per $1,000,000
            if not is_buy:
                sec_fee = total_value * self.config.sec_fee_per_dollar
                total_commission += sec_fee
            
            # FINRA TAF (only on sells): $0.000166 per share, max $8.30 per trade
            if not is_buy:
                finra_fee = min(quantity * self.config.finra_taf_per_share, 8.30)
                total_commission += finra_fee
        
        return round(total_commission, 2)
    
    def generate_trade_id(self, symbol: str, trade_type: TradeType) -> str:
        """
        Generate unique trade ID.
        
        Args:
            symbol: Stock symbol
            trade_type: Type of trade
            
        Returns:
            Unique trade ID (e.g., "AMD_SCALP_001")
        """
        self.trade_counter += 1
        return f"{symbol}_{trade_type.value.upper()}_{self.trade_counter:03d}"
    
    def open_trade(
        self,
        symbol: str,
        trade_type: TradeType,
        quantity: int,
        entry_price: float,
        buy_order_id: str
    ) -> str:
        """
        Record a new trade entry.
        
        Args:
            symbol: Stock symbol
            trade_type: Type of trade (scalp, swing, options)
            quantity: Number of shares
            entry_price: Entry price per share
            buy_order_id: Alpaca buy order ID
            
        Returns:
            trade_id: Unique identifier for this trade
        """
        trade_id = self.generate_trade_id(symbol, trade_type)
        
        entry = TradeEntry(
            trade_id=trade_id,
            symbol=symbol,
            trade_type=trade_type,
            quantity=quantity,
            entry_price=entry_price,
            entry_time=datetime.now(),
            buy_order_id=buy_order_id
        )
        
        self.open_trades[trade_id] = entry
        
        logger.info(
            f"Trade opened: {trade_id} | {symbol} | {quantity} shares @ ${entry_price:.2f} | "
            f"Order: {buy_order_id}"
        )
        
        return trade_id
    
    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        sell_order_id: str,
        quantity_sold: Optional[int] = None
    ) -> Optional[CompletedTrade]:
        """
        Close a trade and calculate P&L (including commissions).
        
        Args:
            trade_id: Trade identifier from open_trade()
            exit_price: Exit price per share
            sell_order_id: Alpaca sell order ID
            quantity_sold: Quantity sold (None = full position)
            
        Returns:
            CompletedTrade with full details, or None if trade not found
        """
        if trade_id not in self.open_trades:
            logger.error(f"Trade {trade_id} not found in open trades")
            return None
        
        entry = self.open_trades[trade_id]
        
        # Default to full position
        if quantity_sold is None:
            quantity_sold = entry.quantity
        
        # Calculate commissions
        commission_buy = self.calculate_commission(
            trade_type=entry.trade_type,
            quantity=entry.quantity,
            price=entry.entry_price,
            is_buy=True
        )
        
        commission_sell = self.calculate_commission(
            trade_type=entry.trade_type,
            quantity=quantity_sold,
            price=exit_price,
            is_buy=False
        )
        
        # Create exit record
        exit_record = TradeExit(
            exit_price=exit_price,
            exit_time=datetime.now(),
            sell_order_id=sell_order_id,
            quantity_sold=quantity_sold
        )
        
        # Create completed trade with commissions
        completed = CompletedTrade(
            entry=entry,
            exit=exit_record,
            commission_buy=commission_buy,
            commission_sell=commission_sell
        )
        
        # Remove from open trades if fully closed
        if completed.status == TradeStatus.CLOSED:
            del self.open_trades[trade_id]
        else:
            # Update remaining quantity for partial close
            entry.quantity -= quantity_sold
            entry.total_cost = entry.quantity * entry.entry_price
        
        # Add to history
        self.closed_trades.append(completed)
        
        logger.info(
            f"Trade closed: {trade_id} | {entry.symbol} | "
            f"P&L: ${completed.total_gain:+.2f} (${completed.total_gain_after_fees:+.2f} after fees) | "
            f"Fees: ${commission_buy + commission_sell:.2f} | "
            f"Return: {completed.gain_percentage:+.2f}% ({completed.gain_percentage_after_fees:+.2f}% after fees) | "
            f"Hold: {completed.hold_duration_days:.1f} days"
        )
        
        # V8 Agent Coordination: Update agent performance based on trade outcome (use after-fee P&L)
        if self.agent_coordinator:
            try:
                self.agent_coordinator.update_from_trade_outcome(
                    trade_id=trade_id,
                    pnl_pct=completed.gain_percentage_after_fees  # Use after-fee percentage
                )
                logger.debug(f"Updated agent coordinator with trade outcome: {trade_id}")
            except Exception as e:
                logger.error(f"Failed to update agent coordinator: {e}")
        
        return completed
    
    def close_trade_by_symbol(
        self,
        symbol: str,
        trade_type: TradeType,
        exit_price: float,
        sell_order_id: str,
        quantity_sold: Optional[int] = None
    ) -> Optional[CompletedTrade]:
        """
        Close the oldest open trade for a symbol/type.
        
        Useful when you don't have the trade_id but know symbol and type.
        
        Args:
            symbol: Stock symbol
            trade_type: Type of trade
            exit_price: Exit price
            sell_order_id: Alpaca sell order ID
            quantity_sold: Quantity sold (None = full position)
            
        Returns:
            CompletedTrade or None if no matching trade found
        """
        # Find oldest matching trade
        matching_trades = [
            (tid, entry) for tid, entry in self.open_trades.items()
            if entry.symbol == symbol and entry.trade_type == trade_type
        ]
        
        if not matching_trades:
            logger.warning(f"No open {trade_type.value} trade found for {symbol}")
            return None
        
        # Sort by entry time (oldest first)
        matching_trades.sort(key=lambda x: x[1].entry_time)
        trade_id = matching_trades[0][0]
        
        # Close the trade and update coordinator
        completed = self.close_trade(trade_id, exit_price, sell_order_id, quantity_sold)
        
        return completed
    
    def get_open_trades(self, symbol: Optional[str] = None) -> List[TradeEntry]:
        """
        Get all open trades, optionally filtered by symbol.
        
        Args:
            symbol: Optional symbol filter
            
        Returns:
            List of open trade entries
        """
        if symbol:
            return [
                entry for entry in self.open_trades.values()
                if entry.symbol == symbol
            ]
        return list(self.open_trades.values())
    
    def get_closed_trades(
        self,
        symbol: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[CompletedTrade]:
        """
        Get closed trades, optionally filtered.
        
        Args:
            symbol: Optional symbol filter
            limit: Maximum number to return (most recent)
            
        Returns:
            List of completed trades
        """
        trades = self.closed_trades
        
        if symbol:
            trades = [t for t in trades if t.entry.symbol == symbol]
        
        if limit:
            trades = trades[-limit:]
        
        return trades
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get overall performance summary (using after-fee P&L).
        
        Returns:
            Dictionary with performance metrics
        """
        if not self.closed_trades:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'total_pnl_after_fees': 0.0,
                'avg_pnl': 0.0,
                'avg_pnl_after_fees': 0.0,
                'total_fees': 0.0,
                'avg_hold_days': 0.0,
                'open_positions': len(self.open_trades)
            }
        
        winning = [t for t in self.closed_trades if t.total_gain_after_fees > 0]
        losing = [t for t in self.closed_trades if t.total_gain_after_fees < 0]
        
        total_pnl = sum(t.total_gain for t in self.closed_trades)
        total_pnl_after_fees = sum(t.total_gain_after_fees for t in self.closed_trades)
        total_fees = sum(t.commission_buy + t.commission_sell for t in self.closed_trades)
        avg_pnl = total_pnl / len(self.closed_trades)
        avg_pnl_after_fees = total_pnl_after_fees / len(self.closed_trades)
        avg_hold = sum(t.hold_duration_days for t in self.closed_trades) / len(self.closed_trades)
        
        return {
            'total_trades': len(self.closed_trades),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(self.closed_trades) * 100,
            'total_pnl': total_pnl,
            'total_pnl_after_fees': total_pnl_after_fees,
            'avg_pnl': avg_pnl,
            'avg_pnl_after_fees': avg_pnl_after_fees,
            'total_fees': total_fees,
            'avg_hold_days': avg_hold,
            'open_positions': len(self.open_trades)
        }
    
    def get_performance_by_trade_type(self) -> Dict[TradeType, Dict[str, Any]]:
        """
        Get performance summary broken down by trade type (using after-fee P&L).
        
        Returns:
            Dictionary mapping TradeType to performance metrics
        """
        results = {}
        
        for trade_type in TradeType:
            # Filter closed trades by type
            type_trades = [t for t in self.closed_trades if t.entry.trade_type == trade_type]
            
            # Filter open trades by type
            type_open = [t for t in self.open_trades.values() if t.trade_type == trade_type]
            
            if not type_trades:
                results[trade_type] = {
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'win_rate': 0.0,
                    'total_pnl': 0.0,
                    'total_pnl_after_fees': 0.0,
                    'avg_pnl': 0.0,
                    'avg_pnl_after_fees': 0.0,
                    'total_fees': 0.0,
                    'avg_hold_days': 0.0,
                    'open_positions': len(type_open)
                }
                continue
            
            winning = [t for t in type_trades if t.total_gain_after_fees > 0]
            losing = [t for t in type_trades if t.total_gain_after_fees < 0]
            
            total_pnl = sum(t.total_gain for t in type_trades)
            total_pnl_after_fees = sum(t.total_gain_after_fees for t in type_trades)
            total_fees = sum(t.commission_buy + t.commission_sell for t in type_trades)
            avg_pnl = total_pnl / len(type_trades)
            avg_pnl_after_fees = total_pnl_after_fees / len(type_trades)
            avg_hold = sum(t.hold_duration_days for t in type_trades) / len(type_trades)
            
            results[trade_type] = {
                'total_trades': len(type_trades),
                'winning_trades': len(winning),
                'losing_trades': len(losing),
                'win_rate': len(winning) / len(type_trades) * 100,
                'total_pnl': total_pnl,
                'total_pnl_after_fees': total_pnl_after_fees,
                'avg_pnl': avg_pnl,
                'avg_pnl_after_fees': avg_pnl_after_fees,
                'total_fees': total_fees,
                'avg_hold_days': avg_hold,
                'open_positions': len(type_open)
            }
        
        return results
    
    def format_daily_summary(self) -> str:
        """
        Format daily performance summary for Discord with per-trade-type breakdowns.
        Shows both before and after fee metrics.
        
        Returns:
            Formatted string ready for Discord webhook
        """
        summary = self.get_performance_summary()
        by_type = self.get_performance_by_trade_type()
        
        # Emoji based on overall P&L (after fees)
        if summary['total_pnl_after_fees'] > 0:
            emoji = "🟢"
            status = "PROFITABLE DAY"
        elif summary['total_pnl_after_fees'] < 0:
            emoji = "🔴"
            status = "LOSS DAY"
        else:
            emoji = "⚪"
            status = "BREAKEVEN DAY"
        
        # Format hold duration
        if summary['avg_hold_days'] < 1:
            hold_str = f"{summary['avg_hold_days'] * 24:.1f} hours"
        else:
            hold_str = f"{summary['avg_hold_days']:.1f} days"
        
        # Build message
        message = f"""
{emoji} **DAILY PERFORMANCE SUMMARY** - {status}

**Overall Trading Activity:**
• Total Trades: {summary['total_trades']}
• Winning Trades: {summary['winning_trades']} 🟢
• Losing Trades: {summary['losing_trades']} 🔴
• Win Rate: {summary['win_rate']:.1f}%

**Overall Financial Performance:**
• Total P&L (Before Fees): ${summary['total_pnl']:+.2f}
• Total P&L (After Fees): ${summary['total_pnl_after_fees']:+.2f}
• Total Fees Paid: ${summary['total_fees']:.2f}
• Avg P&L per Trade: ${summary['avg_pnl_after_fees']:+.2f}
• Average Hold Duration: {hold_str}

**Overall Open Positions:** {summary['open_positions']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Add per-trade-type breakdowns
        for trade_type in [TradeType.SWING, TradeType.SCALP, TradeType.OPTIONS]:
            stats = by_type[trade_type]
            
            # Skip if no trades of this type
            if stats['total_trades'] == 0 and stats['open_positions'] == 0:
                continue
            
            # Trade type emoji and label
            if trade_type == TradeType.SWING:
                type_emoji = "💰"
                type_label = "SWING TRADES"
            elif trade_type == TradeType.SCALP:
                type_emoji = "⚡"
                type_label = "SCALP TRADES"
            else:
                type_emoji = "🧬"
                type_label = "OPTIONS TRADES"
            
            # Format hold duration for this type
            if stats['total_trades'] > 0:
                if stats['avg_hold_days'] < 1:
                    type_hold_str = f"{stats['avg_hold_days'] * 24:.1f} hours"
                else:
                    type_hold_str = f"{stats['avg_hold_days']:.1f} days"
            else:
                type_hold_str = "N/A"
            
            # Add section for this trade type
            message += f"""
{type_emoji} **{type_label}:**
• Trades: {stats['total_trades']} (W: {stats['winning_trades']} 🟢 | L: {stats['losing_trades']} 🔴)
• Win Rate: {stats['win_rate']:.1f}%
• Total P&L: ${stats['total_pnl_after_fees']:+.2f} (Fees: ${stats['total_fees']:.2f})
• Avg P&L: ${stats['avg_pnl_after_fees']:+.2f}
• Avg Hold: {type_hold_str}
• Open: {stats['open_positions']}

"""
        
        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        return message.strip()
