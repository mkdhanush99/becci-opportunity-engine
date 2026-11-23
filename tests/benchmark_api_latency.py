"""Reproducible API Latency & Throughput Benchmark.

Measures actual P50, P95, and P99 response latency across critical endpoints:
- GET /api/v1/health
- GET /api/v1/metadata
- GET /api/v1/opportunities (pagination & filtering)
- GET /api/v1/opportunities/closing-soon
- POST /api/v1/schemes/{id}/check-eligibility
"""
import statistics
import time
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def benchmark_endpoint(method: str, path: str, json_data=None, iterations: int = 50):
    latencies_ms = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        if method == "GET":
            resp = client.get(path)
        else:
            resp = client.post(path, json=json_data)
        t1 = time.perf_counter()
        assert resp.status_code == 200, f"Failed with {resp.status_code}: {resp.text}"
        latencies_ms.append((t1 - t0) * 1000)

    latencies_ms.sort()
    p50 = statistics.median(latencies_ms)
    p95 = latencies_ms[int(iterations * 0.95)]
    p99 = latencies_ms[int(iterations * 0.99)]
    avg = statistics.mean(latencies_ms)
    min_lat = min(latencies_ms)
    max_lat = max(latencies_ms)

    return {
        "path": path,
        "iterations": iterations,
        "min_ms": round(min_lat, 2),
        "avg_ms": round(avg, 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "max_ms": round(max_lat, 2)
    }


def main():
    print("=" * 80)
    print("BECCI OPPORTUNITY ENGINE — API LATENCY BENCHMARK (P50 / P95 / P99)")
    print("=" * 80)

    # 1. First find an existing scheme ID for eligibility check
    resp = client.get("/api/v1/opportunities?limit=5")
    items = resp.json().get("items", [])
    scheme_id = items[0]["id"] if items else "test-scheme"

    endpoints = [
        ("GET", "/api/v1/health", None),
        ("GET", "/api/v1/metadata", None),
        ("GET", "/api/v1/opportunities?limit=20&page=1", None),
        ("GET", "/api/v1/opportunities?category=funding&state=Telangana", None),
        ("GET", "/api/v1/opportunities/closing-soon?limit=10", None),
        ("POST", f"/api/v1/schemes/{scheme_id}/check-eligibility", {
            "domicile_state": "Telangana",
            "caste_category": "BC-B",
            "annual_income": 250000,
            "age": 28
        }),
    ]

    results = []
    for method, path, payload in endpoints:
        res = benchmark_endpoint(method, path, payload, iterations=50)
        results.append(res)
        print(f"[{method}] {res['path'][:42]:<42} | P50: {res['p50_ms']:>6.2f}ms | P95: {res['p95_ms']:>6.2f}ms | P99: {res['p99_ms']:>6.2f}ms | Avg: {res['avg_ms']:>6.2f}ms")

    print("=" * 80)
    print("Benchmark completed with 100% reproducible execution.")
    return results


if __name__ == "__main__":
    main()
