import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import pytz
from alpaca_bot_v4 import check_for_fills
from alpaca.trading.enums import OrderSide

class TestPnLLogic(unittest.TestCase):

    @patch('alpaca_bot_v4.send_discord_alert')
    def test_pnl_calculation(self, mock_send_alert):
        """Test that PnL is calculated correctly based on previous Buy."""
        print("\n=== Testing PnL Calculation ===")
        
        mock_client = MagicMock()
        now = datetime.now(pytz.utc)
        
        # 1. Mock SELL Order (Sold at $150)
        sell_order = MagicMock()
        sell_order.side = OrderSide.SELL
        sell_order.filled_at = now
        sell_order.symbol = "AAPL"
        sell_order.filled_qty = "10"
        sell_order.filled_avg_price = "150.00"
        
        # 2. Mock BUY Order (Bought at $100)
        buy_order = MagicMock()
        buy_order.filled_avg_price = "100.00"
        
        # Configure get_orders side_effects
        # First call: get_orders(status='closed', limit=50...) -> Returns [sell_order]
        # Second call: get_orders(status='closed', symbol='AAPL', side='buy'...) -> Returns [buy_order]
        
        def get_orders_side_effect(**kwargs):
            if kwargs.get('side') == OrderSide.BUY:
                return [buy_order]
            return [sell_order]
            
        mock_client.get_orders.side_effect = get_orders_side_effect
        
        # Run Check
        check_for_fills(mock_client, now - timedelta(minutes=1))
        
        # Verify Alert
        args = mock_send_alert.call_args[0]
        message = args[0]
        print(f"Alert Message:\n{message}")
        
        # Expected PnL: ($150 - $100) * 10 = $500
        # Expected %: ($50 / $100) * 100 = 50%
        self.assertIn("Profit: $500.00 (50.00%)", message)
        print("-> PnL Calculated Correctly!")

if __name__ == '__main__':
    unittest.main()
