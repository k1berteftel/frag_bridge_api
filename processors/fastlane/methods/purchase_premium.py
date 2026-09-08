from __future__ import annotations

import httpx
import json
import time
from typing import TYPE_CHECKING, get_args

from errors import (
    ConfigurationError,
    FragmentAPIError,
    UnexpectedError,
    UserNotFoundError,
    VerificationError,
    FragmentBaseError
)
from models import PremiumResult, Wallet, EvmPaymentResult
from processors.fastlane.utils.http import build_headers, fetch_fragment_hash, post_FragmentAPI
from processors.fastlane.utils.evm import fetch_evm_invoice
from processors.fastlane.utils.api import confirm_request #, call
from processors.fastlane.utils.wallet import build_account_info, execute_transaction
from utils.transaction import get_total_debit

from constants import DEVICE_FINGERPRINT, EVM_PAYMENT_METHODS, PREMIUM_GIFT_PAGE, TON_PAYMENT_METHODS, DEFAULT_TIMEOUT


async def purchase_premium(
    wallet: Wallet,
    username: str,
    months: int,
    show_sender: bool = False,
    payment_method: str = "ton",
) -> PremiumResult | EvmPaymentResult:
    '''
    Gift Telegram Premium to a user.

    Supports TON, USDT (TON), and EVM-based payments
    (USDT/USDC on ETH/BASE/POL).
    '''
    if months not in (3, 6, 12):
        raise ConfigurationError(ConfigurationError.INVALID_MONTHS)

    try:
        headers = build_headers(PREMIUM_GIFT_PAGE)

        async with httpx.AsyncClient(
            cookies=wallet.cookies.to_dict(),
            timeout=DEFAULT_TIMEOUT,
        ) as session:
            # fragment_hash = await fetch_fragment_hash(
            #     wallet.cookies.to_dict(),
            #     headers,
            #     PREMIUM_GIFT_PAGE,
            #     DEFAULT_TIMEOUT,
            # )

            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "searchPremiumGiftRecipient",
                    "query": username,
                    "months": months,
                },
            )
            recipient = result.get("found", {}).get("recipient")
            if not recipient:
                raise UserNotFoundError(
                    UserNotFoundError.NOT_FOUND.format(username=username),
                )

            await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "updatePremiumState",
                    "mode": "new",
                    "lv": "false",
                    "dh": str(int(time.time())),
                },
            )

            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "initGiftPremiumRequest",
                    "recipient": recipient,
                    "months": str(months),
                    "payment_method": payment_method,
                },
            )
            if result.get("error"):
                raise FragmentAPIError(result["error"])

            req_id = result.get("req_id")
            if not req_id:
                raise FragmentAPIError(
                    FragmentAPIError.NO_REQUEST_ID.format(
                        context="Premium purchase",
                    )
                )

            account = await build_account_info(wallet)
            transaction = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "getGiftPremiumLink",
                    "account": json.dumps(account),
                    "device": DEVICE_FINGERPRINT,
                    "transaction": 1,
                    "id": req_id,
                    "show_sender": int(show_sender),
                },
            )
            if transaction.get("need_verify"):
                raise VerificationError(VerificationError.KYC_REQUIRED)

        if payment_method in EVM_PAYMENT_METHODS or transaction.get("evm"):
            invoice = await fetch_evm_invoice(
                cookies=wallet.cookies.to_dict(),
                page_path="/premium/gift",
                recipient=recipient,
                payment_method=payment_method,
                months=months,
                timeout=DEFAULT_TIMEOUT,
            )
            return EvmPaymentResult(
                item_kind="premium",
                target=username,
                amount=months,
                payment_method=payment_method,
                invoice=invoice,
            )

        if payment_method not in TON_PAYMENT_METHODS:
            raise FragmentAPIError(
                f"Unsupported payment_method flow: {payment_method}"
            )

        tx_result = await execute_transaction(wallet, transaction)

        if tx_result.boc and req_id:
            try:
                await confirm_request(
                    wallet,
                    req_id,
                    tx_result.boc,
                    referer="premium/gift",
                )
            except Exception:
                pass

        total_cost, total_fees = await get_total_debit(tx_result.tx_hash, wallet.tonapi_key)

        return PremiumResult(
            transaction_id=tx_result.tx_hash,
            username=username,
            amount=months,
            cost=total_cost,
            fee=total_fees,
            payment_method=payment_method,
        )

    except FragmentBaseError:
        raise
    except Exception as exc:
        raise UnexpectedError(
            UnexpectedError.UNEXPECTED.format(exc=exc),
        ) from exc