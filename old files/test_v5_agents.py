import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v5 import SentimentAgent, FundamentalAgent, TechnicalAgent

class TestV5Agents(unittest.TestCase):

    def test_sentiment_agent_vader(self):
        """Verify VADER sentiment works (Negative)."""
        print("\n=== Testing Sentiment Agent ===")
        agent = SentimentAgent(use_ai=False)
        
        # Mock get_news to return bad news
        with patch.object(agent, 'get_news', return_value=['Stock crashes 50%', 'Revenue misses big time']):
            score = agent.analyze('FAKE')
            print(f"Bad News Score: {score}")
            self.assertTrue(score < 0)

    @patch('yfinance.Ticker')
    def test_fundamental_agent(self, mock_ticker):
        """Verify Fundamental Agent scoring."""
        print("\n=== Testing Fundamental Agent ===")
        agent = FundamentalAgent()
        
        # Mock Info (Good Company)
        mock_ticker.return_value.info = {
            'trailingPE': 20,       # Good (0-25) -> +1
            'profitMargins': 0.20,  # Good (>15%) -> +2
            'revenueGrowth': 0.15   # Good (>10%) -> +2
        }
        # Mock Calendar (Earnings in 30 days)
        # yfinance calendar is often a DataFrame
        import pandas as pd
        from datetime import datetime
        mock_ticker.return_value.calendar = pd.DataFrame([datetime.now() + pd.Timedelta(days=30)])
        
        # Base 5 + 1 + 2 + 2 = 10
        result = agent.analyze('FAKE')
        score = result['score']
        print(f"Good Company Score: {score}, Earn: {result['days_to_earnings']}")
        self.assertEqual(score, 10)

    def test_technical_agent_wait(self):
        """Verify Technical Agent waits if no data."""
        print("\n=== Testing Technical Agent ===")
        agent = TechnicalAgent()
        
        # Mock fetch_data to return None
        with patch.object(agent, 'fetch_data', return_value=None):
            result = agent.analyze('FAKE')
            print(f"No Data Result: {result}")
            self.assertEqual(result['signal'], 'WAIT')

if __name__ == '__main__':
    unittest.main()
