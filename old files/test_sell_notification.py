import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import pytz
from alpaca_bot_v4 import check_for_fills
from alpaca.trading.enums import OrderSide

class TestSellNotification(unittest.TestCase):

    @patch('alpaca_bot_v4.send_discord_alert')
    def test_sell_alert(self, mock_send_alert):
        """Test that a new SELL fill triggers a Discord alert."""
        print("\n=== Testing Sell Notification ===")
        
        mock_client = MagicMock()
        
        # Setup Times
        now = datetime.now(pytz.utc)
        last_check = now - timedelta(minutes=5)
        fill_time = now - timedelta(minutes=1) # Filled 1 min ago (NEW)
        
        # Mock Order
        mock_order = MagicMock()
        mock_order.side = OrderSide.SELL
        mock_order.filled_at = fill_time
        mock_order.symbol = "AAPL"
        mock_order.filled_qty = "100"
        mock_order.filled_avg_price = "150.00"
        
        # Return this order
        mock_client.get_orders.return_value = [mock_order]
        
        # Run Check
        new_check_time = check_for_fills(mock_client, last_check)
        
        # Verify Alert Sent
        mock_send_alert.assert_called_once()
        args = mock_send_alert.call_args[0]
        message = args[0]
        print(f"Alert Message Sent:\n{message}")
        
        self.assertIn("💰 SOLD AAPL", message)
        self.assertIn("100 shares", message)
        self.assertIn("$150.00", message)
        self.assertIn("Total Value: $15000.00", message)
        
        # Verify Time Update
        self.assertEqual(new_check_time, fill_time)
        print("-> Time updated correctly.")

if __name__ == '__main__':
    unittest.main()
