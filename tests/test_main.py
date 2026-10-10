import requests
import pytest
from fastapi import HTTPException

from backend import main


def test_parse_dispute() -> None:
    payload = {
        "dispute_id": "PP-R-TEST",
        "status": "WAITING_FOR_SELLER_RESPONSE",
        "dispute_life_cycle_stage": "INQUIRY",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "dispute_amount": {"value": "10.00", "currency_code": "USD"},
        "seller_response_due_date": "2026-10-30T04:33:35.822Z",
        "disputed_transactions": [
            {"seller_transaction_id": "SELLER-TRANSACTION"}
        ],
        "evidences": [
            {
                "evidence_type": "PROOF_OF_FULFILLMENT",
                "source": "REQUESTED_FROM_SELLER",
            },
            {"evidence_type": "CREATE", "source": "SUBMITTED_BY_BUYER"},
        ],
        "links": [
            {"rel": "self", "method": "GET"},
            {"rel": "provide_evidence", "method": "POST"},
            {"rel": "accept_claim", "method": "POST"},
        ],
    }

    dispute = main.parse_dispute(payload)

    assert dispute.model_dump() == {
        "dispute_id": "PP-R-TEST",
        "status": "WAITING_FOR_SELLER_RESPONSE",
        "lifecycle_stage": "INQUIRY",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "amount": "10.00",
        "currency": "USD",
        "response_deadline": "2026-10-30T04:33:35.822Z",
        "seller_transaction_id": "SELLER-TRANSACTION",
        "requested_evidence_types": ["PROOF_OF_FULFILLMENT"],
        "available_actions": ["accept_claim", "provide_evidence"],
    }


def test_parse_dispute_with_missing_optional_fields() -> None:
    dispute = main.parse_dispute({"dispute_id": "PP-R-TEST"})

    assert dispute.status is None
    assert dispute.amount is None
    assert dispute.seller_transaction_id is None
    assert dispute.requested_evidence_types == []
    assert dispute.available_actions == []


def test_rejects_non_sandbox_url(monkeypatch) -> None:
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")

    with pytest.raises(HTTPException) as caught:
        main.read_dispute("PP-R-TEST")

    assert caught.value.status_code == 500
    assert caught.value.detail == "PAYPAL_BASE_URL must point to PayPal Sandbox."


def test_paypal_error_does_not_expose_token(monkeypatch, capsys) -> None:
    paypal_response = requests.Response()
    paypal_response.status_code = 403
    paypal_response._content = b'{"name":"NOT_AUTHORIZED","access_token":"hidden"}'
    error = requests.HTTPError(response=paypal_response)

    def fail_auth(base_url: str) -> str:
        raise error

    monkeypatch.setattr(main, "get_access_token", fail_auth)

    with pytest.raises(HTTPException) as caught:
        main.read_dispute("PP-R-TEST")

    assert caught.value.status_code == 502
    assert caught.value.detail == "PayPal request failed with HTTP 403."
    assert "hidden" not in capsys.readouterr().err
