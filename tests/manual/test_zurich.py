import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.fetcher import fetcher_service
from services.foreign_fetcher import foreign_fetcher
from core import settings

async def test_zurich_fetch():
    print("--- Testing JJIT for Zurich ---")
    try:
        async with fetcher_service as fetch:
            jjit_offers = await fetch.fetch_offers(
                keywords=["Python"],
                locations=["Zurich"],
                remote=True
            )
            print(f"JJIT found {len(jjit_offers)} offers for Zurich (including remote)")
            if jjit_offers:
                for o in jjit_offers[:3]:
                    print(f"  - {o.get('title')} at {o.get('companyName')} ({o.get('city')})")
    except Exception as e:
        print(f"JJIT error: {e}")

    print("\n--- Testing Broad Zurich Search (no Python keyword) ---")
    try:
        # Search for JUST Zurich on foreign boards
        foreign_offers_pure = await foreign_fetcher.fetch_all(
            keywords=["Zurich"],
            enabled_sources=["remoteok", "wwr", "arbeitnow", "remotive"]
        )
        
        print(f"Total offers fetched with 'Zurich' search: {len(foreign_offers_pure)}")
        
        # Filter and print
        zurich_specific = []
        for o in foreign_offers_pure:
            city = str(o.get('city', '') or '').lower()
            title = str(o.get('title', '') or '').lower()
            
            if 'zurich' in city or 'zurich' in title or 'zürich' in city or 'zürich' in title:
                zurich_specific.append(o)
        
        print(f"Found {len(zurich_specific)} specific Zurich matches")
        if zurich_specific:
            for o in zurich_specific[:20]:
                print(f"  - {o.get('title')} at {o.get('company_name')} (City: {o.get('city')}, Source: {o.get('source')})")
        
    except Exception as e:
        print(f"Broad search error: {e}")

if __name__ == "__main__":
    asyncio.run(test_zurich_fetch())
