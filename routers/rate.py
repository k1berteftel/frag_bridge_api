import logging

from fastapi import APIRouter, Request, HTTPException

from database.db import DataBase
from wallets.manager import WalletStorage
from utils.exchange import get_stars_rate as get_stars_rates
from wallets.select import get_random_wallet


PREMIUM_USDT = {
    3: 12,
    6: 16,
    12: 29
}


logger = logging.getLogger(__name__)


router = APIRouter(prefix='/rate')


@router.get('/stars')
async def get_stars_rate(req: Request):
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage

    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path)

    wallet = await get_random_wallet(wallet_storage)
    rates = await get_stars_rates(api_key=wallet.tonapi_key)
    await db.update_request(request_id)
    return {
        'ton_per_star': rates.get('ton_per_star'),
        'usdt_per_star': rates.get('usdt_per_star')
    }


@router.get('/premium')
async def get_premium_rate(req: Request):
    db: DataBase = req.app.state.db
    wallet_storage: WalletStorage = req.app.state.wallet_storage

    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    logger.info('Downloading request-data to database')
    path = req.url.path
    request_id = await db.add_request(api_key, path)

    wallet = await get_random_wallet(wallet_storage)
    rates = await get_stars_rates(api_key=wallet.tonapi_key)
    await db.update_request(request_id)
    usdt_per_ton = rates.get('usdt_per_ton')
    return {
        '3_months': round(PREMIUM_USDT.get(3) / usdt_per_ton, 4),
        '6_months': round(PREMIUM_USDT.get(6) / usdt_per_ton, 4),
        '12_months': round(PREMIUM_USDT.get(12) / usdt_per_ton, 4)
    }
