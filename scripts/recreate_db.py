import asyncio
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import db_manager
from models.models import Base
# Import all models to ensure they are registered with Base
from models import JobOffer, SystemSettings, ProcessingLog

async def recreate_db():
    print("⚠️  WARNING: This will DROP ALL TABLES and delete all data!")
    print("⏳ 3 seconds to cancel (Ctrl+C)...")
    await asyncio.sleep(3)
    
    print("🔄 Dropping all tables...")
    await db_manager.initialize()
    
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        print("✅ Tables dropped.")
        
        print("🔄 Creating new tables with updated schema...")
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Tables created successfully.")
        
    await db_manager.close()

if __name__ == "__main__":
    try:
        asyncio.run(recreate_db())
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled.")
