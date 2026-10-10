from backend.evidence import (
    ITEM_NOT_RECEIVED,
    NOT_AS_DESCRIBED,
    UNAUTHORISED,
    AuthorizationData,
    DescriptionData,
    EvidenceInput,
    FactStatus,
    PaymentData,
    PolicyData,
    RefundData,
    RiskLevel,
    RuleOutcome,
    ShipmentData,
    assess_evidence,
)


ADDRESS = "2211 N First St, San Jose, CA 95131"


def complete_inr(**changes) -> EvidenceInput:
    values = {
        "dispute_reason": ITEM_NOT_RECEIVED,
        "payment": PaymentData("COMPLETED", ADDRESS),
        "shipment": ShipmentData(True, "DELIVERED", ADDRESS),
        "policy": PolicyData(True),
        "refund": RefundData(False),
    }
    values.update(changes)
    return EvidenceInput(**values)


def fact(assessment, fact_id: str):
    return next(item for item in assessment.facts if item.fact_id == fact_id)


def test_completed_payment_is_verified_support() -> None:
    assessment = assess_evidence(
        EvidenceInput(ITEM_NOT_RECEIVED, payment=PaymentData("COMPLETED"))
    )

    assert fact(assessment, "payment_completed").status is FactStatus.VERIFIED
    assert "payment_completed" in assessment.supporting_fact_ids


def test_missing_tracking_is_not_delivery_evidence() -> None:
    assessment = assess_evidence(
        complete_inr(shipment=ShipmentData(True, None, ADDRESS))
    )

    assert fact(assessment, "delivery_confirmed").status is FactStatus.MISSING
    assert "delivery_confirmed" not in assessment.supporting_fact_ids
    assert assessment.risk is RiskLevel.MEDIUM


def test_confirmed_delivery_allows_low_risk_with_complete_evidence() -> None:
    assessment = assess_evidence(complete_inr())

    assert fact(assessment, "delivery_confirmed").value == "DELIVERED"
    assert assessment.risk is RiskLevel.LOW
    assert assessment.requires_review is False


def test_matching_addresses_are_verified() -> None:
    assessment = assess_evidence(
        complete_inr(
            shipment=ShipmentData(
                True,
                "DELIVERED",
                "  2211 n first st, san jose, ca 95131 ",
            )
        )
    )

    assert fact(assessment, "shipping_address_matches").value is True


def test_address_mismatch_is_high_risk() -> None:
    assessment = assess_evidence(
        complete_inr(shipment=ShipmentData(True, "DELIVERED", "Different address"))
    )

    assert fact(assessment, "shipping_address_matches").value is False
    assert assessment.risk is RiskLevel.HIGH


def test_existing_refund_is_high_risk() -> None:
    assessment = assess_evidence(complete_inr(refund=RefundData(True)))

    assert fact(assessment, "prior_refund_exists").value is True
    assert assessment.risk is RiskLevel.HIGH


def test_incomplete_payment_is_high_risk() -> None:
    assessment = assess_evidence(
        complete_inr(payment=PaymentData("PENDING", ADDRESS))
    )

    assert assessment.risk is RiskLevel.HIGH
    assert "payment_completed" not in assessment.supporting_fact_ids


def test_missing_order_information_is_unknown_and_high_risk() -> None:
    assessment = assess_evidence(EvidenceInput(ITEM_NOT_RECEIVED))

    assert fact(assessment, "payment_completed").status is FactStatus.UNKNOWN
    assert assessment.risk is RiskLevel.HIGH


def test_conflicting_shipment_evidence_is_high_risk() -> None:
    assessment = assess_evidence(
        complete_inr(shipment=ShipmentData(False, "DELIVERED", ADDRESS))
    )

    consistency = next(
        rule for rule in assessment.rules if rule.rule_id == "evidence_consistency"
    )
    assert consistency.outcome is RuleOutcome.FAIL
    assert assessment.risk is RiskLevel.HIGH


def test_unsupported_reason_requires_review() -> None:
    assessment = assess_evidence(EvidenceInput("OTHER"))

    assert assessment.risk is RiskLevel.HIGH
    assert assessment.requires_review is True
    assert assessment.rules[0].rule_id == "supported_dispute_reason"


def test_not_as_described_with_insufficient_evidence() -> None:
    assessment = assess_evidence(
        EvidenceInput(
            NOT_AS_DESCRIBED,
            payment=PaymentData("COMPLETED"),
            policy=PolicyData(True),
            refund=RefundData(False),
            description=DescriptionData(item_description="Blue shirt"),
        )
    )

    assert fact(assessment, "condition_evidence").status is FactStatus.MISSING
    assert assessment.risk is RiskLevel.MEDIUM
    assert assessment.requires_review is True


def test_unauthorized_claim_with_insufficient_evidence() -> None:
    assessment = assess_evidence(
        EvidenceInput(
            UNAUTHORISED,
            payment=PaymentData("COMPLETED"),
            policy=PolicyData(True),
            refund=RefundData(False),
            authorization=AuthorizationData(),
        )
    )

    assert fact(assessment, "authorization_evidence").status is FactStatus.MISSING
    assert assessment.risk is RiskLevel.MEDIUM
    assert assessment.requires_review is True
