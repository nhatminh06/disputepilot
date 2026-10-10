from dataclasses import dataclass
from enum import StrEnum


ITEM_NOT_RECEIVED = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"
NOT_AS_DESCRIBED = "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
UNAUTHORISED = "UNAUTHORISED"


class FactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RuleOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidenceFact:
    fact_id: str
    status: FactStatus
    value: str | bool | None
    source: str


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    outcome: RuleOutcome
    fact_ids: list[str]
    explanation: str


@dataclass(frozen=True)
class EvidenceAssessment:
    dispute_reason: str
    risk: RiskLevel
    requires_review: bool
    facts: list[EvidenceFact]
    supporting_fact_ids: list[str]
    rules: list[RuleResult]


@dataclass(frozen=True)
class PaymentData:
    status: str | None
    shipping_address: str | None = None
    source: str = "payment"


@dataclass(frozen=True)
class ShipmentData:
    exists: bool
    tracking_status: str | None = None
    shipping_address: str | None = None
    source: str = "shipment"


@dataclass(frozen=True)
class PolicyData:
    supports_contest: bool
    source: str = "merchant_policy"


@dataclass(frozen=True)
class RefundData:
    exists: bool
    source: str = "refund_history"


@dataclass(frozen=True)
class DescriptionData:
    item_description: str | None = None
    condition_evidence: str | None = None
    source: str = "order_and_fulfillment"


@dataclass(frozen=True)
class AuthorizationData:
    evidence: str | None = None
    source: str = "payment_authorization"


@dataclass(frozen=True)
class EvidenceInput:
    dispute_reason: str
    payment: PaymentData | None = None
    shipment: ShipmentData | None = None
    policy: PolicyData | None = None
    refund: RefundData | None = None
    description: DescriptionData | None = None
    authorization: AuthorizationData | None = None


def _fact(
    fact_id: str,
    status: FactStatus,
    value: str | bool | None,
    source: str,
) -> EvidenceFact:
    return EvidenceFact(fact_id, status, value, source)


def _payment_fact(payment: PaymentData | None) -> EvidenceFact:
    if payment is None:
        return _fact("payment_completed", FactStatus.UNKNOWN, None, "not_checked")
    if payment.status is None:
        return _fact("payment_completed", FactStatus.MISSING, None, payment.source)
    return _fact(
        "payment_completed",
        FactStatus.VERIFIED,
        payment.status,
        payment.source,
    )


def _shipment_facts(
    payment: PaymentData | None,
    shipment: ShipmentData | None,
) -> list[EvidenceFact]:
    if shipment is None:
        return [
            _fact("shipment_record_exists", FactStatus.UNKNOWN, None, "not_checked"),
            _fact("delivery_confirmed", FactStatus.UNKNOWN, None, "not_checked"),
            _fact("shipping_address_matches", FactStatus.UNKNOWN, None, "not_checked"),
        ]
    if not shipment.exists:
        return [
            _fact("shipment_record_exists", FactStatus.MISSING, None, shipment.source),
            _fact("delivery_confirmed", FactStatus.MISSING, None, shipment.source),
            _fact(
                "shipping_address_matches",
                FactStatus.MISSING,
                None,
                shipment.source,
            ),
        ]

    record = _fact(
        "shipment_record_exists", FactStatus.VERIFIED, True, shipment.source
    )
    if shipment.tracking_status is None:
        delivery = _fact(
            "delivery_confirmed", FactStatus.MISSING, None, shipment.source
        )
    else:
        delivery = _fact(
            "delivery_confirmed",
            FactStatus.VERIFIED,
            shipment.tracking_status,
            shipment.source,
        )

    if payment is None:
        address = _fact(
            "shipping_address_matches", FactStatus.UNKNOWN, None, "not_checked"
        )
    elif payment.shipping_address is None or shipment.shipping_address is None:
        address = _fact(
            "shipping_address_matches", FactStatus.MISSING, None, shipment.source
        )
    else:
        payment_address = " ".join(payment.shipping_address.lower().split())
        shipment_address = " ".join(shipment.shipping_address.lower().split())
        address = _fact(
            "shipping_address_matches",
            FactStatus.VERIFIED,
            payment_address == shipment_address,
            f"{payment.source},{shipment.source}",
        )
    return [record, delivery, address]


def _policy_fact(policy: PolicyData | None) -> EvidenceFact:
    if policy is None:
        return _fact(
            "merchant_policy_supports_contest",
            FactStatus.UNKNOWN,
            None,
            "not_checked",
        )
    return _fact(
        "merchant_policy_supports_contest",
        FactStatus.VERIFIED,
        policy.supports_contest,
        policy.source,
    )


def _refund_fact(refund: RefundData | None) -> EvidenceFact:
    if refund is None:
        return _fact("prior_refund_exists", FactStatus.UNKNOWN, None, "not_checked")
    return _fact(
        "prior_refund_exists", FactStatus.VERIFIED, refund.exists, refund.source
    )


