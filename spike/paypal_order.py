import argparse
import json
import sys
from typing import Any
from uuid import uuid4

import requests

from paypal_spike import PAYPAL_BASE_URL, REQUEST_TIMEOUT_SECONDS, get_access_token


def create_order(token: str, request_id: str) -> requests.Response:
    response = requests.post(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": request_id,
            "Prefer": "return=representation",
        },
        json={
            "intent": "CAPTURE",
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": "https://example.com/",
                        "cancel_url": "https://example.com/",
                    }
                }
            },
            "purchase_units": [
                {
                    "description": "DisputePilot sandbox test",
                    "amount": {"currency_code": "USD", "value": "10.00"},
                }
            ],
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def get_order(token: str, order_id: str) -> requests.Response:
    response = requests.get(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def capture_order(token: str, order_id: str, request_id: str) -> requests.Response:
    response = requests.post(
        f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": request_id,
            "Prefer": "return=representation",
        },
        json={},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def approval_url(order: dict[str, Any]) -> str | None:
    for link in order.get("links", []):
        if link.get("rel") in {"approve", "payer-action"}:
            return link.get("href")
    return None


def print_create(response: requests.Response) -> None:
    order = response.json()
    print(f"PASS: HTTP {response.status_code}")
    print(f"Order ID: {order.get('id', 'not present')}")
    print(f"Order status: {order.get('status', 'not present')}")
    print(f"Approval URL: {approval_url(order) or 'not present'}")


def print_get(response: requests.Response) -> None:
    order = response.json()
    fields = {
        "id": order.get("id", "not present"),
        "status": order.get("status", "not present"),
        "purchase_units": order.get("purchase_units", "not present"),
        "payment_source": order.get("payment_source", "not present"),
        "links": order.get("links", "not present"),
    }
    print(f"PASS: HTTP {response.status_code}")
    print(json.dumps(fields, indent=2, sort_keys=True))


def print_capture(response: requests.Response) -> None:
    order = response.json()
    captures = [
        capture
        for unit in order.get("purchase_units", [])
        for capture in unit.get("payments", {}).get("captures", [])
    ]
    capture = captures[0] if captures else {}
    print(f"PASS: HTTP {response.status_code}")
    print(f"Order ID: {order.get('id', 'not present')}")
    print(f"Order status: {order.get('status', 'not present')}")
    print(f"Capture ID: {capture.get('id', 'not present')}")
    print(f"Capture status: {capture.get('status', 'not present')}")
    amount = capture.get("amount", "not present")
    print(f"Capture amount: {json.dumps(amount, sort_keys=True)}")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="PayPal Sandbox Orders v2 spike")
    commands = cli.add_subparsers(dest="operation", required=True)
    commands.add_parser("create")
    for operation in ("get", "capture"):
        command = commands.add_parser(operation)
        command.add_argument("order_id")
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
        if args.operation == "create":
            request_id = str(uuid4())
            print(f"PayPal-Request-Id: {request_id}")
            print_create(create_order(token, request_id))
        elif args.operation == "get":
            print_get(get_order(token, args.order_id))
        else:
            request_id = str(uuid4())
            print(f"PayPal-Request-Id: {request_id}")
            print_capture(capture_order(token, args.order_id, request_id))
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
