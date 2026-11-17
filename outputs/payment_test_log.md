# Payment and delivery test log (MOCKED)

Everything in this log is **MOCKED**. No payment provider, real or sandbox, was contacted. No money moved and nothing was delivered to anyone.

- Product id: `demo-product`
- Mock price: 1900 cents
- Approvals in this run were given by: **the automated test harness (these are not founder decisions)**

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | delivery_blocked_without_approval | PASS | refused as expected: auto-delivery for demo-product has not been approved by the founder |
| 2 | auto_delivery_enabled | PASS | approved by test-harness (automated, not a founder decision) |
| 3 | payment_triggers_delivery | PASS | webhook outcome: delivered; access link: https://example.invalid/mock-download/order_mock_0001 |
| 4 | duplicate_webhook_single_delivery | PASS | replayed event evt_mock_0002: duplicate_ignored; deliveries stayed at 1 |
| 5 | bad_signature_rejected | PASS | tampered event: rejected_bad_signature |
| 6 | refund_blocked_without_approval | PASS | refused as expected: no founder approval for action refund-002-e7173f |
| 7 | refund_revokes_access | PASS | refund outcome: access_revoked; buyer still has access: False |
| 8 | reconciliation_matches | PASS | gross 3800c - fees 170c - refunds 1900c = expected payout 1730c; paid out 1730c; mismatches: none |
| 9 | reconciliation_detects_mismatch | PASS | injected a 5c payout error; reported: ['payouts total 1735 != expected 1730 (payments 3800 - fees 170 - refunds 1900)'] |

**9 of 9 checks passed.**
