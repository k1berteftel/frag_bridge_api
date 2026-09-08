import asyncio
import base64
import random
import ssl
from typing import TYPE_CHECKING, Any

from ton_core import NetworkGlobalID, Cell
from tonutils.wallet import WalletV4R2
from tonutils.client import TonapiClient

from processors.fastlane.utils.wallet import check_ton_payment_balance
from constants import MIN_TON_BALANCE
from models import Wallet
from errors import WalletError, ParseError, TransactionError


def clean_decode(payload: str) -> str | Cell:
    """Decode a base64-encoded BOC payload to a plain-text comment string."""
    s = payload.strip()
    if not s:
        return ""
    s += "=" * (-len(s) % 4)
    try:
        boc = base64.b64decode(s, altchars=b"-_", validate=True)
        cell = Cell.one_from_boc(boc)
        sl = cell.begin_parse()
        op = sl.load_uint(32)
        if op != 0:
            # Non-zero op code means this is a structured message (e.g. jetton transfer),
            # not a plain text comment — return the full cell as-is.
            return cell
        try:
            return sl.load_snake_string().strip()
        except UnicodeDecodeError:
            return cell
    except Exception as exc:
        raise ParseError(ParseError.UNPARSEABLE.format(context="payload decode", exc=exc)) from exc


async def process_transaction(
    wallet: Wallet,
    transaction_data: dict[str, Any],
    required_payment_amount: float | None = None,
) -> str:
    if "transaction" not in transaction_data or not transaction_data["transaction"].get("messages"):
        raise TransactionError(TransactionError.INVALID_PAYLOAD)

    message = transaction_data["transaction"]["messages"][0]
    amount_ton = int(message["amount"]) / 1_000_000_000

    async with TonapiClient(api_key=wallet.tonapi_key) as ton:
        wallet, _, _, _ = WalletV4R2.from_mnemonic(client=ton, mnemonic=wallet.mnemonic)

        # Check balance covers selected payment flow requirements.
        try:
            balance_ton = (await wallet.balance()) / 1_000_000_000
            wallet.address.to_str(False, False)
            await check_ton_payment_balance(balance_ton, amount_ton, required_payment_amount)
        except WalletError:
            raise
        except Exception as exc:
            raise WalletError(WalletError.TON_BALANCE_CHECK_FAILED.format(exc=exc)) from exc

        try:
            raw_payload = str(message.get("payload", ""))
            payload = clean_decode(raw_payload)

            for attempt in range(3):
                try:
                    result = await wallet.transfer(
                        destination=message["address"],
                        amount=int(message["amount"]),  # nanotons, not TON
                        body=payload
                    )
                    return str(result)
                except Exception as e:
                    error_msg = str(e)

                    # Обработка ошибок seqno
                    if "Duplicate msg_seqno" in error_msg or "Too old seqno" in error_msg:
                        if attempt < 2:
                            await asyncio.sleep(5)
                            continue

                    elif "Connection reset" in error_msg:
                        await asyncio.sleep(5)
                        if attempt <= 1:
                            continue
                        raise TransactionError(TransactionError.DUPLICATE_SEQNO) from e
                    raise
        except (WalletError, TransactionError):
            raise
        except Exception as exc:
            cause: BaseException | None = exc
            while cause is not None:
                if isinstance(cause, ssl.SSLError):
                    raise TransactionError(TransactionError.BROADCAST_FAILED_SSL.format(exc=exc)) from exc
                cause = cause.__cause__ or cause.__context__
            raise TransactionError(TransactionError.BROADCAST_FAILED.format(exc=exc)) from exc

    raise TransactionError(TransactionError.BROADCAST_FAILED.format(exc="transfer loop exited without result"))