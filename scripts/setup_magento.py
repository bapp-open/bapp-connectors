#!/usr/bin/env python3
"""
Set up Magento 2 for integration testing.

Run after docker compose services are healthy:
    docker compose -f docker-compose.test.yml up -d magento-db magento
    python scripts/setup_magento.py
"""

import subprocess
import sys
import time

MG_HOST = "127.0.0.1"
MG_PORT = 8890
MG_URL = f"http://{MG_HOST}:{MG_PORT}"
COMPOSE_FILE = "docker-compose.test.yml"

# Admin credentials for token generation
ADMIN_USER = "admin"
ADMIN_PASS = "Admin123!"
ACCESS_TOKEN = None


def wait_for_service():
    import socket
    print("Waiting for Magento (this can take 2-3 minutes on first run)...")
    for _ in range(60):
        try:
            with socket.create_connection((MG_HOST, MG_PORT), timeout=2):
                print("  Magento is up.")
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(5)
    print("  Magento did not start in time.")
    return False


def get_admin_token():
    """Get an admin bearer token via POST /rest/V1/integration/admin/token."""
    import requests
    global ACCESS_TOKEN
    print("Getting admin token...")
    try:
        resp = requests.post(
            f"{MG_URL}/rest/V1/integration/admin/token",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
            timeout=30,
        )
        if resp.status_code == 200:
            ACCESS_TOKEN = resp.json()
            print(f"  Token: {ACCESS_TOKEN[:20]}...")
            return True
        print(f"  Failed: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        return False


def verify():
    import requests
    print("Verifying API access...")
    try:
        resp = requests.get(
            f"{MG_URL}/rest/V1/products",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
            params={"searchCriteria[pageSize]": "1"},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total_count", 0)
            print(f"  API works! Products: {total}")
            return True
        print(f"  API returned {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"  API error: {e}")
        return False


def main():
    if not wait_for_service():
        return 1

    # Wait extra for Magento setup to finish
    print("Waiting for Magento setup to complete...")
    time.sleep(30)

    if not get_admin_token():
        print("Retrying after 30s...")
        time.sleep(30)
        if not get_admin_token():
            print("\nFailed to get admin token.")
            return 1

    print()
    if verify():
        print(f"\nMagento ready at {MG_URL}")
        print(f"  access_token: {ACCESS_TOKEN}")
        return 0
    else:
        print("\nSetup failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
