#!/usr/bin/env python3
"""
mercury-order-load.py

Correct async load test with *real* latency separation:

1) queue_wait_ms  - waiting for client concurrency slot
2) pool_wait_ms   - waiting for a TCP connection from pool
3) request_io_ms  - request -> response (body fully read)

Derived:
- request_latency_ms = pool_wait_ms + request_io_ms
- total_ms           = queue_wait_ms + request_latency_ms
"""

import asyncio
import os
import random
import statistics
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


# ---------- Config ----------
BASE_URL = os.getenv("ORDER_BASE_URL", "http://localhost").rstrip("/")
ORDER_PATH = os.getenv("ORDER_PATH", "/orders/api/v1/orders")
TOTAL_REQUESTS = int(os.getenv("TOTAL_REQUESTS", "10000"))
CONCURRENCY = int(os.getenv("CONCURRENCY", "200"))
TIMEOUT_S = float(os.getenv("TIMEOUT_S", "10"))
QTY_MAX = int(os.getenv("QTY_MAX", "1"))
MAX_ITEM_ID = int(os.getenv("MAX_ITEM_ID", "100000"))

URL = f"{BASE_URL}{ORDER_PATH}"


# ---------- Helpers ----------
def percentile(vals: List[float], p: float) -> float:
    vals = sorted(vals)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] if f == c else vals[f] * (c - k) + vals[c] * (k - f)


def print_stats(vals: List[float], label: str):
    if not vals:
        print(f"{label}: (none)")
        return
    print(f"{label} (ms):")
    print(f"  p50: {percentile(vals, 50):.2f}")
    print(f"  p95: {percentile(vals, 95):.2f}")
    print(f"  p99: {percentile(vals, 99):.2f}")
    print(f"  min: {min(vals):.2f}")
    print(f"  max: {max(vals):.2f}")
    print(f"  avg: {statistics.mean(vals):.2f}")


def make_order_payload() -> Dict[str, Any]:
    n_items = random.randint(1, 3)
    ids = random.sample(range(1, MAX_ITEM_ID + 1), n_items)
    items = []
    subtotal = 0.0

    for i in ids:
        qty = random.randint(1, QTY_MAX)
        line_total = qty * 10.0
        subtotal += line_total
        items.append({
            "itemId": i,
            "sku": f"SKU-{i}",
            "qty": qty,
            "unitPrice": 10.0,
            "lineTotal": line_total
        })

    tax = round(subtotal * 0.08, 2)
    total = round(subtotal + tax, 2)

    return {
        "userId": 1,
        "subtotalAmount": subtotal,
        "discountAmount": 0.0,
        "taxAmount": tax,
        "totalAmount": total,
        "items": items,
    }


# ---------- Tracing ----------
class Timings:
    __slots__ = ("conn_start", "conn_end", "req_start", "resp_end")

    def __init__(self):
        self.conn_start = None
        self.conn_end = None
        self.req_start = None
        self.resp_end = None


def trace_config():
    tc = aiohttp.TraceConfig()

    async def conn_q_start(_, ctx, __):
        ctx.trace_request_ctx["t"].conn_start = time.perf_counter()

    async def conn_q_end(_, ctx, __):
        ctx.trace_request_ctx["t"].conn_end = time.perf_counter()

    async def req_start(_, ctx, __):
        ctx.trace_request_ctx["t"].req_start = time.perf_counter()

    async def req_end(_, ctx, __):
        ctx.trace_request_ctx["t"].resp_end = time.perf_counter()

    tc.on_connection_queued_start.append(conn_q_start)
    tc.on_connection_queued_end.append(conn_q_end)
    tc.on_request_start.append(req_start)
    tc.on_request_end.append(req_end)

    return tc


# ---------- Result ----------
@dataclass
class Result:
    ok: bool
    status: Optional[int]
    queue_wait_ms: float
    pool_wait_ms: float
    request_io_ms: float
    request_latency_ms: float
    total_ms: float
    error: Optional[str]


# ---------- Worker ----------
async def worker(session: aiohttp.ClientSession, sem: asyncio.Semaphore) -> Result:
    payload = make_order_payload()
    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": f"load-{uuid.uuid4()}",
    }

    q0 = time.perf_counter()
    try:
        async with sem:
            q1 = time.perf_counter()
            queue_wait_ms = (q1 - q0) * 1000.0

            t = Timings()
            ctx = {"t": t}

            async with session.post(URL, json=payload, headers=headers, trace_request_ctx=ctx) as resp:
                await resp.read()

            pool_wait_ms = (
                (t.conn_end - t.conn_start) * 1000.0
                if t.conn_start and t.conn_end else 0.0
            )

            request_io_ms = (
                (t.resp_end - t.req_start) * 1000.0
                if t.req_start and t.resp_end else 0.0
            )

            req_lat = pool_wait_ms + request_io_ms
            total = queue_wait_ms + req_lat

            return Result(
                ok=200 <= resp.status < 300,
                status=resp.status,
                queue_wait_ms=queue_wait_ms,
                pool_wait_ms=pool_wait_ms,
                request_io_ms=request_io_ms,
                request_latency_ms=req_lat,
                total_ms=total,
                error=None if resp.status < 300 else f"HTTP_{resp.status}",
            )

    except Exception as e:
        total = (time.perf_counter() - q0) * 1000.0
        return Result(False, None, 0, 0, 0, 0, total, type(e).__name__)


# ---------- Runner ----------
async def run():
    print(f"Target:         {URL}")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Concurrency:    {CONCURRENCY}")
    print(f"Timeout (sec):  {TIMEOUT_S}")
    print("")

    sem = asyncio.Semaphore(CONCURRENCY)

    connector = aiohttp.TCPConnector(
        limit=CONCURRENCY,
        limit_per_host=CONCURRENCY,
    )

    timeout = aiohttp.ClientTimeout(total=TIMEOUT_S)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        trace_configs=[trace_config()],
    ) as session:
        tasks = [worker(session, sem) for _ in range(TOTAL_REQUESTS)]
        results = await asyncio.gather(*tasks)

    ok = [r for r in results if r.ok]
    fail = [r for r in results if not r.ok]

    print("===== Load Test Results =====")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Success:        {len(ok)}")
    print(f"Failures:       {len(fail)}")
    print("")

    print_stats([r.queue_wait_ms for r in ok], "QUEUE WAIT")
    print()
    print_stats([r.pool_wait_ms for r in ok], "POOL WAIT")
    print()
    print_stats([r.request_io_ms for r in ok], "REQUEST I/O")
    print()
    print_stats([r.total_ms for r in ok], "TOTAL")
    print("")

    if fail:
        errors = {}
        for r in fail:
            errors[r.error] = errors.get(r.error, 0) + 1

        print("Failures breakdown:")
        for k, v in sorted(errors.items()):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(run())