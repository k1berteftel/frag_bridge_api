import asyncio
import logging

from fastapi import APIRouter, Request, HTTPException

from database.db import DataBase
from processors.fastlane.process import process_purchase
from processors.queue.aggregator import QueueManager
from processors.queue.polling import polling_task
from wallets.manager import WalletStorage
from wallets.select import get_free_wallet, get_random_wallet
from utils.distibution import process_distribution
from utils.exchange import get_stars_rate
from models import DistributeRequest

logger = logging.getLogger(__name__)

ALLOW_IP = [  # todo: сделать проверки айпишников
    ''
]

router = APIRouter(prefix='/distribute')


@router.post('/')
async def handle_user_distribute(msg: DistributeRequest, req: Request):
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage

    logger.info('Start user deposit distribution...')
    earn = await process_distribution(float(msg.deposit), wallet_storage)
    if earn:
        await db.update_income_earn(earn)
        return {
            'ok': True
        }
    logger.error('Error Error during user deposit distribution')
    return {
        'ok': False
    }




