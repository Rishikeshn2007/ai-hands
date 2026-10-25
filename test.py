"""
test.py  Tests all ai-hands API endpoints.
Run:  python test.py
Requires the server to be running: uvicorn main:app --reload
"""

import os
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://localhost:8000"
API_KEY  = os.getenv("SERVER_API_KEY")

PASS = "\033[92m+\033[0m"
FAIL = "\033[91mx\033[0m"

results = []

def check(name, passed, info=""):
    symbol = PASS if passed else FAIL
    print(f"  {symbol}  {name}" + (f"  ->  {info}" if info else ""))
    results.append(passed)

def run_tests():
    print(f"\n{'-'*50}")
    print("  ai-hands API Test Suite")
    print(f"  Server : {BASE_URL}")
    print(f"  API Key: {'set' if API_KEY else 'NOT SET'}")
    print(f"{'-'*50}\n")

    auth = {"Server-API-Key": API_KEY}

    # 1. Status page (public)
    print("[1] GET / � public status page")
    try:
        r = httpx.get(f"{BASE_URL}/", timeout=10)
        check("Status 200", r.status_code == 200, f"got {r.status_code}")
    except httpx.ConnectError:
        check("Server reachable", False, "Connection refused � is the server running?")
        print("\n  Aborting: server is not reachable.\n")
        sys.exit(1)

    # 2. Weather � valid key
    print("\n[2] GET /weather/London � valid key")
    r = httpx.get(f"{BASE_URL}/weather/London", headers=auth, timeout=15)
    check("Status 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Response is JSON object", isinstance(data, dict))

    # 3. News � valid key
    print("\n[3] GET /news/technology � valid key")
    r = httpx.get(f"{BASE_URL}/news/technology", headers=auth, timeout=30)
    check("Status 200", r.status_code == 200, f"got {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        check("Has 'results' field", "results" in data)
        check("Has 'query' field",   "query"   in data)

    # 4. Auth � missing key
    print("\n[4] GET /weather/London � missing key")
    r = httpx.get(f"{BASE_URL}/weather/London", timeout=10)
    check("Status 401", r.status_code == 401, f"got {r.status_code}")

    # 5. Auth � wrong key
    print("\n[5] GET /weather/London � wrong key")
    r = httpx.get(f"{BASE_URL}/weather/London", headers={"Server-API-Key": "wrong-key"}, timeout=10)
    check("Status 401", r.status_code == 401, f"got {r.status_code}")

    # Summary
    total  = len(results)
    passed = sum(results)
    print(f"\n{'-'*50}")
    print(f"  Results: {passed}/{total} passed")
    if passed == total:
        print("  All tests passed!")
    else:
        print(f"  {total - passed} test(s) failed.")
    print(f"{'-'*50}\n")
    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    run_tests()
