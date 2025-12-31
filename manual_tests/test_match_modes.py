import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.fetcher import FetcherService

# Keywords for testing (5 items)
KEYWORDS = ["Python", "Django", "AWS", "Docker", "Kubernetes"]

# Sample offers with different keyword counts
TEST_OFFERS = [
    {
        "title": "Python Junior (1 match)",
        "description": "We only use Python here.",
        "city": "Remote", "workplaceType": "remote"
    },
    {
        "title": "Backend Dev (2 matches)",
        "description": "Python and Django developer needed.",
        "city": "Remote", "workplaceType": "remote"
    },
    {
        "title": "DevOps (3 matches)",
        "description": "Python, Docker and Kubernetes position.",
        "city": "Remote", "workplaceType": "remote"
    },
    {
        "title": "Senior FullStack (4 matches)",
        "description": "Python, Django, Docker and AWS experience required.",
        "city": "Remote", "workplaceType": "remote"
    },
    {
        "title": "Lead Engineer (5 matches)",
        "description": "Python, Django, AWS, Docker and Kubernetes expert.",
        "city": "Remote", "workplaceType": "remote"
    }
]

def test_mode(mode_name):
    print(f"\n--- Testing Mode: {mode_name.upper()} ---")
    
    # Threshold calculation (same as in fetcher.py)
    num_kws = len(KEYWORDS)
    if mode_name == "relaxed": threshold = 1
    elif mode_name == "strict": threshold = max(1, int(num_kws * 0.8))
    else: threshold = max(1, int(num_kws * 0.4))
    
    print(f"Keywords: {KEYWORDS} (Count: {num_kws})")
    print(f"Required matches (threshold): {threshold}")
    
    filtered = FetcherService._filter_offers(
        offers=TEST_OFFERS,
        keywords=KEYWORDS,
        keyword_match_mode=mode_name,
        remote=True
    )
    
    print(f"Results: Found {len(filtered)} matches")
    for offer in filtered:
        print(f"   ✅ {offer['title']}")
    
    # Explanation
    if mode_name == "relaxed":
        print("Note: Relaxed accepts anything with at least 1 keyword.")
    elif mode_name == "moderate":
        print(f"Note: Moderate (40% of {num_kws}) requires at least {threshold} keywords.")
    elif mode_name == "strict":
        print(f"Note: Strict (80% of {num_kws}) requires at least {threshold} keywords.")

if __name__ == "__main__":
    test_mode("relaxed")
    test_mode("moderate")
    test_mode("strict")
