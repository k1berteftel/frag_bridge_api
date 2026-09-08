import asyncio
import json
import aiofiles
import aiohttp
import logging
from typing import Literal

import tonutils.client
import tonutils.wallet

from models import Wallet


logger = logging.getLogger(__name__)


class WalletStorage:
    def __init__(self, path: str = 'wallets.json'):
        self._path = path
        self._lock = asyncio.Lock()

    async def _read_file(self) -> dict:
        async with self._lock:
            async with aiofiles.open(self._path, 'r', encoding='utf-8') as f:
                content = await f.read()
                wallets = json.loads(content)
            return wallets

    async def _update_file(self, wallets: dict):
        async with self._lock:
            async with aiofiles.open(self._path, 'w+', encoding='utf-8') as f:
                content = json.dumps(wallets, indent=4)
                await f.write(content)

    async def _get_wallet_balance(self, tonapi_key: str, mnemonic: list[str]) -> float | None:
        counter = 0
        while counter < 3:
            try:
                ton_client = tonutils.client.TonapiClient(api_key=tonapi_key)
                ton_wallet, _, _, _ = tonutils.wallet.WalletV4R2.from_mnemonic(
                    ton_client,
                    mnemonic=mnemonic
                )
                balance = await ton_wallet.balance()
                return balance
            except Exception as err:
                logger.error(f'Error during update balance: {err}')
                counter += 1
                logger.info(f'Counter: {counter}')
                await asyncio.sleep(1)
        return None

    async def get_wallets(self) -> list[Wallet]:
        wallets = await self._read_file()
        wallets = [Wallet.from_dict(wallet_id, wallet) for wallet_id, wallet in wallets.items()]
        return wallets

    async def get_wallet(self, wallet_id: str) -> Wallet | None:
        wallets = await self._read_file()
        wallet_data = wallets.get(wallet_id)
        return Wallet.from_dict(wallet_id, wallet_data) if wallet_data else None

    async def update_wallet_balance(self, wallet_id: str, tonapi_key: str, mnemonic: list[str]):
        balance = await self._get_wallet_balance(tonapi_key, mnemonic)
        if balance is None:
            return
        wallets = await self._read_file()
        wallets[wallet_id]['balance'] = balance
        await self._update_file(wallets)

    async def update_wallet_batch(self, wallet_id: str, value: int):
        wallets = await self._read_file()
        wallets[wallet_id]['batch'] = value
        await self._update_file(wallets)

    async def set_wallet_status(self, wallet_id: str, status: Literal["free", "busy", "sync"]):
        wallets = await self._read_file()
        wallets[wallet_id]['status'] = status
        await self._update_file(wallets)

    async def update_wallets(self):
        wallets = await self.get_wallets()
        for wallet in wallets:
            await self.update_wallet_balance(wallet.id, wallet.tonapi_key, wallet.mnemonic)
            await self.set_wallet_status(wallet.id, 'free')

    async def update_wallet(self, wallet: Wallet):
        """Обновляет кошелек в файле"""
        wallets = await self._read_file()
        wallets[wallet.id] = wallet.to_dict()
        await self._update_file(wallets)

    async def set_cooldown(self, wallet_id: str, seconds: int | None = 15):
        wallet = await self.get_wallet(wallet_id)
        if wallet:
            if seconds is None:
                wallet.clear_cooldown()
            else:
                wallet.set_cooldown(seconds)
            await self.update_wallet(wallet)

    async def is_on_cooldown(self, wallet_id: str) -> bool:
        wallet = await self.get_wallet(wallet_id)
        return wallet.is_on_cooldown if wallet else False