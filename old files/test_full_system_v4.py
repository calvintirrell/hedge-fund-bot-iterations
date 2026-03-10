import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import pytz
import pandas as pd
import os
from dotenv import load_dotenv
from alpaca_bot_v4 import check_strategy, check_for_fills
from alpaca.trading.enums import OrderSide

# Load Env for Real Discord URL
load_dotenv()

class TestFullSystemV4(unittest.TestCase):

    @patch('alpaca_bot_v4.fetch_and_prepare_data')
    def test_buy_and_sell_alerts(self, mock_fetch):
        """
        Simulates a full cycle:
        1. Detects a BUY signal for NVDA -> Sends BUY Alert.
        2. Detects a filled SELL order for AAPL -> Sends SELL Alert.
        """
        print("\n=== STARTING FULL SYSTEM SIMULATION ===")
        print("Goal: Trigger REAL Buy and Sell Alerts in Discord.")
        
        # --- PART 1: BUY SIGNAL (NVDA) ---
        print("\n[1/2] Simulating BUY Signal for NVDA...")
        
        mock_client = MagicMock()
        mock_client.get_account.return_value.trading_blocked = False
        mock_client.get_account.return_value.equity = 100000
        mock_client.get_open_position.side_effect = Exception("No position") 

        # Mock Data (Perfect Buy Setup)
        # Daily
        daily_mock = MagicMock()
        daily_mock.__len__.return_value = 201
        daily_mock.iloc.__getitem__.return_value = {'close': 100, 'SMA_50': 110, 'SMA_200': 100} # UP
        daily_mock.ta.sma = MagicMock()
        
        # Hourly
        hourly_mock = MagicMock()
        hourly_mock.__len__.return_value = 201
        hourly_mock.iloc.__getitem__.return_value = {'close': 100, 'SMA_50': 105, 'SMA_200': 100} # UP
        hourly_mock.ta.sma = MagicMock()
        
        # Intraday
        intraday_mock = MagicMock()
        intraday_mock.__len__.return_value = 100
        intraday_mock.empty = False
        intraday_mock.dropna.return_value = intraday_mock
        intraday_mock.iloc.__getitem__.return_value = {
            'close': 105, 'SMA_20': 102, 'SMA_50': 100, 'RSI_14': 50, 'VWAP_D': 104
        }
        intraday_mock.ta.sma = MagicMock()
        intraday_mock.ta.rsi = MagicMock()
        intraday_mock.ta.vwap = MagicMock()
        
        mock_fetch.side_effect = [daily_mock, hourly_mock, intraday_mock]
        
        # Run Strategy
        check_strategy(mock_client, "NVDA")
        
        # Verify Buy Order
        mock_client.submit_order.assert_called()
        print("SUCCESS: NVDA Buy Signal Processed.")
        
        # --- PART 2: SELL NOTIFICATION (AAPL) ---
        print("\n[2/2] Simulating SELL Fill for AAPL...")
        
        # Setup Times
        now = datetime.now(pytz.utc)
        last_check = now - timedelta(minutes=10)
        fill_time = now - timedelta(minutes=1) # Filled 1 min ago
        
        # Mock Filled Order
        mock_order = MagicMock()
        mock_order.side = OrderSide.SELL
        mock_order.filled_at = fill_time
        mock_order.symbol = "AAPL"
        mock_order.filled_qty = "50"
        mock_order.filled_avg_price = "180.00"
        
        # Configure get_orders to return the Sell Order first, then the Buy Order for PnL
        # First call: get_orders(status='closed', limit=50...) -> Returns [mock_order] (The Sell)
        # Second call: get_orders(status='closed', symbol='AAPL', side='buy'...) -> Returns [mock_buy]
        
        mock_buy = MagicMock()
        mock_buy.filled_avg_price = "150.00" # Bought at $150
        
        def get_orders_side_effect(**kwargs):
            # Check if 'filter' argument is passed (New V4 logic)
            filter_obj = kwargs.get('filter')
            if filter_obj and hasattr(filter_obj, 'side') and filter_obj.side == OrderSide.BUY:
                return [mock_buy]
            
            # Fallback for old logic or direct kwargs (if any)
            if kwargs.get('side') == OrderSide.BUY:
                return [mock_buy]
                
            # Otherwise (checking for fills), return the mock sell
            return [mock_order]
            
        mock_client.get_orders.side_effect = get_orders_side_effect
        
        # Run Check Fills
        check_for_fills(mock_client, last_check)
        
        print("SUCCESS: AAPL Sell Notification Processed.")
        print("\n=== SIMULATION COMPLETE ===")
        print("Check your Discord for TWO messages:")
        print("1. 🚀 BUY NVDA...")
        print("2. 💰 SOLD AAPL... (With Profit: $1500.00)")

if __name__ == '__main__':
    unittest.main()
