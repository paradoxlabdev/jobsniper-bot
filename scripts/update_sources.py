import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage import storage_service
from core.database import db_manager

async def update_sources():
    print("Updating system settings to enable all sources...")
    try:
        await db_manager.initialize()
        
        # All supported sources
        all_sources = "jjit,remoteok,remotive,arbeitnow,weworkremotely"
        
        # Update settings in DB
        await storage_service.update_system_settings(enabled_sources=all_sources)
        
        # Verify
        settings = await storage_service.get_system_settings()
        print(f"✅ Success! Enabled sources: {settings.enabled_sources}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(update_sources())
