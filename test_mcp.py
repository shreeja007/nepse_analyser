#!/usr/bin/env python3
"""
Test script for the NEPSE MCP Server
This script tests the MCP server functionality by simulating tool calls
"""

import asyncio
import sys
from fastmcp import Client

MCP_SERVER_URL = "http://0.0.0.0:9000/mcp"

# List of all MCP tools and their required arguments (update as per mcp_server copy.py)
MCP_TOOLS = [
    {"name": "get_market_summary", "args": {}},
    {"name": "get_live_market", "args": {}},
    {"name": "get_company_details", "args": {"symbol": "NABIL"}},
    {"name": "get_price_volume", "args": {}},
    {"name": "get_top_gainers", "args": {}},
    {"name": "get_top_losers", "args": {}},
    {"name": "get_nepse_index", "args": {}},
    {"name": "get_sector_indices", "args": {}},
    {"name": "check_market_status", "args": {}},
    {"name": "get_company_list", "args": {}},
    {"name": "get_floorsheet", "args": {}},
    {"name": "get_company_floorsheet", "args": {"symbol": "NABIL"}},
    {"name": "get_price_history", "args": {"symbol": "NABIL"}},
    {"name": "get_market_depth", "args": {"symbol": "NABIL"}},
    {"name": "get_supply_demand", "args": {}},
    {"name": "get_top_turnover", "args": {}},
    {"name": "get_comprehensive_market_data", "args": {}},
    {"name": "validate_stock_symbol_tool", "args": {"symbol": "NABIL"}},
    {"name": "get_validation_stats", "args": {}},
]



async def test_mcp_server():
    """Test the MCP server functionality using FastMCP Client"""
    print("Testing NEPSE MCP Server (FastMCP Client)...")
    print("=" * 50)

    client = Client(MCP_SERVER_URL)
    success_count = 0
    total_tests = len(MCP_TOOLS)

    async with client:
        # Ping server
        try:
            await client.ping()
            print("✓ MCP server ping successful.")
        except Exception as e:
            print(f"✗ MCP server ping failed: {e}")
            return False

        # List tools
        try:
            tools = await client.list_tools()
            print(f"Available tools: {len(tools)}")
        except Exception as e:
            print(f"✗ Failed to list tools: {e}")
            return False

        # Test each tool
        for i, tool in enumerate(MCP_TOOLS, 1):
            print(f"\nTest {i}/{total_tests}: {tool['name']}")
            print("-" * 40)
            try:
                result = await client.call_tool(tool['name'], tool['args'])
                print(f"✓ SUCCESS: Tool '{tool['name']}' executed successfully")
                if isinstance(result, list):
                    print(f"  Data preview: List with {len(result)} items")
                elif isinstance(result, dict):
                    preview_keys = list(result.keys())[:3]
                    print(f"  Data preview keys: {preview_keys}")
                else:
                    print(f"  Data: {str(result)[:100]}")
                success_count += 1
            except Exception as e:
                print(f"✗ FAILED: Tool '{tool['name']}' failed with error: {e}")

    print("\n" + "=" * 50)
    print(f"Test Results: {success_count}/{total_tests} tests passed")
    if success_count == total_tests:
        print("🎉 All tests passed! MCP server is working correctly.")
    else:
        print(f"⚠️  Some tests failed. Check your MCP server is running on {MCP_SERVER_URL}")
    return success_count == total_tests



async def test_tool_listing():
    """Test tool listing functionality using FastMCP Client"""
    print("\nTesting tool listing...")
    print("-" * 30)
    client = Client(MCP_SERVER_URL)
    async with client:
        try:
            tools = await client.list_tools()
            print(f"Available tools: {len(tools)}")
            for tool in tools:
                print(f"  • {tool.get('name')}: {tool.get('description')}")
        except Exception as e:
            print(f"Failed to list tools: {e}")


if __name__ == "__main__":
    print("NEPSE MCP Server Test Suite (FastMCP HTTP)")
    print("This script tests the MCP server via HTTP API.")
    print(f"Make sure your MCP server is running on {MCP_SERVER_URL}")
    print()
    try:
        asyncio.run(test_tool_listing())
        success = asyncio.run(test_mcp_server())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)
