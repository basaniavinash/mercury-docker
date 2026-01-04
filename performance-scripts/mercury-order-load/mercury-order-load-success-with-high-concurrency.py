#!/usr/bin/env python3
"""
mercury-order-load.py

Async load test for Mercury Order Service (SUCCESS-only mode):
- Sends POST /api/v1/orders
- Measures p50/p95/p99 latency (ms)
- All requests are designed to PASS (no out-of-stock)
- Adds X-Request-Id per request

Usage:
  python3 mercury-order-load.py

Optional env vars:
  ORDER_BASE_URL   (default: http://localhost:8081)
  ORDER_PATH       (default: /api/v1/orders)
  TOTAL_REQUESTS   (default: 20000)
  CONCURRENCY      (default: 200)
  TIMEOUT_S        (default: 10)
  QTY_MAX          (default: 1)   # keep qty low to avoid stock depletion
"""

import asyncio
import os
import random
import statistics
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


# ---------- Config ----------
BASE_URL = os.getenv("ORDER_BASE_URL", "http://localhost:8081").rstrip("/")
ORDER_PATH = os.getenv("ORDER_PATH", "/api/v1/orders")
TOTAL_REQUESTS = int(os.getenv("TOTAL_REQUESTS", "10000"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "200"))
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "10"))
QTY_MAX = int(os.getenv("QTY_MAX", "1"))
MAX_ITEM_ID = int(os.getenv("MAX_ITEM_ID", "100000"))

URL = f"{BASE_URL}{ORDER_PATH}"

def pick_item():
    i = random.randint(1, MAX_ITEM_ID)
    return {"itemId": i, "sku": f"SKU-{i}", "unitPrice": 10.00}


def percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return sorted_vals[0]
    if p >= 100:
        return sorted_vals[-1]

    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def make_order_payload() -> Dict[str, Any]:
    """
    SUCCESS-ONLY payload:
    - qty stays small (<= QTY_MAX) to avoid depletion
    - totals are consistent
    """
    n_items = random.randint(1, 3)
    ids = random.sample(range(1, MAX_ITEM_ID + 1), k=n_items)
    chosen = [{"itemId": i, "sku": f"SKU-{i}", "unitPrice": 10.00} for i in ids]
    items: List[Dict[str, Any]] = []
    subtotal = 0.0

    for it in chosen:
        qty = random.randint(1, max(1, QTY_MAX))

        unit_price = float(it["unitPrice"])
        line_total = round(unit_price * qty, 2)
        subtotal += line_total

        items.append(
            {
                "itemId": it["itemId"],
                "sku": it["sku"],
                "qty": qty,
                "unitPrice": unit_price,
                "lineTotal": line_total,
            }
        )

    discount = 0.0
    tax = round(subtotal * 0.08, 2)
    total = round(subtotal - discount + tax, 2)

    return {
        "userId": 1,
        "subtotalAmount": round(subtotal, 2),
        "discountAmount": round(discount, 2),
        "taxAmount": tax,
        "totalAmount": total,
        "items": items,
    }


@dataclass
class Result:
    ok: bool
    status_code: Optional[int]
    latency_ms: float
    error_key: Optional[str]
    request_id: str


async def worker(client: httpx.AsyncClient, sem: asyncio.Semaphore) -> Result:
    request_id = f"load-{uuid.uuid4()}"
    payload = make_order_payload()

    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }

    start = time.perf_counter()
    try:
        async with sem:
            resp = await client.post(URL, json=payload, headers=headers)
        latency_ms = (time.perf_counter() - start) * 1000.0

        if 200 <= resp.status_code < 300:
            return Result(True, resp.status_code, latency_ms, None, request_id)

        return Result(False, resp.status_code, latency_ms, f"HTTP_{resp.status_code}", request_id)

    except httpx.ReadTimeout:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, "timeout", request_id)
    except httpx.ConnectError:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, "connect_error", request_id)
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, f"exception:{type(e).__name__}", request_id)


def print_latency_stats_ms(vals: List[float], label: str):
    if not vals:
        print(f"{label}: (none)")
        return
    vals = sorted(vals)
    print(f"{label} (ms):")
    print(f"  p50: {percentile(vals, 50):.2f}")
    print(f"  p95: {percentile(vals, 95):.2f}")
    print(f"  p99: {percentile(vals, 99):.2f}")
    print(f"  min: {vals[0]:.2f}")
    print(f"  max: {vals[-1]:.2f}")
    print(f"  avg: {statistics.mean(vals):.2f}")


async def run():
    print(f"Target:         {URL}")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Concurrency:    {CONCURRENCY}")
    print(f"Timeout (sec):  {TIMEOUT_S}")
    print(f"QTY_MAX:        {QTY_MAX}")
    print("")

    sem = asyncio.Semaphore(CONCURRENCY)

    limits = httpx.Limits(
        max_connections=CONCURRENCY * 2,
        max_keepalive_connections=CONCURRENCY * 2,
        keepalive_expiry=30.0,
    )

    timeout = httpx.Timeout(
        connect=TIMEOUT_S,
        read=TIMEOUT_S,
        write=TIMEOUT_S,
        pool=TIMEOUT_S,
    )

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        tasks = [asyncio.create_task(worker(client, sem)) for _ in range(TOTAL_REQUESTS)]
        results: List[Result] = await asyncio.gather(*tasks)

    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]

    all_lat = [r.latency_ms for r in results]
    ok_lat = [r.latency_ms for r in ok]

    print("===== Load Test Results =====")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Success:        {len(ok)}")
    print(f"Failures:       {len(fail)}")
    print("")

    print_latency_stats_ms(all_lat, "ALL requests")
    print("")
    print_latency_stats_ms(ok_lat, "SUCCESS only")
    print("")

    if fail:
        err_counts: Dict[str, int] = {}
        for r in fail:
            k = r.error_key or "unknown"
            err_counts[k] = err_counts.get(k, 0) + 1

        print("Failures breakdown:")
        for k in sorted(err_counts.keys()):
            print(f"  {k}: {err_counts[k]}")

        print("")
        print("Sample failed request IDs (search in logs):")
        for r in fail[: min(5, len(fail))]:
            print(f"  requestId={r.request_id} err={r.error_key} status={r.status_code}")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass