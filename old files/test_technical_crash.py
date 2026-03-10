import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import pandas_ta as ta
import numpy as np
from alpaca_bot_v5 import TechnicalAgent

class TestTechnicalCrash(unittest.TestCase):
    def test_indicators_run_without_error(self):
        print("\n=== Testing Technical Indicators (ATR, MACD, VOL) ===")
        agent = TechnicalAgent()
        
        # Create a Fake DataFrame with enough data (100 rows)
        # We need: close, volume, high, low (for ATR)
        df = pd.DataFrame({
            'close': np.random.uniform(100, 200, 100),
            'high': np.random.uniform(100, 200, 100),
            'low': np.random.uniform(100, 200, 100),
            'volume': np.random.uniform(1000, 5000, 100),
            'open': np.random.uniform(100, 200, 100)
        })
        # Ensure high > low
        df['high'] = df[['close', 'open']].max(axis=1) + 1
        df['low'] = df[['close', 'open']].min(axis=1) - 1
        
        # Mock fetch_data to return this DF for all calls
        # The agent calls fetch_data 3 times: Daily, Hourly, Intraday
        # We want Intraday to return our DF.
        with patch.object(agent, 'fetch_data', return_value=df):
            try:
                # This called analyze("TEST")
                # accessing .ta.vacd would crash here
                result = agent.analyze("TEST")
                
                print("Analysis Result:", result)
                
                # Verify we got a dictionary back (WAIT or BUY)
                # It might be WAIT due to random data trend, but it shouldn't be None or Crash
                self.assertIn('signal', result)
                print("✅ PASS: Technical Analysis completed without crashing.")
                
            except AttributeError as e:
                print(f"❌ FAIL: Crashed with AttributeError: {e}")
                raise e
            except Exception as e:
                print(f"❌ FAIL: Crashed with Exception: {e}")
                raise e

if __name__ == '__main__':
    unittest.main()
