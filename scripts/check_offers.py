import asyncio
import os
import sys
from sqlalchemy import select, func

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.models import JobOffer
from core.database import db_manager

async def check_offers():
    print("Checking database for job offers...")
    try:
        await db_manager.initialize()
        
        async with db_manager.get_session() as session:
            # Count total offers
            stmt_count = select(func.count(JobOffer.id))
            result_count = await session.execute(stmt_count)
            total = result_count.scalar()
            
            # Count analyzed offers
            stmt_analyzed = select(func.count(JobOffer.id)).where(JobOffer.analyzed == True)
            result_analyzed = await session.execute(stmt_analyzed)
            analyzed = result_analyzed.scalar()
            
            # Get last 5 offers
            stmt_last = select(JobOffer).order_by(JobOffer.id.desc()).limit(5)
            result_last = await session.execute(stmt_last)
            offers = result_last.scalars().all()
            
            print(f"\n📊 --- DATABASE STATS ---")
            print(f"Total offers: {total}")
            print(f"Analyzed by AI: {analyzed}")
            
            if offers:
                print(f"\n🕒 --- LAST 5 OFFERS ---")
                for o in offers:
                    status = "✅ Analyzed" if o.analyzed else "⏳ Pending"
                    score = f" (Score: {o.match_score}%)" if o.match_score is not None else ""
                    print(f"[{o.id}] {o.company_name} - {o.title} | {status}{score}")
            else:
                print("\n❌ No offers found in database.")
                
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await db_manager.close()

if __name__ == "__main__":
    asyncio.run(check_offers())
