import json
import os
import re
import secrets
import sys
from dataclasses import asdict, replace
from typing import Annotated, Any, NoReturn
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool

from backend import database
from backend.evidence import EvidenceInput, PaymentData, assess_evidence


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
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"api-m.sandbox.paypal.com", "api.sandbox.paypal.com"}
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
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
        allow_redirects=False,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_dispute(base_url: str, token: str, dispute_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{base_url}/v1/customer/disputes/{dispute_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
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


def get_capture(base_url: str, token: str, capture_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{base_url}/v2/payments/captures/{capture_id}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


def capture_id_for_dispute(payload: dict[str, Any]) -> str | None:
    transactions = payload.get("disputed_transactions") or []
    if len(transactions) != 1:
        return None
    capture_id = transactions[0].get("seller_transaction_id")
    if isinstance(capture_id, str) and re.fullmatch(r"[A-Z0-9-]+", capture_id):
        return capture_id
    return None


def assess_paypal_dispute(
    dispute: dict[str, Any],
    capture: dict[str, Any] | None,
    payment_source: str,
) -> dict[str, Any]:
    capture_id = capture_id_for_dispute(dispute)
    payment = None
    # A held dispute transaction is not the historical capture status.
    if capture and capture_id and capture.get("id") == capture_id:
        if capture.get("status") == "COMPLETED":
            payment = PaymentData("COMPLETED", source=payment_source)
        else:
            payment_source += ": historical completion not established by current status"
    assessment = assess_evidence(
        EvidenceInput(dispute_reason=dispute.get("reason") or "", payment=payment)
    )
    assessment = replace(
        assessment,
        facts=[
            replace(fact, source=payment_source)
            if fact.fact_id == "payment_completed" else fact
            for fact in assessment.facts
        ],
    )
    return {"dispute_id": dispute["dispute_id"], **asdict(assessment)}


@app.get("/api/disputes/{dispute_id}/assessment")
def read_assessment(
    dispute_id: Annotated[str, Path(pattern=r"^[A-Z0-9-]+$")],
) -> dict[str, Any]:
    base_url = paypal_base_url()
    try:
        token = get_access_token(base_url)
        dispute = get_dispute(base_url, token, dispute_id)
    except requests.RequestException as error:
        raise_paypal_error(error)
    return assessment_for_dispute(base_url, token, dispute)


def assessment_for_dispute(
    base_url: str, token: str, dispute: dict[str, Any],
) -> dict[str, Any]:
    capture_id = capture_id_for_dispute(dispute)
    capture = None
    source = "paypal.disputed_transactions: missing or ambiguous seller transaction ID"
    if capture_id:
        source = f"paypal:/v2/payments/captures/{capture_id}"
        try:
            capture = get_capture(base_url, token, capture_id)
        except requests.RequestException as error:
            response = error.response
            status = response.status_code if response is not None else "not available"
            print(
                f"PayPal failure HTTP {status}: {sanitized_body(response, error)}",
                file=sys.stderr,
            )
            source += f": lookup failed HTTP {status}"
    return assess_paypal_dispute(dispute, capture, source)


MESSAGE = 'We are reviewing your dispute and will follow up with additional information.'


def authenticate_merchant(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    expected = os.getenv('DEV_MERCHANT_TOKEN', '')
    merchant = os.getenv('DEV_MERCHANT_ID', '')
    if len(expected) < 32 or not merchant:
        raise HTTPException(503, 'Development merchant credentials are not configured.')
    scheme, _, supplied = (authorization or '').partition(' ')
    if scheme.lower() != 'bearer' or not secrets.compare_digest(
        supplied.encode(), expected.encode(),
    ):
        raise HTTPException(401, 'Merchant authentication required.',
                            headers={'WWW-Authenticate': 'Bearer'})
    return merchant


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: UUID
    action_type: str
    confirmed: StrictBool


@app.post('/api/disputes/{dispute_id}/investigate', status_code=201)
def investigate(
    dispute_id: Annotated[str, Path(pattern=r'^[A-Z0-9-]{1,255}$')],
    merchant: Annotated[str, Depends(authenticate_merchant)],
) -> dict[str, Any]:
    base_url = paypal_base_url()
    try:
        token = get_access_token(base_url)
        dispute = get_dispute(base_url, token, dispute_id)
        if dispute.get('dispute_id') != dispute_id:
            raise HTTPException(502, 'PayPal returned a different dispute.')
        assessment = assessment_for_dispute(base_url, token, dispute)
    except requests.RequestException as error:
        raise_paypal_error(error)
    try:
        return database.create_run(parse_dispute(dispute).model_dump(),
                                   assessment, merchant, MESSAGE)
    except psycopg.Error as error:
        raise HTTPException(503, 'Could not persist investigation.') from error


def verify_message_allowed(dispute: dict[str, Any], dispute_id: str) -> None:
    if (
        dispute.get('dispute_id') != dispute_id
        or dispute.get('dispute_life_cycle_stage') != 'INQUIRY'
        or dispute.get('status') != 'WAITING_FOR_SELLER_RESPONSE'
        or dispute.get('reason') not in {
            'MERCHANDISE_OR_SERVICE_NOT_RECEIVED',
            'MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED', 'UNAUTHORISED',
        }
    ):
        raise HTTPException(409, 'Current dispute does not permit this action.')
    for link in dispute.get('links') or []:
        if link.get('rel') not in ('send_message', 'send-message'):
            continue
        href = link.get('href')
        expected = f'/v1/customer/disputes/{dispute_id}/send-message'
        if link.get('method') == 'POST' and href in {
            f'https://api-m.sandbox.paypal.com{expected}',
            f'https://api.sandbox.paypal.com{expected}',
        }:
            return
    raise HTTPException(409, 'PayPal does not currently offer send_message.')


@app.post('/disputes/{dispute_id}/approve')
def approve(
    dispute_id: Annotated[str, Path(pattern=r'^[A-Z0-9-]{1,255}$')],
    request: ApprovalRequest,
    merchant: Annotated[str, Depends(authenticate_merchant)],
) -> JSONResponse:
    if request.action_type != 'SEND_MESSAGE':
        raise HTTPException(422, 'Only SEND_MESSAGE is supported.')
    if not request.confirmed:
        raise HTTPException(422, 'Explicit merchant confirmation is required.')
    base_url = paypal_base_url()
    try:
        run = database.get_pending_run(request.run_id, dispute_id, merchant)
    except psycopg.Error as error:
        raise HTTPException(503, 'Database unavailable. No action was dispatched.') from error
    if run['action_type'] != 'SEND_MESSAGE' or run['message'] != MESSAGE:
        raise HTTPException(409, 'Run does not contain the supported message action.')
    try:
        token = get_access_token(base_url)
        current = get_dispute(base_url, token, dispute_id)
    except requests.RequestException as error:
        raise_paypal_error(error)
    verify_message_allowed(current, dispute_id)
    try:
        database.reserve(request.run_id, dispute_id, merchant,
                         parse_dispute(current).model_dump())
    except psycopg.Error as error:
        raise HTTPException(503, 'Reservation failed. No action was dispatched.') from error

    from backend.paypal_writes import send_message

    status, result = send_message(base_url, token, dispute_id, run['message'])
    try:
        database.finish(request.run_id, status, result, merchant)
    except psycopg.Error as error:
        raise HTTPException(
            503, 'Result persistence failed. Action requires reconciliation; do not retry.',
        ) from error
    return JSONResponse(
        status_code=200 if status == 'SUCCEEDED' else 502,
        content={'run_id': str(request.run_id), 'execution_status': status,
                 'paypal_result': result},
    )
