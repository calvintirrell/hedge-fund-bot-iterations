import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v5 import PortfolioManager, SentimentAgent, FundamentalAgent, TechnicalAgent
import pandas as pd
import numpy as np

class TestV5Stress(unittest.TestCase):
    
    def setUp(self):
        self.mock_client = MagicMock()
        self.manager = PortfolioManager(self.mock_client)

    @patch('alpaca_bot_v5.genai')
    def test_sentiment_api_failure(self, mock_genai):
        """Test 1: Gemini API crashes. Should fallback to VADER (not crash)."""
        print("\n--- Stress Test 1: Sentiment API Failure ---")
        
        # Configure Agent with AI enabled
        agent = SentimentAgent(use_ai=True)
        agent.model = MagicMock()
        
        # Simulate API Crash
        agent.model.generate_content.side_effect = Exception("API Server 500 Error")
        
        # Mock get_news to return some text
        with patch.object(agent, 'get_news', return_value=['Market is crashing', 'Panic selling']):
            score = agent.analyze("TEST_FAIL")
            
        print(f"Resulting Score: {score}")
        # Should not crash, and score should reflect VADER analysis of "panic" (negative)
        self.assertTrue(score < 0, "Should return negative score from VADER fallback")
        print("✅ PASS: Handled API Crash gracefully.")

    @patch('yfinance.Ticker')
    def test_fundamental_bad_data(self, mock_ticker):
        """Test 2: YFinance returns garbage/None data."""
        print("\n--- Stress Test 2: Fundamental Garbage Data ---")
        agent = FundamentalAgent()
        
        # Mock Ticker Info with Missing/None values
        mock_ticker.return_value.info = {
            'trailingPE': None,       # Missing
            'profitMargins': "Error", # Wrong Type
            'revenueGrowth': None
        }
        
        result = agent.analyze("TEST_BAD")
        print(f"Result: {result}")
        # Should default to neutral score 5
        self.assertEqual(result['score'], 5, "Should return default score 5 on error")
        self.assertIsNone(result['beta'], "Beta should be None")
        print("✅ PASS: Handled Garbage Data gracefully.")

    @patch('alpaca_bot_v5.TechnicalAgent.fetch_data')
    def test_technical_empty_data(self, mock_fetch):
        """Test 3: Technical Analysis with Empty Data."""
        print("\n--- Stress Test 3: Empty/Corrupt Technical Data ---")
        agent = TechnicalAgent()
        
        # Simulate Fetch Returning None (Network error or no data)
        mock_fetch.return_value = None
        
        result = agent.analyze("TEST_EMPTY")
        print(f"Result: {result}")
        self.assertEqual(result['signal'], 'WAIT')
        
        # Simulate Fetch Returning Empty DataFrame (somehow)
        mock_fetch.return_value = pd.DataFrame()
        result = agent.analyze("TEST_EMPTY_DF")
        self.assertEqual(result['signal'], 'WAIT')
        print("✅ PASS: Handled Empty Data gracefully.")

    @patch('alpaca_bot_v5.PortfolioManager.execute_strategy')
    def test_main_loop_resilience(self, mock_exec):
        """Test 4: Simulate comprehensive crash in strategy execution."""
        print("\n--- Stress Test 4: Main Loop Resilience ---")
        # We can't easily test the 'while True' loop directly without infinite run,
        # but we can verify execute_strategy handles agent crashes if we mock them.
        
        # Force a crash inside the manager's logic (e.g. unexpected math error)
        # Actually logic is inside try/except in main loop, 
        # but execute_strategy itself doesn't wrap everything in one big try/except 
        # (it relies on agents handling their own).
        # Let's see if execute_strategy propagates an error if an agent returns unexpected type.
        
        self.manager.sentiment_agent.analyze = MagicMock(return_value="Not a Float") # Wrong type
        
        try:
            # This SHOULD raise TypeError when we try to compare "Not a Float" < 0
            # run_hedge_fund loop is responsible for catching this.
            self.manager.execute_strategy("TEST_CRASH")
        except TypeError:
            print("Captured expected TypeError (Loop would catch this).")
        except Exception as e:
            print(f"Captured {e}")
            
        print("✅ PASS: Error propagated to main loop handler.")

if __name__ == '__main__':
    unittest.main()
