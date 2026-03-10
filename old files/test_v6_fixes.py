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

# Mock pandas_ta to avoid dependency issues during test
sys.modules['pandas_ta'] = MagicMock()

# Mock Alpaca to avoid import errors (since we are testing logic not API)
mock_alpaca = MagicMock()
sys.modules['alpaca'] = mock_alpaca
sys.modules['alpaca.trading'] = mock_alpaca
sys.modules['alpaca.trading.client'] = mock_alpaca
sys.modules['alpaca.trading.requests'] = mock_alpaca
sys.modules['alpaca.trading.enums'] = mock_alpaca

# Mock Google Generative AI
mock_genai = MagicMock()
sys.modules['google'] = MagicMock()
sys.modules['google.generativeai'] = mock_genai

# Import the module to test
# Assuming alpaca_bot_v6.py is in the same directory
try:
    import alpaca_bot_v6 as bot
except ImportError:
    # Try adding current dir to path
    sys.path.append(os.getcwd())
    import alpaca_bot_v6 as bot

class TestV6Fixes(unittest.TestCase):
    
    def setUp(self):
        # Monkey-patch pandas DataFrame to support .ta accessor
        # This mocks the pandas_ta library extension
        if not hasattr(pd.DataFrame, 'ta'):
             pd.DataFrame.ta = property(lambda self: MagicMock())

        self.tech_agent = bot.TechnicalAgent()
        self.fund_agent = bot.FundamentalAgent()
        self.dt_agent = bot.DayTradingAgent()
        
        # Mock Client for PortfolioManager
        self.mock_client = MagicMock()
        self.manager = bot.PortfolioManager(self.mock_client)
        # Inject agents into manager to control them
        self.manager.technical_agent = self.tech_agent
        self.manager.fundamental_agent = self.fund_agent
        self.manager.day_trading_agent = self.dt_agent
        self.manager.sentiment_agent = MagicMock() # Mock sentiment to pass checks

    # =========================================================================
    # TEST CASE 1: DataFrame Cleaning (The "Multiple Columns" Error)
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_tech_agent_fetch_data_robustness(self, mock_ticker_cls):
        print("\n[TEST] Verifying TechnicalAgent Data Fetching...")
        
        # Setup Mock Ticker and History
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        # Scenario A: MultiIndex Columns (The main culprit)
        # Simulating: yf.download returning ('Close', 'SPY') structure
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
        iterables = [['close', 'volume'], ['SPY']]
        columns = pd.MultiIndex.from_product(iterables, names=['Price', 'Ticker'])
        data = np.random.rand(100, 2)
        df_multi = pd.DataFrame(data, index=dates, columns=columns)
        
        mock_ticker.history.return_value = df_multi
        
        # Run method
        df_clean = self.tech_agent.fetch_data('SPY', datetime.now(), '1h')
        
        # Assertions
        self.assertIsNotNone(df_clean, "Stored DataFrame shouldn't be None")
        self.assertFalse(isinstance(df_clean.columns, pd.MultiIndex), "Index should be flattened")
        self.assertIn('close', df_clean.columns, "Column 'close' should be present")
        print(" -> passed: MultiIndex flattened.")

        # Scenario B: Duplicate Columns
        # Simulating: yf returning 'Close' twice
        df_dup = pd.DataFrame({
            'Close': np.random.rand(100),
            'close': np.random.rand(100), # Duplicate case-insensitive
            'Volume': np.random.rand(100)
        }, index=dates)
        mock_ticker.history.return_value = df_dup
        
        df_clean_2 = self.tech_agent.fetch_data('SPY', datetime.now(), '1h')
        
        # Assertions
        # The fix should duplicate columns. drop_duplicates handled via loc[:,~duplicated]
        # Our code lowercases first, so 'Close' and 'close' become 'close', 'close'.
        # Then ~duplicated() keeps only the first one.
        self.assertTrue(df_clean_2.columns.is_unique, "Columns should be unique")
        self.assertIn('close', df_clean_2.columns)
        print(" -> passed: duplicate columns handled.")

    # =========================================================================
    # TEST CASE 2: Fundamental Analysis Safety (The "NoneType" Error)
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_fundamental_agent_safety(self, mock_ticker_cls):
        print("\n[TEST] Verifying FundamentalAgent Safety...")
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        # Scenario A: info is None
        mock_ticker.info = None
        
        # Run
        res = self.fund_agent.analyze('MSFT')
        
        # Assert
        self.assertEqual(res['score'], 5, "Should return neutral score 5 on missing info")
        print(" -> passed: info=None handled safely.")
        
        # Scenario B: calendar is broken
        mock_ticker.info = {'trailingPE': 15} # Valid info
        # Simulate calendar access raising exception or being None
        type(mock_ticker).calendar = property(lambda self: None) 
        
        res2 = self.fund_agent.analyze('MSFT')
        self.assertEqual(res2['days_to_earnings'], 999, "Should default to 999 on missing calendar")
        print(" -> passed: calendar=None handled safely.")

    # =========================================================================
    # TEST CASE 3: DayTrading Agent Robustness
    # =========================================================================
    @patch('yfinance.Ticker')
    def test_day_trading_agent_columns(self, mock_ticker_cls):
        print("\n[TEST] Verifying DayTradingAgent Data...")
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        
        # Mock 5m Data with weird casing
        dates = pd.date_range(end=datetime.now(), periods=60, freq='5min')
        df = pd.DataFrame({
            'Close': np.random.rand(60) * 100,
            'Volume': np.random.rand(60) * 1000
        }, index=dates)
        
        # MOCK pandas_ta ACCESSOR MANUALLY (Handled in setUp)
        # We assume the code calls df.ta.rsi(...) etc.
        # We just need it not to crash.
        
        mock_ticker.history.return_value = df
        
        res = self.dt_agent.analyze('IBM')
        
        self.assertNotEqual(res['signal'], 'ERROR', "Should not return ERROR signal")
        self.assertIn(res['signal'], ['BUY', 'WAIT'])
        print(" -> passed: DayTradingAgent handled DataFrame correctly.")

    # =========================================================================
    # TEST CASE 4: Order Validation (The "Stop > Price" Error)
    # =========================================================================
    def test_order_validation_logic(self):
        print("\n[TEST] Verifying PortfolioManager Order Validation...")
        
        # Mock Account
        mock_account = MagicMock()
        mock_account.equity = '100000'
        mock_account.buying_power = '200000'
        self.mock_client.get_account.return_value = mock_account
        
        # FORCE NO OPEN POSITION so we enter Buy Logic
        # get_open_position raises exception if not found in Alpaca or returns 404
        self.mock_client.get_open_position.side_effect = Exception("Position not found")

        # Mock Agents to return a BUY signal
        # Technical: Returns a price that is inexplicably LOWER than the stop we will check?
        # Actually logic is: Stop = Price - (ATR * 2).
        # We want to simulate a case where logic fails or data is weird.
        # But specifically, we want to test that if we somehow calculate stop >= price, it bails.
        
        # Let's force a scenario by mocking technical_agent.analyze
        self.tech_agent.analyze = MagicMock(return_value={
            'signal': 'BUY',
            'close': 100.0,
            'atr': -5.0, # Negative ATR logic trap
            'vol_confirmed': True
        })
        
        self.fund_agent.analyze = MagicMock(return_value={'score': 8, 'beta': 1.0})
        self.manager.sentiment_agent.analyze = MagicMock(return_value={'score': 0.8})
        
        # Execute
        self.manager.execute_strategy('TEST_SYM', check_swing=True)
        
        # Assert
        # logic: stop_price = 100 - (-5 * 2) = 110.
        # Check: 110 >= 100 is True.
        # Should Log Error and NOT call submit_order.
        
        self.mock_client.submit_order.assert_not_called()
        print(" -> passed: Aborted trade where Stop Price > Entry Price.")

if __name__ == '__main__':
    unittest.main()
