#!/usr/bin/env python3
"""
Test script for stock map updater

This script tests the stock map update functionality locally.
"""

import asyncio
import sys
import os
import subprocess
import time
import signal
from pathlib import Path

def start_server():
    """Start the FastAPI server"""
    print("Starting FastAPI server...")
    process = subprocess.Popen([
        sys.executable, "server.py"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for server to start
    print("Waiting for server to start...")
    for i in range(30):
        try:
            import httpx
            with httpx.Client() as client:
                response = client.get("http://localhost:8000/health")
                if response.status_code == 200:
                    print("Server is ready!")
                    return process
        except:
            pass
        time.sleep(1)
        print(f"Waiting... ({i+1}/30)")

    print("Failed to start server")
    process.terminate()
    return None

def stop_server(process):
    """Stop the FastAPI server"""
    if process:
        print("Stopping server...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

async def test_update():
    """Test the stock map update"""
    print("\n=== Testing Stock Map Update ===")

    # Import the updater
    sys.path.append(os.getcwd())
    from updateStocksMap import StockMapUpdater

    async with StockMapUpdater() as updater:
        success = await updater.update_stock_map()
        return success

def main():
    """Main test function"""
    print("=== NEPSE Stock Map Update Test ===")

    # Check if required files exist
    required_files = ["server.py", "updateStocksMap.py", "requirements.txt"]
    for file in required_files:
        if not Path(file).exists():
            print(f"Error: Required file '{file}' not found")
            return False

    # Start server
    server_process = start_server()
    if not server_process:
        return False

    try:
        # Test the update
        success = asyncio.run(test_update())

        if success:
            print("\n✅ Stock map update test PASSED!")
            print("✅ stockmap.json has been updated")
        else:
            print("\n❌ Stock map update test FAILED!")

        return success

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        return False

    finally:
        stop_server(server_process)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
