import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import os
from dotenv import load_dotenv
from alpaca_bot_v4 import check_strategy

# Load Env to get the REAL Webhook URL
load_dotenv()

class TestIntegrationV4(unittest.TestCase):

    @patch('alpaca_bot_v4.fetch_and_prepare_data')
    def test_full_buy_flow_with_discord(self, mock_fetch):
        """
        Simulates a PERFECT BUY scenario to trigger the Discord Alert.
        """
        print("\n=== STARTING INTEGRATION TEST ===")
        print("Goal: Trigger a REAL Discord Notification.")
        
        # 1. Mock Trading Client
        mock_client = MagicMock()
        mock_client.get_account.return_value.trading_blocked = False
        mock_client.get_account.return_value.equity = 100000 # $100k Equity
        mock_client.get_open_position.side_effect = Exception("No position") # No position held
        
        # 2. Mock Data for ALL Timeframes
        # We need 3 calls: Daily, Hourly, Intraday
        
        # 2. Mock Data using MagicMock (Bypass pandas_ta entirely)
        
        # A. Daily Data (UP Trend)
        daily_mock = MagicMock()
        daily_mock.__len__.return_value = 201
        daily_mock.iloc.__getitem__.return_value = {
            'close': 150,
            'SMA_50': 160,
            'SMA_200': 150
        }
        daily_mock.ta.sma = MagicMock()
        
        # B. Hourly Data (UP Trend)
        hourly_mock = MagicMock()
        hourly_mock.__len__.return_value = 201
        hourly_mock.iloc.__getitem__.return_value = {
            'close': 150,
            'SMA_50': 155,
            'SMA_200': 150
        }
        hourly_mock.ta.sma = MagicMock()
        # We can just mock the columns directly if we mock the .ta accessor, 
        # but simpler to just mock the values AFTER calculation? 
        # No, let's just use the same trick or just mock the ta calls to do nothing?
        # Actually, for Intraday, the logic is:
        # intraday_df.ta.sma...
        # Let's just make the price constantly rising?
        intraday_mock = MagicMock()
        intraday_mock.__len__.return_value = 100
        intraday_mock.empty = False
        # Mock .dropna() to return self (chaining)
        intraday_mock.dropna.return_value = intraday_mock
        
        # Mock .iloc[-1] with PERFECT signals
        intraday_mock.iloc.__getitem__.return_value = {
            'close': 155,      # Price
            'SMA_20': 152,     # Fast
            'SMA_50': 150,     # Slow (Fast > Slow)
            'RSI_14': 50,      # Not Overbought
            'VWAP_D': 154      # Price > VWAP
        }
        # Mock .ta methods
        intraday_mock.ta.sma = MagicMock()
        intraday_mock.ta.rsi = MagicMock()
        intraday_mock.ta.vwap = MagicMock()
        
        # Set return values
        mock_fetch.side_effect = [daily_mock, hourly_mock, intraday_mock]
        
        # 3. Run Strategy
        print("Running strategy check for 'AAPL'...")
        check_strategy(mock_client, "AAPL")
        
        # 4. Verify Order Submission (Mocked)
        mock_client.submit_order.assert_called()
        print("SUCCESS: Order 'submitted' to Alpaca (Mocked).")
        
        # 5. Verify Discord (Real)
        # The check_strategy function calls send_discord_alert internally.
        # If you see the message in Discord, it worked.
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        if webhook_url:
            print(f"Discord Webhook URL found: {webhook_url[:10]}...")
            print("CHECK YOUR DISCORD CHANNEL NOW!")
        else:
            print("WARNING: No DISCORD_WEBHOOK_URL found in .env. You won't see an alert.")

if __name__ == '__main__':
    unittest.main()
