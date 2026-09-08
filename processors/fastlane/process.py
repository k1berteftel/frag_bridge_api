import logging
from typing import Literal

from utils.transaction import check_transaction
from processors.fastlane.methods import purchase_stars, purchase_premium, topup_ton#, transfer_ton
from database.db import DataBase
from wallets.manager import WalletStorage
from models import PurchaseRequest, Wallet
from errors import (
    ConfigurationError,
    FragmentAPIError,
    UnexpectedError,
    UserNotFoundError,
)


logger = logging.getLogger(__name__)


async def process_purchase(
        msg: PurchaseRequest,
        purchase_type: Literal['stars', 'premium', 'topup', 'ton'],
        target_wallet: Wallet,
        wallet_storage: WalletStorage,
        db: DataBase
) -> dict:
    logger.info(f'Get purchase message: {msg.receiver}|{msg.currency}|{purchase_type}')
    await wallet_storage.set_wallet_status(target_wallet.id, 'busy')
    print(target_wallet.id)
    print(target_wallet.balance)

    cost = 0.0
    fee = 0.0
    tx_hash = None
    error = None
    error_message = ''
    transaction_id = await db.add_transaction(int(target_wallet.id), purchase_type)


    logger.info(f'Start send request')
    try:
        if purchase_type == 'stars':
            result = await purchase_stars(target_wallet, msg.receiver, msg.currency)
            cost, fee, tx_hash = result.cost, result.fee, result.transaction_id
            # TODO: Проверить что именно возвращается (сумма списанная в ton или кол-во звезд операции)
        elif purchase_type == 'premium':
            result = await purchase_premium(target_wallet, msg.receiver, msg.currency)
            cost, fee, tx_hash = result.cost, result.fee, result.transaction_id
        elif purchase_type == 'topup':
            result = await topup_ton(target_wallet, msg.receiver, msg.currency)
            cost, fee, tx_hash = result.cost, result.fee, result.transaction_id
        # else:
        #     result = await transfer_ton(target_wallet, msg.receiver, msg.currency)
    except ConfigurationError as err:
        logger.error(f'"{purchase_type}" purchase Configuration err: {err}')
        error = err
        error_message = str(err)
    except UserNotFoundError as err:
        logger.error(f'"{purchase_type}" purchase UserNotFound err: {err}')
        error = err
        error_message = str(err)
    except FragmentAPIError as err:
        logger.error(f'"{purchase_type}" purchase FragmentAPI err: {err}')
        error = err
        error_message = str(err)
    except UnexpectedError as err:
        logger.error(f'"{purchase_type}" purchase Unexpected err: {err}')
        error = err
        error_message = str(err)
    except Exception as err:  # Critical error
        logger.error(f'"{purchase_type}" purchase Critical err: {err}')
        error = err
        error_message = str(err)

    await wallet_storage.update_wallet_balance(target_wallet.id, target_wallet.tonapi_key, target_wallet.mnemonic)
    await wallet_storage.set_wallet_status(target_wallet.id, 'free')
    await wallet_storage.set_cooldown(target_wallet.id, 15)

    if error_message:
        print(error)
        result = {
            'status': False,
            'code': getattr(error, 'CODE', 424),
            'message:': error_message
        }
    if tx_hash:
        logger.info("Start checking transaction tx-hash...")
        status = await check_transaction(tx_hash, target_wallet.tonapi_key)
        result = {
            'status': status,
            'tx_hash': tx_hash,
            'sum': cost + fee,
            'cost': cost,
            'fee': fee
        }

    logger.info('Downloading transaction data to database')
    if result.get('message'):
        await db.update_transaction(
            transaction_id,
            status='failed',
            code=result.get('code'),
            message=result.get('message')
        )
    else:
        await wallet_storage.update_wallet_batch(target_wallet.id, target_wallet.batch + 1)
        await db.update_transaction(
            transaction_id,
            status='success',
            sum=result.get('cost') + result.get('fee'),
            cost=result.get('cost'),
            fee=result.get('fee')
        )

    return result




