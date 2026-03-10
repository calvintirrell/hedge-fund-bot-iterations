import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add local directory to path to import alpaca_bot_v6
sys.path.append(os.getcwd())
sys.path.append("/Users/ct/Documents/Code Projects/alpaca_bot")

# Mock the dependencies before importing the bot to avoid requiring API keys
with patch.dict(os.environ, {
    "API_KEY": "TEST_KEY", 
    "SECRET_KEY": "TEST_SECRET", 
    "GEMINI_API_KEY": "TEST_GEMINI", 
    "DISCORD_WEBHOOK_URL": "TEST_WEBHOOK"
}):
    # Mock modules that might be missing
    sys.modules['vaderSentiment'] = MagicMock()
    sys.modules['vaderSentiment.vaderSentiment'] = MagicMock()
    # sys.modules['google'] = MagicMock() # Do not mock root google, it breaks yfinance protobuf
    sys.modules['google.generativeai'] = MagicMock()
    
    import alpaca_bot_v6

class TestSellLogic(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.manager = alpaca_bot_v6.PortfolioManager(self.mock_client)
        
        # Mock dependencies
        self.manager.technical_agent = MagicMock()
        self.manager.sentiment_agent = MagicMock()
        self.manager.fundamental_agent = MagicMock()
        self.manager.day_trading_agent = MagicMock()
        self.manager.options_agent = MagicMock()

    def create_mock_position(self, symbol, entry_price, current_price):
        position = MagicMock()
        position.symbol = symbol
        position.avg_entry_price = str(entry_price)
        position.current_price = str(current_price)
        position.qty = "10"
        position.market_value = str(float(current_price) * 10)
        return position

    def test_smart_exit_take_profit(self):
        """Test Smart Exit: Profitable + Bearish Technicals -> SELL"""
        symbol = "MDB"
        entry_price = 100.0
        current_price = 105.0 # +5% Profit
        
        # Mock Position
        self.mock_client.get_open_position.return_value = self.create_mock_position(symbol, entry_price, current_price)
        
        # Mock Technicals: WAIT + Bearish Reason
        self.manager.technical_agent.analyze.return_value = {
            'signal': 'WAIT',
            'reason': 'MACD Bearish', # <-- Trigger
            'close': current_price,
            'atr': 2.0
        }
        
        self.manager.execute_strategy(symbol, check_swing=True)
        
        # Verify Close Position was called
        self.mock_client.close_position.assert_called_with(symbol)
        print("\n✅ Test Passed: Smart Exit triggered on MACD Bearish (+5% gain)")

    def test_hard_take_profit_10_percent(self):
        """Test Hard Take Profit: >10% Gain -> SELL IMMEDIATELY"""
        symbol = "NVDA"
        entry_price = 100.0
        current_price = 112.0 # +12% Profit
        
        # Mock Position
        self.mock_client.get_open_position.return_value = self.create_mock_position(symbol, entry_price, current_price)
        
        # Mock Technicals: BUY (Even if technicals are good, we take profit!)
        self.manager.technical_agent.analyze.return_value = {
            'signal': 'BUY',
            'reason': 'Strong Uptrend',
            'close': current_price,
            'atr': 2.0
        }
        
        self.manager.execute_strategy(symbol, check_swing=True)
        
        # Verify Close Position was called
        self.mock_client.close_position.assert_called_with(symbol)
        print("\n✅ Test Passed: Hard Take Profit triggered at +12% gain")

    def test_hold_normal_condition(self):
        """Test Hold: Profitable but Technicals are Neutral/Good -> HOLD"""
        symbol = "AAPL"
        entry_price = 100.0
        current_price = 105.0 # +5% Profit
        
        # Mock Position
        self.mock_client.get_open_position.return_value = self.create_mock_position(symbol, entry_price, current_price)
        
        # Mock Technicals: BUY (Bullish)
        self.manager.technical_agent.analyze.return_value = {
            'signal': 'BUY',
            'reason': 'Uptrend',
            'close': current_price,
            'atr': 2.0
        }
        
        self.manager.execute_strategy(symbol, check_swing=True)
        
        # Verify Close Position was NOT called
        self.mock_client.close_position.assert_not_called()
        print("\n✅ Test Passed: Position HELD (Bullish Technicals, +5% gain)")
        
    def test_hold_no_profit(self):
        """Test Hold: Loss Position -> HOLD (Wait for Stop Loss or Recovery)"""
        symbol = "TSLA"
        entry_price = 100.0
        current_price = 95.0 # -5% Loss
        
        # Mock Position
        self.mock_client.get_open_position.return_value = self.create_mock_position(symbol, entry_price, current_price)
        
        # Mock Technicals: WAIT (Bearish)
        self.manager.technical_agent.analyze.return_value = {
            'signal': 'WAIT',
            'reason': 'MACD Bearish',
            'close': current_price,
            'atr': 2.0
        }
        
        self.manager.execute_strategy(symbol)
        
        # Verify Close Position was NOT called (Bot adds on dips if conditions met, or holds. Doesn't panic sell stocks unless SL hit)
        # Note: In V6 logic, if price < entry, it logs "EVALUATING TO ADD MORE". It does NOT sell.
        self.mock_client.close_position.assert_not_called()
        print("\n✅ Test Passed: Loss Position HELD (Not panic selling via Smart Exit)")

if __name__ == '__main__':
    unittest.main()
