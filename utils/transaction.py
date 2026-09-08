import asyncio
import logging
import aiohttp
from decimal import Decimal
from typing import List, Dict, Tuple, Optional

import tonutils.client
import tonutils.wallet
from ton_core import Cell, Address

logger = logging.getLogger(__name__)


async def check_transaction(
        tx_hash: str,
        TONAPI_KEY: str,
        max_attempts: int = 15,
        base_delay: float = 2.0
) -> bool:
    """
    Валидация транзакции в TON через tonapi.io по хешу транзакции
    """
    if not tx_hash or not isinstance(tx_hash, str):
        logger.error(f"Invalid tx_hash: {tx_hash}")
        return False

    attempts = 0
    url = f"https://tonapi.io/v2/blockchain/transactions/{tx_hash}"

    headers = {
        "Authorization": f"Bearer {TONAPI_KEY}",
        "Accept": "application/json",
    }

    current_delay = base_delay
    max_delay = 15
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while attempts < max_attempts:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        logger.debug(f"Tx {tx_hash[:8]} not indexed (attempt {attempts + 1})")
                        attempts += 1
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 1.5, max_delay)
                        continue

                    if resp.status != 200:
                        if resp.status == 429:
                            await asyncio.sleep(min(current_delay * 2, max_delay))
                            current_delay = min(current_delay * 2, max_delay)
                        attempts += 1
                        continue

                    data = await resp.json()

                    # Проверяем, есть ли исходящие сообщения (транзакция должна их иметь для успеха)
                    out_msgs = data.get("out_msgs", [])
                    if not out_msgs or len(out_msgs) == 0:
                        logger.debug(f"Tx {tx_hash[:8]} has no outgoing messages - transaction failed to deliver")
                        return False

                    # Проверяем успешность транзакции
                    if not data.get("success", False):
                        logger.debug(f"Tx {tx_hash[:8]} marked as unsuccessful")
                        return False

                    compute_phase = data.get("compute_phase", {})
                    if not compute_phase.get("success", False):
                        exit_code = compute_phase.get("exit_code", "unknown")
                        logger.debug(f"Tx {tx_hash[:8]} compute phase failed (exit_code: {exit_code})")
                        return False

                    action_phase = data.get("action_phase")
                    if action_phase is not None:
                        if not action_phase.get("success", False):
                            logger.debug(f"Tx {tx_hash[:8]} action phase failed")
                            return False

                    if data.get("aborted", False):
                        logger.debug(f"Tx {tx_hash[:8]} was aborted")
                        return False

                    logger.info(f"Tx {tx_hash[:8]} successfully validated (out_msgs: {len(out_msgs)})")
                    return True

            except asyncio.TimeoutError:
                logger.debug(f"Timeout for tx {tx_hash[:8]} (attempt {attempts + 1})")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)

            except Exception as e:
                logger.debug(f"Error for tx {tx_hash[:8]}: {e}")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)

    logger.warning(f"Tx {tx_hash[:8]} not found after {max_attempts} attempts")
    return False


async def get_transaction_amount(
        tx_hash: str,
        tonapi_key: str,
        raw_address: str,
        max_attempts: int = 15,
        base_delay: float = 2.0
) -> Decimal:
    """
    Получает точную сумму перевода на указанный адрес из транзакции.
    Работает только для обычных (одиночных транзакций).

    Args:
        tx_hash: Хеш транзакции
        tonapi_key: API ключ Tonapi
        raw_address: Адрес получателя (в любом формате)
        max_attempts: Максимальное количество попыток
        base_delay: Базовая задержка между попытками

    Returns:
        Decimal: Сумма в TON
    """
    if not tx_hash or not isinstance(tx_hash, str):
        logger.error(f"Invalid tx_hash: {tx_hash}")
        return Decimal(0)

    attempts = 0
    url = f"https://tonapi.io/v2/blockchain/transactions/{tx_hash}"

    headers = {
        "Authorization": f"Bearer {tonapi_key}",
        "Accept": "application/json",
    }

    current_delay = base_delay
    max_delay = 15
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while attempts < max_attempts:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        logger.debug(f"Tx {tx_hash[:8]} not indexed (attempt {attempts + 1})")
                        attempts += 1
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 1.5, max_delay)
                        continue

                    if resp.status != 200:
                        if resp.status == 429:
                            await asyncio.sleep(min(current_delay * 2, max_delay))
                            current_delay = min(current_delay * 2, max_delay)
                        attempts += 1
                        continue

                    data = await resp.json()

                    # Проверяем out_msgs
                    out_msgs = data.get('out_msgs', [])

                    for msg in out_msgs:
                        # 1. Обычный перевод
                        dest = msg.get('destination', {})
                        if dest.get('address') == raw_address:
                            amount_nano = int(msg.get('value', 0))
                            amount_ton = Decimal(amount_nano) / Decimal(1_000_000_000)
                            logger.info(f"Found direct transfer: {amount_ton} TON")
                            return amount_ton

                    logger.error(f"Данных по транзакции не найдено")
                    return Decimal(0)

            except asyncio.TimeoutError:
                logger.debug(f"Timeout for tx {tx_hash[:8]} (attempt {attempts + 1})")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)
            except Exception as e:
                logger.debug(f"Error for tx {tx_hash[:8]}: {e}")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)

    return Decimal(0)


