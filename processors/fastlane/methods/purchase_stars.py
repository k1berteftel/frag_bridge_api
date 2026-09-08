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
from models import StarsResult, Wallet, EvmPaymentResult
from processors.fastlane.utils.http import build_headers, fetch_fragment_hash, post_FragmentAPI
from processors.fastlane.utils.evm import fetch_evm_invoice
from processors.fastlane.utils.api import confirm_request #, call
from processors.fastlane.utils.wallet import build_account_info, execute_transaction
from utils.transaction import get_total_debit

from constants import DEVICE_FINGERPRINT, EVM_PAYMENT_METHODS, STARS_PAGE, TON_PAYMENT_METHODS, DEFAULT_TIMEOUT


async def purchase_stars(
    wallet: Wallet,
    username: str,
    amount: int,
    show_sender: bool = False,
    payment_method: str = "ton",
) -> StarsResult | EvmPaymentResult:
    '''
    Send Telegram Stars to a user.

    Args:
        payment_method: One of "ton", "usdt_ton", "usdt_eth", "usdt_pol",
            "usdc_eth", "usdc_base", "usdc_pol".

    Returns:
        StarsResult (for TON-based methods) or EvmPaymentResult
        (for EVM methods — caller must complete payment manually).
    '''
    if not isinstance(amount, int) or not (50 <= amount <= 1_000_000):
        raise ConfigurationError(ConfigurationError.INVALID_STARS_AMOUNT)

    try:
        headers = build_headers(STARS_PAGE)

        async with httpx.AsyncClient(
            cookies=wallet.cookies.to_dict(),
            timeout=DEFAULT_TIMEOUT,
        ) as session:
            # fragment_hash = await fetch_fragment_hash(
            #     client.cookies,
            #     headers,
            #     STARS_PAGE,
            #     DEFAULT_TIMEOUT,
            # )

            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "searchStarsRecipient",
                    "query": username,
                    "quantity": "",
                },
            )
            recipient = result.get("found", {}).get("recipient")
            if not recipient:
                raise UserNotFoundError(
                    UserNotFoundError.NOT_FOUND.format(username=username),
                )

            print(wallet.id)
            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "initBuyStarsRequest",
                    "recipient": recipient,
                    "quantity": str(amount),
                    "payment_method": payment_method,
                },
            )
            if result.get("error"):
                raise FragmentAPIError(result["error"])

            req_id = result.get("req_id")
            if not req_id:
                raise FragmentAPIError(
                    FragmentAPIError.NO_REQUEST_ID.format(
                        context="Stars purchase",
                    )
                )

            account = await build_account_info(wallet)
            transaction = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "getBuyStarsLink",
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
                page_path="/stars/buy",
                recipient=recipient,
                payment_method=payment_method,
                quantity=amount,
                timeout=DEFAULT_TIMEOUT,
            )
            return EvmPaymentResult(
                item_kind="stars",
                target=username,
                amount=amount,
                payment_method=payment_method,
                invoice=invoice,
            )

        if payment_method not in TON_PAYMENT_METHODS:
            raise FragmentAPIError(
                f"Unsupported payment_method flow: {payment_method}"
            )

        # print(f'result before execute transaction: {transaction}')
        # print(transaction['transaction']['messages'][0])
        # print(transaction['transaction']['messages'][0]['amount'])
        # print(float(transaction['transaction']['messages'][0].get('amount')) / 1_000_000_000)
        tx_result = await execute_transaction(wallet, transaction)

        if tx_result.boc and req_id:
            try:
                await confirm_request(
                    wallet,
                    req_id,
                    tx_result.boc,
                    referer="stars/buy",
                )
            except Exception:
                pass

        total_cost, total_fees = await get_total_debit(tx_result.tx_hash, wallet.tonapi_key)

        return StarsResult(
            transaction_id=tx_result.tx_hash,
            username=username,
            amount=amount,
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