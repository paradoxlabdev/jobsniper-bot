#!/usr/bin/env python3
"""
Reset offers table to clear all corrupted data.
This ensures valid URLs and IDs are fetched fresh.
"""
# Add project root to path
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.models import JobOffer
from core.database import db_manager
from sqlalchemy import delete

async def reset_offers():
    print("🧹 Cleaning up job offers table...")
    await db_manager.initialize()
    
    async with db_manager.get_session() as session:
        # Delete all offers
        stmt = delete(JobOffer)
        result = await session.execute(stmt)
        deleted = result.rowcount
        
        await session.commit()
        print(f"✅ Deleted {deleted} offers.")
        print("Bot will strictly fetch fresh, valid data on next run.")
    
    await db_manager.close()

if __name__ == "__main__":
    asyncio.run(reset_offers())
