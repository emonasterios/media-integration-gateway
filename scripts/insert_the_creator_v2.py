import sys
sys.path.insert(0, '/app')
import asyncio
from src.db import engine
import sqlalchemy as sa

async def check_and_insert():
    async with engine.begin() as conn:
        # Check if media already exists
        result = await conn.execute(sa.text("SELECT id, title FROM media WHERE title = 'The Creator'"))
        existing = result.fetchone()
        
        if existing:
            media_id = existing[0]
            print(f"Media already exists with id: {media_id}")
        else:
            # Insert media
            result = await conn.execute(sa.text("""
                INSERT INTO media (title, original_title, media_type, year, synopsis, poster_url, genres)
                VALUES (
                    'The Creator',
                    'The Creator',
                    'movie',
                    2023,
                    'En medio de una guerra futura entre la raza humana y las fuerzas de la inteligencia artificial.',
                    'https://cdn.cuevana-8.com/unsafe/rs:fill:1280:720/q:70/plain/tmdb/t/p/w1280/kjQBrc00fB2RjHZB3PGR4w9ibpz.jpg',
                    '["Ciencia Ficción", "Acción", "Aventura"]'
                )
            """))
            media_id = result.lastrowid
            print(f"Media inserted with id: {media_id}")

        # Check if source already exists
        result = await conn.execute(sa.text("SELECT id FROM sources WHERE media_id = :media_id"), {"media_id": media_id})
        existing_source = result.fetchone()
        
        if existing_source:
            print(f"Source already exists for media_id: {media_id}")
        else:
            # Insert source
            await conn.execute(sa.text("""
                INSERT INTO sources (media_id, provider, url, quality, language)
                VALUES (:media_id, 'cuevana-8.com', 'https://cuevana-8.com/vod-movie/v1/the-creator.mp4?d=8062&q=1080&title=The-Creator', '1080p', 'es')
            """), {"media_id": media_id})
            print(f"Source inserted for media_id: {media_id}")

asyncio.run(check_and_insert())
