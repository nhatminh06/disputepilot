import json
import os
import sys
from typing import Annotated, Any, NoReturn

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel


load_dotenv()

DEFAULT_PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"
REQUEST_TIMEOUT_SECONDS = 20

app = FastAPI(title="DisputePilot")


class DisputeResponse(BaseModel):
    dispute_id: str
    status: str | None
    lifecycle_stage: str | None
    reason: str | None
    amount: str | None
    currency: str | None
    response_deadline: str | None
    seller_transaction_id: str | None
    requested_evidence_types: list[str]
    available_actions: list[str]


def paypal_base_url() -> str:
    base_url = os.getenv("PAYPAL_BASE_URL", DEFAULT_PAYPAL_BASE_URL).rstrip("/")
    if "sandbox" not in base_url.lower():
        raise HTTPException(
            status_code=500,
            detail="PAYPAL_BASE_URL must point to PayPal Sandbox.",
        )
    return base_url


def get_access_token(base_url: str) -> str:
    client_id = os.getenv("PAYPAL_CLIENT_ID")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="PayPal credentials are missing.")

    response = requests.post(
        f"{base_url}/v1/oauth2/token",
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        data={"grant_type": "client_credentials"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_dispute(base_url: str, token: str, dispute_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{base_url}/v1/customer/disputes/{dispute_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def parse_dispute(payload: dict[str, Any]) -> DisputeResponse:
    dispute_amount = payload.get("dispute_amount") or {}
    transactions = payload.get("disputed_transactions") or []
    seller_transaction_id = next(
        (
            transaction.get("seller_transaction_id")
            for transaction in transactions
            if transaction.get("seller_transaction_id")
        ),
        None,
    )
    evidence_types = sorted(
        {
            evidence["evidence_type"]
            for evidence in payload.get("evidences") or []
            if evidence.get("source") == "REQUESTED_FROM_SELLER"
            and evidence.get("evidence_type")
        }
    )
    actions = sorted(
        {
            link["rel"]
            for link in payload.get("links") or []
            if link.get("method") != "GET" and link.get("rel")
        }
    )

    return DisputeResponse(
        dispute_id=payload["dispute_id"],
        status=payload.get("status"),
        lifecycle_stage=payload.get("dispute_life_cycle_stage"),
        reason=payload.get("reason"),
        amount=dispute_amount.get("value"),
        currency=dispute_amount.get("currency_code"),
        response_deadline=payload.get("seller_response_due_date"),
        seller_transaction_id=seller_transaction_id,
        requested_evidence_types=evidence_types,
        available_actions=actions,
    )


def sanitized_body(response: requests.Response | None, error: Exception) -> str:
    if response is None:
        return str(error)[:1000]
    try:
        body = response.json()
    except requests.JSONDecodeError:
        text = response.text
        for secret in (
            os.getenv("PAYPAL_CLIENT_ID"),
            os.getenv("PAYPAL_CLIENT_SECRET"),
        ):
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:1000]

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[redacted]"
                if any(
                    word in key.lower()
                    for word in ("token", "secret", "authorization")
                )
                else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return json.dumps(redact(body))[:1000]


def raise_paypal_error(error: requests.RequestException) -> NoReturn:
    response = error.response
    status = response.status_code if response is not None else "not available"
    body = sanitized_body(response, error)
    print(f"PayPal failure HTTP {status}: {body}", file=sys.stderr)
    raise HTTPException(
        status_code=502,
        detail=f"PayPal request failed with HTTP {status}.",
    ) from error


@app.get("/api/disputes/{dispute_id}", response_model=DisputeResponse)
def read_dispute(
    dispute_id: Annotated[str, Path(pattern=r"^[A-Z0-9-]+$")],
) -> DisputeResponse:
    base_url = paypal_base_url()
    try:
        token = get_access_token(base_url)
        payload = get_dispute(base_url, token, dispute_id)
    except requests.RequestException as error:
        raise_paypal_error(error)
    return parse_dispute(payload)
