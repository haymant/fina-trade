from __future__ import annotations
import json
import sys
import urllib.request

url = sys.argv[1] if len(sys.argv) > 1 else "https://fina-trade-ten.vercel.app/mcp"

def post(payload, session=""):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("content-type", "application/json")
    req.add_header("accept", "application/json, text/event-stream")
    if session: req.add_header("mcp-session-id", session)
    with urllib.request.urlopen(req, timeout=120) as response:
        sid = response.headers.get("mcp-session-id", session)
        body = response.read().decode()
    rows = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    return (json.loads(rows[-1]) if rows else {"result": {}}), sid

init, session = post({"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{"protocolVersion":"2025-03-26", "capabilities":{}, "clientInfo":{"name":"query-smoke","version":"1"}}})
post({"jsonrpc":"2.0", "method":"notifications/initialized"}, session)

def call(name, arguments):
    result, _ = post({"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":name, "arguments":arguments}}, session)
    payload = result["result"]
    if payload.get("isError"): raise RuntimeError(payload)
    return payload.get("structuredContent") or json.loads(next(x["text"] for x in payload["content"] if x["type"] == "text"))

migration = call("database_migrate", {})
print("migration", migration)
for name in ("rfq_query", "quote_query", "trade_query", "lifecycle_query"):
    result = call(name, {})
    assert "created_from" in result and "created_to" in result and "rows" in result
    print(name, json.dumps({"count": result["count"], "created_from": result["created_from"], "created_to": result["created_to"], "sample": result["rows"][:1]}, default=str))
print("QUERY SMOKE PASSED")
