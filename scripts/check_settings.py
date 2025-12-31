import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage import storage_service

async def check():
    s = await storage_service.get_system_settings()
    print(f"Keywords: '{s.search_keywords}'")
    print(f"Locations: '{s.locations}'")
    print(f"Remote: {s.include_remote}")
    print(f"Threshold: {s.match_threshold}")

if __name__ == "__main__":
    asyncio.run(check())
