import sys
sys.path.insert(0, '/app')
import asyncio
from src.db import engine
import sqlalchemy as sa

async def fix_provider():
    async with engine.begin() as conn:
        result = await conn.execute(sa.text("""
            UPDATE sources SET provider = 'cuevana3' WHERE media_id = 20330
        """))
        print(f"Updated {result.rowcount} rows")
        
        # Verify
        result = await conn.execute(sa.text("SELECT media_id, provider, url FROM sources WHERE media_id = 20330"))
        row = result.fetchone()
        print(f"Source: {row}")

asyncio.run(fix_provider())
