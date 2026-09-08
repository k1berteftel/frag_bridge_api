from __future__ import annotations

import asyncio
import base64
import ssl
from typing import (
    TYPE_CHECKING,
    Any,
)

from ton_core import (
    Cell,
    NetworkGlobalID,
)
from tonutils.client import TonapiClient
from tonutils.wallet import (
    WalletV4R2
)

from errors import (
    ConfirmationTimeout,
    ProxyError,
    TransactionError,
    WalletError,
)

from constants import (
    CONFIRMATION_INTERVAL,
    CONFIRMATION_MAX_ATTEMPTS,
    MIN_TON_BALANCE,
    TONAPI_BASE_URL,
    TONAPI_DEFAULT_KEY,
    TONAPI_PROXY_BASE
)

from models import (
    Wallet,
    TransactionResult,
    WalletInfo
)
from processors.fastlane.utils.decoder import decode_boc_comment


def _is_proxy_key(api_key: str) -> bool:
    '''Check if api_key is the default proxy key.'''
    return api_key.strip() == TONAPI_DEFAULT_KEY.strip()


def _get_tonapi_kwargs(api_key: str) -> dict[str, Any]:
    '''Build kwargs for TonapiClient constructor.'''
    base_url = (
        TONAPI_PROXY_BASE if _is_proxy_key(api_key) else TONAPI_BASE_URL
    )
    return {
        # "network": NetworkGlobalID.MAINNET,
        "api_key": api_key,
        # "base_url": base_url,
    }


def _check_proxy_error(
    exc: Exception,
    api_key: str,
) -> None:
    '''Raise ProxyError if the exception looks like a connectivity issue.'''
    exc_str = str(exc).lower()
    if _is_proxy_key(api_key) and (
        "connect" in exc_str
        or "timeout" in exc_str
        or "refused" in exc_str
        or "unreachable" in exc_str
    ):
        raise ProxyError(
            ProxyError.PROXY_UNAVAILABLE.format(
                url=TONAPI_PROXY_BASE,
                exc=exc,
            )
        ) from exc


async def _wait_confirmation(
    client: TonapiClient,
    wallet: WalletV4R2,
    initial_seqno: int,
    initial_balance: float,
) -> tuple[bool, int | None, float | None]:
    '''
    Wait for transaction confirmation by checking seqno and balance.

    Polls every CONFIRMATION_INTERVAL seconds for up to
    CONFIRMATION_MAX_ATTEMPTS attempts.

    Confirmation conditions (both must be true):
    1. seqno has incremented (network accepted the transaction)
    2. balance has decreased (TON were actually spent)

    Returns:
        Tuple of (confirmed, current_seqno, current_balance_ton).
    '''
    for _ in range(CONFIRMATION_MAX_ATTEMPTS):
        await asyncio.sleep(CONFIRMATION_INTERVAL)

        try:
            current_seqno = await wallet.get_seqno(client, wallet.address)
            current_balance = await wallet.balance()

            if (
                current_seqno > initial_seqno
                and current_balance < initial_balance
            ):
                return True, current_seqno, current_balance

        except Exception:
            continue

    return False, None, None


