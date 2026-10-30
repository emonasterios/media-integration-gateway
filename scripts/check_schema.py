import asyncio, sys
sys.path.insert(0, '/app')
from src.db import engine
import sqlalchemy as sa

async def schema():
    async with engine.begin() as conn:
        def get_cols(connection, table):
            return sa.inspect(connection).get_columns(table)
        for t in ['media', 'sources']:
            cols = await conn.run_sync(get_cols, t)
            print(f'{t}:')
            for col in cols:
                cname = col['name']
                ctype = col['type']
                print(f'  {cname} ({ctype})')
            print()

asyncio.run(schema())
