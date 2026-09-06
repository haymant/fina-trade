#!/usr/bin/env bash
set -euo pipefail
base="${1:-https://fina-trade-ten.vercel.app/mcp}"
init=$(curl -fsS -D /tmp/fina-mcp-headers -X POST "$base" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"fina-remote-smoke","version":"1"}}}')
session=$(awk 'tolower($1)=="mcp-session-id:" {print $2}' /tmp/fina-mcp-headers | tr -d '\r')
test -n "$session"
echo "$init"
call() {
  curl -fsS -X POST "$base" \
    -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    -H "mcp-session-id: $session" \
    --data "$1"
}
call '{"jsonrpc":"2.0","method":"notifications/initialized"}' >/dev/null
call '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"database_health","arguments":{}}}'
