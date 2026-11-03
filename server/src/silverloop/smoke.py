import sys

import httpx


def main() -> None:
    base_url = "http://127.0.0.1:8000"
    with httpx.Client(base_url=base_url, timeout=5) as client:
        health = client.get("/health")
        health.raise_for_status()
        client.post("/v1/demo/reset").raise_for_status()
        state = client.get("/v1/people/mdm-lim/state")
        state.raise_for_status()
        print(f"Smoke test passed: {health.json()['status']} / {state.json()['attention_band']}")


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, KeyError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
