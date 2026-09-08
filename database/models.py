import datetime
from typing import Literal

from sqlalchemy import BigInteger, VARCHAR, ForeignKey, DateTime, Boolean, Column, Integer, String, Numeric, func, ARRAY, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncAttrs


class Base(AsyncAttrs, DeclarativeBase):
    pass


class UsersTable(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    username: Mapped[str] = mapped_column(VARCHAR)
    name: Mapped[str] = mapped_column(VARCHAR)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True)

    referral: Mapped[int] = mapped_column(BigInteger, default=None, nullable=True)
    refs: Mapped[int] = mapped_column(Integer, default=0)
    earn: Mapped[float] = mapped_column(Numeric(12, 6), default=0)

    active: Mapped[int] = mapped_column(Integer, default=1)
    activity: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now())
    entry: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now())


class UserAPITable(Base):
    __tablename__ = 'user-api'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(ForeignKey('users.user_id', ondelete='CASCADE'))
    api_key: Mapped[str] = mapped_column(VARCHAR, unique=True)
    balance: Mapped[float] = mapped_column(Numeric(12, 6), default=0)

    requests: Mapped["RequestsTable"] = relationship('RequestsTable', lazy="selectin", cascade='all, delete', uselist=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now())


class RequestsTable(Base):
    """Полная разветка пользовательских запросов к api"""
    __tablename__ = 'requests'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    api_key: Mapped[str] = mapped_column(ForeignKey('user-api.api_key', ondelete='CASCADE'))
    path: Mapped[str] = mapped_column(VARCHAR)
    json: Mapped[dict] = mapped_column(JSON, nullable=True)

    done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now())


class TransactionsTable(Base):
    """Данные покупок совершенных через api"""
    __tablename__ = 'transactions'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    wallet_id: Mapped[int] = mapped_column(Integer)
    sum: Mapped[float] = mapped_column(Numeric(12, 6), default=None, nullable=True)  # Общая сумма списания с баланса пользователя
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=None, nullable=True)  # Сумма операции
    fee: Mapped[float] = mapped_column(Numeric(12, 6), default=None, nullable=True)  # Комиссия блокчейна ton
    # due: Mapped[float] = mapped_column(Numeric(12, 6), default=None, nullable=True)  # Комиссионный сбор (на поддержку системы)

    status: Mapped[Literal['success', 'failed', 'in_process']] = mapped_column(VARCHAR, default='in_process')

    code: Mapped[int] = mapped_column(Integer, default=None, nullable=True)
    error: Mapped[str] = mapped_column(String, default=None, nullable=True)

    purchase: Mapped[Literal['stars', 'premium', 'ton', 'topup']] = mapped_column(VARCHAR)

    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=False), default=func.now())


class IncomeStaticTable(Base):
    """Данные по личным доходам"""
    __tablename__ = 'income-statistics'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    earn: Mapped[float] = mapped_column(Numeric(12, 6), default=0)  # прямая комиссия
    due: Mapped[float] = mapped_column(Numeric(12, 6), default=0)  # комиссия на поддержку сервиса

    today: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    yesterday: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    before_yesterday: Mapped[float] = mapped_column(Numeric(12, 6), default=0)

    week: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    month: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
