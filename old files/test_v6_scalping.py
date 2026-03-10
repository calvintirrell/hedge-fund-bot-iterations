import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v6 import PortfolioManager

from alpaca.trading.enums import OrderType, OrderSide, OrderClass

class TestScalpingLogic(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        # Mock initial account state
        self.mock_account = MagicMock()
        self.mock_account.buying_power = '100000'
        self.mock_account.equity = '100000'
        self.mock_client.get_account.return_value = self.mock_account
        
        # Instantiate Manager (mocks agents via patch in test methods usually, short cutting here for simplicity)
        with patch('alpaca_bot_v6.SentimentAgent'), \
             patch('alpaca_bot_v6.FundamentalAgent'), \
             patch('alpaca_bot_v6.TechnicalAgent'), \
             patch('alpaca_bot_v6.DayTradingAgent'):
             self.manager = PortfolioManager(self.mock_client)
        
        # Mock get_position_counts to standard empty state
        self.manager.get_position_counts = MagicMock(return_value={'scalp': 0, 'swing': 0})

    def test_scalp_trigger(self):
        print("\n=== Testing Scalp Trigger ===")
        symbol = "TEST"
        
        # 1. Setup: NO Position
        self.mock_client.get_open_position.side_effect = Exception("No position")
        
        # 2. Mock DayTradingAgent to return BUY
        mock_scalp_res = {
            'signal': 'BUY',
            'price': 100.0,
            'reason': 'RSI Oversold'
        }
        self.manager.day_trading_agent.analyze.return_value = mock_scalp_res
        
        # 3. Execute
        with patch('alpaca_bot_v6.send_discord_alert'):
            self.manager.execute_strategy(symbol)
            
        # 4. Verify Order Submission
        self.mock_client.submit_order.assert_called()
        call_args = self.mock_client.submit_order.call_args
        order_request = call_args.kwargs['order_data']
        
        print(f"✅ Order Submitted: {order_request.qty} shares @ $100 (Type: {order_request.order_class})")
        
        # Expect 100 shares ($10,000 target)
        self.assertEqual(int(order_request.qty), 100)
        
        # Verify OTO
        self.assertEqual(order_request.order_class, OrderClass.OTO)
        
        # Verify Initial Stop (-2%)
        self.assertEqual(order_request.stop_loss.stop_price, 98.00)
        
        print("✅ OTO Params Confirmed.")

    def test_swing_fallback(self):
        print("\n=== Testing Swing Strategy Fallback ===")
        symbol = "TEST"
        
        self.mock_client.get_open_position.side_effect = Exception("No position")
        self.manager.day_trading_agent.analyze.return_value = {'signal': 'WAIT'}
        self.manager.technical_agent.analyze.return_value = {'signal': 'WAIT', 'reason': 'Trend Down'}
        
        self.manager.execute_strategy(symbol)
        
        self.mock_client.submit_order.assert_not_called()
        print("✅ No Order.")

if __name__ == '__main__':
    unittest.main()
