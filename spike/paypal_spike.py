import argparse
import json
import os
import sys
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()

PAYPAL_BASE_URL = os.getenv(
    "PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"
).rstrip("/")
REQUEST_TIMEOUT_SECONDS = 20


def get_access_token() -> str:
    """Authenticate with PayPal using the OAuth2 client-credentials flow."""
    client_id = os.getenv("PAYPAL_CLIENT_ID")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(
            "PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set in the environment."
        )

    response = requests.post(
        f"{PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def list_disputes(token: str) -> dict[str, Any]:
    """Return the current account's PayPal disputes."""
    response = requests.get(
        f"{PAYPAL_BASE_URL}/v1/customer/disputes",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def get_dispute_response(token: str, dispute_id: str) -> requests.Response:
    response = requests.get(
        f"{PAYPAL_BASE_URL}/v1/customer/disputes/{dispute_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def get_dispute(token: str, dispute_id: str) -> dict[str, Any]:
    """Return one PayPal dispute by ID."""
    response = get_dispute_response(token, dispute_id)
    return response.json()


def _sanitized(data: Any) -> Any:
    private_keys = {
        "account_id",
        "address",
        "email",
        "email_address",
        "name",
        "payer_id",
        "phone_number",
    }
    if isinstance(data, dict):
        return {
            key: "[redacted]" if key in private_keys else _sanitized(value)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_sanitized(value) for value in data]
    return data


def _values_for_key(data: Any, wanted_key: str) -> list[Any]:
    """Find values for an exact key anywhere in a nested JSON response."""
    values: list[Any] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key == wanted_key:
                values.append(value)
            values.extend(_values_for_key(value, wanted_key))
    elif isinstance(data, list):
        for item in data:
            values.extend(_values_for_key(item, wanted_key))
    return values


def _related_fields(data: Any, path: str = "") -> list[tuple[str, Any]]:
    """Find order, capture, shipment, and tracking fields without assuming a schema."""
    matches: list[tuple[str, Any]] = []
    keywords = ("order", "capture", "shipment", "tracking")
    if isinstance(data, dict):
        for key, value in data.items():
            field_path = f"{path}.{key}" if path else key
            if any(keyword in key.lower() for keyword in keywords):
                matches.append((field_path, value))
            matches.extend(_related_fields(value, field_path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            matches.extend(_related_fields(item, f"{path}[{index}]"))
    return matches


def _print_value(label: str, values: list[Any]) -> None:
    print(f"  {label}:")
    if not values:
        print("    not present")
        return
    for value in values:
        rendered = json.dumps(value, indent=2, sort_keys=True)
        print(f"    {rendered}")


def _print_dispute_summary(dispute: dict[str, Any]) -> None:
    print("\nDispute inspection:")
    _print_value("dispute ID", _values_for_key(dispute, "dispute_id"))
    _print_value("status", _values_for_key(dispute, "status"))
    _print_value("reason", _values_for_key(dispute, "reason"))
    _print_value("dispute amount", _values_for_key(dispute, "dispute_amount"))
    _print_value(
        "allowed response options",
        _values_for_key(dispute, "allowed_response_options"),
    )
    _print_value("transaction IDs", _values_for_key(dispute, "transaction_id"))
    _print_value(
        "buyer transaction IDs", _values_for_key(dispute, "buyer_transaction_id")
    )
    _print_value(
        "seller transaction IDs", _values_for_key(dispute, "seller_transaction_id")
    )

    print("  order/capture/shipment/tracking-related fields:")
    related = _related_fields(dispute)
    if not related:
        print("    not present")
    else:
        for path, value in related:
            print(f"    {path}: {json.dumps(value, indent=2, sort_keys=True)}")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="PayPal Sandbox disputes spike")
    cli.add_argument(
        "--dispute-id",
        help="fetch a dispute directly without relying on the dispute list",
    )
    return cli


def main() -> int:
    args = parser().parse_args()
    if "sandbox" not in PAYPAL_BASE_URL.lower():
        print(
            "FAIL: PAYPAL_BASE_URL must contain 'sandbox'. No API request sent.",
            file=sys.stderr,
        )
        return 1

    try:
        token = get_access_token()
        print("PASS: Authenticated with PayPal Sandbox (access token received).")

        if args.dispute_id:
            response = get_dispute_response(token, args.dispute_id)
            dispute = response.json()
            print(f"PASS: HTTP {response.status_code}")
            print(f"PASS: Fetched dispute {args.dispute_id} directly.")
            print(json.dumps(_sanitized(dispute), indent=2, sort_keys=True))
            _print_dispute_summary(_sanitized(dispute))
            return 0

        dispute_list = list_disputes(token)
        print("PASS: Listed PayPal disputes.")
        print("\nDispute list response:")
        print(json.dumps(_sanitized(dispute_list), indent=2, sort_keys=True))

        disputes = dispute_list.get("items", [])
        if not disputes:
            print(
                "\nPASS: Authentication worked, but no sandbox disputes currently exist."
            )
            return 0

        dispute_id = disputes[0].get("dispute_id")
        if not dispute_id:
            raise ValueError("The first dispute did not contain a dispute_id.")

        dispute = get_dispute(token, dispute_id)
        print(f"\nPASS: Fetched dispute {dispute_id}.")
        print("\nDispute detail response:")
        sanitized = _sanitized(dispute)
        print(json.dumps(sanitized, indent=2, sort_keys=True))
        _print_dispute_summary(sanitized)
        return 0
    except requests.HTTPError as error:
        response = error.response
        status = response.status_code if response is not None else "not available"
        body = response.text[:1000] if response is not None else str(error)
        print(f"FAIL: HTTP {status}", file=sys.stderr)
        print(f"PayPal response: {body}", file=sys.stderr)
        return 1
    except (requests.RequestException, ValueError, KeyError) as error:
        print("FAIL: HTTP status not available", file=sys.stderr)
        print(f"PayPal response: {str(error)[:1000]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
