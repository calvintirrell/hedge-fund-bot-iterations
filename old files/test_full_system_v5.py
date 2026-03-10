import unittest
from unittest.mock import MagicMock, patch
from alpaca_bot_v5 import PortfolioManager
from alpaca.trading.enums import OrderSide

class TestFullSystemV5(unittest.TestCase):
    
    @patch('alpaca_bot_v5.SentimentAgent')
    @patch('alpaca_bot_v5.FundamentalAgent')
    @patch('alpaca_bot_v5.TechnicalAgent')
    def test_hedge_fund_decision_making(self, MockTech, MockFund, MockSent):
        print("\n=== 🏦 AI HEDGE FUND SIMULATION: 'War Room' ===")
        print("Scenario: Analyzing NVIDIA (NVDA) for a potential Buy.\n")

        # 1. Setup The Team (Mocks)
        mock_client = MagicMock()
        mock_client.get_account.return_value.equity = 100000
        mock_client.get_open_position.side_effect = Exception("No Position") # We don't own it yet

        manager = PortfolioManager(mock_client)
        
        # Override the agents with our specific mocks
        manager.sentiment_agent = MockSent.return_value
        manager.fundamental_agent = MockFund.return_value
        manager.technical_agent = MockTech.return_value

        # 2. Agent Inputs (The "Briefing")
        
        # Technical Agent reports:
        # "Charts look perfect. Uptrend, Above VWAP, and Bullish MACD Crossover!"
        MockTech.return_value.analyze.return_value = {
            'signal': 'BUY',
            'close': 140.00,
            'atr': 2.50
        }
        
        # Fundamental Agent reports:
        # "Company is solid. Great margins, Analyst Buy rating. Beta is a bit high (2.1)."
        MockFund.return_value.analyze.return_value = {
            'score': 9,       # High Score
            'beta': 2.1       # High Beta Warning
        }

        # Sentiment Agent reports:
        # "News is very positive today."
        MockSent.return_value.analyze.return_value = 0.85 # Strong Positive

        # 3. The Decision
        print(">> PORTFOLIO MANAGER: Calling the team to order...\n")
        
        print(f"📈 TECHNICAL AGENT: 'Charts are GREEN. Price $140.00. Volatility (ATR) is $2.50.'")
        print(f"🏢 FUNDAMENTAL AGENT: 'Financials are rock solid (9/10). Analysts say BUY. Note: Beta is 2.1 (Volatile).'")
        print(f"🧠 SENTIMENT AGENT: 'Market sentiment is Bullish (Score: 0.85). People love this stock right now.'")
        
        print("\n>> PORTFOLIO MANAGER: Analyzing inputs...")
        
        # Spy on the execute_strategy method to see what happens
        # We run the actual method!
        manager.execute_strategy("NVDA")
        
        # 4. Verify The Trade
        print("\n>> RESULT:")
        if mock_client.submit_order.called:
            args = mock_client.submit_order.call_args[1]['order_data']
            print(f"✅ DECISION: BUY EXECUTED!")
            print(f"   - Shares: {args.qty}")
            print(f"   - Buy Price: Market (approx $140)")
            print(f"   - Protective Stop: ${args.stop_loss.stop_price} (Calculated via ATR)")
        else:
            print("❌ DECISION: REJECTED")

        print("\n=== Simulation Complete ===")

if __name__ == '__main__':
    unittest.main()
