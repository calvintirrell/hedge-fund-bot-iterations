import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from alpaca_bot_v4 import calculate_qty, check_strategy, STOP_LOSS_PERCENT
from alpaca.trading.enums import OrderType, OrderSide

class TestAlpacaBotV4(unittest.TestCase):

    def test_dynamic_position_sizing(self):
        """Test if quantity is calculated correctly based on 1% risk."""
        equity = 100000 # $100k account
        risk_pct = 0.01 # 1% risk = $1000
        price = 100.0
        stop_pct = 2.5 # 2.5% stop = $2.50 risk per share
        
        # Expected: $1000 / $2.50 = 400 shares
        qty = calculate_qty(equity, price)
        print(f"\n[Dynamic Sizing] Equity: ${equity}, Price: ${price}, Stop: {stop_pct}% -> Qty: {qty}")
        self.assertEqual(qty, 400)

    @patch('alpaca_bot_v4.fetch_and_prepare_data')
    def test_golden_cross_logic(self, mock_fetch):
        """Test that strategy REJECTS trade if Golden Cross is missing."""
        print("\n[Golden Cross] Testing rejection logic...")
        
        # Mock Trading Client
        mock_client = MagicMock()
        mock_client.get_account.return_value.trading_blocked = False
        mock_client.get_account.return_value.equity = 100000
        mock_client.get_open_position.side_effect = Exception("No position") # No position held

        # 1. Mock Daily Data (UP Trend)
        daily_df = pd.DataFrame({'close': [100]*201})
        daily_df['SMA_50'] = 110 # Fast
        daily_df['SMA_200'] = 100 # Slow
        # Trend = UP
        
        # 2. Mock Hourly Data (DOWN Trend - NO Golden Cross)
        hourly_df = pd.DataFrame({'close': [100]*201})
        hourly_df['SMA_50'] = 90 # Fast
        hourly_df['SMA_200'] = 100 # Slow
        # Trend = DOWN
        
        # Setup mock returns
        # First call is Daily, Second is Hourly
        mock_fetch.side_effect = [daily_df, hourly_df] 

        # Run Strategy
        check_strategy(mock_client, "TEST_SYM")
        
        # Verify NO order was submitted
        mock_client.submit_order.assert_not_called()
        print("-> Trade correctly SKIPPED due to missing Golden Cross.")

    @patch('alpaca_bot_v4.fetch_and_prepare_data')
    def test_trailing_stop_upgrade(self, mock_fetch):
        """Test that Fixed Stop is upgraded to Trailing Stop."""
        print("\n[Trailing Stop] Testing upgrade logic...")
        
        mock_client = MagicMock()
        mock_client.get_account.return_value.trading_blocked = False
        
        # Mock Position Exists
        mock_position = MagicMock()
        mock_position.qty = "10"
        mock_client.get_open_position.return_value = mock_position
        
        # Mock Existing Fixed Stop Order
        mock_order = MagicMock()
        mock_order.order_type = OrderType.STOP
        mock_order.id = "fixed_stop_id"
        mock_client.get_orders.return_value = [mock_order]
        
        # Run Strategy
        # We need fetch to return a valid DF for the Daily check (first call)
        # so it proceeds to the position check.
        daily_df = pd.DataFrame({'close': [100]*201})
        daily_df['SMA_50'] = 110 
        daily_df['SMA_200'] = 100
        mock_fetch.return_value = daily_df
        
        check_strategy(mock_client, "TEST_SYM")
        
        # Verify Cancel called
        mock_client.cancel_order_by_id.assert_called_with("fixed_stop_id")
        
        # Verify Submit called with Trailing Stop
        args, kwargs = mock_client.submit_order.call_args
        submitted_order = kwargs['order_data']
        
        print(f"-> Cancelled Fixed Stop ID: fixed_stop_id")
        print(f"-> Submitted New Order Type: {type(submitted_order)}")
        # Check if it's a TrailingStopOrderRequest (by checking attributes)
        self.assertEqual(submitted_order.trail_percent, STOP_LOSS_PERCENT)
        print("-> Upgrade successful!")

if __name__ == '__main__':
    unittest.main()
