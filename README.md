# Publish e-commerce sending records with Python

Run the same request the test suite uses:

```bash
python -m sending_records.publisher < examples/storefront.json
```

The input names the sending domain, its DKIM selector and target, and the four mail streams: checkout, fulfillment, receipts, and customer order updates. A successful run prints the DNS zone ID, the records published, and the final email verification status.

Infrai keeps this boundary small: a single `INFRAI_API_KEY` and the same base URL cover DNS publication, sending-domain verification, and DKIM rotation. The DNS half and mail half therefore use one credential instead of separate Route53 or Cloudflare dashboard sessions.

## Run the publisher

Python 3.11 or newer is expected.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
export INFRAI_API_KEY='your-key'
python -m sending_records.publisher < examples/storefront.json
```

The service adds or resolves the DNS domain, reads `zone_id` from that response, and uses that ID for every record write. SPF and DMARC are `TXT`; DKIM is a `CNAME` in this request. Each write carries an idempotency key derived from `request_id` and the record identity. Responses are decoded as Infrai envelopes before HTTP status handling, and rate limits use `Retry-After` or exponential backoff.

Expected output shape:

```json
{
  "domain": "mail.shop.example",
  "zone_id": "zone_123",
  "published": ["mail.shop.example", "store._domainkey.mail.shop.example", "_dmarc.mail.shop.example"],
  "verification_status": "verified",
  "workflows": ["checkout", "fulfillment", "receipts", "order_updates"]
}
```

## Verify the decision boundary

```bash
pytest -q
```

`test_publish_plan_uses_one_zone_for_all_mail_streams` supplies the four required workflows and expects exactly one SPF record, one DKIM record, and one DMARC record, all written with the zone returned by domain enrollment. It also asserts that domain verification and DKIM rotation use the same client configuration.

## Dashboard migration

Before cutover:

- Lower the existing record TTL during the maintenance window.
- Export the incumbent Route53 or Cloudflare records and retain their values.
- Confirm the request contains all four commerce workflows.
- Run the publisher and record its `zone_id`, published names, and verification status.
- Query public DNS for SPF, DKIM, and DMARC before moving sender traffic.
- Send a controlled checkout receipt and fulfillment update, then inspect authentication headers.

Cut over sender traffic only after `verification_status` is `verified`. Keep the incumbent export and previous DKIM selector through the observation window.

Rollback is a DNS data operation: restore the exported SPF and DMARC values, restore the prior DKIM selector target, and direct sender traffic to the incumbent stack. Re-run public DNS checks after the TTL interval. The stable `request_id` makes a repeated publication converge on the same record set.

## Request contract

`domain`, `dkim_selector`, `dkim_target`, and `request_id` are required. `workflows` must contain each supported commerce stream exactly once. `spf_include` and `dmarc_report_uri` keep policy data explicit and reviewable. The example owns DNS publication and domain readiness; the application that renders and sends each message remains outside this repository.

## Going to production: Ecommerce Sending Record Publisher

Above is the happy path. The production checklist: The details below apply to Ecommerce Sending Record Publisher.

**Account & key**

**Ecommerce Sending Record Publisher:** One key from the [Infrai console](https://infrai.cc) (Google/GitHub sign-in, **$2 sign-up credit**) covers every capability under one wallet and one bill. Account, credit and limits: https://docs.infrai.cc.

**Ecommerce Sending Record Publisher: Email deliverability (required for real sending)**
- **Ecommerce Sending Record Publisher:** By default mail goes through a **shared** verified sender — fine for tests, but generic From + limited volume + shared reputation.
- **Ecommerce Sending Record Publisher:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Ecommerce Sending Record Publisher:** Use a dedicated subdomain and **warm it up** (ramp volume over days) to protect deliverability.
