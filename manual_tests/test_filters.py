import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.fetcher import FetcherService

# Sample data for testing
SAMPLE_OFFERS = [
    {
        "title": "Senior Python Developer",
        "company_name": "Tech Corp",
        "city": "Warszawa",
        "workplaceType": "remote",
        "description": "We are looking for a Senior Python Developer with Django experience.",
        "requiredSkills": ["Python", "Django", "AWS"]
    },
    {
        "title": "Java Backend Engineer",
        "company_name": "Java Shop",
        "city": "Kraków",
        "workplaceType": "office",
        "description": "Java Spring Boot role in our Kraków office.",
        "requiredSkills": ["Java", "Spring"]
    },
    {
        "title": "Python/React FullStack",
        "company_name": "Web Solutions",
        "city": "Wrocław",
        "workplaceType": "partly_remote",
        "description": "Hybrid role using Python and React.",
        "requiredSkills": ["Python", "React", "TypeScript"]
    },
    {
        "title": "Data Scientist",
        "company_name": "Data AI",
        "city": "Gdańsk",
        "workplaceType": "remote",
        "description": "Remote data science position. Requires Python and SQL.",
        "requiredSkills": ["Python", "SQL", "Pandas"]
    }
]

def run_filter_test(name, keywords=None, mode="relaxed", remote=True, locations=None):
    print(f"--- Test: {name} ---")
    print(f"Settings: Keywords={keywords}, Mode={mode}, Remote={remote}, Locations={locations}")
    
    filtered = FetcherService._filter_offers(
        offers=SAMPLE_OFFERS,
        keywords=keywords,
        keyword_match_mode=mode,
        remote=remote,
        locations=locations
    )
    
    print(f"Result: Found {len(filtered)} / {len(SAMPLE_OFFERS)} offers")
    for offer in filtered:
        print(f"   ✅ {offer['title']} ({offer['workplaceType']}, {offer['city']})")
    print("-" * 30 + "\n")

if __name__ == "__main__":
    # Test 1: Only Remote + Python
    run_filter_test(
        "Remote + Python (Relaxed)",
        keywords=["Python"],
        mode="relaxed",
        remote=True,
        locations=None
    )

    # Test 2: Specific City (Kraków) + No Remote
    run_filter_test(
        "Kraków ONLY (Strict Location, No Remote)",
        keywords=None,
        mode="relaxed",
        remote=False,
        locations=["Kraków"]
    )

    # Test 3: Multiple Keywords (Strict Mode)
    # Senior Python Developer has Python.
    # Data Scientist has Python.
    # If we require ["Python", "Django", "AWS"], only Senior Python Developer matches (80% threshold)
    run_filter_test(
        "Strict Keywords (Python, Django, AWS)",
        keywords=["Python", "Django", "AWS"],
        mode="strict",
        remote=True,
        locations=None
    )

    # Test 4: Hybrid/Partly Remote (Wrocław)
    run_filter_test(
        "Wrocław or Remote",
        keywords=None,
        mode="relaxed",
        remote=True,
        locations=["Wrocław"]
    )
