import sys
sys.path.insert(0, '/app')
import asyncio
from src.db import engine
import sqlalchemy as sa

async def insert_source():
    async with engine.begin() as conn:
        await conn.execute(sa.text("""
            INSERT INTO sources (media_id, provider, url, quality, language)
            VALUES (:media_id, 'cuevana-8.com', 'https://cuevana-8.com/vod-movie/v1/the-creator.mp4?d=8062&q=1080&title=The-Creator', '1080p', 'es')
        """), {"media_id": 20330})
        print(f"Source inserted for media_id: 20330")

asyncio.run(insert_source())
