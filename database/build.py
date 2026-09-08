from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text
from database.models import Base


class PostgresBuild:
    def __init__(self, url: str):
        self.engine = create_async_engine(url)

    async def create_tables(self, base):
        async with self.engine.begin() as conn:
            await conn.run_sync(base.metadata.create_all)

    async def drop_tables(self, base):
        async with self.engine.begin() as conn:
            await conn.run_sync(base.metadata.drop_all)

    # async def clear_all(self):
    #     async with self.engine.begin() as conn:
    #         await conn.execute(text("DROP TABLE IF EXISTS applications, users, deeplinks, bots, admins, prices, \"bot-static\", \"general-static\" CASCADE"))

    def session(self) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(self.engine, expire_on_commit=False)