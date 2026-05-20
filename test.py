from nepse import AsyncNepse
import asyncio

async def test_nepse():
    nepse = AsyncNepse()
    nepse.setTLSVerification(False)

    print("Testing getDailyNepseIndexGraph...")
    result = await nepse.getSupplyDemand()
    print("Result:", result)

if __name__ == "__main__":
    asyncio.run(test_nepse())