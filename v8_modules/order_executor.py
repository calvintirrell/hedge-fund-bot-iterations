"""
Order Executor Module
Handles order submission and management
"""

import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    TrailingStopOrderRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderStatus,
    QueryOrderStatus,
    OrderType,
    OrderClass
)

logger = logging.getLogger(__name__)


class OrderExecutor:
    """
    Handles order submission and management.
    
    Features:
    - Market order execution
    - Bracket order execution (entry + stop loss)
    - Trailing stop order management
    - Order cancellation
    - Position closing
    """
    
    def __init__(self, trading_client: TradingClient):
        """
        Initialize OrderExecutor.
        
        Args:
            trading_client: Alpaca TradingClient instance
        """
        self.client = trading_client
        logger.info("OrderExecutor initialized")
    
    def execute_market_buy(
        self,
        symbol: str,
        quantity: int,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None
    ) -> Optional[Any]:
        """
        Execute a market buy order.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            stop_price: Optional stop loss price for bracket order
            client_order_id: Optional custom order ID
            
        Returns:
            Order object if successful, None otherwise
        """
        try:
            if stop_price:
                # Bracket order with stop loss
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    order_class=OrderClass.BRACKET,
                    stop_loss={'stop_price': stop_price},
                    client_order_id=client_order_id
                )
                logger.info(f"Submitting bracket buy order: {symbol} x{quantity} with stop @ ${stop_price:.2f}")
            else:
                # Simple market order
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                    client_order_id=client_order_id
                )
                logger.info(f"Submitting market buy order: {symbol} x{quantity}")
            
            order = self.client.submit_order(order_data=order_data)
            logger.info(f"✅ Buy order submitted: {symbol} - Order ID: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"❌ Failed to execute buy order for {symbol}: {e}")
            return None
    
    def execute_market_sell(
        self,
        symbol: str,
        quantity: int,
        client_order_id: Optional[str] = None
    ) -> Optional[Any]:
        """
        Execute a market sell order.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            client_order_id: Optional custom order ID
            
        Returns:
            Order object if successful, None otherwise
        """
        try:
            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id
            )
            
            logger.info(f"Submitting market sell order: {symbol} x{quantity}")
            order = self.client.submit_order(order_data=order_data)
            logger.info(f"✅ Sell order submitted: {symbol} - Order ID: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"❌ Failed to execute sell order for {symbol}: {e}")
            return None
    
    def set_trailing_stop(
        self,
        symbol: str,
        quantity: int,
        trail_percent: float
    ) -> Optional[Any]:
        """
        Set a trailing stop order.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            trail_percent: Trailing stop percentage (e.g., 3.0 for 3%)
            
        Returns:
            Order object if successful, None otherwise
        """
        try:
            order_data = TrailingStopOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.GTC,
                trail_percent=trail_percent
            )
            
            logger.info(f"Setting trailing stop: {symbol} x{quantity} @ {trail_percent}%")
            order = self.client.submit_order(order_data=order_data)
            logger.info(f"✅ Trailing stop set: {symbol} - Order ID: {order.id}")
            return order
            
        except Exception as e:
            logger.error(f"❌ Failed to set trailing stop for {symbol}: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order by ID.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.client.cancel_order_by_id(order_id)
            logger.info(f"✅ Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to cancel order {order_id}: {e}")
            return False
    
    def cancel_all_orders_for_symbol(self, symbol: str) -> int:
        """
        Cancel all open orders for a symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Number of orders cancelled
        """
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            orders = self.client.get_orders(filter=req)
            
            cancelled_count = 0
            for order in orders:
                if self.cancel_order(order.id):
                    cancelled_count += 1
            
            logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
            return cancelled_count
            
        except Exception as e:
            logger.error(f"❌ Failed to cancel orders for {symbol}: {e}")
            return 0
    
    def close_position(self, symbol: str, safe_close: bool = True) -> bool:
        """
        Close a position.
        
        Args:
            symbol: Stock symbol
            safe_close: If True, cancel all orders first to avoid errors
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if safe_close:
                # Cancel all open orders first
                cancelled = self.cancel_all_orders_for_symbol(symbol)
                if cancelled > 0:
                    time.sleep(0.5)  # Wait for cancellations to propagate
            
            logger.info(f"Closing position: {symbol}")
            self.client.close_position(symbol)
            logger.info(f"✅ Position closed: {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to close position {symbol}: {e}")
            return False
    
    def upgrade_stop_to_trailing(
        self,
        symbol: str,
        quantity: int,
        trail_percent: float,
        fixed_stop_order_id: str
    ) -> bool:
        """
        Upgrade a fixed stop loss to a trailing stop.
        
        Args:
            symbol: Stock symbol
            quantity: Number of shares
            trail_percent: Trailing stop percentage
            fixed_stop_order_id: ID of the fixed stop order to cancel
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Cancel fixed stop
            if not self.cancel_order(fixed_stop_order_id):
                return False
            
            time.sleep(0.5)  # Wait for cancellation
            
            # Set trailing stop
            order = self.set_trailing_stop(symbol, quantity, trail_percent)
            return order is not None
            
        except Exception as e:
            logger.error(f"❌ Failed to upgrade stop for {symbol}: {e}")
            return False
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list:
        """
        Get open orders.
        
        Args:
            symbol: Optional symbol to filter by
            
        Returns:
            List of open orders
        """
        try:
            if symbol:
                req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            else:
                req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            
            orders = self.client.get_orders(filter=req)
            return orders
            
        except Exception as e:
            logger.error(f"❌ Failed to get open orders: {e}")
            return []
    
    def get_order_by_id(self, order_id: str) -> Optional[Any]:
        """
        Get order details by ID.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order object if found, None otherwise
        """
        try:
            order = self.client.get_order_by_id(order_id)
            return order
        except Exception as e:
            logger.error(f"❌ Failed to get order {order_id}: {e}")
            return None
