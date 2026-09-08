import asyncio
import random

from wallets.manager import WalletStorage
from models import Wallet


async def get_free_wallet(cost: float, wallet_storage: WalletStorage) -> dict | None | Wallet:
    """
    Поллит менеджер кошельков на выбор свободного кошелька
    :param cost: Стоимость (суммарная!!) операции в ton
    :param wallet_storage: Менеджер кошельков
    :return: dict - Ошибка (Raise 500),
            None - передача задачи на агрегатор,
            Wallet - свободный кошелек
    """
    wallets = await wallet_storage.get_wallets()
    enough = False
    for wallet in wallets:
        if wallet.balance > cost:
            enough = True
            break

    if not enough:
        sum = 0
        for wallet in wallets:
            sum += wallet.balance
        if sum < cost:
            return {
                'status': False,
                'message': "Enough balance"
            }
        else:
            return None
    free_wallets = []
    for wallet in wallets:
        if wallet.status == 'free' and not wallet.is_on_cooldown and wallet.balance > cost:
            free_wallets.append(wallet)
    if not free_wallets:
        await asyncio.sleep(2.5)
        return await get_free_wallet(cost, wallet_storage)
    return max(free_wallets, key=lambda x: x.balance)


async def get_random_wallet(wallet_storage: WalletStorage) -> Wallet:
    wallets = await wallet_storage.get_wallets()
    collected_wallets = []
    for wallet in wallets:
        if wallet.status == 'free':
            collected_wallets.append(wallet)
    if not collected_wallets:
        return random.choice(wallets)
    return random.choice(collected_wallets)
