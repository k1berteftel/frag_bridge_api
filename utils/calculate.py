import logging
from typing import List, Dict
from models import Wallet

logger = logging.getLogger(__name__)


def distribute_collection(
        target_amount: float,
        donor_wallets: List[Wallet],
        min_reserve_percent: float = 0.1,  # Минимальный резерв на кошельке (10%)
        max_transfer_percent: float = 0.7,  # Максимальный % от баланса за один раз
        round_to_decimals: int = 6,  # Точность округления (увеличил для точности)
        tx_fee: float = 0.01,  # Комиссия за одну транзакцию перевода в TON
        collection_buffer_percent: float = 0.05  # Буфер в процентах от target_amount (5%)
) -> List[Dict]:
    """
    Рассчитывает необходимые суммы для сбора с донорских кошельков

    Args:
        target_amount: Сумма которую необходимо собрать (без учета комиссий)
        donor_wallets: Список кошельков-доноров
        min_reserve_percent: Какой процент баланса оставлять нетронутым
        max_transfer_percent: Максимальный процент от баланса для перевода
        round_to_decimals: Точность округления
        tx_fee: Комиссия за одну транзакцию перевода
        collection_buffer_percent: Буфер в процентах от target_amount (для компенсации погрешностей)

    Returns:
        List[Dict] - список словарей с ключами:
            - 'mnemonic': List[str] - мнемоника кошелька
            - 'tonapi_key': str - API ключ
            - 'amount': float - сумма для перевода
            - 'address': str - адрес кошелька для логирования
    """
    # Фильтруем только кошельки с положительным балансом
    active_wallets = [w for w in donor_wallets if w.balance > 0]

    if not active_wallets:
        logger.warning("Нет активных кошельков-доноров с положительным балансом")
        return []

    # Рассчитываем количество транзакций сбора (максимально возможное)
    max_transactions = len(active_wallets)

    # Рассчитываем общую комиссию за все транзакции сбора
    total_fees = max_transactions * tx_fee

    # Рассчитываем буферную сумму (для компенсации погрешностей округления)
    buffer_amount = target_amount * (collection_buffer_percent / 100)

    # Итоговая сумма для сбора (целевая сумма + комиссии + буфер)
    total_to_collect = target_amount + total_fees + buffer_amount

    logger.info(f'Целевая сумма: {target_amount} TON')
    logger.info(f'Комиссии ({max_transactions} транзакций): {total_fees} TON')
    logger.info(f'Буфер ({collection_buffer_percent}%): {buffer_amount} TON')
    logger.info(f'Итого нужно собрать: {total_to_collect} TON')

    available_funds = []
    total_available = 0.0

    for wallet in active_wallets:
        # Рассчитываем минимальный резерв
        min_reserve = wallet.balance * min_reserve_percent
        # Максимально доступная сумма с учетом резерва
        max_available = wallet.balance - min_reserve
        # Максимальная сумма за одну транзакцию
        max_transfer = wallet.balance * max_transfer_percent

        # Доступная сумма - минимум между доступной и максимальной для перевода
        available = min(max_available, max_transfer)

        if available > 0:
            available_funds.append({
                'wallet': wallet,
                'mnemonic': wallet.mnemonic,
                'tonapi_key': wallet.tonapi_key,
                'address': wallet.address,
                'balance': wallet.balance,
                'available': available,
                'weight': available  # Вес для распределения
            })
            total_available += available
            logger.debug(f'  Кошелек {wallet.address[:20]}...: баланс={wallet.balance}, доступно={available}')

    if not available_funds:
        logger.warning("Нет доступных средств для сбора")
        return []

    # Если общая доступная сумма меньше необходимой, используем экстренный сбор
    if total_available < total_to_collect:
        logger.warning(
            f'Доступно только {total_available} TON, требуется {total_to_collect} TON. Используем экстренный сбор.')
        return _emergency_collect(active_wallets, total_to_collect, min_reserve_percent, tx_fee)

    # Используем взвешенное распределение
    logger.info(f'Доступно {total_available} TON, распределяем {total_to_collect} TON')
    transfers = _weighted_distribution(available_funds, total_to_collect, round_to_decimals)

    # Логируем итоговую сумму сбора
    total_collected = sum(t['amount'] for t in transfers)
    logger.info(f'Распределение завершено: {len(transfers)} доноров, собрано {total_collected} TON')
    logger.info(
        f'Из них: целевая сумма {target_amount} TON + комиссии {len(transfers) * tx_fee} TON + буфер {total_collected - target_amount - len(transfers) * tx_fee} TON')

    return transfers


