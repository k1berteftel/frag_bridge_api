import asyncio
import logging

from fastapi import APIRouter, Request, HTTPException

from database.db import DataBase
from processors.fastlane.process import process_purchase
from processors.queue.aggregator import QueueManager
from processors.queue.polling import polling_task
from wallets.manager import WalletStorage
from wallets.select import get_free_wallet, get_random_wallet
from utils.exchange import get_stars_rate
from models import PurchaseRequest
from constants import PREMIUM_USDT, FRAGMENT_FEE, SYSTEM_COMM

logger = logging.getLogger(__name__)


router = APIRouter(prefix='/purchase')


@router.post('/stars')
async def send_stars(msg: PurchaseRequest, req: Request):
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage
    queues: QueueManager = req.app.state.queue_manager
    api_key = req.headers.get('Api-Key')
    print(api_key)
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path, msg.model_dump())

    logger.info("Calculating the cost of the operation")
    wallet = await get_random_wallet(wallet_storage)
    rate = await get_stars_rate(api_key=wallet.tonapi_key)
    ton_per_star = rate.get("ton_per_star")
    cost = (msg.currency * ton_per_star) + FRAGMENT_FEE + SYSTEM_COMM
    if user_api.balance < cost:
        return HTTPException(status_code=402, detail='There is not enough balance to perform the operation')

    logger.info("Choosing target wallet...")
    result = await get_free_wallet(cost, wallet_storage)
    if isinstance(result, dict):
        logger.error('Failed to choose target wallet')
        return HTTPException(status_code=500, detail='System error')

    if result is None:
        logger.info('Add queue task')
        task_id = await queues.add_task(msg, cost, 'stars')
        logger.info('Start polling task')
        while True:
            result = await polling_task(task_id, queues)
            if result is None:
                await asyncio.sleep(3)
                continue
            break
    else:
        result = await process_purchase(msg, 'stars', result, wallet_storage, db)

    if result.get('message'):
        return {
            'ok': result.get('status'),
            'code': result.get('code', 430),
            'message': result.get('message')
        }
    logger.info(f'Tx-hash of successful purchase: {result.get("tx_hash")}')
    await db.update_request(request_id)
    await db.increment_user_balance(user_api.user_id, -result.get('sum'))
    return {
        'ok': result.get('status')
    }


@router.post('/premium')
async def send_premium(msg: PurchaseRequest, req: Request):
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage
    queues: QueueManager = req.app.state.queue_manager
    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path, msg.model_dump())

    logger.info('Check premium-request args')
    if msg.currency not in list(PREMIUM_USDT.keys()):
        return HTTPException(411, detail='The number of subscription months must be exactly 3,6, or 12')

    logger.info("Calculating the cost of the operation")
    wallet = await get_random_wallet(wallet_storage)
    rate = await get_stars_rate(api_key=wallet.tonapi_key)
    usdt_per_ton = rate.get('usdt_per_ton')
    cost = round(PREMIUM_USDT[msg.currency] / usdt_per_ton, 4) + FRAGMENT_FEE + SYSTEM_COMM
    if user_api.balance < cost:
        return HTTPException(status_code=402, detail='There is not enough balance to perform the operation')

    logger.info("Choosing target wallet...")
    result = await get_free_wallet(cost, wallet_storage)
    if isinstance(result, dict):
        logger.error('Failed to choose target wallet')
        return HTTPException(status_code=500, detail='System error')

    if result is None:
        logger.info('Add queue task')
        task_id = await queues.add_task(msg, cost, 'premium')
        logger.info('Start polling task')
        while True:
            result = await polling_task(task_id, queues)
            if result is None:
                await asyncio.sleep(3)
                continue
            break
    else:
        result = await process_purchase(msg, 'premium', result, wallet_storage, db)

    if result.get('message'):
        return {
            'ok': result.get('status'),
            'code': result.get('code', 430),
            'message': result.get('message')
        }
    logger.info(f'Tx-hash of successful purchase: {result.get("tx_hash")}')
    await db.update_request(request_id)
    await db.increment_user_balance(user_api.user_id, -result.get('sum'))
    return {
        'ok': result.get('status')
    }


@router.post('/ton')
async def send_ton(msg: PurchaseRequest, req: Request):
    return "OK"
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage
    queues: QueueManager = req.app.state.queue_manager
    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path, msg.model_dump())

    logger.info("Calculating the cost of the operation")
    wallet = await get_random_wallet(wallet_storage)
    cost = msg.currency + SYSTEM_COMM
    if user_api.balance < cost:
        return HTTPException(status_code=402, detail='There is not enough balance to perform the operation')

    logger.info("Choosing target wallet...")
    result = await get_free_wallet(cost, wallet_storage)
    if isinstance(result, dict):
        logger.error('Failed to choose target wallet')
        return HTTPException(status_code=500, detail='System error')

    if result is None:
        logger.info('Add queue task')
        task_id = await queues.add_task(msg, cost, 'ton')
        logger.info('Start polling task')
        while True:
            result = await polling_task(task_id, queues)
            if result is None:
                await asyncio.sleep(3)
                continue
            break
    else:
        result = await process_purchase(msg, 'ton', result, wallet_storage, db)

    if result.get('message'):
        return {
            'ok': result.get('status'),
            'code': result.get('code', 430),
            'message': result.get('message')
        }
    logger.info(f'Tx-hash of successful purchase: {result.get("tx_hash")}')
    await db.update_request(request_id)
    return {
        'ok': result.get('status')
    }


@router.post('/topup')
async def topup_ton(msg: PurchaseRequest, req: Request):
    return "OK"
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage
    queues: QueueManager = req.app.state.queue_manager
    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path, msg.model_dump())

    logger.info("Calculating the cost of the operation")
    wallet = await get_random_wallet(wallet_storage)
    cost = msg.currency + FRAGMENT_FEE
    if user_api.balance < cost:
        return HTTPException(status_code=402, detail='There is not enough balance to perform the operation')

    logger.info("Choosing target wallet...")
    result = await get_free_wallet(cost, wallet_storage)
    if isinstance(result, dict):
        logger.error('Failed to choose target wallet')
        return HTTPException(status_code=500, detail='System error')

    if result is None:
        logger.info('Add queue task')
        task_id = await queues.add_task(msg, cost, 'topup')
        logger.info('Start polling task')
        while True:
            result = await polling_task(task_id, queues)
            if result is None:
                await asyncio.sleep(3)
                continue
            break
    else:
        result = await process_purchase(msg, 'ton', result, wallet_storage, db)

    if result.get('message'):
        return {
            'ok': result.get('status'),
            'code': result.get('code', 430),
            'message': result.get('message')
        }
    logger.info(f'Tx-hash of successful purchase: {result.get("tx_hash")}')
    await db.update_request(request_id)
    return {
        'ok': result.get('status')
    }
