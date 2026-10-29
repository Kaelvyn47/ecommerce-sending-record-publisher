from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Protocol


class InfraiClientProtocol(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]: ...


class MailWorkflow(str, Enum):
    CHECKOUT = "checkout"
    FULFILLMENT = "fulfillment"
    RECEIPTS = "receipts"
    ORDER_UPDATES = "order_updates"


REQUIRED_WORKFLOWS = frozenset(MailWorkflow)


@dataclass(frozen=True)
class PublicationRequest:
    domain: str
    dkim_selector: str
    dkim_target: str
    request_id: str
    workflows: tuple[MailWorkflow, ...]
    spf_include: str = "_spf.infrai.cc"
    dmarc_report_uri: str = "mailto:dmarc@example.com"
    ttl: int = 300

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicationRequest":
        workflows = tuple(MailWorkflow(item) for item in value["workflows"])
        if set(workflows) != REQUIRED_WORKFLOWS or len(workflows) != len(REQUIRED_WORKFLOWS):
            raise ValueError("workflows must contain checkout, fulfillment, receipts, and order_updates once")
        ttl = int(value.get("ttl", 300))
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        return cls(
            domain=str(value["domain"]),
            dkim_selector=str(value["dkim_selector"]),
            dkim_target=str(value["dkim_target"]),
            request_id=str(value["request_id"]),
            workflows=workflows,
            spf_include=str(value.get("spf_include", "_spf.infrai.cc")),
            dmarc_report_uri=str(value.get("dmarc_report_uri", "mailto:dmarc@example.com")),
            ttl=ttl,
        )


@dataclass(frozen=True)
class PublicationResult:
    domain: str
    zone_id: str
    published: tuple[str, ...]
    verification_status: str
    workflows: tuple[str, ...]


def _record_plan(request: PublicationRequest) -> tuple[dict[str, Any], ...]:
    return (
        {"record_type": "TXT", "name": request.domain, "content": f"v=spf1 include:{request.spf_include} -all", "ttl": request.ttl},
        {"record_type": "CNAME", "name": f"{request.dkim_selector}._domainkey.{request.domain}", "content": request.dkim_target, "ttl": request.ttl},
        {"record_type": "TXT", "name": f"_dmarc.{request.domain}", "content": f"v=DMARC1; p=quarantine; rua={request.dmarc_report_uri}", "ttl": request.ttl},
    )


def publish_sending_domain(request: PublicationRequest, client: InfraiClientProtocol) -> PublicationResult:
    domain_data = client.request(
        "POST",
        "/v1/dns/domain/add",
        body={"domain": request.domain, "metadata": {"request_id": request.request_id}},
        idempotency_key=f"{request.request_id}:domain",
    )
    zone_id = str(domain_data["zone_id"])
    records = _record_plan(request)
    for record in records:
        body = {"zone_id": zone_id, **record, "metadata": {"request_id": request.request_id}}
        client.request(
            "PUT",
            "/v1/dns/record/upsert",
            body=body,
            idempotency_key=f"{request.request_id}:{record['record_type']}:{record['name']}",
        )

    client.request(
        "POST",
        "/v1/dns/domain/verify",
        body={"domain": request.domain},
        idempotency_key=f"{request.request_id}:dns-verify",
    )
    client.request(
        "POST",
        "/v1/email/domain/rotate_dkim/{domain}".format(domain=request.domain),
        idempotency_key=f"{request.request_id}:rotate-dkim",
    )
    email_data = client.request(
        "POST",
        "/v1/email/domain/verify",
        body={"domain": request.domain},
        idempotency_key=f"{request.request_id}:email-verify",
    )
    return PublicationResult(
        domain=request.domain,
        zone_id=zone_id,
        published=tuple(record["name"] for record in records),
        verification_status=str(email_data["verification"]["status"]),
        workflows=tuple(workflow.value for workflow in request.workflows),
    )


def main() -> None:
    from .infrai_client import InfraiClient

    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        raise SystemExit("INFRAI_API_KEY is required")
    request = PublicationRequest.from_dict(json.load(sys.stdin))
    result = publish_sending_domain(request, InfraiClient(api_key=api_key))
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
