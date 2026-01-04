#!/usr/bin/env python3
"""
mercury-order-load.py

Async load test for Mercury Order Service:
- Sends POST /api/v1/orders
- Measures p50/p95/p99 latency
- Mixes successful + out-of-stock requests
- Adds X-Request-Id per request
- Prints error breakdown (status codes + exception types)

Usage:
  python3 mercury-order-load.py

Optional env vars:
  ORDER_BASE_URL   (default: http://localhost:8081)
  ORDER_PATH       (default: /api/v1/orders)
  TOTAL_REQUESTS   (default: 5000)
  CONCURRENCY      (default: 50)
  OUT_OF_STOCK_PCT (default: 5)   # percent of requests forced to fail
  TIMEOUT_S        (default: 10)
"""

import asyncio
import os
import random
import statistics
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx


# ---------- Config ----------
BASE_URL = os.getenv("ORDER_BASE_URL", "http://localhost:8081").rstrip("/")
ORDER_PATH = os.getenv("ORDER_PATH", "/api/v1/orders")
TOTAL_REQUESTS = int(os.getenv("TOTAL_REQUESTS", "5000"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "50"))
OUT_OF_STOCK_PCT = int(os.getenv("OUT_OF_STOCK_PCT", "5"))  # 0..100
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "10"))

URL = f"{BASE_URL}{ORDER_PATH}"

# Your seeded catalog snippet shows:
# item ids 1..100, sku "SKU-<id>", unit_price = 10
# We'll use that.
ITEMS = [{"itemId": i, "sku": f"SKU-{i}", "unitPrice": 10.00} for i in range(1, 101)]


# ---------- Helpers ----------
def percentile(sorted_vals: List[float], p: float) -> float:
    """
    p in [0, 100]. Uses linear interpolation between closest ranks.
    """
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


def make_order_payload(force_out_of_stock: bool) -> Dict[str, Any]:
    """
    Builds an Order payload consistent with your model:
      Order { userId, subtotalAmount, discountAmount, taxAmount, totalAmount, items[] }
      OrderItem { itemId, sku, qty, unitPrice, lineTotal }
    """
    n_items = random.randint(1, 3)
    chosen = random.sample(ITEMS, k=n_items)

    items: List[Dict[str, Any]] = []
    subtotal = 0.0

    for it in chosen:
        qty = random.randint(1, 3)
        if force_out_of_stock:
            # huge qty to guarantee UPDATE ... WHERE available_qty >= qty fails
            qty = 10_000

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
    # simple fake tax so totals make sense
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
    error_key: Optional[str]  # e.g. "HTTP_400", "timeout", "connect_error", etc.
    request_id: str


async def worker(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    idx: int,
) -> Result:
    request_id = f"load-{uuid.uuid4()}"
    force_oos = (random.randint(1, 100) <= OUT_OF_STOCK_PCT)
    payload = make_order_payload(force_oos)

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

        # Non-2xx: classify by status
        return Result(
            False,
            resp.status_code,
            latency_ms,
            f"HTTP_{resp.status_code}",
            request_id,
        )

    except httpx.ReadTimeout:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, "timeout", request_id)
    except httpx.ConnectError:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, "connect_error", request_id)
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return Result(False, None, latency_ms, f"exception:{type(e).__name__}", request_id)


async def run():
    print(f"Target:          {URL}")
    print(f"Total requests:  {TOTAL_REQUESTS}")
    print(f"Concurrency:     {CONCURRENCY}")
    print(f"Out-of-stock %:  {OUT_OF_STOCK_PCT}")
    print(f"Timeout (sec):   {TIMEOUT_S}")
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
        tasks = [asyncio.create_task(worker(client, sem, i)) for i in range(TOTAL_REQUESTS)]
        results: List[Result] = await asyncio.gather(*tasks)

    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]

    all_lat = sorted([r.latency_ms for r in results])
    ok_lat = sorted([r.latency_ms for r in ok])
    fail_lat = sorted([r.latency_ms for r in fail])

    def fmt(ms: float) -> str:
        return f"{ms:.2f}"

    def print_stats(label: str, vals: List[float]):
        if not vals:
            print(f"{label}: (none)")
            return
        print(f"{label}:")
        print(f"  p50: {fmt(percentile(vals, 50))}")
        print(f"  p95: {fmt(percentile(vals, 95))}")
        print(f"  p99: {fmt(percentile(vals, 99))}")
        print(f"  min: {fmt(vals[0])}")
        print(f"  max: {fmt(vals[-1])}")
        print(f"  avg: {fmt(statistics.mean(vals))}")

    # error breakdown
    err_counts: Dict[str, int] = {}
    for r in fail:
        key = r.error_key or "unknown"
        err_counts[key] = err_counts.get(key, 0) + 1

    print("===== Load Test Results =====")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Success:        {len(ok)}")
    print(f"Failures:       {len(fail)}")
    print("")

    print("Latency (ms) — ALL")
    print_stats("all", all_lat)
    print("")

    if ok_lat:
        print("Latency (ms) — SUCCESS only")
        print_stats("ok", ok_lat)
        print("")

    if fail_lat:
        print("Latency (ms) — FAIL only")
        print_stats("fail", fail_lat)
        print("")

    if err_counts:
        print("Failures breakdown:")
        for k in sorted(err_counts.keys()):
            print(f"  {k}: {err_counts[k]}")

    # Helpful sanity output: sample request IDs from failures (to find logs fast)
    if fail:
        sample = fail[: min(5, len(fail))]
        print("")
        print("Sample failed request IDs (search these in logs):")
        for r in sample:
            print(f"  requestId={r.request_id}  err={r.error_key}  status={r.status_code}")

    print("")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass