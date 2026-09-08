"""
Модуль распределения средств между рабочими кошельками и кошельком дохода
Функциональный подход, без ООП
"""
import uuid
import asyncio
import logging
from typing import List, Dict, Tuple, Optional, Literal
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

import tonutils.wallet
from tonutils.contract import MessageAny
from tonutils.wallet.messages import TransferMessage
from tonutils.client import TonapiClient
from tonutils.utils import to_nano
from ton_core import SendMode, begin_cell

from wallets.manager import WalletStorage
from utils.transaction import get_transaction_amount, check_transaction, send_from_wallet
from models import Wallet
from config.config_data import Config, load_config


config: Config = load_config()


logger = logging.getLogger(__name__)


# ============= СТРУКТУРЫ ДАННЫХ =============

@dataclass
class TransferTarget:
    """Структура целевого перевода"""
    wallet_id: str
    address: str
    amount: Decimal
    transfer_type: Literal['work', 'income']
    memo: Optional[str] = None  # Добавляем поле для memo


@dataclass
class DistributionPlan:
    """Полный план распределения средств"""
    deposited_amount: Decimal
    user_amount: Decimal
    income_wallet_amount: Decimal
    work_wallets_total: Decimal
    current_total_balance: Decimal
    target_balance_per_wallet: Decimal
    transfers: List[TransferTarget]
    total_transfers_sum: Decimal
    fees_estimate: Decimal
    work_wallets_count: int
    created_at: datetime
    distribution_id: str  # Уникальный ID для идентификации


def generate_distribution_id() -> str:
    """Генерирует уникальный ID для распределения"""
    return f"DIST_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"


def create_transfer_message_with_memo(
        destination: str,
        amount: float,
        memo: Optional[str] = None
) -> TransferMessage:
    """
    Создает TransferMessage с опциональным memo-комментарием.

    В TON комментарий передается в теле сообщения:
    - op_code: 0x0 (текстовый комментарий)
    - данные: UTF-8 строка
    """
    if memo:
        # Создаем тело с комментарием
        body = begin_cell()
        body.store_uint(0, 32)  # op_code для текстового комментария
        body.store_string(memo)  # сам комментарий
        return TransferMessage(
            destination=destination,
            amount=amount,
            body=body.end_cell()
        )
    else:
        # Обычный перевод без комментария
        return TransferMessage(
            destination=destination,
            amount=amount
        )


def extract_comment_from_message(in_msg: MessageAny):
    if not in_msg or not in_msg.body:
        return None

    try:
        body_slice = in_msg.body.begin_parse()
        if body_slice.remaining_bits == 0:
            return None

        op_code = body_slice.load_uint(32)
        if op_code == 0:
            comment_bytes = body_slice.load_bytes(body_slice.remaining_bits // 8)
            try:
                return comment_bytes.decode('utf-8')
            except UnicodeDecodeError:
                return comment_bytes.hex()
        return None

    except Exception as e:
        logger.error(f"Ошибка при извлечении комментария: {e}")
        return None


def calculate_distribution(
        deposited_amount: float,
        current_wallets: List[Wallet],
        income_wallet_address: str,
        distribution_id: Optional[str] = None,
        user_percent: Decimal = Decimal("0.995"),
        income_percent: Decimal = Decimal("0.005"),
        min_transfer_threshold: Decimal = Decimal("0.001"),
) -> DistributionPlan:
    """
    Рассчитывает распределение средств между кошельками используя проверенный алгоритм выравнивания.

    Алгоритм:
    1. Сортируем кошельки по балансу (от меньшего к большему)
    2. Постепенно поднимаем самые бедные кошельки до уровня следующего
    3. Если не хватает средств - распределяем остаток равномерно
    4. Добавляем перевод на кошелек дохода с memo
    """
    # Генерируем ID если не передан
    if distribution_id is None:
        distribution_id = generate_distribution_id()

    # Валидация входных данных
    if deposited_amount <= 0:
        raise ValueError("Сумма пополнения должна быть больше 0")

    if not current_wallets:
        raise ValueError("Нет рабочих кошельков для распределения")

    if not (0 < user_percent <= 1 and 0 < income_percent <= 1):
        raise ValueError("Проценты должны быть в диапазоне (0, 1]")

    if abs(user_percent + income_percent - Decimal("1")) > Decimal("0.001"):
        raise ValueError(
            f"Сумма процентов должна быть равна 1: {user_percent} + {income_percent} = {user_percent + income_percent}"
        )

    # 🔥 Рассчитываем комиссии
    estimated_transfers_count = len(current_wallets) + 1
    fees_estimate = _estimate_fees(estimated_transfers_count)

    # Вычитаем комиссии из суммы пополнения
    deposit_for_distribution = deposited_amount - float(fees_estimate)

    if deposit_for_distribution <= 0:
        raise ValueError(
            f"Сумма пополнения {deposited_amount} TON слишком мала для покрытия комиссий {fees_estimate} TON"
        )

    # Рассчитываем суммы для распределения
    user_amount = deposit_for_distribution * float(user_percent)
    income_amount = deposit_for_distribution * float(income_percent)
    work_wallets_total = user_amount

    logger.info(f"📋 Распределение {distribution_id}")
    logger.info(f"Сумма пополнения: {deposited_amount} TON")
    logger.info(f"Оценка комиссий: {fees_estimate} TON")
    logger.info(f"Сумма для распределения: {deposit_for_distribution} TON")
    logger.info(f"Пользователю (99.5%): {user_amount} TON")
    logger.info(f"Кошелек дохода (0.5%): {income_amount} TON")

    # Получаем текущие балансы
    balances = {w.id: float(w.balance) for w in current_wallets}
    total_current_balance = sum(balances.values())

    # 🔥 ИСПОЛЬЗУЕМ ПРОВЕРЕННЫЙ АЛГОРИТМ ВЫРАВНИВАНИЯ
    n = len(current_wallets)

    # Создаем список кортежей (баланс, индекс, объект кошелька)
    indexed_wallets = sorted(
        [(balances.get(w.id, 0), i, w) for i, w in enumerate(current_wallets)],
        key=lambda x: x[0]
    )

    # Массив для сумм пополнения каждого кошелька
    top_up_amounts = [0.0] * n
    remaining = work_wallets_total

    # Проходим по уровням (от самого бедного к самому богатому)
    for level in range(n):
        current_balance, idx, wallet = indexed_wallets[level]
        count = level + 1  # количество кошельков в текущей группе

        # Проверяем, есть ли следующий кошелек
        if level + 1 < n:
            next_balance = indexed_wallets[level + 1][0]
            # Сколько нужно, чтобы поднять все кошельки в группе до уровня следующего
            needed = (next_balance - current_balance) * count

            if needed <= remaining:
                # Можем поднять все кошельки в группе до уровня следующего
                for j in range(level + 1):
                    orig_idx = indexed_wallets[j][1]
                    add_amount = next_balance - indexed_wallets[j][0]
                    top_up_amounts[orig_idx] += add_amount

                remaining -= needed

                # Обновляем балансы в indexed_wallets для текущей группы
                for j in range(level + 1):
                    indexed_wallets[j] = (next_balance, indexed_wallets[j][1], indexed_wallets[j][2])
            else:
                # Не хватает средств - распределяем остаток равномерно между текущей группой
                add_per_wallet = remaining / count
                for j in range(level + 1):
                    orig_idx = indexed_wallets[j][1]
                    top_up_amounts[orig_idx] += add_per_wallet
                remaining = 0
                break
        else:
            # Это последний уровень - распределяем остаток между всеми кошельками
            add_per_wallet = remaining / count
            for j in range(level + 1):
                orig_idx = indexed_wallets[j][1]
                top_up_amounts[orig_idx] += add_per_wallet
            remaining = 0
            break

    # 🔥 Формируем список переводов для рабочих кошельков
    transfers = []
    for i, wallet in enumerate(current_wallets):
        top_up = top_up_amounts[i]

        # Округляем до 9 знаков (как в TON)
        amount = Decimal(str(top_up)).quantize(Decimal("0.000000001"))

        # Добавляем перевод только если сумма превышает порог
        if amount > min_transfer_threshold:
            transfers.append(TransferTarget(
                wallet_id=wallet.id,
                address=wallet.address,
                amount=amount,
                transfer_type='work',
                memo=None
            ))

            logger.debug(
                f"Кошелек {wallet.id}: "
                f"было {balances.get(wallet.id, 0)} TON, "
                f"станет {balances.get(wallet.id, 0) + float(amount)} TON, "
                f"перевод {amount} TON"
            )

    # Добавляем перевод на кошелек дохода (с memo)
    income_amount_decimal = Decimal(str(income_amount)).quantize(Decimal("0.000000001"))
    income_transfer = TransferTarget(
        wallet_id="income",
        address=income_wallet_address,
        amount=income_amount_decimal,
        transfer_type='income',
        memo=distribution_id
    )

    all_transfers = transfers + [income_transfer]

    # 🔥 Проверяем итоговую сумму переводов на рабочие кошельки
    total_transfers_sum = sum(float(t.amount) for t in transfers)

    # Если есть небольшое расхождение из-за округления, корректируем последний перевод
    if abs(total_transfers_sum - work_wallets_total) > Decimal("0.0001"):
        logger.warning(
            f"Несоответствие сумм: распределяем {work_wallets_total} TON, "
            f"сумма переводов {total_transfers_sum} TON. Корректируем..."
        )

        # Корректируем последний перевод
        if transfers:
            last_transfer = transfers[-1]
            correction = Decimal(str(work_wallets_total - total_transfers_sum))
            last_transfer.amount = (last_transfer.amount + correction).quantize(Decimal("0.000000001"))
            total_transfers_sum = sum(float(t.amount) for t in transfers)
            logger.info(f"Скорректированная сумма переводов: {total_transfers_sum}")

    # Рассчитываем итоговый целевой баланс (средний)
    target_balance_final = (total_current_balance + work_wallets_total) / len(current_wallets)

    plan = DistributionPlan(
        deposited_amount=deposited_amount,
        user_amount=user_amount,
        income_wallet_amount=float(income_amount_decimal),
        work_wallets_total=work_wallets_total,
        current_total_balance=total_current_balance,
        target_balance_per_wallet=target_balance_final,
        transfers=all_transfers,
        total_transfers_sum=sum(float(t.amount) for t in transfers),
        fees_estimate=float(fees_estimate),
        work_wallets_count=len(current_wallets),
        created_at=datetime.now(),
        distribution_id=distribution_id,
    )

    _log_distribution_plan(plan)
    return plan


def _estimate_fees(transaction_count: int) -> Decimal:
    """
    Оценка комиссий для мульти-транзакции.
    """
    # Базовая комиссия за транзакцию
    base_fee = Decimal("0.005")
    # Комиссия за каждый перевод
    per_transfer_fee = Decimal("0.0005") * transaction_count
    # Итоговая комиссия с запасом 30% для безопасности
    total_fee = (base_fee + per_transfer_fee) * Decimal("1.3")

    # Минимальная комиссия
    if total_fee < Decimal("0.01"):
        total_fee = Decimal("0.01")

    return total_fee.quantize(Decimal("0.000000001"))


def _log_distribution_plan(plan: DistributionPlan):
    """Логирование деталей плана распределения"""
    logger.info("=" * 60)
    logger.info("ПЛАН РАСПРЕДЕЛЕНИЯ СРЕДСТВ")
    logger.info("=" * 60)
    logger.info(f"Сумма пополнения: {plan.deposited_amount} TON")
    logger.info(f"Пользователю (99.5%): {plan.user_amount} TON")
    logger.info(f"Кошелек дохода (0.5%): {plan.income_wallet_amount} TON")
    logger.info(f"Всего рабочих кошельков: {plan.work_wallets_count}")
    logger.info(f"Целевой баланс на кошелек: {plan.target_balance_per_wallet} TON")
    logger.info(f"Количество переводов: {len(plan.transfers)}")
    logger.info(f"Общая сумма переводов: {plan.total_transfers_sum} TON")
    logger.info(f"Оценка комиссий: {plan.fees_estimate} TON")
    logger.info("=" * 60)


def _build_transfer_plan(
        wallets: List[Wallet],
        balances: Dict[str, Decimal],
        target_balance: Decimal,
        min_threshold: Decimal,
) -> List[TransferTarget]:
    """Построение плана переводов для рабочих кошельков"""
    transfers = []

    for wallet in wallets:
        current_balance = balances.get(wallet.id, Decimal("0"))
        deficit = target_balance - current_balance

        if deficit > min_threshold:
            transfer = TransferTarget(
                wallet_id=wallet.id,
                address=wallet.address,
                amount=deficit,
                transfer_type='work',
                memo=None  # Рабочие кошельки без memo
            )
            transfers.append(transfer)

            logger.debug(
                f"Кошелек {wallet.id}: "
                f"было {current_balance} TON, "
                f"станет {target_balance} TON, "
                f"перевод {deficit} TON"
            )

    transfers.sort(key=lambda x: x.amount, reverse=True)
    return transfers


async def _wait_for_wallets(wallet_storage: WalletStorage) -> list[Wallet]:
    async def iterate_wallets(wallets: list[Wallet]) -> bool:
        count_wallets = 0
        for wallet in wallets:
            if wallet.status == 'free':
                await wallet_storage.set_wallet_status(wallet.id, 'busy')
                count_wallets += 1
            elif wallet.status == 'busy':
                count_wallets += 1
        return count_wallets == len(wallets)

    while True:
        wallets = await wallet_storage.get_wallets()
        status = await iterate_wallets(wallets)
        if not status:
            await asyncio.sleep(1)
            continue
        return await wallet_storage.get_wallets()


async def get_income_transaction_amount(client: TonapiClient, memo: str) -> float | Decimal:
    wallet, _, _, _ = tonutils.wallet.WalletV4R2.from_mnemonic(client, config.income_wallet.mnemonic)
    transactions = await wallet.transactions(10)
    for transaction in transactions:
        memo_comment = extract_comment_from_message(transaction.in_msg)
        if memo_comment and memo_comment == memo:
            return Decimal(transaction.in_msg.info.value_coins) / 1_000_000_000

    logger.error(f'Income transaction memo: "{memo}" not found')
    return Decimal(0)


async def process_distribution(deposit: float | Decimal, wallet_storage: WalletStorage):
    distribution_id = generate_distribution_id()
    logger.info(f"Начало распределения {distribution_id}")

    wallets = await _wait_for_wallets(wallet_storage)
    distribution = calculate_distribution(float(deposit), wallets, config.income_wallet.address, distribution_id)
    print(distribution.total_transfers_sum)
    # return

    # подготовка к распределению средств
    client = TonapiClient(wallets[0].tonapi_key)
    mnemonic, subwallet_id = (
        config.distribution_wallet.mnemonic,
        config.distribution_wallet.subwallet_id
    )
    wallet, _, _, _ = tonutils.wallet.HighloadWalletV3.from_mnemonic(client, mnemonic, subwallet_id)
    transfer_massages = []
    for transfer in distribution.transfers:
        if transfer.transfer_type == 'income' and transfer.memo:
            msg = create_transfer_message_with_memo(
                destination=transfer.address,
                amount=float(transfer.amount),
                memo=transfer.memo
            )
            logger.info(f"📝 Добавлен memo для кошелька дохода: {transfer.memo}")
        else:
            msg = TransferMessage(
                destination=transfer.address,
                amount=float(transfer.amount),
            )
        transfer_massages.append(msg)

    attempts = 0
    max_attempts = 3
    tx_hash = None
    while attempts != max_attempts:
        try:
            tx_hash = await wallet.batch_transfer_messages(
                messages=transfer_massages,
                send_mode=SendMode.PAY_GAS_SEPARATELY + SendMode.IGNORE_ERRORS
            )
        except Exception:
            attempts += 1
            continue
        logger.info(f'Tx hash of distribution: {tx_hash}')
        status = await check_transaction(tx_hash, wallets[0].tonapi_key, max_attempts=6)
        if not status:
            attempts += 1
            continue
        break
    print(tx_hash)
    if tx_hash is None:
        return 0.0

    for wallet in await wallet_storage.get_wallets():
        await wallet_storage.update_wallet_balance(wallet.id, wallet.tonapi_key, wallet.mnemonic)
        await wallet_storage.set_wallet_status(wallet.id, 'free')

    income_amount = await get_income_transaction_amount(client, distribution_id)
    return income_amount


async def test():
    pass
    # wallet_storage = WalletStorage('/Users/kirill/Desktop/frag_bridge_api/wallets.json')
    # wallets = await wallet_storage.get_wallets()
    # client = TonapiClient(wallets[0].tonapi_key)
    # wallet, _, _, _ = tonutils.wallet.WalletV4R2.from_mnemonic(client, config.income_wallet.mnemonic)
    # transactions = await wallet.transactions(1)
    # print(datetime.fromtimestamp(transactions[0].now))
    # ton_amount = Decimal(transactions[0].in_msg.info.value_coins) / 1_000_000_000
    # print(ton_amount)
    # tx_hash = '079ce4ae7eda1d8595512e96f0a1b1751670ea459d20739e0d4d836794c44dd7'
    # wallet_storage = WalletStorage('/Users/kirill/Desktop/frag_bridge_api/wallets.json')
    # wallets = await wallet_storage.get_wallets()
    # income = await get_transaction_amount(tx_hash, wallets[0].tonapi_key, config.income_wallet.raw_address)
    # print(income)


# asyncio.run(test())
