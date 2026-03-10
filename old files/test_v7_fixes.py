import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
import sys
import os

# Suppress logging during tests
logging.basicConfig(level=logging.CRITICAL)

# Mock libs to enable V7 Import
sys.modules['pandas_ta'] = MagicMock()

mock_alpaca = MagicMock()
sys.modules['alpaca'] = mock_alpaca
sys.modules['alpaca.trading'] = mock_alpaca
sys.modules['alpaca.trading.client'] = mock_alpaca
sys.modules['alpaca.trading.requests'] = mock_alpaca
sys.modules['alpaca.trading.enums'] = mock_alpaca

mock_genai = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.generativeai'] = mock_genai

# Import the V7 module
try:
    import alpaca_bot_v7 as bot
except ImportError:
    sys.path.append(os.getcwd())
    import alpaca_bot_v7 as bot

class TestV7Fixes(unittest.TestCase):
    
    def setUp(self):
        # Monkey-patch pandas DataFrame to support .ta accessor
        if not hasattr(pd.DataFrame, 'ta'):
             pd.DataFrame.ta = property(lambda self: MagicMock())

        self.tech_agent = bot.TechnicalAgent()
        self.fund_agent = bot.FundamentalAgent()
        self.dt_agent = bot.DayTradingAgent()
        
        self.mock_client = MagicMock()
        self.manager = bot.PortfolioManager(self.mock_client)
        # Inject agents
        self.manager.technical_agent = self.tech_agent
        self.manager.fundamental_agent = self.fund_agent
        self.manager.day_trading_agent = self.dt_agent
        self.manager.sentiment_agent = MagicMock()
        self.manager.options_agent = MagicMock() # V7 specific

    # =========================================================================
    # TEST 1: Technical Data Fetching (V7 updated)
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_tech_agent_fetch_data_robustness(self, mock_ticker_cls):
        print("\n[TEST V7] TechnicalAgent Data Fetching...")
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        # Test MultiIndex Flattening
        dates = pd.date_range(start='2024-01-01', periods=10, freq='1h')
        iterables = [['close'], ['SPY']]
        columns = pd.MultiIndex.from_product(iterables)
        df_multi = pd.DataFrame(np.random.rand(10, 1), index=dates, columns=columns)
        mock_ticker.history.return_value = df_multi
        
        df_clean = self.tech_agent.fetch_data('SPY', datetime.now(), '1h')
        self.assertIsNotNone(df_clean)
        self.assertIn('close', df_clean.columns)
        print(" -> passed: MultiIndex flattened.")

    # =========================================================================
    # TEST 2: Fundamental Safety
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_fundamental_agent_safety(self, mock_ticker_cls):
        print("\n[TEST V7] FundamentalAgent Safety...")
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        # Scenario: info is None
        mock_ticker.info = None
        res = self.fund_agent.analyze('MSFT')
        self.assertEqual(res['score'], 5)
        print(" -> passed: info=None check works.")

    # =========================================================================
    # TEST 3: DayTrading Agent (Gamma Sniper Core)
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_day_trading_agent_robust(self, mock_ticker_cls):
        print("\n[TEST V7] DayTradingAgent Robustness...")
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        dates = pd.date_range(end=datetime.now(), periods=60, freq='5min')
        df = pd.DataFrame({
            'Close': np.random.rand(60) * 100,
            'Volume': np.random.rand(60) * 1000
        }, index=dates)
        mock_ticker.history.return_value = df
        
        res = self.dt_agent.analyze('AMD')
        self.assertIn(res['signal'], ['BUY', 'WAIT'])
        print(" -> passed: DayTradingAgent uses history() and handles columns.")

    # =========================================================================
    # TEST 4: Portfolio Manager Sanity Check (Stock Buy)
    # =========================================================================
    def test_order_validation_logic(self):
        print("\n[TEST V7] Order Validation...")
        mock_account = MagicMock()
        mock_account.equity = '100000'
        mock_account.buying_power = '200000'
        self.mock_client.get_account.return_value = mock_account
        self.mock_client.get_open_position.side_effect = Exception("Not found")

        # Mock Agents to return BUY with INVALID STOP logic
        self.tech_agent.analyze = MagicMock(return_value={
            'signal': 'BUY',
            'close': 100.0,
            'atr': -5.0, # Negative ATR -> Stop > Price
            'vol_confirmed': True
        })
        self.fund_agent.analyze = MagicMock(return_value={'score': 8, 'beta': 1.0})
        self.manager.sentiment_agent.analyze = MagicMock(return_value={'score': 0.8})
        
        # Disable V7 Options Logic for this test to hit Stock logic
        with patch('alpaca_bot_v7.ENABLE_OPTIONS', False):
            # Also ensure scalping doesn't trigger
            self.dt_agent.analyze = MagicMock(return_value={'signal': 'WAIT'})
            
            self.manager.execute_strategy('TEST', check_swing=True)
            
        self.mock_client.submit_order.assert_not_called()
        print(" -> passed: Invalid order aborted.")

if __name__ == '__main__':
    unittest.main()
