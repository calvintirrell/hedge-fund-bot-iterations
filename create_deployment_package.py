#!/usr/bin/env python3
"""
V8 Deployment Package Creator
Creates a clean deployment package with only required files
"""

import os
import shutil
import tarfile
from pathlib import Path

def create_deployment_package():
    """Create deployment package for V8 trading bot"""
    
    print("🚀 Creating V8 Deployment Package...")
    print("=" * 60)
    
    # Define deployment directory
    deploy_dir = Path("v8_deployment")
    
    # Clean up existing deployment directory
    if deploy_dir.exists():
        print(f"📁 Removing existing {deploy_dir}/")
        shutil.rmtree(deploy_dir)
    
    # Create fresh deployment directory
    print(f"📁 Creating {deploy_dir}/")
    deploy_dir.mkdir()
    
    # Required files
    required_files = [
        "alpaca_bot_v8.py",
        "notifications.py",
        ".env",
        "requirements.txt"
    ]
    
    # Copy main files
    print("\n📄 Copying main files...")
    for file in required_files:
        if Path(file).exists():
            shutil.copy2(file, deploy_dir / file)
            print(f"  ✅ {file}")
        else:
            print(f"  ⚠️  {file} - NOT FOUND (may need to create)")
    
    # Copy v8_modules directory
    print("\n📦 Copying v8_modules/...")
    v8_modules_src = Path("v8_modules")
    v8_modules_dst = deploy_dir / "v8_modules"
    
    if v8_modules_src.exists():
        # Create v8_modules directory
        v8_modules_dst.mkdir()
        
        # Copy all .py files (exclude __pycache__ and tests)
        py_files = list(v8_modules_src.glob("*.py"))
        for py_file in py_files:
            shutil.copy2(py_file, v8_modules_dst / py_file.name)
            print(f"  ✅ v8_modules/{py_file.name}")
        
        print(f"\n  📊 Copied {len(py_files)} module files")
    else:
        print("  ❌ v8_modules/ directory not found!")
        return False
    
    # Create __init__.py if it doesn't exist
    init_file = v8_modules_dst / "__init__.py"
    if not init_file.exists():
        init_file.touch()
        print(f"  ✅ Created v8_modules/__init__.py")
    
    # Create README for deployment
    print("\n📝 Creating deployment README...")
    readme_content = """# V8 Trading Bot Deployment Package

## Quick Start

1. Install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure .env file with your API keys:
   ```bash
   nano .env
   ```

3. Run the bot:
   ```bash
   python alpaca_bot_v8.py
   ```

4. Run in background (recommended):
   ```bash
   screen -S trading_bot
   python alpaca_bot_v8.py
   # Press Ctrl+A then D to detach
   ```

## Files Included

- alpaca_bot_v8.py - Main trading bot
- notifications.py - Discord notifications
- .env - Environment variables (configure with your keys)
- requirements.txt - Python dependencies
- v8_modules/ - Performance optimization modules

## Support

See DEPLOYMENT-GUIDE.md for detailed instructions.
"""
    
    with open(deploy_dir / "README.md", "w") as f:
        f.write(readme_content)
    print("  ✅ README.md")
    
    # Create .gitignore
    print("\n🔒 Creating .gitignore...")
    gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
ENV/

# Environment
.env

# Logs
*.log

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Trading data
agent_performance_history.json
"""
    
    with open(deploy_dir / ".gitignore", "w") as f:
        f.write(gitignore_content)
    print("  ✅ .gitignore")
    
    # Count files
    print("\n" + "=" * 60)
    print("📊 Package Summary:")
    print("=" * 60)
    
    all_files = list(deploy_dir.rglob("*"))
    py_files = list(deploy_dir.rglob("*.py"))
    
    print(f"  Total files: {len([f for f in all_files if f.is_file()])}")
    print(f"  Python files: {len(py_files)}")
    print(f"  Package size: {get_dir_size(deploy_dir):.2f} KB")
    
    # Create tar.gz archive
    print("\n📦 Creating compressed archive...")
    archive_name = "v8_deployment.tar.gz"
    
    with tarfile.open(archive_name, "w:gz") as tar:
        tar.add(deploy_dir, arcname=deploy_dir.name)
    
    archive_size = Path(archive_name).stat().st_size / 1024
    print(f"  ✅ {archive_name} ({archive_size:.2f} KB)")
    
    # Final instructions
    print("\n" + "=" * 60)
    print("✅ Deployment Package Created Successfully!")
    print("=" * 60)
    print(f"\n📁 Deployment directory: {deploy_dir}/")
    print(f"📦 Compressed archive: {archive_name}")
    print("\n🚀 Next Steps:")
    print("  1. Upload to Google Cloud:")
    print(f"     gcloud compute scp {archive_name} your-instance:~/")
    print("\n  2. On Google Cloud instance:")
    print(f"     tar -xzf {archive_name}")
    print(f"     cd {deploy_dir.name}")
    print("     python3 -m venv .venv")
    print("     source .venv/bin/activate")
    print("     pip install -r requirements.txt")
    print("     python alpaca_bot_v8.py")
    print("\n  3. Run in background:")
    print("     screen -S trading_bot")
    print("     python alpaca_bot_v8.py")
    print("     # Press Ctrl+A then D to detach")
    print("\n" + "=" * 60)
    
    return True

def get_dir_size(path):
    """Get directory size in KB"""
    total = 0
    for entry in Path(path).rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total / 1024

if __name__ == "__main__":
    try:
        success = create_deployment_package()
        if success:
            print("\n✅ Done!")
        else:
            print("\n❌ Failed to create deployment package")
            exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
