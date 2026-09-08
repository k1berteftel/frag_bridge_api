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
from models import AdsTopupResult, Wallet, EvmPaymentResult
from processors.fastlane.utils.http import build_headers, fetch_fragment_hash, post_FragmentAPI
from processors.fastlane.utils.evm import fetch_evm_invoice
from processors.fastlane.utils.api import confirm_request #, call
from processors.fastlane.utils.wallet import build_account_info, execute_transaction
from utils.transaction import get_total_debit

from constants import DEVICE_FINGERPRINT, EVM_PAYMENT_METHODS, ADS_TOPUP_PAGE, TON_PAYMENT_METHODS, DEFAULT_TIMEOUT


async def topup_ton(
    wallet: Wallet,
    username: str,
    amount: int,
    show_sender: bool = False,
) -> AdsTopupResult:
    '''
    Top up TON to a recipient Telegram Ads balance.
    '''
    if not isinstance(amount, int) or not (1 <= amount <= 1000000000):
        raise ConfigurationError(ConfigurationError.INVALID_TON_AMOUNT)

    try:
        headers = build_headers(ADS_TOPUP_PAGE)

        async with httpx.AsyncClient(
            cookies=wallet.cookies.to_dict(),
            timeout=DEFAULT_TIMEOUT,
        ) as session:
            # fragment_hash = await fetch_fragment_hash(
            #     wallet.cookies.to_dict(),
            #     headers,
            #     ADS_TOPUP_PAGE,
            #     DEFAULT_TIMEOUT,
            # )

            await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "updateAdsTopupState",
                    "mode": "new",
                },
            )

            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "searchAdsTopupRecipient",
                    "query": username,
                },
            )
            recipient = result.get("found", {}).get("recipient")
            if not recipient:
                raise UserNotFoundError(
                    UserNotFoundError.NOT_FOUND.format(username=username),
                )

            result = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "initAdsTopupRequest",
                    "recipient": recipient,
                    "amount": amount,
                },
            )
            if result.get("error"):
                raise FragmentAPIError(result["error"])

            req_id = result.get("req_id")
            if not req_id:
                raise FragmentAPIError(
                    FragmentAPIError.NO_REQUEST_ID.format(
                        context="TON topup",
                    )
                )

            account = await build_account_info(wallet)
            transaction = await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "getAdsTopupLink",
                    "account": json.dumps(account),
                    "device": DEVICE_FINGERPRINT,
                    "transaction": 1,
                    "id": req_id,
                    "show_sender": int(show_sender),
                },
            )
            if transaction.get("need_verify"):
                raise VerificationError(VerificationError.KYC_REQUIRED)

        tx_result = await execute_transaction(wallet, transaction)

        if tx_result.boc and req_id:
            try:
                await confirm_request(
                    wallet,
                    req_id,
                    tx_result.boc,
                    referer="ads/topup",
                )
            except Exception:
                pass

        total_cost, total_fees = await get_total_debit(tx_result.tx_hash, wallet.tonapi_key)

        return AdsTopupResult(
            transaction_id=tx_result.tx_hash,
            username=username,
            cost=total_cost,
            fee=total_fees,
            amount=amount,
        )

    except FragmentBaseError:
        raise
    except Exception as exc:
        raise UnexpectedError(
            UnexpectedError.UNEXPECTED.format(exc=exc),
        ) from exc