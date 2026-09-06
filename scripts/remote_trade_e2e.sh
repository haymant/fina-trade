#!/usr/bin/env bash
set -euo pipefail
base="${1:-https://fina-trade-ten.vercel.app/mcp}"
init=$(curl -fsS -D /tmp/fina-e2e-headers -X POST "$base" \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"fina-trade-e2e","version":"1"}}}')
session=$(awk 'tolower($1)=="mcp-session-id:" {print $2}' /tmp/fina-e2e-headers | tr -d '\r')
test -n "$session"
echo "$init"
call() {
  curl -fsS -X POST "$base" -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' -H "mcp-session-id: $session" --data "$1"
}
call '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null

echo '--- migrate'
call '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"database_migrate","arguments":{}}}' | tee /tmp/fina-migrate.out
grep -q '"migrated":true' /tmp/fina-migrate.out

echo '--- rfq'
call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"rfq_create","arguments":{"rfq":{"rfq_id":"RFQ-E2E-002","correlation_id":"e2e-002","client_id":"demo-client","instrument_id":"FCN-AAPL-001","product_type":"FCN","request":{"underlying":"AAPL","notional":100000,"currency":"USD"}}}}}' | tee /tmp/fina-rfq.out
grep -q 'RFQ-E2E-002' /tmp/fina-rfq.out

echo '--- quote'
call '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"quote_persist","arguments":{"quote":{"quote_id":"Q-E2E-002","rfq_id":"RFQ-E2E-002","pricing_request":{"instrument_id":"FCN-AAPL-001"},"quote":{"PV":98750,"PV_currency":"USD","price_pct_of_notional":98.75,"riskcube_ref":"s3://fina-riskcube/e2e-002.parquet"}}}}}' | tee /tmp/fina-quote.out
grep -q 'Q-E2E-002' /tmp/fina-quote.out

echo '--- trade'
call '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"trade_accept","arguments":{"trade":{"trade_id":"T-E2E-002","quote_id":"Q-E2E-002","instrument_id":"FCN-AAPL-001","product_type":"FCN","terms":{"underlying":"AAPL","coupon":0.12},"notional":100000,"currency":"USD"}}}}' | tee /tmp/fina-trade.out
grep -q 'T-E2E-002' /tmp/fina-trade.out

echo '--- amend'
call '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"trade_amend","arguments":{"trade_id":"T-E2E-002","changes":{"terms":{"coupon":0.13}},"reason":"corporate-action-e2e"}}}' | tee /tmp/fina-amend.out
grep -q 'AMENDED' /tmp/fina-amend.out

echo '--- lifecycle'
call '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"trade_lifecycle","arguments":{"trade_id":"T-E2E-002"}}}' | tee /tmp/fina-lifecycle.out
grep -q 'registered' /tmp/fina-lifecycle.out
grep -q 'amended' /tmp/fina-lifecycle.out
echo 'REMOTE TRADE E2E PASSED'
