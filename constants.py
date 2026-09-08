

import json
from typing import Any, Literal, get_args

from tonutils.wallet import WalletV4R2, WalletV5R1

PREMIUM_USDT = {
    3: 12,
    6: 16,
    12: 29
}
FRAGMENT_FEE = 0.0004  # В ton
SYSTEM_COMM = 0.001  # В ton


WalletVersionType = Literal["V4R2", "V5R1"]
SUPPORTED_WALLET_VERSIONS: frozenset[str] = frozenset(
    get_args(WalletVersionType),
)

WALLET_CLASSES: dict[str, Any] = {
    "V4R2": WalletV4R2,
    "V5R1": WalletV5R1,
}

MIN_TON_BALANCE: float = 0.01

DEFAULT_TIMEOUT: float = 30.0

CONFIRMATION_INTERVAL: float = 3.0
CONFIRMATION_MAX_ATTEMPTS: int = 40

REQUIRED_COOKIE_KEYS: tuple[str, ...] = (
    "stel_ssid",
    "stel_dt",
    "stel_token",
    "stel_ton_token",
)

AUTH_REQUIRED_COOKIE_KEYS: tuple[str, ...] = (
    "stel_ssid",
    "stel_dt",
)

TONAPI_BASE_URL: str = "https://tonapi.io/v2"
TONAPI_PROXY_BASE: str = "https://tonapi.ru:444/v2"
TONAPI_DEFAULT_KEY: str = "AH" + "0" * 48

FRAGMENT_DOMAIN: str = "fragment.com"  # for rookiepy
FRAGMENT_BASE_URL: str = f"https://{FRAGMENT_DOMAIN}"
STARS_PAGE: str = f"{FRAGMENT_BASE_URL}/stars/buy"
STARS_GIVEAWAY_PAGE: str = f"{FRAGMENT_BASE_URL}/stars/giveaway"
PREMIUM_GIFT_PAGE: str = f"{FRAGMENT_BASE_URL}/premium/gift"
PREMIUM_GIVEAWAY_PAGE: str = f"{FRAGMENT_BASE_URL}/premium/giveaway"
ADS_TOPUP_PAGE: str = f"{FRAGMENT_BASE_URL}/ads/topup"
NUMBERS_PAGE: str = f"{FRAGMENT_BASE_URL}/numbers"
GIFTS_PAGE: str = f"{FRAGMENT_BASE_URL}/gifts"

DEVICE_FINGERPRINT: str = json.dumps(
    {
        "platform": "android",
        "appName": "Tonkeeper",
        "appVersion": "26.04.3",
        "maxProtocolVersion": 2,
        "features": [
            "SendTransaction",
            {
                "name": "SignData",
                "types": ["text", "binary", "cell"],
            },
            {
                "name": "SendTransaction",
                "maxMessages": 255,
            },
        ],
    },
    separators=(",", ":"),
)

# Base HTTP headers — shared across all Fragment API requests.
# Each method merges these with its own "referer" and "x-aj-referer".
BASE_HEADERS: dict[str, str] = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
    "origin": FRAGMENT_BASE_URL,
    "priority": "u=1, i",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Mobile Safari/537.36"
    ),
    "x-requested-with": "XMLHttpRequest",
}


EVM_PAYMENT_METHODS: frozenset[str] = frozenset({
    "usdt_eth",
    "usdt_pol",
    "usdc_eth",
    "usdc_base",
    "usdc_pol",
})

EVM_CHAIN_NAMES: dict[int, str] = {
    1: "ETH",
    8453: "BASE",
    137: "POL",
}

EVM_TOKEN_DECIMALS: dict[str, int] = {
    "0xdac17f958d2ee523a2206206994597c177e3d24f": 6,
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,
    "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": 6,
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": 6,
}

EVM_TOKEN_SYMBOLS: dict[str, str] = {
    "0xdac17f958d2ee523a2206206994597c177e3d24f": "USDT",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
}

VALID_PAYMENT_METHODS: frozenset[str] = frozenset({
    "ton",
    "usdt_ton",
    "usdt_eth",
    "usdt_pol",
    "usdc_eth",
    "usdc_base",
    "usdc_pol",
})

TON_PAYMENT_METHODS: frozenset[str] = frozenset({"ton", "usdt_ton"})