async def get_total_debit(tx_hash: str, tonapi_key: str) -> tuple[Decimal, Decimal]:
    """
    Получает итоговую сумму списания с кошелька по хешу транзакции.

    Args:
        tx_hash: Хеш транзакции
        tonapi_key: API ключ Tonapi

    Returns:
        Decimal: Итоговая сумма списания в TON (переводы + комиссии)
    """
    if not tx_hash or not isinstance(tx_hash, str):
        logger.error(f"Invalid tx_hash: {tx_hash}")
        return Decimal(0), Decimal(0)

    url = f"https://tonapi.io/v2/blockchain/transactions/{tx_hash}"

    headers = {
        "Authorization": f"Bearer {tonapi_key}",
        "Accept": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        for attempt in range(15):
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        await asyncio.sleep(2)
                        continue

                    if resp.status != 200:
                        await asyncio.sleep(2)
                        continue

                    data = await resp.json()

                    # Сумма всех исходящих переводов
                    total_out = 0
                    for msg in data.get('out_msgs', []):
                        total_out += int(msg.get('value', 0))

                    # Общая комиссия
                    total_fees = int(data.get('total_fees', 0))

                    logger.info(
                        f"Total debit: {Decimal(total_out + total_fees) / Decimal(1_000_000_000)} TON (transfers: {Decimal(total_out) / Decimal(1_000_000_000)} TON, fees: {Decimal(total_fees) / Decimal(1_000_000_000)} TON)")

                    return Decimal(total_out) / Decimal(1_000_000_000), Decimal(total_fees) / Decimal(1_000_000_000)

            except Exception as e:
                logger.error(f"Error getting tx {tx_hash}: {e}")
                await asyncio.sleep(2)

    logger.warning(f"Transaction {tx_hash} not found after 15 attempts")
    return Decimal(0), Decimal(0)


async def send_from_wallet(
        client,
        mnemonic: List[str],
        target_address: str,
        amount: float,
        tonapi_key: str,
        retry_count: int = 0,
        max_retries: int = 4
) -> Tuple[bool, Optional[str]]:
    """
    Отправляет средства с одного кошелька на целевой адрес

    Args:
        client: TonapiClient (уже созданный)
        mnemonic: мнемоника кошелька-отправителя
        target_address: адрес получателя
        amount: сумма для отправки
        tonapi_key: API ключ для проверки транзакции
        retry_count: текущая попытка
        max_retries: максимальное количество попыток

    Returns:
        Tuple[bool, Optional[str]]: (успех, хеш_транзакции или None)
    """
    if amount <= 0:
        logger.debug(f'Пропуск отправки {amount} TON на {target_address[:20]}...')
        return True, None

    try:
        # Создаем кошелек отправителя
        wallet, _, _, _ = tonutils.wallet.WalletV4R2.from_mnemonic(
            client,
            mnemonic=mnemonic
        )

        # Получаем актуальный seqno
        seqno = await wallet.get_seqno(client, wallet.address)
        logger.info(f'  Seqno перед отправкой: {seqno}')

        # Отправляем транзакцию
        tx_hash = await wallet.transfer(
            destination=target_address,
            amount=amount,
            comment='Funds collection for task execution'
        )

        logger.info(f'  Транзакция отправлена, хеш: {tx_hash[:16]}...')

        # Ждем начальной задержки для индексации
        await asyncio.sleep(3)

        # Проверяем транзакцию через check_transaction
        is_confirmed = await check_transaction(
            tx_hash=tx_hash,
            TONAPI_KEY=tonapi_key,
            max_attempts=40,
            base_delay=2.0
        )

        if is_confirmed:
            logger.info(f'  ✅ Транзакция подтверждена')
            return True, tx_hash
        else:
            logger.error(f'  ❌ Транзакция не подтвердилась')

            if retry_count < max_retries:
                logger.info(f'  Повторная попытка {retry_count + 1}/{max_retries}...')
                await asyncio.sleep(5)
                return await send_from_wallet(
                    client, mnemonic, target_address, amount, tonapi_key,
                    retry_count + 1, max_retries
                )
            return False, tx_hash

    except Exception as e:
        error_msg = str(e)

        # Обработка ошибок seqno
        if "Duplicate msg_seqno" in error_msg or "Too old seqno" in error_msg:
            if retry_count < max_retries:
                logger.error(f'  Ошибка seqno: {error_msg}')
                logger.info(f'  Повторная попытка {retry_count + 1}/{max_retries}, ждем 5 секунд...')
                await asyncio.sleep(5)
                return await send_from_wallet(
                    client, mnemonic, target_address, amount, tonapi_key,
                    retry_count + 1, max_retries
                )
            else:
                logger.error(f'  Не удалось отправить после {max_retries} попыток')
                return False, None

        elif "Connection reset" in error_msg:
            logger.error(f'  Ошибка соединения, повтор через 5 секунд...')
            await asyncio.sleep(5)
            if retry_count < max_retries:
                return await send_from_wallet(
                    client, mnemonic, target_address, amount, tonapi_key,
                    retry_count + 1, max_retries
                )
            return False, None
        else:
            logger.error(f'  Неизвестная ошибка: {error_msg}')
            return False, None


async def collect_funds_from_seeds_string(
        target_address: str,
        source_wallets: List[Dict],
        target_amount: float
) -> Dict:
    """
    Собирает средства с донорских кошельков на целевой кошелек

    Args:
        target_address: адрес целевого кошелька
        source_wallets: список словарей с данными донорских кошельков
                       каждый словарь должен содержать:
                       - 'mnemonic': List[str] - мнемоника кошелька
                       - 'amount': float - сумма для отправки
                       - 'tonapi_key': str - API ключ для проверки транзакции
                       - 'address': str (опционально) - адрес для логирования
        target_amount: общая целевая сумма (для логирования)

    Returns:
        Dict: {
            status: bool,
            error: str (пустая строка если ошибок нет)
        }
    """
    if not source_wallets:
        error_msg = "Список донорских кошельков пуст"
        logger.error(error_msg)
        return {
            'status': False,
            'error': error_msg
        }

    logger.info(f'Начинаем сбор {target_amount} TON на кошелек {target_address[:20]}...')
    logger.info(f'Количество доноров: {len(source_wallets)}')

    # Отправляем транзакции последовательно для надежности
    for i, wallet_info in enumerate(source_wallets):
        # Извлекаем данные из словаря
        mnemonic = wallet_info.get('mnemonic')
        amount = wallet_info.get('amount', 0)
        tonapi_key = wallet_info.get('tonapi_key')
        donor_address = wallet_info.get('address', f'донор_{i + 1}')

        # Проверяем обязательные поля
        if not mnemonic:
            error_msg = f'Отсутствует мнемоника для донора {i + 1}'
            logger.error(error_msg)
            return {
                'status': False,
                'error': error_msg
            }

        if not tonapi_key:
            error_msg = f'Отсутствует tonapi_key для донора {i + 1}'
            logger.error(error_msg)
            return {
                'status': False,
                'error': error_msg
            }

        if amount <= 0:
            logger.info(
                f'  Донор {i + 1}/{len(source_wallets)} ({donor_address[:20]}...): сумма {amount} <= 0, пропускаем')
            continue

        logger.info(f'  Донор {i + 1}/{len(source_wallets)} ({donor_address[:20]}...): отправка {amount} TON')

        try:
            # Создаем клиент для донора
            client = tonutils.client.TonapiClient(api_key=tonapi_key)

            success, tx_hash = await send_from_wallet(
                client=client,
                mnemonic=mnemonic,
                target_address=target_address,
                amount=amount,
                tonapi_key=tonapi_key,
                max_retries=4
            )

            if success:
                logger.info(f'  ✅ Донор {i + 1}/{len(source_wallets)} успешно отправил {amount} TON')
            else:
                error_msg = f'Донор {i + 1} не смог отправить {amount} TON после всех попыток'
                logger.error(f'  ❌ {error_msg}')
                return {
                    'status': False,
                    'error': error_msg
                }

        except Exception as e:
            error_msg = f'Ошибка при обработке донора {i + 1}: {e}'
            logger.error(f'  ❌ {error_msg}')
            return {
                'status': False,
                'error': error_msg
            }

        # Задержка между транзакциями для избежания проблем с seqno
        if i < len(source_wallets) - 1:
            await asyncio.sleep(2)

    # Все транзакции успешны
    total_collected = sum(
        wallet_info.get('amount', 0) for wallet_info in source_wallets if wallet_info.get('amount', 0) > 0)
    logger.info(f'✅ Сбор средств успешно завершен! Собрано {total_collected} TON на кошелек {target_address[:20]}...')

    return {
        'status': True,
        'error': ''
    }


# Альтернативная версия с параллельной отправкой (для больших объемов)
async def collect_funds_from_seeds_string_parallel(
        target_address: str,
        source_wallets: List[Dict],
        target_amount: float,
        max_concurrent: int = 3
) -> Dict:
    """
    Собирает средства с донорских кошельков параллельно

    Args:
        target_address: адрес целевого кошелька
        source_wallets: список словарей с данными донорских кошельков
                       каждый словарь должен содержать:
                       - 'mnemonic': List[str] - мнемоника кошелька
                       - 'amount': float - сумма для отправки
                       - 'tonapi_key': str - API ключ для проверки транзакции
                       - 'address': str (опционально) - адрес для логирования
        target_amount: общая целевая сумма
        max_concurrent: максимальное количество параллельных отправок

    Returns:
        Dict: {status: bool, error: str}
    """
    if not source_wallets:
        return {
            'status': False,
            'error': "Список донорских кошельков пуст"
        }

    # Фильтруем только доноров с положительной суммой
    valid_donors = [w for w in source_wallets if w.get('amount', 0) > 0]

    if not valid_donors:
        logger.warning("Нет доноров с положительной суммой для отправки")
        return {
            'status': True,
            'error': ''
        }

    logger.info(f'Начинаем параллельный сбор {target_amount} TON на {target_address[:20]}...')
    logger.info(f'Количество доноров: {len(valid_donors)}, максимум параллельных: {max_concurrent}')

    # Создаем семафор для ограничения параллельных отправок
    semaphore = asyncio.Semaphore(max_concurrent)

    async def send_with_semaphore(wallet_info, index):
        async with semaphore:
            mnemonic = wallet_info.get('mnemonic')
            amount = wallet_info.get('amount', 0)
            tonapi_key = wallet_info.get('tonapi_key')
            donor_address = wallet_info.get('address', f'донор_{index + 1}')

            # Проверяем обязательные поля
            if not mnemonic:
                return {
                    'success': False,
                    'index': index,
                    'address': donor_address,
                    'amount': amount,
                    'error': 'Missing mnemonic'
                }

            if not tonapi_key:
                return {
                    'success': False,
                    'index': index,
                    'address': donor_address,
                    'amount': amount,
                    'error': 'Missing tonapi_key'
                }

            logger.info(f'  Донор {index + 1}/{len(valid_donors)} ({donor_address[:20]}...): отправка {amount} TON')

            try:
                client = tonutils.client.TonapiClient(api_key=tonapi_key)

                success, tx_hash = await send_from_wallet(
                    client=client,
                    mnemonic=mnemonic,
                    target_address=target_address,
                    amount=amount,
                    tonapi_key=tonapi_key,
                    max_retries=4
                )

                if success:
                    logger.info(f'  ✅ Донор {index + 1}/{len(valid_donors)} успешно отправил {amount} TON')
                    return {
                        'success': True,
                        'index': index,
                        'address': donor_address,
                        'amount': amount,
                        'tx_hash': tx_hash
                    }
                else:
                    return {
                        'success': False,
                        'index': index,
                        'address': donor_address,
                        'amount': amount,
                        'error': 'Transaction failed after retries'
                    }

            except Exception as e:
                logger.error(f'  ❌ Ошибка донора {index + 1}: {e}')
                return {
                    'success': False,
                    'index': index,
                    'address': donor_address,
                    'amount': amount,
                    'error': str(e)
                }

    # Запускаем все отправки параллельно
    tasks = [send_with_semaphore(wallet_info, i) for i, wallet_info in enumerate(valid_donors)]
    results = await asyncio.gather(*tasks)

    # Анализируем результаты
    failed = [r for r in results if not r.get('success')]

    if failed:
        # Если есть неудачные транзакции, возвращаем ошибку
        total_failed_amount = sum(f['amount'] for f in failed)
        error_msg = f'Не удалось отправить {total_failed_amount} TON от {len(failed)} доноров'
        logger.error(error_msg)

        # Логируем детали неудач
        for f in failed:
            logger.error(f'  - Донор {f["index"] + 1}: {f["amount"]} TON, ошибка: {f.get("error")}')

        return {
            'status': False,
            'error': error_msg
        }

    # Все транзакции успешны
    total_collected = sum(r['amount'] for r in results)
    logger.info(f'✅ Параллельный сбор средств успешно завершен! Собрано {total_collected} TON')

    return {
        'status': True,
        'error': ''
    }


async def get_transaction_total_debit(
        tx_hash: str,
        tonapi_key: str,
        sender_address: str,  # адрес отправителя (ваш Highload Wallet)
        max_attempts: int = 15,
        base_delay: float = 2.0
) -> Tuple[bool, Decimal, Decimal, Decimal]:
    """
    Получает полную сумму списания с кошелька с учетом всех комиссий.

    Returns:
        Tuple[found: bool, total_debit: Decimal, transfer_amount: Decimal, fees: Decimal]
        - total_debit: полная сумма списания (перевод + комиссии)
        - transfer_amount: сумма перевода получателю
        - fees: общая комиссия
    """
    if not tx_hash or not isinstance(tx_hash, str):
        logger.error(f"Invalid tx_hash: {tx_hash}")
        return False, Decimal(0), Decimal(0), Decimal(0)

    attempts = 0
    url = f"https://tonapi.io/v2/blockchain/transactions/{tx_hash}"

    headers = {
        "Authorization": f"Bearer {tonapi_key}",
        "Accept": "application/json",
    }

    current_delay = base_delay
    max_delay = 15
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while attempts < max_attempts:
            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 404:
                        logger.debug(f"Tx {tx_hash[:8]} not indexed (attempt {attempts + 1})")
                        attempts += 1
                        await asyncio.sleep(current_delay)
                        current_delay = min(current_delay * 1.5, max_delay)
                        continue

                    if resp.status != 200:
                        if resp.status == 429:
                            await asyncio.sleep(min(current_delay * 2, max_delay))
                            current_delay = min(current_delay * 2, max_delay)
                        attempts += 1
                        continue

                    data = await resp.json()

                    # 1. Получаем общую сумму комиссии
                    total_fees = Decimal(data.get('total_fees', 0)) / Decimal(1_000_000_000)
                    logger.info(f"💰 Total fees: {total_fees} TON")

                    # 2. Получаем out_msgs для суммы перевода
                    out_msgs = data.get('out_msgs', [])
                    transfer_sum = Decimal(0)
                    transfer_count = 0

                    for msg in out_msgs:
                        # Проверяем, что это исходящий перевод от нашего кошелька
                        source = msg.get('source', {})
                        if source.get('address') == sender_address:
                            amount_nano = int(msg.get('value', 0))
                            amount_ton = Decimal(amount_nano) / Decimal(1_000_000_000)
                            transfer_sum += amount_ton
                            transfer_count += 1
                            logger.info(
                                f"📤 Transfer {transfer_count}: {amount_ton} TON to {msg.get('destination', {}).get('address')}")

                    # 3. Полная сумма списания = сумма переводов + комиссия
                    total_debit = transfer_sum + total_fees

                    logger.info(f"📊 Итог:")
                    logger.info(f"  Сумма переводов: {transfer_sum} TON")
                    logger.info(f"  Комиссия: {total_fees} TON")
                    logger.info(f"  Полное списание: {total_debit} TON")

                    return True, total_debit, transfer_sum, total_fees

            except asyncio.TimeoutError:
                logger.debug(f"Timeout for tx {tx_hash[:8]} (attempt {attempts + 1})")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)

            except Exception as e:
                logger.debug(f"Error for tx {tx_hash[:8]}: {e}")
                attempts += 1
                await asyncio.sleep(current_delay)
                current_delay = min(current_delay * 1.5, max_delay)

    logger.warning(f"Tx {tx_hash[:8]} not found after {max_attempts} attempts")
    return False, Decimal(0), Decimal(0), Decimal(0)


async def test(
        max_attempts: int = 15,
        base_delay: float = 2.0
):
    tonapi_key = 'AEJ5FNA6RYFWBMQAAAAGTZI7I5E5HTVKEPT7654LPITWWH3MYGT3SH6RDRQSKUIGLECQ6WQ'
    tx_hash = 'b20124ff4b10c535dddaefb2a2cb31111d7496859c713728721f8ea5fbec15f4'
    result = await get_total_debit(tx_hash, tonapi_key)
    print(result)


# asyncio.run(test())