def _description_facts(description: DescriptionData | None) -> list[EvidenceFact]:
    if description is None:
        return [
            _fact("item_description", FactStatus.UNKNOWN, None, "not_checked"),
            _fact("condition_evidence", FactStatus.UNKNOWN, None, "not_checked"),
        ]
    description_fact = _fact(
        "item_description",
        FactStatus.VERIFIED if description.item_description else FactStatus.MISSING,
        description.item_description,
        description.source,
    )
    condition_fact = _fact(
        "condition_evidence",
        FactStatus.VERIFIED if description.condition_evidence else FactStatus.MISSING,
        description.condition_evidence,
        description.source,
    )
    return [description_fact, condition_fact]


def _authorization_fact(
    authorization: AuthorizationData | None,
) -> EvidenceFact:
    if authorization is None:
        return _fact("authorization_evidence", FactStatus.UNKNOWN, None, "not_checked")
    return _fact(
        "authorization_evidence",
        FactStatus.VERIFIED if authorization.evidence else FactStatus.MISSING,
        authorization.evidence,
        authorization.source,
    )


def _supports(fact: EvidenceFact) -> bool:
    if fact.status is not FactStatus.VERIFIED:
        return False
    if fact.fact_id == "payment_completed":
        return fact.value == "COMPLETED"
    if fact.fact_id == "delivery_confirmed":
        return isinstance(fact.value, str) and fact.value.upper() == "DELIVERED"
    if fact.fact_id == "prior_refund_exists":
        return fact.value is False
    return bool(fact.value)


def _rule(fact: EvidenceFact) -> RuleResult:
    if _supports(fact):
        return RuleResult(
            fact.fact_id,
            RuleOutcome.PASS,
            [fact.fact_id],
            f"{fact.fact_id} is verified and supports contesting.",
        )
    if fact.status is FactStatus.VERIFIED:
        return RuleResult(
            fact.fact_id,
            RuleOutcome.FAIL,
            [fact.fact_id],
            f"{fact.fact_id} is verified and does not support contesting.",
        )
    return RuleResult(
        fact.fact_id,
        RuleOutcome.UNKNOWN,
        [fact.fact_id],
        f"{fact.fact_id} lacks verified supporting evidence.",
    )


def assess_evidence(data: EvidenceInput) -> EvidenceAssessment:
    payment = _payment_fact(data.payment)
    policy = _policy_fact(data.policy)
    refund = _refund_fact(data.refund)
    facts = [payment, policy, refund]

    required_ids: list[str]
    if data.dispute_reason == ITEM_NOT_RECEIVED:
        shipment_facts = _shipment_facts(data.payment, data.shipment)
        facts.extend(shipment_facts)
        required_ids = [
            "payment_completed",
            "shipment_record_exists",
            "delivery_confirmed",
            "shipping_address_matches",
            "merchant_policy_supports_contest",
            "prior_refund_exists",
        ]
    elif data.dispute_reason == NOT_AS_DESCRIBED:
        facts.extend(_description_facts(data.description))
        required_ids = [
            "payment_completed",
            "item_description",
            "condition_evidence",
            "merchant_policy_supports_contest",
            "prior_refund_exists",
        ]
    elif data.dispute_reason == UNAUTHORISED:
        facts.append(_authorization_fact(data.authorization))
        required_ids = [
            "payment_completed",
            "authorization_evidence",
            "merchant_policy_supports_contest",
            "prior_refund_exists",
        ]
    else:
        rule = RuleResult(
            "supported_dispute_reason",
            RuleOutcome.FAIL,
            [],
            "The dispute reason is unsupported and requires review.",
        )
        return EvidenceAssessment(
            data.dispute_reason,
            RiskLevel.HIGH,
            True,
            facts,
            [],
            [rule],
        )

    by_id = {fact.fact_id: fact for fact in facts}
    required = [by_id[fact_id] for fact_id in required_ids]
    rules = [_rule(fact) for fact in required]
    supporting_fact_ids = [fact.fact_id for fact in required if _supports(fact)]

    conflict = (
        data.shipment is not None
        and not data.shipment.exists
        and data.shipment.tracking_status is not None
    )
    if conflict:
        rules.append(
            RuleResult(
                "evidence_consistency",
                RuleOutcome.FAIL,
                ["shipment_record_exists", "delivery_confirmed"],
                "Tracking data conflicts with the confirmed absence of a "
                "shipment record.",
            )
        )

    high_risk = (
        data.payment is None
        or (payment.status is FactStatus.VERIFIED and not _supports(payment))
        or refund.value is True
        or conflict
        or (
            data.dispute_reason == ITEM_NOT_RECEIVED
            and (
                by_id["shipment_record_exists"].status is FactStatus.MISSING
                or (
                    by_id["shipping_address_matches"].status is FactStatus.VERIFIED
                    and by_id["shipping_address_matches"].value is False
                )
            )
        )
    )
    all_supported = all(_supports(fact) for fact in required)
    if high_risk:
        risk = RiskLevel.HIGH
    elif all_supported:
        risk = RiskLevel.LOW
    else:
        risk = RiskLevel.MEDIUM

    return EvidenceAssessment(
        data.dispute_reason,
        risk,
        risk is not RiskLevel.LOW,
        facts,
        supporting_fact_ids,
        rules,
    )
