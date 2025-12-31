import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import settings
# Override redis settings for local test if needed (handled by env vars or default)
# config.py reads from env. We will set env vars when running.

from services.fetcher import FetcherService

async def test_fetcher():
    print("🚀 Testing FetcherService V2...")
    
    # Enable debug logging for params
    import logging
    logging.getLogger("services.fetcher").setLevel(logging.DEBUG)
    
    async with FetcherService() as fetcher:
        print("1. Testing connection...")
        if await fetcher.test_connection():
            print("✅ Connection OK")
        else:
            print("❌ Connection Failed")
            return

        print("\n2. Fetching with multiple categories (Python=5, JS=1)...")
        # Assuming 5 and 1 are valid IDs. 
        # API v2 usually uses string IDs or specific mappings. 
        # But we are testing param construction primarily.
        
        offers = await fetcher.fetch_offers(
            keywords=["Python"],
            category_ids=["5", "1"], # Python, JS
            remote=True,
            items_count=10 # fetch limited items effectively by logic
        )
        
        print(f"✅ Fetched {len(offers)} offers.")
        if offers:
            print(f"   Sample: {offers[0].get('title')} @ {offers[0].get('companyName')}")

if __name__ == "__main__":
    try:
        asyncio.run(test_fetcher())
    except KeyboardInterrupt:
        print("\n❌ Cancelled")
