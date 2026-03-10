import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v5 import PortfolioManager
from alpaca.trading.enums import OrderType, OrderSide, QueryOrderStatus
from alpaca.trading.requests import TrailingStopOrderRequest

class TestTrailingStopUpgrade(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Instantiate PortfolioManager directly
        with patch('alpaca_bot_v5.SentimentAgent'), \
             patch('alpaca_bot_v5.FundamentalAgent'), \
             patch('alpaca_bot_v5.TechnicalAgent'), \
             patch('alpaca_bot_v5.send_discord_alert') as mock_alert:
             self.manager = PortfolioManager(self.mock_client)
             self.mock_alert = mock_alert


    def test_upgrade_fixed_to_trailing(self):
        print("\n=== Testing Trailing Stop Upgrade Logic ===")
        symbol = "TEST"
        qty = 10
        
        # 1. Simulate an EXISTING Position
        mock_position = MagicMock()
        mock_position.symbol = symbol
        mock_position.qty = qty
        
        # Mock get_all_positions returning this position
        self.mock_client.get_all_positions.return_value = [mock_position]
        
        # 2. Simulate an OPEN FIXED STOP order (but NO Trailing Stop)
        mock_fixed_order = MagicMock()
        mock_fixed_order.id = "fixed_order_123"
        mock_fixed_order.order_type = OrderType.STOP # Fixed Stop
        
        self.mock_client.get_orders.return_value = [mock_fixed_order]
        
        # 3. Running execute_strategy should trigger the upgrade
        # We assume Sentiment/Fundamental/Technical are mocked or irrelevant because 
        # the code returns EARLY if position exists.
        
        # 3. Running upgrade_stops should trigger the upgrade
        self.manager.upgrade_stops()
            
        # 4. VERIFICATION
        # Expect Cancel called on Fixed Stop
        self.mock_client.cancel_order_by_id.assert_called_with("fixed_order_123")
        print("✅ Fixed Stop Cancelled.")
        
        # Expect Submit Order called with Trailing Stop
        # We need to capture the call args to verify it's a Trailing Stop
        self.mock_client.submit_order.assert_called()
        call_args = self.mock_client.submit_order.call_args
        order_request = call_args.kwargs['order_data']
        
        self.assertIsInstance(order_request, TrailingStopOrderRequest)
        self.assertEqual(order_request.symbol, symbol)
        self.assertEqual(order_request.qty, qty)
        self.assertEqual(order_request.trail_percent, 3.0) # Checking against constant
        print("✅ Trailing Stop Submitted (3.0%).")
        
        # Verify Discord Alert
        self.mock_alert.assert_called()
        print("✅ Discord Alert Sent.")

    def test_no_double_upgrade(self):
        print("\n=== Testing No Double Upgrade ===")
        symbol = "TEST"
        
        # 1. Simulate Position
        mock_position = MagicMock()
        mock_position.symbol = symbol
        mock_position.qty = 10
        
        # Mock get_all_positions returning this position
        self.mock_client.get_all_positions.return_value = [mock_position]
        
        # 2. Simulate OPEN TRAILING STOP order
        mock_trailing_order = MagicMock()
        mock_trailing_order.order_type = OrderType.TRAILING_STOP
        
        self.mock_client.get_orders.return_value = [mock_trailing_order]
        
        # 3. Run Strategy
        self.manager.upgrade_stops()
        
        # 4. Verify NO Cancel and NO Submit
        self.mock_client.cancel_order_by_id.assert_not_called()
        self.mock_client.submit_order.assert_not_called()
        print("✅ No Action Taken (Trailing Stop already exists).")

if __name__ == '__main__':
    unittest.main()
