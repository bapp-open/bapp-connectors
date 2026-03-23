#!/usr/bin/env python3
"""
Set up WooCommerce for integration testing.

Run after docker compose services are healthy:
    docker compose -f docker-compose.test.yml up -d
    python scripts/setup_woocommerce.py
    uv run --extra dev pytest tests/shop/ -v -m integration
"""

import subprocess
import sys
import time

WOO_HOST = "127.0.0.1"
WOO_PORT = 8888
WOO_URL = f"http://{WOO_HOST}:{WOO_PORT}"
COMPOSE_FILE = "docker-compose.test.yml"
CONTAINER = "woocommerce"

# Known test API keys
CONSUMER_KEY = "ck_testkey123456789"
CONSUMER_SECRET = "cs_testsecret123456789"


def docker_exec(cmd: str) -> str:
    """Run a command inside the woocommerce container."""
    full_cmd = f"docker compose -f {COMPOSE_FILE} exec -T {CONTAINER} bash -c {repr(cmd)}"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def wait_for_service():
    """Wait for WordPress to respond."""
    import socket
    print("Waiting for WordPress...")
    for _ in range(30):
        try:
            with socket.create_connection((WOO_HOST, WOO_PORT), timeout=2):
                print("  WordPress is up.")
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(2)
    print("  WordPress did not start in time.")
    return False


def install_wp_cli():
    """Install WP-CLI inside the WordPress container."""
    print("Installing WP-CLI...")
    docker_exec(
        "test -f /usr/local/bin/wp || "
        "(curl -sO https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar "
        "&& chmod +x wp-cli.phar && mv wp-cli.phar /usr/local/bin/wp)"
    )


def setup_wordpress():
    """Install WordPress core."""
    print("Setting up WordPress...")
    check = docker_exec("wp core is-installed --allow-root 2>/dev/null && echo OK || echo NO")
    if "OK" in check:
        print("  Already installed.")
        return
    docker_exec(
        f"wp core install --allow-root "
        f"--url={WOO_URL} --title=TestShop "
        f"--admin_user=admin --admin_password=admin "
        f"--admin_email=test@test.com --skip-email"
    )
    print("  Installed.")


def setup_woocommerce():
    """Install WooCommerce plugin."""
    print("Setting up WooCommerce...")
    check = docker_exec("wp plugin is-installed woocommerce --allow-root 2>/dev/null && echo OK || echo NO")
    if "OK" in check:
        docker_exec("wp plugin activate woocommerce --allow-root 2>/dev/null")
        print("  Already installed, activated.")
    else:
        docker_exec("wp plugin install woocommerce --activate --allow-root")
        print("  Installed and activated.")

    docker_exec("wp option update woocommerce_store_address '123 Test St' --allow-root 2>/dev/null")
    docker_exec("wp option update woocommerce_default_country RO --allow-root 2>/dev/null")
    docker_exec("wp option update woocommerce_currency RON --allow-root 2>/dev/null")
    docker_exec("wp rewrite structure '/%postname%/' --allow-root 2>/dev/null")
    docker_exec("wp rewrite flush --allow-root 2>/dev/null")


def create_api_keys():
    """Create WooCommerce API keys via wp eval."""
    print("Creating API keys...")
    # Use single-quoted PHP via heredoc to avoid shell escaping issues
    docker_exec(
        """php -r '
define("ABSPATH", "/var/www/html/");
define("WPINC", "wp-includes");
require_once ABSPATH . "wp-load.php";
global $wpdb;
$key = "ck_testkey123456789";
$secret = "cs_testsecret123456789";
$wpdb->delete($wpdb->prefix . "woocommerce_api_keys", array("description" => "Test"));
$wpdb->insert($wpdb->prefix . "woocommerce_api_keys", array(
    "user_id" => 1,
    "description" => "Test",
    "permissions" => "read_write",
    "consumer_key" => wc_api_hash($key),
    "consumer_secret" => $secret,
    "truncated_key" => substr($key, -7),
));
echo "Key ID: " . $wpdb->insert_id . "\\n";
'"""
    )


def enable_http_basic_auth():
    """Allow WooCommerce REST API Basic Auth over HTTP for testing.

    Installs a mu-plugin that hooks into woocommerce_rest_authentication_errors
    to authenticate API requests using WC API keys over HTTP (normally requires HTTPS).
    """
    print("Enabling HTTP Basic Auth for testing...")
    # Write the mu-plugin as a PHP file using a subprocess to avoid escaping issues
    php_code = r'''<?php
// Authenticate WC API key requests over HTTP via determine_current_user (test only)
add_filter("determine_current_user", function($user_id) {
    if ($user_id) return $user_id;
    if (!defined("REST_REQUEST") || !REST_REQUEST) return $user_id;
    $ck = isset($_SERVER["PHP_AUTH_USER"]) ? sanitize_text_field($_SERVER["PHP_AUTH_USER"]) : "";
    if (empty($ck) || !function_exists("wc_api_hash")) return $user_id;
    global $wpdb;
    $row = $wpdb->get_row($wpdb->prepare(
        "SELECT user_id FROM {$wpdb->prefix}woocommerce_api_keys WHERE consumer_key = %s",
        wc_api_hash($ck)
    ));
    return $row ? (int)$row->user_id : $user_id;
}, 20);
'''
    full_cmd = (
        f"docker compose -f {COMPOSE_FILE} exec -T {CONTAINER} bash -c "
        f"'mkdir -p /var/www/html/wp-content/mu-plugins'"
    )
    subprocess.run(full_cmd, shell=True, capture_output=True)

    # Write the PHP file via python through docker exec stdin
    full_cmd = (
        f"docker compose -f {COMPOSE_FILE} exec -T {CONTAINER} "
        f"tee /var/www/html/wp-content/mu-plugins/force-basic-auth.php"
    )
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, input=php_code)

    check = docker_exec("cat /var/www/html/wp-content/mu-plugins/force-basic-auth.php 2>/dev/null")
    if "determine_current_user" in check:
        print("  Installed mu-plugin.")
    else:
        print("  WARNING: mu-plugin may not have been written correctly.")


def ensure_auth_header_passthrough():
    """Ensure Apache passes Authorization header to PHP."""
    print("Ensuring auth header passthrough...")
    docker_exec(
        'grep -q "HTTP_AUTHORIZATION" /var/www/html/.htaccess 2>/dev/null || '
        'echo \'SetEnvIf Authorization "(.*)" HTTP_AUTHORIZATION=$1\' >> /var/www/html/.htaccess'
    )
    print("  Done.")


def verify():
    """Verify WooCommerce API is accessible."""
    import requests
    print("Verifying API access...")
    try:
        resp = requests.get(
            f"{WOO_URL}/wp-json/wc/v3/products",
            auth=(CONSUMER_KEY, CONSUMER_SECRET),
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"  API works! Status: {resp.status_code}")
            return True
        print(f"  API returned {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        print(f"  API error: {e}")
        return False


def main():
    if not wait_for_service():
        return 1

    install_wp_cli()
    setup_wordpress()
    setup_woocommerce()
    create_api_keys()
    enable_http_basic_auth()
    ensure_auth_header_passthrough()

    print()
    if verify():
        print(f"\nWooCommerce ready at {WOO_URL}")
        print(f"  consumer_key:    {CONSUMER_KEY}")
        print(f"  consumer_secret: {CONSUMER_SECRET}")
        return 0
    else:
        print("\nSetup failed — API not accessible.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
