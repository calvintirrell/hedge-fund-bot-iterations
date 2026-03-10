import unittest
from unittest.mock import MagicMock, patch
import logging
import sys
import os

# Suppress logging during tests
logging.basicConfig(level=logging.CRITICAL)

# Mock libs
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

# Import V7 (Superset of V6 features typically, but we should test the actual code logic)
try:
    import alpaca_bot_v7 as bot
except ImportError:
    sys.path.append(os.getcwd())
    import alpaca_bot_v7 as bot

class TestPnLNotifications(unittest.TestCase):
    
    def setUp(self):
        self.mock_client = MagicMock()
        self.manager = bot.PortfolioManager(self.mock_client)
        self.manager.technical_agent = MagicMock()
        
        # Mock Discord Sender
        # We need to patch the imported function in the module
        self.discord_patcher = patch('alpaca_bot_v7.send_discord_alert')
        self.mock_send_discord = self.discord_patcher.start()
        
    def tearDown(self):
        self.discord_patcher.stop()

    def test_moonshot_exit_pnl(self):
        print("\n[TEST] Moonshot Exit PnL Format...")
        # Simulate Position
        mock_pos = MagicMock()
        mock_pos.avg_entry_price = '100.0'
        mock_pos.qty = '10'
        self.mock_client.get_open_position.return_value = mock_pos
        
        # Simulate Tech Agent returning High Price (+20% gain)
        # Price = 120. PnL = (120-100)*10 = $200.
        self.manager.technical_agent.analyze.return_value = {
            'close': 120.0,
            'signal': 'WAIT'
        }
        
        # Run Check
        self.manager.execute_strategy('TEST', check_swing=True)
        
        # Verify Discord Call
        self.mock_send_discord.assert_called()
        msg = self.mock_send_discord.call_args[0][0]
        
        print(f"Captured Msg: {msg}")
        self.assertIn("+$200.00", msg)
        self.assertIn("+20.00%", msg)
        print(" -> PASSED: Found Dollar and %")

    def test_options_stop_loss_pnl(self):
        print("\n[TEST] Options Stop Loss PnL Format...")
        # Enable Options
        with patch('alpaca_bot_v7.ENABLE_OPTIONS', True):
            # Simulate Option Position
            mock_pos = MagicMock()
            mock_pos.symbol = "AMD230616C00100000" # Option Symbol
            mock_pos.qty = '1'
            mock_pos.avg_entry_price = '2.00'
            mock_pos.current_price = '1.00' # -50% Loss
            mock_pos.unrealized_plpc = '-0.50'
            mock_pos.unrealized_pl = '-100.00' # $1.00 loss * 100 shares
            mock_pos.asset_class = 'us_option'
            
            self.mock_client.get_all_positions.return_value = [mock_pos]
            
            self.manager.manage_options_risk()
            
            self.mock_send_discord.assert_called()
            msg = self.mock_send_discord.call_args[0][0]
            
            print(f"Captured Msg: {msg}")
            self.assertIn("-$100.00", msg)
            self.assertIn("-50.00%", msg)
            print(" -> PASSED: Found Dollar and %")

if __name__ == '__main__':
    unittest.main()
