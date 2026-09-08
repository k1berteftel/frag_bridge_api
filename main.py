import asyncio
import logging

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Response
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config.config_data import Config, load_config
from routers import purchase_router, check_router, rate_router, system_router
from processors.queue.aggregator import QueueManager
from wallets.manager import WalletStorage
from utils.schedule import start_schedulers
from database.models import Base
from database.build import PostgresBuild
from database.db import DataBase, setup_database


config: Config = load_config()

app = FastAPI()


format = '[{asctime}] #{levelname:8} {filename}:{lineno} - {name} - {message}'

logging.basicConfig(
    level=logging.DEBUG,
    format=format,
    style='{'
)


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": format,
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "uvicorn.access": {"level": "INFO", "handlers": ["default"], "propagate": False},
        "": {"handlers": ["default"], "level": "DEBUG", "propagate": False},  # корневой логгер
    },
    "root": {
        "level": "DEBUG",
        "handlers": ["default"],
    },
}


logger = logging.getLogger(__name__)


async def main():
    #print(config.wallet.seed_phrase)

    logger.info('Start API system')

    # блок инициализации
    database = PostgresBuild(config.db.dns)
    session = database.session()
    # await database.drop_tables(Base)
    await setup_database(session)
    await database.create_tables(Base)

    db = DataBase(session)

    wallet_storage = WalletStorage()
    await wallet_storage.update_wallets()

    queue_manager = QueueManager(wallet_storage, db)
    await queue_manager.init_queue()

    scheduler: AsyncIOScheduler = AsyncIOScheduler()
    scheduler.start()
    await start_schedulers(wallet_storage, db, scheduler)

    # блок настройки приложения

    app.include_router(check_router)  # Check эндпоинты
    app.include_router(rate_router)  # Purchase эндпоинты
    app.include_router(purchase_router)  # Purchase эндпоинты
    app.include_router(system_router)  # Системные эндпоинты

    app.state.db = db
    app.state.wallet_storage = wallet_storage
    app.state.queue_manager = queue_manager

    uvicorn_config = uvicorn.Config(app, host='0.0.0.0', port=8090, log_level="info", log_config=LOGGING_CONFIG)  # ssl_keyfile='ssl/key.pem', ssl_certfile='ssl/cert.pem'
    server = uvicorn.Server(uvicorn_config)
    try:
        await server.serve()
    except Exception:
        ...
    finally:
        queue_manager._polling_task.cancel()
        await server.shutdown()
        logger.info('Stop fragment system')


if __name__ == '__main__':
    asyncio.run(main())
