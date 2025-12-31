import requests
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://localhost:8080"
ENDPOINT = "/api/v1/items/category?category=CLOTHING&limit=50"

TOTAL_REQUESTS = 5000
CONCURRENCY = 50
TIMEOUT = 5  # seconds


def percentile(data, p):
    """
    Compute percentile manually to avoid library ambiguity
    """
    if not data:
        return None
    k = int(len(data) * (p / 100))
    k = min(k, len(data) - 1)
    return data[k]


def make_request(session):
    start = time.perf_counter_ns()
    response = session.get(BASE_URL + ENDPOINT, timeout=TIMEOUT)
    end = time.perf_counter_ns()

    latency_ms = (end - start) / 1_000_000
    return latency_ms, response.status_code


def main():
    latencies = []
    failures = 0

    with requests.Session() as session:
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(make_request, session)
                for _ in range(TOTAL_REQUESTS)
            ]

            for future in as_completed(futures):
                latency, status = future.result()
                if status == 200:
                    latencies.append(latency)
                else:
                    failures += 1

    latencies.sort()

    print("\n===== Load Test Results =====")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Concurrency:     {CONCURRENCY}")
    print(f"Failures:        {failures}")

    print("\nLatency (ms):")
    print(f"  p50: {percentile(latencies, 50):.2f}")
    print(f"  p95: {percentile(latencies, 95):.2f}")
    print(f"  p99: {percentile(latencies, 99):.2f}")
    print(f"  min: {min(latencies):.2f}")
    print(f"  max: {max(latencies):.2f}")
    print(f"  avg: {statistics.mean(latencies):.2f}")


if __name__ == "__main__":
    main()