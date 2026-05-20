#!/usr/bin/env python3
"""
Quick update script that starts server and updates stock map in one command
"""

import subprocess
import sys
import time
import signal
import os
from pathlib import Path

def main():
    print("🚀 NEPSE Stock Map Quick Update")
    print("=" * 40)

    # Check if files exist
    if not Path("server.py").exists():
        print("❌ server.py not found")
        return 1

    if not Path("updateStocksMap.py").exists():
        print("❌ updateStocksMap.py not found")
        return 1

    server_process = None

    try:
        # Start server
        print("📡 Starting API server...")
        server_process = subprocess.Popen([
            sys.executable, "server.py"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Wait for server to start
        print("⏳ Waiting for server to be ready...")
        time.sleep(5)

        # Run update
        print("🔄 Updating stock map...")
        result = subprocess.run([
            sys.executable, "updateStocksMap.py", "--verbose"
        ])

        if result.returncode == 0:
            print("✅ Stock map updated successfully!")
            return 0
        else:
            print("❌ Stock map update failed!")
            return 1

    except KeyboardInterrupt:
        print("\n⚠️  Update cancelled by user")
        return 1

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    finally:
        if server_process:
            print("🛑 Stopping server...")
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()

if __name__ == "__main__":
    sys.exit(main())
