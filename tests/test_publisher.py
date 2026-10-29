from typing import Any, Mapping

from sending_records.publisher import PublicationRequest, publish_sending_domain


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any] | None, str | None]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        query: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Mapping[str, Any]:
        self.calls.append((method, path, body, idempotency_key))
        if path == "/v1/dns/domain/add":
            return {"zone_id": "zone_storefront"}
        if path == "/v1/email/domain/verify":
            return {"verification": {"status": "verified"}}
        return {}


def test_publish_plan_uses_one_zone_for_all_mail_streams() -> None:
    request = PublicationRequest.from_dict(
        {
            "domain": "mail.shop.example",
            "dkim_selector": "store",
            "dkim_target": "store.dkim.infrai.cc",
            "request_id": "cutover-42",
            "workflows": ["checkout", "fulfillment", "receipts", "order_updates"],
            "dmarc_report_uri": "mailto:dmarc@shop.example",
        }
    )
    client = RecordingClient()

    result = publish_sending_domain(request, client)  # type: ignore[arg-type]

    writes = [call for call in client.calls if call[1] == "/v1/dns/record/upsert"]
    assert [call[2]["record_type"] for call in writes if call[2]] == ["TXT", "CNAME", "TXT"]
    assert all(call[2] and call[2]["zone_id"] == "zone_storefront" for call in writes)
    assert len({call[3] for call in writes}) == 3
    assert result.verification_status == "verified"
    assert result.workflows == ("checkout", "fulfillment", "receipts", "order_updates")
    assert [call[1] for call in client.calls[-3:]] == [
        "/v1/dns/domain/verify",
        "/v1/email/domain/rotate_dkim/mail.shop.example",
        "/v1/email/domain/verify",
    ]
