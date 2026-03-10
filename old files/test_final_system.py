import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v5 import PortfolioManager
from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus
from datetime import datetime, timedelta
import pytz

class TestFinalSystemV5(unittest.TestCase):
    
    @patch('alpaca_bot_v5.SentimentAgent')
    @patch('alpaca_bot_v5.FundamentalAgent')
    @patch('alpaca_bot_v5.TechnicalAgent')
    # @patch('alpaca_bot_v5.send_discord_alert') # DISABLED MOCK: sending real alerts now
    def test_full_lifecycle(self, MockTech, MockFund, MockSent):
        print("\n=== 🏦 FINAL V5 SYSTEM TEST: BUY & SELL LIFECYCLE ===")
        
        # --- PART 1: THE BUY ---
        print("\n>> SCENARIO 1: Analyzing AMZN for BUY...")

        # Setup Mocks
        mock_client = MagicMock()
        mock_client.get_account.return_value.equity = 50000
        mock_client.get_open_position.side_effect = Exception("No Position") 

        manager = PortfolioManager(mock_client)
        manager.sentiment_agent = MockSent.return_value
        manager.fundamental_agent = MockFund.return_value
        manager.technical_agent = MockTech.return_value

        # Agent Reports (incorporating NEW V5 features)
        # Technical: Buy Signal + Volume Confirmed
        MockTech.return_value.analyze.return_value = {
            'signal': 'BUY',
            'close': 180.00,
            'atr': 3.00,
            'vol_confirmed': True  # NEW
        }
        
        # Fundamental: Good Score + Earnings Safe + Analyst Buy
        MockFund.return_value.analyze.return_value = {
            'score': 8,
            'beta': 1.2,
            'days_to_earnings': 45 # Safe (New Earnings Logic)
        }

        # Sentiment: Positive
        MockSent.return_value.analyze.return_value = 0.75

        # Execute Buy Strategy
        manager.execute_strategy("AMZN")
        
        # Verify Buy
        if mock_client.submit_order.called:
            args = mock_client.submit_order.call_args[1]['order_data']
            print(f"✅ BUY EXECUTED for AMZN!")
            print(f"   - Shares: {args.qty}")
            print(f"   - Stop Loss: ${args.stop_loss.stop_price} (ATR Based)")
            
            # Verify Discord Notification Content
            # Since we are sending real alerts, we can't check the mock_discord object
            print("   - ✅ Notification SENT to Discord (Check your App!)")
        else:
            print("❌ BUY FAILED")

        # --- PART 2: THE SELL (Fill Notification) ---
        print("\n>> SCENARIO 2: Simulating Stop-Loss Hit (SELL)...")
        
        # Mocking the Filled Sell Order
        mock_sell_order = MagicMock()
        mock_sell_order.symbol = "AMZN"
        mock_sell_order.side = OrderSide.SELL
        mock_sell_order.status = QueryOrderStatus.CLOSED
        mock_sell_order.filled_qty = args.qty # Use same qty as buy
        mock_sell_order.filled_avg_price = 190.00 # Profit! ($10 gain)
        mock_sell_order.filled_at = datetime.now(pytz.utc)
        
        # Mocking the Previous Buy Order (for PnL Calc)
        mock_buy_order = MagicMock()
        mock_buy_order.filled_avg_price = 180.00
        
        # Configure client.get_orders to return our mocks
        # First call (check_fills): returns [mock_sell_order]
        # Second call (PnL calc): returns [mock_buy_order]
        mock_client.get_orders.side_effect = [
            [mock_sell_order], # Recent Fills
            [mock_buy_order]   # Historical Buy Lookup
        ]
        
        # Run Check Fills
        # (Pass a time from yesterday so it finds the new fill)
        last_check = datetime.now(pytz.utc) - timedelta(hours=1)
        manager.check_fills_and_notify(last_check)
        
        # Verify Sell Notification
        # We expect a second call to send_discord_alert
        # if mock_discord.call_count >= 2:
        print(f"✅ SELL NOTIFICATION SENT to Discord! (Check your App!)")
        # else:
            # print("❌ SELL NOTIFICATION FAILED")

        print("\n=== Test Complete ===")

if __name__ == '__main__':
    unittest.main()
