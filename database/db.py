import datetime
from typing import Literal

from sqlalchemy import select, insert, update, column, text, delete, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import (UserAPITable, RequestsTable, TransactionsTable, IncomeStaticTable)


async def setup_database(session: async_sessionmaker):
    async with session() as session:
        if not await session.scalar(select(IncomeStaticTable)):
            await session.execute(insert(IncomeStaticTable).values())
        await session.commit()


class DataBase():
    def __init__(self, session: async_sessionmaker):
        self._sessions = session

    async def add_transaction(self, wallet_id: int, purchase: Literal['stars', 'premium', 'ton', 'topup']) -> int:
        async with self._sessions() as session:
            result = await session.execute(insert(TransactionsTable).values(
                wallet_id=wallet_id,
                purchase=purchase
            ).returning(TransactionsTable.id))
            await session.commit()
        return result.scalar()

    async def add_request(self, api_key: str, path: str, data: dict = None) -> int:
        async with self._sessions() as session:
            result = await session.execute(insert(RequestsTable).values(
                api_key=api_key,
                path=path,
                json=data
            ).returning(RequestsTable.id))
            await session.commit()
        return result.scalar()

    async def get_user_api(self, api_key: str):
        async with self._sessions() as session:
            result = await session.scalar(select(UserAPITable).where(UserAPITable.api_key == api_key))
        return result

    async def get_income(self):
        async with self._sessions() as session:
            result = await session.scalar(select(IncomeStaticTable))
            return result

    async def update_transaction(self, id: int, **kwargs):
        async with self._sessions() as session:
            await session.execute(update(TransactionsTable).where(TransactionsTable.id == id).values(
                kwargs
            ))
            await session.commit()

    async def update_request(self, id: int):
        async with self._sessions() as session:
            await session.execute(update(RequestsTable).where(RequestsTable.id == id).values(
                done=True
            ))
            await session.commit()

    async def update_income_earn(self, earn: int | float):
        async with self._sessions() as session:
            await session.execute(update(IncomeStaticTable).values(
                earn=IncomeStaticTable.earn + earn,
                today=IncomeStaticTable.today + earn,
                week=IncomeStaticTable.week + earn,
                month=IncomeStaticTable.month + earn
            ))
            await session.commit()

    async def update_income_due(self, due: int | float):
        async with self._sessions() as session:
            await session.execute(update(IncomeStaticTable).values(
                earn=IncomeStaticTable.due + due,
                today=IncomeStaticTable.today + due,
                week=IncomeStaticTable.week + due,
                month=IncomeStaticTable.month + due
            ))
            await session.commit()

    async def increment_user_balance(self, user_id: int, balance: float | int):
        async with self._sessions() as session:
            await session.execute(update(UserAPITable).where(UserAPITable.user_id == user_id).values(
                balance=UserAPITable.balance + balance
            ))
            await session.commit()

    async def set_income_value(self, column: str, value: any):
        async with self._sessions() as session:
            await session.execute(update(IncomeStaticTable).values(
                {
                    column: value
                }
            ))
            await session.commit()

    async def set_income_values(self, **kwargs):
        async with self._sessions() as session:
            await session.execute(update(IncomeStaticTable).values(
                kwargs
            ))
            await session.commit()

