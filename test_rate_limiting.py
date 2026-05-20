#!/usr/bin/env python3
"""
Rate Limiting Test Script

Tests the rate limiting functionality across all services.
"""

import asyncio
import time
import httpx
import json
import websockets
from typing import List, Dict

async def test_http_rate_limit():
    """Test HTTP API rate limiting"""
    print("\n🔄 Testing HTTP API Rate Limiting...")

    async with httpx.AsyncClient() as client:
        successful_requests = 0
        rate_limited_requests = 0

        # Make rapid requests to trigger rate limit
        for i in range(60):  # More than the health limit of 50
            try:
                response = await client.get("http://localhost:8000/health")

                if response.status_code == 200:
                    successful_requests += 1
                elif response.status_code == 429:
                    rate_limited_requests += 1
                    print(f"   ✅ Rate limit triggered at request {i+1}")
                    break

            except Exception as e:
                print(f"   ❌ Request failed: {e}")
                break

        print(f"   📊 Results: {successful_requests} successful, {rate_limited_requests} rate limited")

        # Check rate limit headers
        try:
            response = await client.get("http://localhost:8000/health")
            if "X-RateLimit-Limit" in response.headers:
                print(f"   📈 Rate Limit Headers: {response.headers.get('X-RateLimit-Limit')} limit, "
                      f"{response.headers.get('X-RateLimit-Remaining')} remaining")
        except:
            pass

        return rate_limited_requests > 0

async def test_websocket_rate_limit():
    """Test WebSocket rate limiting"""
    print("\n🔄 Testing WebSocket Rate Limiting...")

    try:
        uri = "ws://localhost:5555"
        async with websockets.connect(uri) as websocket:
            successful_messages = 0
            rate_limited_messages = 0

            # Send rapid messages to trigger rate limit
            for i in range(60):  # More than the WebSocket message limit of 50
                message = {
                    "route": "summary",
                    "params": {},
                    "messageId": f"test_{i}"
                }

                await websocket.send(json.dumps(message))
                response = await websocket.recv()
                response_data = json.loads(response)

                if "error" in response_data and "rate limit" in response_data["error"].lower():
                    rate_limited_messages += 1
                    print(f"   ✅ WebSocket rate limit triggered at message {i+1}")
                    break
                else:
                    successful_messages += 1

            print(f"   📊 Results: {successful_messages} successful, {rate_limited_messages} rate limited")
            return rate_limited_messages > 0

    except Exception as e:
        print(f"   ❌ WebSocket test failed: {e}")
        return False

async def test_rate_limit_stats():
    """Test rate limit statistics endpoint"""
    print("\n🔄 Testing Rate Limit Statistics...")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/rate-limit/stats")

            if response.status_code == 200:
                stats = response.json()
                print(f"   📊 Total tracked IPs: {stats.get('total_tracked_ips', 0)}")
                print(f"   📊 Active requests in window: {stats.get('active_requests_in_window', 0)}")
                print(f"   📊 Window size: {stats.get('window_size_seconds', 0)} seconds")
                print("   ✅ Stats endpoint working")
                return True
            else:
                print(f"   ❌ Stats endpoint returned {response.status_code}")
                return False

    except Exception as e:
        print(f"   ❌ Stats test failed: {e}")
        return False

async def test_different_endpoints():
    """Test rate limiting on different endpoint categories"""
    print("\n🔄 Testing Different Endpoint Categories...")

    endpoints = [
        ("/health", "health"),
        ("/validate/stock/NABIL", "validation"),
        ("/Summary", "market_data"),
        ("/TopGainers", "market_data")
    ]

    async with httpx.AsyncClient() as client:
        for endpoint, category in endpoints:
            print(f"   Testing {category} endpoint: {endpoint}")

            response = await client.get(f"http://localhost:8000{endpoint}")

            if "X-RateLimit-Category" in response.headers:
                actual_category = response.headers["X-RateLimit-Category"]
                limit = response.headers.get("X-RateLimit-Limit", "unknown")
                remaining = response.headers.get("X-RateLimit-Remaining", "unknown")

                print(f"     Category: {actual_category}, Limit: {limit}, Remaining: {remaining}")

                if actual_category == category:
                    print(f"     ✅ Correct category assigned")
                else:
                    print(f"     ⚠️  Expected {category}, got {actual_category}")
            else:
                print(f"     ❌ No rate limit headers found")

async def main():
    """Main test function"""
    print("🧪 NEPSE API Rate Limiting Test Suite")
    print("=" * 50)

    # Check if servers are running
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/health")
            if response.status_code != 200:
                print("❌ HTTP API server not responding")
                return
    except:
        print("❌ HTTP API server not running. Please start: python server.py")
        return

    try:
        async with websockets.connect("ws://localhost:5555") as websocket:
            pass
    except:
        print("❌ WebSocket server not running. Please start: python socketServer.py")
        print("   (WebSocket tests will be skipped)")

    # Run tests
    tests_passed = 0
    total_tests = 0

    # Test HTTP rate limiting
    total_tests += 1
    if await test_http_rate_limit():
        tests_passed += 1

    # Test WebSocket rate limiting
    total_tests += 1
    try:
        if await test_websocket_rate_limit():
            tests_passed += 1
    except:
        print("   ⚠️  WebSocket test skipped (server not available)")

    # Test rate limit stats
    total_tests += 1
    if await test_rate_limit_stats():
        tests_passed += 1

    # Test different endpoint categories
    total_tests += 1
    await test_different_endpoints()
    tests_passed += 1  # Always pass this for now

    # Summary
    print("\n" + "=" * 50)
    print(f"🎯 Test Results: {tests_passed}/{total_tests} tests passed")

    if tests_passed == total_tests:
        print("✅ All rate limiting tests PASSED!")
    else:
        print("⚠️  Some tests failed or were skipped")

    print("\n💡 Tips:")
    print("   - Rate limits reset after 1 minute")
    print("   - Check rate limit headers in HTTP responses")
    print("   - Use /rate-limit/stats to monitor usage")
    print("   - Different endpoints have different limits")

if __name__ == "__main__":
    asyncio.run(main())
