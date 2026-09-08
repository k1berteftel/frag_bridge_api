import logging
import asyncio

import tonutils.wallet
from tonutils.client import TonapiClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.distibution import _wait_for_wallets, process_distribution, calculate_distribution, generate_distribution_id
from wallets.manager import WalletStorage
from database.db import DataBase
from utils.transaction import send_from_wallet
from config.config_data import Config, load_config
from constants import SYSTEM_COMM


logger = logging.getLogger(__name__)
config: Config = load_config()


async def wrapper_today(db: DataBase):
    income = await db.get_income()
    await db.set_income_values(today=0.0, yesterday=income.today, before_yesterday=income.yesterday)


async def wrapper_week(db: DataBase):
    await db.set_income_value('week', 0)


async def wrapper_month(db: DataBase):
    await db.set_income_value('month', 0)


async def check_wallets_batch(wallet_storage: WalletStorage, db: DataBase):
    for wallet in await wallet_storage.get_wallets():
        if wallet.batch >= 10:
            income = wallet.batch * SYSTEM_COMM
            client = TonapiClient(wallet.tonapi_key)
            status, _ = await send_from_wallet(
                client=client,
                mnemonic=wallet.mnemonic,
                target_address=config.income_wallet.address,
                amount=income,
                tonapi_key=wallet.tonapi_key,
                max_retries=5
            )
            if not status:
                continue
            await db.update_income_due(income)
            await wallet_storage.update_wallet_batch(wallet.id, 0)


async def fix_main_wallet_distribution(wallet_storage: WalletStorage):
    wallets = await _wait_for_wallets(wallet_storage)
    client = TonapiClient(wallets[0].tonapi_key)
    mnemonic, subwallet_id = (
        config.distribution_wallet.mnemonic,
        config.distribution_wallet.subwallet_id
    )
    deposit = None
    counter = 0
    while counter < 3:
        try:
            wallet, _, _, _ = tonutils.wallet.HighloadWalletV3.from_mnemonic(client, mnemonic, subwallet_id)
            deposit = await wallet.balance()
            break
        except Exception as err:
            logger.error(f'Error during update balance: {err}')
            counter += 1
            logger.info(f'Counter: {1}')
            await asyncio.sleep(1)
    if deposit is None:
        return
    await process_distribution(deposit, wallet_storage)


async def start_schedulers(wallet_storage: WalletStorage, db: DataBase, scheduler: AsyncIOScheduler):
    scheduler.add_job(
        wrapper_today,
        'cron',
        args=[db],
        hour=0,
        minute=0,
        id='reset_daily_wrapper'
    )
    scheduler.add_job(
        wrapper_week,
        'cron',
        args=[db],
        day_of_week='mon',
        hour=0,
        minute=0,
        id='reset_weekly_wrapper'
    )
    scheduler.add_job(
        wrapper_month,
        'cron',
        args=[db],
        day=1,
        hour=0,
        minute=0,
        id='reset_monthly_wrapper'
    )

    scheduler.add_job(
        check_wallets_batch,
        'interval',
        args=[wallet_storage, db],
        days=2,
        id='process_wallets_batch'
    )

    scheduler.add_job(
        fix_main_wallet_distribution,
        'cron',
        args=[wallet_storage],
        hour=0,
        minute=0,
        id='process_daily_fix'
    )