def _weighted_distribution(
        available_funds: List[dict],
        target_amount: float,
        round_to_decimals: int
) -> List[Dict]:
    """
    Взвешенное распределение сумм сбора между донорами
    """
    total_weight = sum(f['weight'] for f in available_funds)
    transfers = []
    remaining = target_amount

    # Сортируем по весу (от большего к меньшему)
    available_funds.sort(key=lambda x: x['weight'], reverse=True)

    logger.debug(f'Общий вес: {total_weight}, целевая сумма: {target_amount}')

    for fund in available_funds:
        if remaining <= 0:
            break

        # Рассчитываем долю на основе веса
        share = (fund['weight'] / total_weight) * target_amount
        take_amount = min(share, fund['available'], remaining)
        take_amount = round(take_amount, round_to_decimals)

        if take_amount > 0:
            transfers.append({
                'mnemonic': fund['mnemonic'],
                'tonapi_key': fund['tonapi_key'],
                'address': fund['address'],
                'amount': take_amount
            })
            logger.debug(f'  Донор {fund["address"][:20]}...: вес={fund["weight"]}, доля={share}, взять={take_amount}')

            remaining -= take_amount

            # Обновляем доступную сумму и общий вес для следующих итераций
            fund['available'] -= take_amount
            total_weight -= fund['weight']

    # Если осталась небольшая сумма (из-за округления), добавляем её к последней транзакции
    if remaining > 0.0000001 and transfers:
        logger.debug(f'Остаток после распределения: {remaining}, добавляем к последней транзакции')
        last_transfer = transfers[-1]
        corrected_amount = round(last_transfer['amount'] + remaining, round_to_decimals)
        transfers[-1]['amount'] = corrected_amount
        remaining = 0

    if remaining > 0:
        logger.error(f'Не удалось распределить всю сумму, остаток: {remaining}')

    return transfers


def _emergency_collect(
        donor_wallets: List[Wallet],
        target_amount: float,
        min_reserve_percent: float = 0.05,  # В экстренном режиме оставляем только 5%
        tx_fee: float = 0.01
) -> List[Dict]:
    """
    Экстренный сбор средств (берем максимально возможные суммы с каждого кошелька)
    """
    # Сортируем кошельки по балансу (от большего к меньшему)
    sorted_wallets = sorted(
        donor_wallets,
        key=lambda w: w.balance,
        reverse=True
    )

    transfers = []
    remaining = target_amount

    logger.warning(f'Экстренный сбор {target_amount} TON, оставляем резерв {min_reserve_percent * 100}%')

    for wallet in sorted_wallets:
        if remaining <= 0:
            break

        # В экстренном режиме берем почти всё, оставляя только минимальный резерв
        max_take = wallet.balance * (1 - min_reserve_percent)
        take_amount = min(max_take, remaining)
        take_amount = round(take_amount, 8)  # Используем большую точность

        if take_amount > 0:
            transfers.append({
                'mnemonic': wallet.mnemonic,
                'tonapi_key': wallet.tonapi_key,
                'address': wallet.address,
                'amount': take_amount
            })
            logger.debug(f'  Донор {wallet.address[:20]}...: баланс={wallet.balance}, взять={take_amount}')
            remaining -= take_amount

    if remaining > 0:
        logger.error(f'Экстренный сбор не смог собрать всю сумму, остаток: {remaining}')
        # Если не удалось собрать всю сумму, возвращаем пустой список
        return []
    else:
        total_collected = sum(t['amount'] for t in transfers)
        logger.info(f'Экстренный сбор завершен: {len(transfers)} доноров, собрано {total_collected} TON')
        return transfers


# # Альтернативная версия с автоматическим расчетом комиссий
# def distribute_collection_advanced(
#         target_amount: float,
#         donor_wallets: List[Wallet],
#         min_reserve_percent: float = 0.1,
#         max_transfer_percent: float = 0.7,
#         round_to_decimals: int = 6
# ) -> List[Dict]:
#     """
#     Продвинутая версия с автоматическим расчетом комиссий
#     """
#     # Базовая комиссия за транзакцию в TON
#     BASE_TX_FEE = 0.01
#
#     # Рассчитываем количество необходимых транзакций
#     # Предполагаем, что каждый донор сделает по 1 транзакции
#     estimated_tx_count = len([w for w in donor_wallets if w.balance > 0])
#
#     # Динамический буфер (чем больше сумма, тем меньше процент буфера)
#     if target_amount > 10:
#         buffer_percent = 0.01  # 0.01% для больших сумм
#     elif target_amount > 1:
#         buffer_percent = 0.05  # 0.05% для средних сумм
#     else:
#         buffer_percent = 0.1  # 0.1% для маленьких сумм
#
#     return distribute_collection(
#         target_amount=target_amount,
#         donor_wallets=donor_wallets,
#         min_reserve_percent=min_reserve_percent,
#         max_transfer_percent=max_transfer_percent,
#         round_to_decimals=round_to_decimals,
#         tx_fee=BASE_TX_FEE,
#         collection_buffer_percent=buffer_percent
#     )
