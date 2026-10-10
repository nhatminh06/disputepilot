import json

import pytest
import requests
from fastapi import HTTPException

from backend import main


@pytest.fixture
def dispute() -> dict:
    return {
        "dispute_id": "PP-R-TEST",
        "reason": "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
        "disputed_transactions": [
            {"seller_transaction_id": "CAPTURE123", "transaction_status": "HELD"}
        ],
    }


def response(payload: dict, status: int = 200) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


@pytest.fixture
def paypal(monkeypatch, dispute) -> list:
    calls = []
    monkeypatch.setenv("PAYPAL_BASE_URL", main.DEFAULT_PAYPAL_BASE_URL)
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")

    def request(session, method, url, **kwargs):
        calls.append((method.upper(), url))
        assert kwargs["timeout"] == 20
        assert kwargs["allow_redirects"] is False
        if method.upper() == "POST":
            assert url.endswith("/v1/oauth2/token")
            assert kwargs["data"] == {"grant_type": "client_credentials"}
            return response({"access_token": "test-token"})
        assert method.upper() == "GET"
        if url.endswith("/v1/customer/disputes/PP-R-TEST"):
            return response(dispute)
        assert url.endswith("/v2/payments/captures/CAPTURE123")
        return response({"id": "CAPTURE123", "status": "COMPLETED"})

    monkeypatch.setattr(requests.Session, "request", request)
    return calls


def test_mapping_and_no_financial_writes(paypal) -> None:
    result = main.read_assessment("PP-R-TEST")
    facts = {fact["fact_id"]: fact for fact in result["facts"]}
    assert result["dispute_id"] == "PP-R-TEST"
    assert result["risk"] == "MEDIUM"
    assert result["requires_review"] is True
    assert result["supporting_fact_ids"] == ["payment_completed"]
    assert facts["payment_completed"]["value"] == "COMPLETED"
    assert facts["payment_completed"]["source"].endswith("/CAPTURE123")
    for name in (
        "delivery_confirmed", "shipping_address_matches", "prior_refund_exists",
        "shipment_record_exists", "merchant_policy_supports_contest",
    ):
        assert facts[name]["status"] == "UNKNOWN"
        assert facts[name]["value"] is None
    assert [method for method, url in paypal] == ["POST", "GET", "GET"]


@pytest.mark.parametrize("transactions", [[], [{}, {}], [{}], [
    {"seller_transaction_id": "../refund"},
]])
def test_missing_or_ambiguous_capture(paypal, dispute, transactions) -> None:
    dispute["disputed_transactions"] = transactions
    result = main.read_assessment("PP-R-TEST")
    assert result["risk"] == "HIGH"
    assert result["facts"][0]["status"] == "UNKNOWN"
    assert len(paypal) == 2


@pytest.mark.parametrize("status", [403, 404, 500, None])
def test_capture_failure_is_conservative(paypal, monkeypatch, capsys, status) -> None:
    def fail(*args):
        if status is None:
            raise requests.Timeout("capture lookup timed out")
        raise requests.HTTPError(response=response({"name": "ERROR"}, status))

    monkeypatch.setattr(main, "get_capture", fail)
    result = main.read_assessment("PP-R-TEST")
    assert result["risk"] == "HIGH"
    assert result["facts"][0]["status"] == "UNKNOWN"
    assert "lookup failed" in result["facts"][0]["source"]
    assert "PayPal failure HTTP" in capsys.readouterr().err


@pytest.mark.parametrize("capture", [
    {"id": "OTHER", "status": "COMPLETED"},
    {"id": "CAPTURE123", "status": "PENDING",
     "status_details": {"reason": "BUYER_COMPLAINT"}},
    {"id": "CAPTURE123"},
])
def test_unverified_capture_is_not_payment_evidence(dispute, capture) -> None:
    result = main.assess_paypal_dispute(dispute, capture, "paypal:capture")
    assert result["facts"][0]["status"] == "UNKNOWN"
    assert result["supporting_fact_ids"] == []
    assert result["risk"] == "HIGH"


@pytest.mark.parametrize("url", [
    "https://sandbox.attacker.com", "https://api-m.paypal.com",
    "http://api-m.sandbox.paypal.com", "https://api-m.sandbox.paypal.com.evil.com",
    "https://user@api-m.sandbox.paypal.com", "https://api-m.sandbox.paypal.com:444",
    "https://api-m.sandbox.paypal.com/path", "https://api-m.sandbox.paypal.com?q=x",
])
def test_untrusted_url_aborts_before_auth(paypal, monkeypatch, url) -> None:
    monkeypatch.setenv("PAYPAL_BASE_URL", url)
    with pytest.raises(HTTPException) as caught:
        main.read_assessment("PP-R-TEST")
    assert caught.value.status_code == 500
    assert paypal == []


@pytest.mark.parametrize("host", ["api-m.sandbox.paypal.com", "api.sandbox.paypal.com"])
def test_trusted_sandbox_hostname(monkeypatch, host) -> None:
    monkeypatch.setenv("PAYPAL_BASE_URL", f"https://{host}/")
    assert main.paypal_base_url() == f"https://{host}"
