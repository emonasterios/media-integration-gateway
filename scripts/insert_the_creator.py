import sys
sys.path.insert(0, '/app')
import asyncio
from src.db import engine
import sqlalchemy as sa

async def insert_movie():
    async with engine.begin() as conn:
        # Insert media
        result = await conn.execute(sa.text("""
            INSERT INTO media (title, original_title, media_type, year, synopsis, poster_url, genres)
            VALUES (
                'The Creator',
                'The Creator',
                'movie',
                2023,
                'En medio de una guerra futura entre la raza humana y las fuerzas de la inteligencia artificial, Joshua, un duro ex-agente de las fuerzas especiales que llora la desaparición de su esposa, es reclutado para cazar y matar al Creador, el escurridizo arquitecto de la IA avanzada que ha desarrollado una misteriosa arma con el poder de acabar con la guerra... y con la propia humanidad.',
                'https://cdn.cuevana-8.com/unsafe/rs:fill:1280:720/q:70/plain/tmdb/t/p/w1280/kjQBrc00fB2RjHZB3PGR4w9ibpz.jpg',
                '["Ciencia Ficción", "Acción", "Aventura"]'
            )
        """))
        media_id = result.lastrowid
        print(f"Media inserted with id: {media_id}")

        # Insert source
        await conn.execute(sa.text("""
            INSERT INTO sources (media_id, provider, url, quality, language)
            VALUES (:media_id, 'cuevana-8.com', 'https://cuevana-8.com/vod-movie/v1/the-creator.mp4?d=8062&q=1080&title=The-Creator', '1080p', 'es')
        """), {"media_id": media_id})
        print(f"Source inserted for media_id: {media_id}")

asyncio.run(insert_movie())
