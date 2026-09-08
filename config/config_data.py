from dataclasses import dataclass

from environs import Env

'''
    При необходимости конфиг базы данных или других сторонних сервисов
'''


@dataclass
class DB:
    dns: str


@dataclass
class IncomeWallet:
    address: str
    raw_address: str
    mnemonic: list[str]


@dataclass
class DistributionWallet:
    address: str
    mnemonic: list[str]
    subwallet_id: int


@dataclass
class UserBot:
    account: str


@dataclass
class Config:
    db: DB
    income_wallet: IncomeWallet
    distribution_wallet: DistributionWallet
    user_bot: UserBot


def load_config(path: str | None = None) -> Config:
    env: Env = Env()
    env.read_env(path)

    return Config(
        db=DB(
            dns=env('dns')
        ),
        income_wallet=IncomeWallet(
            address=env('income_address'),
            raw_address=env('income_raw_address'),
            mnemonic=env('income_mnemonic').split(' ')
        ),
        distribution_wallet=DistributionWallet(
            address=env('distribution_address'),
            mnemonic=env('distribution_mnemonic').split(' '),
            subwallet_id=int(env('distribution_subwallet_id'))
        ),
        user_bot=UserBot(
            account=env('user_bot_account')
        )
    )