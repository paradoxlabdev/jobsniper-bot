import asyncio
import sys
import os
import json
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.fetcher import FetcherService
from services.foreign_fetcher import ForeignFetcher

async def test_apis():
    print(f"--- API Verification for Keyword: 'Python' ---")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 1. Just Join IT
    print("Testing JUST JOIN IT...")
    jjit_service = FetcherService()
    try:
        await jjit_service.initialize()
        # Fetching with Python keyword
        offers = await jjit_service.fetch_offers(keywords=["Python"], remote=True)
        print(f"✅ JUST JOIN IT: Found {len(offers)} offers")
        for i, offer in enumerate(offers[:2]):
            # JJIT raw offers might use camelCase
            company = offer.get('companyName') or offer.get('company_name') or "Unknown Company"
            title = offer.get('title') or "No Title"
            # Use slugs to build URL if possible
            slug = offer.get('slug')
            url = f"https://justjoin.it/offers/{slug}" if slug else "N/A"
            print(f"   [{i+1}] {title} @ {company}")
            print(f"       URL: {url}")
    except Exception as e:
        print(f"❌ JUST JOIN IT Error: {e}")
    finally:
        await jjit_service.close()

    print("\nTesting FOREIGN JOB BOARDS...")
    foreign_fetcher = ForeignFetcher()
    sources = ['remoteok', 'remotive', 'arbeitnow', 'weworkremotely']
    
    try:
        # Fetch all
        all_foreign = await foreign_fetcher.fetch_all(keywords=["Python"], enabled_sources=sources)
        
        # Manually filter them to ensure they contain "Python" since some APIs return everything
        # This mimics what main.py does
        filtered_foreign = FetcherService._filter_offers(
            offers=all_foreign,
            keywords=["Python"],
            keyword_match_mode="relaxed",
            remote=True
        )

        # Group by source
        source_data = {s: [] for s in ['RemoteOK', 'Remotive', 'Arbeitnow', 'WWR']}
        for offer in filtered_foreign:
            src = offer.get('source')
            if src in source_data:
                source_data[src].append(offer)

        for src_name, offers in source_data.items():
            if offers:
                print(f"✅ {src_name}: Found {len(offers)} offers matching 'Python'")
                for i, offer in enumerate(offers[:2]):
                    print(f"   [{i+1}] {offer.get('title')} @ {offer.get('company_name')}")
                    print(f"       URL: {offer.get('offer_url')}")
            else:
                # Check if we fetched anything at all before filtering
                raw_count = sum(1 for o in all_foreign if o.get('source') == src_name)
                if raw_count > 0:
                    print(f"⚠️ {src_name}: Fetched {raw_count} total, but 0 matched 'Python' after filtering")
                else:
                    print(f"❌ {src_name}: No data returned from API")

    except Exception as e:
        print(f"❌ Foreign Fetcher Error: {e}")

    print(f"\n--- End of Report ---")

if __name__ == "__main__":
    asyncio.run(test_apis())