async def _run_transaction(
    self_wallet: Wallet,
    transaction_data: dict[str, Any],
) -> TransactionResult:
    '''
    Execute a TON transaction with seqno/balance confirmation.

    Steps:
    1. Parse Fragment transaction payload (addresses, amounts, comments)
    2. Check wallet balance is sufficient (amount + gas)
    3. Record initial seqno and balance
    4. Send the transfer
    5. Wait for seqno increment + balance decrease
    6. Return TransactionResult with BOC for confirmReq

    Retries up to 6 times on rate limits, duplicate messages,
    and seqno conflicts.
    '''
    if (
        "transaction" not in transaction_data
        or "messages" not in transaction_data["transaction"]
    ):
        raise TransactionError(TransactionError.INVALID_PAYLOAD)

    messages = transaction_data["transaction"]["messages"]

    total_amount_ton = (
        sum(float(msg["amount"]) / 1_000_000_000 for msg in messages)
    )

    try:
        ton = TonapiClient(**_get_tonapi_kwargs(self_wallet.tonapi_key))
        wallet, _, _, _ = WalletV4R2.from_mnemonic(
            client=ton,
            mnemonic=self_wallet.mnemonic,
        )

        try:
            balance_ton = await wallet.balance()
            required = total_amount_ton + MIN_TON_BALANCE

            if balance_ton < required:
                raise WalletError(
                    WalletError.LOW_BALANCE.format(
                        balance=balance_ton,
                        required=required,
                        gas=MIN_TON_BALANCE,
                        currency="TON",
                    )
                )
        except WalletError:
            raise
        except Exception as exc:
            _check_proxy_error(exc, self_wallet.tonapi_key)
            raise WalletError(
                WalletError.BALANCE_FAILED.format(exc=exc),
            ) from exc

        destinations = []
        amounts = []
        bodies = []

        print(len(messages))
        print(messages)
        print('\n\n')

        for msg in messages:
            print(msg["address"])
            print(float(msg["amount"]) / 1_000_000_000)
            destinations.append(msg["address"])
            amounts.append(float(msg["amount"]) / 1_000_000_000)

            raw_boc = msg.get("payload", "")
            if raw_boc:
                try:
                    payload = decode_boc_comment(raw_boc)
                except Exception:
                    s = raw_boc.strip().replace("-", "+").replace("_", "/")
                    s += "=" * (-len(s) % 4)
                    payload = Cell.one_from_boc(base64.b64decode(s))
            else:
                payload = ""

            bodies.append(payload)

        for attempt in range(6):
            try:

                initial_seqno = await wallet.get_seqno(ton, wallet.address)
                initial_balance = await wallet.balance()

                result = await wallet.transfer(
                    destination=(
                        destinations
                        if len(destinations) > 1
                        else destinations[0]
                    ),
                    amount=(
                        amounts
                        if len(amounts) > 1
                        else amounts[0]
                    ),
                    body=(
                        bodies
                        if len(bodies) > 1
                        else bodies[0]
                    ),
                )

                tx_hash = result

                boc_b64: str | None = None
                try:
                    if hasattr(result, "boc"):
                        boc_b64 = base64.b64encode(
                            result.boc,
                        ).decode("utf-8")
                    elif hasattr(result, "to_boc"):
                        boc_b64 = base64.b64encode(
                            result.to_boc(),
                        ).decode("utf-8")
                except Exception:
                    pass

                confirmed, final_seqno, final_balance = (
                    await _wait_confirmation(
                        ton,
                        wallet,
                        initial_seqno,
                        initial_balance,
                    )
                )

                if not confirmed:
                    raise ConfirmationTimeout(
                        ConfirmationTimeout.TIMEOUT.format(
                            seconds=int(
                                CONFIRMATION_INTERVAL
                                * CONFIRMATION_MAX_ATTEMPTS
                            ),
                            seqno_before=initial_seqno,
                            balance_before=initial_balance,
                        )
                    )

                return TransactionResult(
                    tx_hash=tx_hash,
                    boc=boc_b64,
                    seqno_before=initial_seqno,
                    seqno_after=final_seqno,
                    balance_before=initial_balance,
                    balance_after=final_balance,
                    confirmed=confirmed,
                )

            except ConfirmationTimeout:
                raise
            except Exception as exc:
                exc_str = str(exc).lower()
                if attempt < 5:
                    await asyncio.sleep(4)
                    continue
                raise
            except (
                WalletError,
                TransactionError,
            ):
                raise

    except (
        WalletError,
        TransactionError,
        ProxyError,
        ConfirmationTimeout,
    ):
        raise
    except Exception as exc:
        _check_proxy_error(exc, self_wallet.tonapi_key)
        raise TransactionError(
            TransactionError.BROADCAST_FAILED.format(exc=exc),
        ) from exc

    raise TransactionError(
        TransactionError.BROADCAST_FAILED.format(
            exc="transfer loop exited without result",
        )
    )


async def _get_account_info(
    self_wallet: Wallet,
) -> dict[str, Any]:
    '''Get wallet account info for Fragment API requests.'''
    try:
        ton = TonapiClient(**_get_tonapi_kwargs(self_wallet.tonapi_key))
        wallet, pub_key, _, _ = WalletV4R2.from_mnemonic(
            client=ton,
            mnemonic=self_wallet.mnemonic,
        )
        boc = wallet.state_init.serialize().to_boc()
        return {
            "address": wallet.address.to_str(False, False),
            "publicKey": pub_key.hex(),
            "chain": "-239",
            "walletStateInit": base64.b64encode(boc).decode(),
        }
    except Exception as exc:
        _check_proxy_error(exc, self_wallet.tonapi_key)
        raise WalletError(
            WalletError.ACCOUNT_INFO_FAILED.format(exc=exc),
        ) from exc


async def _get_wallet_info(
    self_wallet: Wallet,
) -> WalletInfo:
    '''Get full wallet info including TON and USDT balances.'''
    try:
        ton = TonapiClient(**_get_tonapi_kwargs(self_wallet.tonapi_key))
        wallet, _, _, _ = WalletV4R2.from_mnemonic(
            client=ton,
            mnemonic=self_wallet.mnemonic,
        )

        balance_ton = round(await wallet.balance(), 4)

        return WalletInfo(
            address=wallet.address.to_str(
                is_user_friendly=True,
                is_bounceable=False,
            ),
            state=str(wallet.state_init),
            balance_ton=balance_ton
        )
    except WalletError:
        raise
    except Exception as exc:
        _check_proxy_error(exc, self_wallet.tonapi_key)
        raise WalletError(
            WalletError.WALLET_INFO_FAILED.format(exc=exc),
        ) from exc


async def execute_transaction(
    wallet: Wallet,
    transaction_data: dict[str, Any],
) -> TransactionResult:
    '''
    Execute a TON transaction with seqno/balance confirmation.

    Returns TransactionResult containing tx_hash and BOC
    for use with confirmReq.
    '''
    return await _run_transaction(
        wallet,
        transaction_data,
    )


async def build_account_info(
    wallet: Wallet,
) -> dict[str, Any]:
    '''Build wallet account info dict for Fragment API requests.'''
    return await _get_account_info(
        wallet
    )


async def fetch_wallet_info(
    wallet: Wallet
) -> WalletInfo:
    '''Fetch full wallet information including balances.'''
    return await _get_wallet_info(
        wallet
    )
