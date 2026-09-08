from __future__ import annotations

from typing import Any

import httpx

from processors.fastlane.utils.http import build_headers, fetch_fragment_hash, post_FragmentAPI
from models import Wallet
from errors import (
    FragmentBaseError,
    UnexpectedError,
)
from constants import FRAGMENT_BASE_URL, DEFAULT_TIMEOUT


async def confirm_request(
        wallet: Wallet,
        req_id: str,
        boc: str,
        referer: str = "stars/buy",
) -> dict[str, Any]:
    '''Send confirmReq to Fragment after broadcasting a TON transaction.'''
    try:
        page_url = f"{FRAGMENT_BASE_URL}/{referer}"
        headers = build_headers(page_url)
        # fragment_hash = await fetch_fragment_hash(
        #     wallet.cookies.to_dict(),
        #     headers,
        #     page_url,
        #     DEFAULT_TIMEOUT,
        # )
        async with httpx.AsyncClient(
                cookies=wallet.cookies.to_dict(),
                timeout=DEFAULT_TIMEOUT,
        ) as session:
            return await post_FragmentAPI(
                session,
                wallet.hash,
                headers,
                {
                    "method": "confirmReq",
                    "id": str(req_id),
                    "boc": boc,
                },
            )
    except FragmentBaseError:
        raise
    except Exception as exc:
        raise UnexpectedError(
            UnexpectedError.UNEXPECTED.format(exc=exc),
        ) from exc


async def call(
        wallet: Wallet,
        method: str,
        data: dict[str, Any] | None = None,
        *,
        page_url: str = FRAGMENT_BASE_URL,
) -> dict[str, Any]:
    '''Send a raw request to the Fragment API.'''
    headers = build_headers(page_url)
    async with httpx.AsyncClient(
            cookies=wallet.cookies.to_dict(),
            timeout=DEFAULT_TIMEOUT,
    ) as session:
        # fragment_hash = await fetch_fragment_hash(
        #     wallet.cookies.to_dict(),
        #     headers,
        #     page_url,
        #     DEFAULT_TIMEOUT,
        # )
        return await post_FragmentAPI(
            session,
            wallet.hash,
            headers,
            {"method": method, **(data or {})},
        )