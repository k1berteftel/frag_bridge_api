import asyncio
import logging
import json
import aiofiles
from pathlib import Path
from datetime import datetime
from typing import Literal
import uuid

from database.db import DataBase
from processors.fastlane.process import process_purchase
from wallets.manager import WalletStorage
from models import PurchaseRequest, Wallet, AggregatorStatus
from utils.transaction import collect_funds_from_seeds_string
from utils.calculate import distribute_collection

RESERVE = 0.1

logger = logging.getLogger(__name__)


class QueueManager:
    def __init__(self, wallet_storage: WalletStorage, db: DataBase, path: str = "queue.json"):
        self.queue_file = Path(path)
        self._lock = asyncio.Lock()
        self.wallet_storage = wallet_storage
        self.db = db

    async def init_queue(self):
        if not self.queue_file.exists():
            async with aiofiles.open(self.queue_file, 'w') as f:
                await f.write(json.dumps({
                    "tasks": []
                }, indent=2))
        self._polling_task = asyncio.create_task(self._polling_task())
        logger.info("QueueManager initialized")

    async def _polling_task(self):
        while True:
            try:
                queue_data = await self._read_queue()
                tasks = queue_data.get('tasks', [])

                task = None
                for t in reversed(tasks):
                    if t.get('status') == AggregatorStatus.PENDING.value:
                        task = t
                        break

                if not task:
                    await asyncio.sleep(3)
                    continue

                task['status'] = AggregatorStatus.PROCESSING.value
                await self._update_task(task)

                logger.info('The task was successfully selected')
                logger.info('Start sorting wallets')

                total_sum = 0
                wallets = await self.wallet_storage.get_wallets()
                collected_wallets = []
                for wallet in wallets:
                    if wallet.status == 'free' and not wallet.is_on_cooldown:
                        total_sum += wallet.balance
                        collected_wallets.append(wallet)

                collected_wallets.sort(key=lambda x: x.balance)

                if not collected_wallets:
                    logger.warning('No free wallets available')
                    task['status'] = AggregatorStatus.PENDING.value
                    await self._update_task(task)
                    await asyncio.sleep(3)
                    continue

                target_wallet = collected_wallets.pop(0)

                logger.info(f'Target wallet balance: {target_wallet.balance}')

                if total_sum < task.get('cost'):
                    logger.info(f'Collected sum: {total_sum}. Need: {task.get("cost")}')
                    task['status'] = AggregatorStatus.PENDING.value
                    await self._update_task(task)
                    logger.info('Wait for 3 sec before continue')
                    await asyncio.sleep(3)
                    continue

                donor_sum = 0
                donor_wallets = []
                for wallet in reversed(collected_wallets):
                    donor_sum += wallet.balance
                    donor_wallets.append(wallet)
                    if donor_sum >= task.get('cost') + RESERVE:
                        break

                if donor_sum < task.get('cost'):
                    logger.info('The amount of balances is not enough for aggregate')
                    task['result']['code'] = 500
                    task['result']['error'] = "The amount of balances is not enough for aggregate"
                    task['status'] = AggregatorStatus.FAILED.value
                    await self._update_task(task)
                    await asyncio.sleep(3)
                    continue

                await self.set_wallets_status([target_wallet, *collected_wallets], 'sync')

                target_amount = task.get('cost') - target_wallet.balance
                source_wallets = distribute_collection(target_amount, donor_wallets)

                if not source_wallets:
                    logger.error('Error during distribution donor wallets')
                    task['result']['code'] = 500
                    task['result']['error'] = "Calculate distribution donor wallets"
                    task['status'] = AggregatorStatus.FAILED.value
                    await self._update_task(task)
                    await self.set_wallets_status([target_wallet, *collected_wallets], 'free')
                    await asyncio.sleep(3)
                    continue

                result = await collect_funds_from_seeds_string(
                    target_wallet.address,
                    source_wallets,
                    target_amount
                )

                if not result.get('status'):
                    logger.error('Error during fundraising')
                    task['result']['code'] = 500
                    task['result']['error'] = result.get('error', 'Unknown error during fundraising')
                    task['status'] = AggregatorStatus.FAILED.value
                    await self._update_task(task)
                    await self.set_wallets_status([target_wallet, *collected_wallets], 'free')
                    await self.update_wallets_balance([target_wallet, *collected_wallets])
                    await asyncio.sleep(3)
                    continue

                await self.update_wallets_balance([target_wallet, *collected_wallets])
                await self.set_wallets_status(collected_wallets, 'free')

                # process_fastlane должен быть асинхронной функцией
                transaction = await process_purchase(
                    msg=PurchaseRequest.model_validate(task.get('data')),
                    purchase_type=task.get('purchase_type'),
                    target_wallet=target_wallet,
                    wallet_storage=self.wallet_storage,
                    db=self.db
                )

                if not transaction.get('status'):
                    logger.error('Error during process transaction')
                    task['result']['code'] = transaction.get('code', 500)
                    task['result']['error'] = transaction.get('message', 'Unknown error during transaction')
                    task['status'] = AggregatorStatus.FAILED.value
                    await self._update_task(task)
                    await self.set_wallets_status([target_wallet], 'free')
                    await asyncio.sleep(3)
                    continue

                task['status'] = AggregatorStatus.COMPLETED.value
                task['result']['tx_hash'] = transaction.get('tx_hash', None)
                task['result']['sum'] = transaction.get('sum', 0.0)
                task['result']['cost'] = transaction.get('cost', 0.0)
                task['result']['fee'] = transaction.get('fee', 0.0)
                await self._update_task(task)
                logger.info(f'Task {task.get("id")} completed successfully')

            except Exception as e:
                logger.error(f'Unexpected error in polling task: {e}', exc_info=True)
                await asyncio.sleep(5)

            await asyncio.sleep(3)

    async def _iter_wallets(self, wallet_ids: list[str], status: Literal["free", "busy", "sync"]) -> bool:
        fresh_wallets = [wallet for wallet in await self.wallet_storage.get_wallets() if wallet.id in wallet_ids]
        for wallet in fresh_wallets:
            if status == 'sync':
                if wallet.status != 'free':
                    return False
            if wallet.status != status:
                await self.wallet_storage.set_wallet_status(wallet.id, status)
        return True

    async def set_wallets_status(self, wallets: list[Wallet], status: Literal["free", "busy", "sync"]):
        global_status = False
        wallet_ids = [wallet.id for wallet in wallets]
        while not global_status:
            global_status = await self._iter_wallets(wallet_ids, status)
            if not global_status:
                await asyncio.sleep(1.5)

    async def update_wallets_balance(self, wallets: list[Wallet]):
        for wallet in wallets:
            await self.wallet_storage.update_wallet_balance(wallet.id, wallet.tonapi_key, wallet.mnemonic)

    async def _update_task(self, target_task: dict):
        queue_data = await self._read_queue()
        tasks = queue_data.get('tasks', [])

        for i in range(len(tasks)):
            if tasks[i].get('id') == target_task.get('id'):
                tasks[i] = target_task
                break

        await self._update_queue(tasks)

    async def _read_queue(self) -> dict:
        async with self._lock:
            async with aiofiles.open(self.queue_file, 'r') as f:
                content = await f.read()
                return json.loads(content) if content else {"tasks": []}

    async def _update_queue(self, tasks: list[dict]):
        queue_data = {'tasks': tasks}
        async with self._lock:
            async with aiofiles.open(self.queue_file, 'w') as f:
                await f.write(json.dumps(queue_data, indent=2))

    async def get_tasks(self) -> list[dict]:
        queue_data = await self._read_queue()
        return queue_data.get('tasks', [])

    async def add_task(self, msg: PurchaseRequest, cost: float, purchase_type: Literal['stars', 'premium', 'ton', 'topup']) -> str:
        task_data = msg.model_dump()
        logger.info(f"Adding task with data: {task_data}")

        queue_data = await self._read_queue()
        tasks = queue_data.get('tasks', [])

        task = {
            'id': str(uuid.uuid4()),
            'data': task_data,
            'result': {
                'tx_hash': '',
                'sum': 0.0,
                'code': '',
                'error': '',
            },
            'cost': cost,
            'purchase_type': purchase_type,
            'status': AggregatorStatus.PENDING.value,
            'created_at': datetime.now().isoformat()
        }

        logger.info(f'Current task: {task}')
        tasks.append(task)
        await self._update_queue(tasks)
        return task.get('id')

    async def del_task(self, task_id: str):
        queue_data = await self._read_queue()
        tasks = queue_data.get('tasks', [])

        for i in range(len(tasks)):
            if tasks[i].get('id') == task_id:
                del tasks[i]
                break

        await self._update_queue(tasks)

    async def stop(self):
        """Метод для остановки polling задачи"""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                logger.info("Polling task cancelled")