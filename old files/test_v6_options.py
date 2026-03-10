import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime, timedelta
# Import the class and global
from alpaca_bot_v6 import OptionsAgent, ENABLE_OPTIONS


class TestOptionsAgent(unittest.TestCase):
    def test_feature_flag_off(self):
        print("\n=== Testing Options Feature Flag ===")
        print(f"ENABLE_OPTIONS is: {ENABLE_OPTIONS}")
        self.assertFalse(ENABLE_OPTIONS) # MUST be False by default

    @patch('yfinance.Ticker')
    def test_get_contract(self, MockTicker):
        print("\n=== Testing Options Selection Logic ===")
        agent = OptionsAgent()
        
        # 1. Mock Ticker & Expirations
        mock_tk = MagicMock()
        # Create dates: 10 days out, 30 days out (Target), 60 days out
        d1 = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        d2 = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        d3 = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
        mock_tk.options = [d1, d2, d3]
        
        # 2. Mock Option Chain (DataFrame)
        # Columns: contractSymbol, lastTradeDate, strike, lastPrice, bid, ask, change, percentChange, volume, openInterest, impliedVolatility, inTheMoney, contractSize, currency
        data = {
            'contractSymbol': ['AMD_CALL_1', 'AMD_CALL_2', 'AMD_CALL_3'],
            'strike': [95.0, 100.0, 105.0], # Price is 100
            'lastPrice': [5.5, 3.0, 1.2],
            'volume': [1000, 500, 20],   # CALL_3 has low volume (should be filtered)
            'openInterest': [2000, 1000, 50],
            'impliedVolatility': [0.4, 0.4, 0.4]
        }
        df = pd.DataFrame(data)
        
        mock_chain = MagicMock()
        mock_chain.calls = df
        mock_chain.puts = df # Simplify
        mock_tk.option_chain.return_value = mock_chain
        
        # Mock History (Current Price = 100)
        hist_df = pd.DataFrame({'Close': [100.0]})
        mock_tk.history.return_value = hist_df
        
        MockTicker.return_value = mock_tk
        
        # 3. Execute
        # Bullish Signal -> Expect Call
        res = agent.get_optimal_contract("AMD", sentiment_score=0.8, technical_signal="BUY")
        
        # 4. Verify
        print(f"Result: {res}")
        self.assertIsNotNone(res)
        self.assertEqual(res['type'], 'call')
        self.assertEqual(res['expiry'], d2) # Should pick 30 day
        # Should pick Strike 100 (ATM) or 95?
        # Logic: Sort by distance to price. 100 is dist 0. 95 is dist 5.
        # Volume/OI filter: CALL_3 (105) volume=20 (Filtered out? Limit is 50).
        # So it chooses between 95 and 100. 
        # 100 is closer.
        self.assertEqual(res['strike'], 100.0)
        self.assertEqual(res['contract_symbol'], 'AMD_CALL_2')
        print("✅ Correctly selected Liquid ATM Call 30 days out.")


    @patch('alpaca_bot_v6.ENABLE_OPTIONS', True) # Force Enable for this test
    @patch('alpaca_bot_v6.send_discord_alert')
    def test_risk_manager(self, mock_alert):
        print("\n=== Testing Options Risk Manager ===")
        # Setup Manager
        mock_client = MagicMock()
        with patch('alpaca_bot_v6.SentimentAgent'), \
             patch('alpaca_bot_v6.FundamentalAgent'), \
             patch('alpaca_bot_v6.TechnicalAgent') as MockPropTech, \
             patch('alpaca_bot_v6.DayTradingAgent'), \
             patch('alpaca_bot_v6.OptionsAgent'):
             
             from alpaca_bot_v6 import PortfolioManager
             manager = PortfolioManager(mock_client)
             
             # Mock Positions
             # 1. OPTION LOSER (-40%) -> Should Stop Loss
             # 2. OPTION WINNER (+60%) -> Should Take Profit
             # 3. OPTION NEUTRAL (+10%) -> Should Check Smart Exit
             
             pos1 = MagicMock()
             pos1.symbol = "AMD230616C00100000" # Call
             pos1.asset_class = 'us_option'
             pos1.qty = 10
             pos1.unrealized_plpc = -0.40 # -40%
             
             pos2 = MagicMock()
             pos2.symbol = "NVDA230616P00200000" # Put
             pos2.asset_class = 'us_option'
             pos2.qty = 5
             pos2.unrealized_plpc = 0.60 # +60%
             
             pos3 = MagicMock()
             pos3.symbol = "TSLA230616C00200000" # Call
             pos3.asset_class = 'us_option'
             pos3.qty = 1
             pos3.unrealized_plpc = 0.10 # +10%
             
             mock_client.get_all_positions.return_value = [pos1, pos2, pos3]
             
             # Mock Smart Exit for TSLA (Call)
             # Technical Agent says SELL -> Smart Exit Trigger
             manager.technical_agent = MockPropTech.return_value
             manager.technical_agent.analyze.return_value = {'signal': 'SELL', 'reason': 'Trend Broken'}
             
             # EXECUTE
             manager.manage_options_risk()
             
             # VERIFY
             # 1. Stop Loss
             mock_client.close_position.assert_any_call("AMD230616C00100000")
             print("✅ Stop Loss Triggered for AMD (-40%)")
             
             # 2. Take Profit
             mock_client.close_position.assert_any_call("NVDA230616P00200000")
             print("✅ Take Profit Triggered for NVDA (+60%)")
             
             # 3. Smart Exit
             # TSLA Underlying is TSLA. Agent says SELL. Call should be closed.
             mock_client.close_position.assert_any_call("TSLA230616C00200000")
             print("✅ Smart Exit Triggered for TSLA (Tech Reversal)")

if __name__ == '__main__':
    unittest.main()

