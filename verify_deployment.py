#!/usr/bin/env python3
"""
V8 Deployment Verification Script
Checks that all required files are present and imports work
"""

import sys
from pathlib import Path

def verify_deployment():
    """Verify V8 deployment is complete and functional"""
    
    print("🔍 Verifying V8 Deployment...")
    print("=" * 60)
    
    errors = []
    warnings = []
    
    # Check main files
    print("\n📄 Checking main files...")
    main_files = [
        "alpaca_bot_v8.py",
        "notifications.py",
        ".env",
        "requirements.txt"
    ]
    
    for file in main_files:
        if Path(file).exists():
            print(f"  ✅ {file}")
        else:
            print(f"  ❌ {file} - MISSING")
            errors.append(f"Missing file: {file}")
    
    # Check v8_modules directory
    print("\n📦 Checking v8_modules/...")
    v8_modules_dir = Path("v8_modules")
    
    if not v8_modules_dir.exists():
        print("  ❌ v8_modules/ directory not found!")
        errors.append("Missing v8_modules/ directory")
        return False, errors, warnings
    
    required_modules = [
        "__init__.py",
        "cache_manager.py",
        "base_agent.py",
        "config.py",
        "trade_tracker.py",
        "position_tracker.py",
        "order_executor.py",
        "analysis_optimizer.py",
        "market_regime.py",
        "async_api_wrapper.py",
        "agent_coordinator.py",
        "agent_performance.py",
        "consensus_engine.py"
    ]
    
    for module in required_modules:
        module_path = v8_modules_dir / module
        if module_path.exists():
            print(f"  ✅ {module}")
        else:
            print(f"  ❌ {module} - MISSING")
            errors.append(f"Missing module: v8_modules/{module}")
    
    # Test imports
    print("\n🔧 Testing imports...")
    
    try:
        from v8_modules.config import get_config
        print("  ✅ v8_modules.config")
    except ImportError as e:
        print(f"  ❌ v8_modules.config - {e}")
        errors.append(f"Import error: v8_modules.config - {e}")
    
    try:
        from v8_modules.agent_coordinator import AgentCoordinator
        print("  ✅ v8_modules.agent_coordinator")
    except ImportError as e:
        print(f"  ❌ v8_modules.agent_coordinator - {e}")
        errors.append(f"Import error: v8_modules.agent_coordinator - {e}")
    
    try:
        from v8_modules.trade_tracker import TradeTracker
        print("  ✅ v8_modules.trade_tracker")
    except ImportError as e:
        print(f"  ❌ v8_modules.trade_tracker - {e}")
        errors.append(f"Import error: v8_modules.trade_tracker - {e}")
    
    try:
        from notifications import send_discord_alert
        print("  ✅ notifications")
    except ImportError as e:
        print(f"  ❌ notifications - {e}")
        errors.append(f"Import error: notifications - {e}")
    
    # Test configuration
    print("\n⚙️  Testing configuration...")
    
    try:
        from v8_modules.config import get_config
        config = get_config()
        
        if config.api_key:
            print("  ✅ API_KEY configured")
        else:
            print("  ⚠️  API_KEY not set in .env")
            warnings.append("API_KEY not configured")
        
        if config.secret_key:
            print("  ✅ SECRET_KEY configured")
        else:
            print("  ⚠️  SECRET_KEY not set in .env")
            warnings.append("SECRET_KEY not configured")
        
        if config.discord_webhook_url:
            print("  ✅ DISCORD_WEBHOOK_URL configured")
        else:
            print("  ⚠️  DISCORD_WEBHOOK_URL not set in .env")
            warnings.append("DISCORD_WEBHOOK_URL not configured")
        
        print(f"  ℹ️  Symbols: {len(config.symbols)} configured")
        print(f"  ℹ️  Target Portfolio: ${config.target_portfolio_value:,.0f}")
        
    except Exception as e:
        print(f"  ❌ Configuration error: {e}")
        errors.append(f"Configuration error: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Verification Summary")
    print("=" * 60)
    
    if not errors and not warnings:
        print("\n✅ ALL CHECKS PASSED!")
        print("\n🚀 Deployment is ready!")
        print("\nNext steps:")
        print("  1. Run: python alpaca_bot_v8.py")
        print("  2. Or run in background: screen -S trading_bot python alpaca_bot_v8.py")
        return True, errors, warnings
    
    if errors:
        print(f"\n❌ ERRORS FOUND: {len(errors)}")
        for error in errors:
            print(f"  • {error}")
    
    if warnings:
        print(f"\n⚠️  WARNINGS: {len(warnings)}")
        for warning in warnings:
            print(f"  • {warning}")
    
    if errors:
        print("\n❌ Deployment has errors - please fix before running")
        return False, errors, warnings
    else:
        print("\n⚠️  Deployment has warnings but should work")
        print("   Consider fixing warnings for full functionality")
        return True, errors, warnings

if __name__ == "__main__":
    try:
        success, errors, warnings = verify_deployment()
        
        if success:
            print("\n✅ Verification complete!")
            sys.exit(0)
        else:
            print("\n❌ Verification failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Verification error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
