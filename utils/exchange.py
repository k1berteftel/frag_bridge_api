#!/usr/bin/env python3
import re
import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List


def get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fetch_with_retry(
        session: aiohttp.ClientSession,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        **kwargs
) -> Optional[Dict[str, Any]]:
    for attempt in range(max_retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15), **kwargs) as response:
                if response.status == 429:
                    await asyncio.sleep(base_delay * (2 ** attempt) * 2)
                    continue

                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(base_delay * (2 ** attempt))

    return None


async def ton_to_usdt_binance(session: aiohttp.ClientSession) -> Dict[str, Any]:
    data = await fetch_with_retry(
        session,
        "https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT",
        max_retries=2
    )

    if data and "price" in data and float(data["price"]) > 0:
        return {
            "usdt_per_ton": float(data["price"]),
            "last_updated": get_timestamp(),
            "source": "binance"
        }
    return {}


async def parse_fragment_transaction(transaction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        for action in transaction.get("actions", []):
            if action.get("type") == "TonTransfer":
                transfer = action.get("TonTransfer", {})
                comment = transfer.get("comment", "")

                stars_match = re.search(r'(\d+)\s+Telegram\s+Stars', comment)
                if not stars_match:
                    continue

                stars = int(stars_match.group(1))
                ton_amount = int(transfer.get("amount", 0)) / 1_000_000_000

                if stars > 0 and ton_amount > 0:
                    ref_match = re.search(r'Ref#(\w+)', comment)
                    return {
                        "timestamp": transaction.get("timestamp", 0),
                        "stars": stars,
                        "ton": ton_amount,
                        "rate_per_star": ton_amount / stars,
                        "reference": ref_match.group(1) if ref_match else "Unknown",
                        "hash": transaction.get("event_id", "")
                    }
    except:
        pass
    return None


async def get_fragment_events(
        session: aiohttp.ClientSession,
        limit: int = 50,
        fragment_address: str = "EQCFJEP4WZ_mpdo0_kMEmsTgvrMHG7K_tWY16pQhKHwoOoy2",
        api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not api_key:
        await asyncio.sleep(2.0)

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    data = await fetch_with_retry(
        session,
        f"https://tonapi.io/v2/accounts/{fragment_address}/events",
        max_retries=3,
        params={"limit": limit},
        headers=headers
    )

    return data.get("events", []) if data else []


async def stars_to_ton_fragment(
        session: aiohttp.ClientSession,
        limit: int = 50,
        fragment_address: str = "EQCFJEP4WZ_mpdo0_kMEmsTgvrMHG7K_tWY16pQhKHwoOoy2",
        api_key: Optional[str] = None
) -> Dict[str, Any]:
    events = await get_fragment_events(session, limit, fragment_address, api_key)

    stars_txs = []
    for event in events:
        if result := await parse_fragment_transaction(event):
            stars_txs.append(result)

    if not stars_txs:
        raise Exception("No Stars transactions found")

    rates = [tx['rate_per_star'] for tx in stars_txs if 0 < tx['rate_per_star'] <= 1]

    if not rates:
        raise Exception("No valid rates found")

    return {
        "ton_per_star": sum(rates) / len(rates),
        "transactions_count": len(stars_txs),
        "min_rate": min(rates),
        "max_rate": max(rates),
        "median_rate": sorted(rates)[len(rates) // 2],
        "timestamp": get_timestamp(),
        "raw_transactions": stars_txs
    }


async def get_stars_rate(
        limit: int = 50,
        include_raw: bool = False,
        fragment_address: str = "EQCFJEP4WZ_mpdo0_kMEmsTgvrMHG7K_tWY16pQhKHwoOoy2",
        api_key: Optional[str] = None
) -> Dict[str, Any]:
    errors = []
    timestamp = get_timestamp()

    async with aiohttp.ClientSession() as session:
        ton_per_star = -1
        stars_to_ton = {}

        for attempt in range(2):
            try:
                stars_to_ton = await stars_to_ton_fragment(
                    session, limit, fragment_address, api_key
                )
                ton_per_star = stars_to_ton.get("ton_per_star", -1)
                if ton_per_star > 0:
                    break
            except Exception as e:
                if attempt == 1:
                    errors.append(f"Fragment error: {e}")
                else:
                    await asyncio.sleep(1.0)

        if ton_per_star <= 0:
            errors.append("Invalid Stars→TON rate")
            ton_per_star = -1

        usdt_per_ton = -1
        ton_to_usdt = {}

        for attempt in range(2):
            try:
                ton_to_usdt = await ton_to_usdt_binance(session)
                usdt_per_ton = ton_to_usdt.get("usdt_per_ton", -1)
                if usdt_per_ton > 0:
                    break
            except Exception as e:
                if attempt == 1:
                    errors.append(f"Binance error: {e}")
                else:
                    await asyncio.sleep(0.5)

        if usdt_per_ton <= 0:
            errors.append("Invalid TON→USDT rate")
            usdt_per_ton = -1

        if ton_per_star > 0 and usdt_per_ton > 0:
            usdt_per_star = ton_per_star * usdt_per_ton
            if usdt_per_star > 10 or usdt_per_star < 0.0001:
                errors.append(f"Suspicious rate: ${usdt_per_star:.6f}")
        else:
            usdt_per_star = -1
            if not errors:
                errors.append("No exchange rates available")

        result = {
            "ton_per_star": ton_per_star,
            "usdt_per_ton": usdt_per_ton,
            "usdt_per_star": usdt_per_star,
            "timestamp": timestamp,
            "errors": errors
        }

        if include_raw:
            result["fragment_raw"] = stars_to_ton
            result["binance_raw"] = ton_to_usdt

        return result

