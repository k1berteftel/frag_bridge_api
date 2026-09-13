import time
from typing import Literal
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from decimal import Decimal

from pydantic import BaseModel


class PurchaseRequest(BaseModel):
    currency: int | float
    receiver: str


class CheckRequest(BaseModel):
    username: str


class DistributeRequest(BaseModel):
    deposit: int | float


@dataclass
class EvmInvoice:
    '''
    EVM payment invoice details from Fragment.

    Returned when a non-TON payment method (USDT/USDC on ETH/BASE/POL)
    is selected for Stars, Premium, Ads, or Giveaway purchases.

    The user must send the exact amount of the specified token to the
    invoice_address on the specified chain. This library does not
    perform automatic EVM payments — the user must implement their
    own EVM wallet logic to complete the payment.
    '''

    req_id: str
    invoice_address: str
    invoice_token: str
    invoice_chain_id: int
    invoice_chain_name: str
    invoice_amount_hex: str
    invoice_amount: float
    invoice_amount_raw: int
    token_symbol: str
    token_decimals: int
    expires_at: int
    payment_method: str
    api_hash: str
    page_url: str

    def __repr__(self) -> str:
        return (
            f"EvmInvoice("
            f"amount={self.invoice_amount} {self.token_symbol}, "
            f"chain='{self.invoice_chain_name}', "
            f"address='{self.invoice_address[:10]}...', "
            f"expires_at={self.expires_at}"
            f")"
        )


@dataclass
class EvmPaymentResult:
    '''
    Result of initiating an EVM payment for Stars/Premium/Ads/Giveaway.

    Contains EvmInvoice with payment details. The user is responsible
    for completing the payment via their own EVM wallet integration.
    No TON transaction is performed.
    '''

    item_kind: str
    target: str
    amount: int
    payment_method: str
    invoice: EvmInvoice

    def __repr__(self) -> str:
        return (
            f"EvmPaymentResult("
            f"kind='{self.item_kind}', "
            f"target='{self.target}', "
            f"amount={self.amount}, "
            f"payment='{self.payment_method}'"
            f")"
        )


@dataclass
class PremiumResult:
    '''Result of a successful Telegram Premium gift.'''

    transaction_id: str
    username: str
    amount: int
    cost: float | Decimal
    fee: float | Decimal
    payment_method: str = "ton"

    def __repr__(self) -> str:
        return (
            f"PremiumResult("
            f"username='{self.username}', "
            f"amount={self.amount} months, "
            f"cost={self.cost} ton"
            f"fee={self.fee} ton"
            f"payment='{self.payment_method}', "
            f"tx='{self.transaction_id}'"
            f")"
        )


@dataclass
class StarsResult:
    '''Result of a successful Telegram Stars purchase.'''

    transaction_id: str
    username: str
    amount: int
    cost: float | Decimal
    fee: float | Decimal
    payment_method: str = "ton"

    def __repr__(self) -> str:
        return (
            f"StarsResult("
            f"username='{self.username}', "
            f"amount={self.amount} stars, "
            f"cost={self.cost} ton"
            f"fee={self.fee} ton"
            f"payment='{self.payment_method}', "
            f"tx='{self.transaction_id}'"
            f")"
        )


@dataclass
class AdsTopupResult:
    '''Result of a successful Telegram Ads TON top-up.'''

    transaction_id: str
    username: str
    amount: int
    cost: float | Decimal
    fee: float | Decimal

    def __repr__(self) -> str:
        return (
            f"AdsTopupResult("
            f"username='{self.username}', "
            f"amount={self.amount} TON, "
            f"cost={self.cost} ton"
            f"fee={self.fee} ton"
            f"tx='{self.transaction_id}'"
            f")"
        )


@dataclass
class TransactionResult:
    '''
    Result of a TON transaction with confirmation details.
    '''

    tx_hash: str
    boc: str | None = None
    seqno_before: int | None = None
    seqno_after: int | None = None
    balance_before: float | None = None
    balance_after: float | None = None
    confirmed: bool = False

    def __repr__(self) -> str:
        return (
            f"TransactionResult("
            f"tx='{self.tx_hash[:16]}...', "
            f"confirmed={self.confirmed}, "
            f"seqno={self.seqno_before}->{self.seqno_after}"
            f")"
        )


@dataclass
class WalletInfo:
    '''Wallet state information.'''

    address: str
    state: str
    balance_ton: float

    def __repr__(self) -> str:
        return (
            f"WalletInfo("
            f"address='{self.address}', "
            f"state='{self.state}', "
            f"balance_ton={self.balance_ton}, "
            f")"
        )


@dataclass
class Cookies:
    stel_token: str
    stel_ssid: str
    stel_ton_token: str
    # stel_dt: str  # А надо ли?

    def to_dict(self):
        return {
            "stel_token": self.stel_token,
            "stel_ssid": self.stel_ssid,
            "stel_ton_token": self.stel_ton_token
      }


@dataclass
class Wallet:
    id: str

    address: str
    raw_address: str
    public_key: str

    mnemonic: list[str]
    tonapi_key: str
    hash: str
    cookies: Cookies

    batch: int
    status: Literal['free', 'busy', 'sync']
    balance: float

    created_at: datetime

    cooldown_until: float | None = None  # Только это добавили

    @property
    def is_on_cooldown(self) -> bool:
        return self.cooldown_until is not None and time.time() < self.cooldown_until

    def set_cooldown(self, seconds: int):
        self.cooldown_until = time.time() + seconds

    def clear_cooldown(self):
        self.cooldown_until = None

    def to_dict(self) -> dict:
        return {
            "data": {
                "seed_phrase": " ".join(self.mnemonic),
                "address": self.address,
                "raw_address": self.raw_address,
                "public_key": self.public_key,
                "created_at": self.created_at.isoformat()
            },
            "connection": {
                "mnemonic": self.mnemonic,
                "tonapi_key": self.tonapi_key,
                "hash": self.hash,
                "cookies": {
                    "stel_token": self.cookies.stel_token,
                    "stel_ssid": self.cookies.stel_ssid,
                    "stel_ton_token": self.cookies.stel_ton_token
                }
            },
            "batch": self.batch,
            "status": self.status,
            "balance": self.balance,
            "cooldown_until": self.cooldown_until  # Добавили
        }

    @classmethod
    def from_dict(cls, wallet_id: str, wallet: dict):
        data = wallet.get('data')
        connection = wallet.get('connection')
        cookies = connection.get('cookies')
        return cls(
            id=wallet_id,
            address=data.get('address'),
            raw_address=data.get('raw_address'),
            public_key=data.get('public_key'),
            mnemonic=connection.get('mnemonic'),
            tonapi_key=connection.get('tonapi_key'),
            hash=connection.get('hash'),
            cookies=Cookies(
                stel_token=cookies.get('stel_token'),
                stel_ssid=cookies.get('stel_ssid'),
                stel_ton_token=cookies.get('stel_ton_token')
            ),
            batch=wallet.get('batch'),
            status=wallet.get('status'),
            balance=wallet.get('balance'),
            created_at=datetime.fromisoformat(data.get('created_at')),
            cooldown_until=wallet.get('cooldown_until')
        )


class AggregatorStatus(str, Enum):
    PENDING = "pending"  # ждет выполнения
    PROCESSING = "processing"  # выполняется сейчас
    COMPLETED = "completed"  # выполнена
    FAILED = "failed"  # ошибка
