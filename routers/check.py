import logging

from fastapi import APIRouter, Request, HTTPException
from pyrogram import Client

from database.db import DataBase
from config.config_data import Config, load_config
from models import CheckRequest

config: Config = load_config()

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/check')


@router.get('/premium')
async def check_premium(msg: CheckRequest, req: Request):
    db: DataBase = req.app.state.db
    api_key = req.headers.get('Api-Key')
    user_api = await db.get_user_api(api_key)
    if not user_api:
        return HTTPException(401, detail='Api key is not valid')

    app = Client(config.user_bot.account)
    try:
        async with app:
            users = await app.get_users([msg.user_id])
            for user in users:
                return {
                    'user_id': msg.user_id,
                    'is_premium': user.is_premium
                }
    except Exception as err:
        logger.error(err)
        return HTTPException(423, f'Unexpected error. Try again later')

