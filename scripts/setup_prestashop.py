#!/usr/bin/env python3
"""
Set up PrestaShop for integration testing.

Run after docker compose services are healthy:
    docker compose -f docker-compose.test.yml up -d presta-db prestashop
    python scripts/setup_prestashop.py
"""

import subprocess
import sys
import time

PS_HOST = "127.0.0.1"
PS_PORT = 8889
PS_URL = f"http://{PS_HOST}:{PS_PORT}"
COMPOSE_FILE = "docker-compose.test.yml"

API_KEY = "TESTKEY123456789ABCDEFGHIJKLMNOP"


def mysql_exec(sql: str) -> str:
    cmd = f"docker compose -f {COMPOSE_FILE} exec -T presta-db mysql -uprestashop -pprestashop prestashop -e {repr(sql)}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def docker_exec(cmd: str) -> str:
    full_cmd = f"docker compose -f {COMPOSE_FILE} exec -T prestashop bash -c {repr(cmd)}"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def wait_for_service():
    import socket
    print("Waiting for PrestaShop...")
    for _ in range(60):
        try:
            with socket.create_connection((PS_HOST, PS_PORT), timeout=2):
                print("  PrestaShop is up.")
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(3)
    print("  PrestaShop did not start in time.")
    return False


def setup_database():
    """Enable webservice, create API key, fix domain, and set permissions via SQL."""
    print("Configuring database...")

    # Enable webservice
    mysql_exec("""
        INSERT INTO ps_configuration (name, value, date_add, date_upd)
        VALUES ('PS_WEBSERVICE', '1', NOW(), NOW())
        ON DUPLICATE KEY UPDATE value = '1'
    """)

    # Fix shop domain for 127.0.0.1 access
    mysql_exec(f"""
        UPDATE ps_shop_url SET domain = '{PS_HOST}:{PS_PORT}', domain_ssl = '{PS_HOST}:{PS_PORT}' WHERE id_shop = 1
    """)
    mysql_exec(f"""
        UPDATE ps_configuration SET value = '{PS_HOST}:{PS_PORT}' WHERE name IN ('PS_SHOP_DOMAIN', 'PS_SHOP_DOMAIN_SSL')
    """)

    # Create API key
    mysql_exec(f"""
        INSERT INTO ps_webservice_account (`key`, description, class_name, is_module, module_name, active)
        VALUES ('{API_KEY}', 'Test', '', 0, '', 1)
        ON DUPLICATE KEY UPDATE active = 1
    """)

    # Get key ID
    result = mysql_exec(f"SELECT id_webservice_account FROM ps_webservice_account WHERE `key` = '{API_KEY}'")
    key_id = result.strip().split('\n')[-1].strip()
    print(f"  API key ID: {key_id}")

    # Link key to shop
    mysql_exec(f"INSERT IGNORE INTO ps_webservice_account_shop (id_webservice_account, id_shop) VALUES ({key_id}, 1)")

    # Grant all permissions for needed resources
    resources = [
        "orders", "products", "categories", "customers", "addresses",
        "countries", "states", "stock_availables", "images",
        "order_histories", "taxes", "combinations", "product_options",
        "product_option_values", "manufacturers", "suppliers",
    ]
    methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"]
    for resource in resources:
        for method in methods:
            mysql_exec(f"""
                INSERT IGNORE INTO ps_webservice_permission (id_webservice_account, resource, method)
                VALUES ({key_id}, '{resource}', '{method}')
            """)

    print("  Database configured.")


def clear_cache():
    """Clear PrestaShop cache."""
    print("Clearing cache...")
    docker_exec("rm -rf /var/www/html/var/cache/prod/* /var/www/html/var/cache/dev/* 2>/dev/null")


def verify():
    import requests
    print("Verifying API access...")
    try:
        resp = requests.get(
            f"{PS_URL}/api/products",
            params={"ws_key": API_KEY, "output_format": "JSON"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            products = data.get("products", [])
            count = len(products) if isinstance(products, list) else 0
            print(f"  API works! Products: {count}")
            return True
        print(f"  API returned {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"  API error: {e}")
        return False


def main():
    if not wait_for_service():
        return 1

    print("Waiting for auto-install to complete...")
    time.sleep(15)

    setup_database()
    clear_cache()

    # Give PS a moment to pick up the changes
    time.sleep(3)

    print()
    if verify():
        print(f"\nPrestaShop ready at {PS_URL}")
        print(f"  api_key: {API_KEY}")
        print(f"  Use ws_key query param for auth")
        return 0
    else:
        print("\nSetup failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
