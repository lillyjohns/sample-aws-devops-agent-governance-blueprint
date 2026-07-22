"""remediation-pr-agent — minimal A2A server for AgentCore Runtime.

The agent-shaped evolution of the propose-fix-pr MCP tool (see
capabilities/a2a/remediation-pr-agent/manifest.yaml). It exposes ONE skill —
"propose a remediation PR from a cost-waste finding" — and delegates the
actual write to the existing gov-blueprint-propose-fix-pr Lambda, so the
governance surface (deterministic transform registry, PR-as-proposal,
SSM-held credential) is exactly the same code path the Gateway tool uses.

Pure stdlib on purpose: AgentCore Runtime CodeConfiguration runs this zip
directly (no container build) and the managed Python runtime does NOT bundle
boto3 — so the Lambda Invoke call is signed with a ~40-line stdlib SigV4
implementation instead (see sigv4.py). A2A contract per AgentCore docs:
streamable HTTP server on 0.0.0.0:9000 at '/', agent card at
/.well-known/agent-card.json, /ping health.
"""

import json
import os
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sigv4 import invoke_lambda

PROPOSE_FIX_PR_FUNCTION = os.environ.get(
    "PROPOSE_FIX_PR_FUNCTION", "gov-blueprint-propose-fix-pr"
)
DEFAULT_FILE_PATH = os.environ.get(
    "DEFAULT_FILE_PATH", "scenarios/demo-workload/template.yaml"
)

AGENT_CARD = {
    "protocolVersion": "0.3.0",
    "name": "remediation-pr-agent",
    "description": (
        "Autonomous remediation agent for cost-waste findings: given a finding "
        "(e.g. gp2 EBS volumes), it applies the runbook-approved deterministic "
        "IaC transform and opens a GitHub pull request as a proposal. A human "
        "reviews and merges — the agent never applies changes directly."
    ),
    "url": os.environ.get("AGENTCORE_RUNTIME_URL", "http://localhost:9000/"),
    "preferredTransport": "JSONRPC",
    "version": "1.0.0",
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text/plain", "application/json"],
    "defaultOutputModes": ["text/plain", "application/json"],
    "skills": [
        {
            "id": "propose-remediation-pr",
            "name": "Propose remediation PR from cost-waste finding",
            "description": (
                "Takes a cost-waste finding (resource type, IaC file path, "
                "waste category such as ebs-gp2-to-gp3) and opens a GitHub PR "
                "with the runbook-approved fix. Say 'dry run' to preview the "
                "diff without opening a PR. Include the finding as JSON for "
                "reviewer context."
            ),
            "tags": ["cost-optimization", "remediation", "github", "pull-request"],
            "examples": [
                "Propose a remediation PR for this finding: {\"resource\": "
                "\"vol-0abc\", \"issue\": \"gp2 volume\", \"file_path\": "
                "\"scenarios/demo-workload/template.yaml\"}",
                "Dry run: what would the gp2->gp3 fix look like for "
                "scenarios/demo-workload/template.yaml?",
            ],
        }
    ],
}


def handle_finding(text: str) -> str:
    """Map an NL request + embedded finding to a propose_fix_pr invocation."""
    finding = None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            finding = json.loads(m.group(0))
        except json.JSONDecodeError:
            finding = None

    args = {
        "change_description": "ebs-gp2-to-gp3",  # the one approved transform today
        "file_path": (finding or {}).get("file_path") or DEFAULT_FILE_PATH,
        "dry_run": bool(re.search(r"dry.?run|preview", text, re.IGNORECASE)),
    }
    fp = re.search(r"[\w./-]+\.(?:ya?ml|json|tf|ts)", text)
    if fp and not (finding or {}).get("file_path"):
        args["file_path"] = fp.group(0)
    if finding:
        args["finding"] = finding

    result = invoke_lambda(PROPOSE_FIX_PR_FUNCTION, args)

    status = result.get("status", "error")
    if status == "pr_opened":
        summary = f"Opened remediation PR: {result['pr_url']} (branch {result['branch']})."
    elif status == "dry_run":
        summary = "Dry run — proposed diff (no PR opened):\n" + result.get("diff", "")
    elif status == "no_change":
        summary = result.get("message", "Nothing to change.")
    else:
        summary = f"Remediation failed: {result.get('error', result)}"
    return summary + "\n\n```json\n" + json.dumps(result, indent=2, default=str)[:4000] + "\n```"


def a2a_response(req_id, text: str, context_id=None, task_id=None):
    """A2A message/send result: a completed agent Message."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "kind": "message",
            "role": "agent",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
            **({"contextId": context_id} if context_id else {}),
            **({"taskId": task_id} if task_id else {}),
        },
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
            card = dict(AGENT_CARD)
            card["url"] = os.environ.get("AGENTCORE_RUNTIME_URL", card["url"])
            self._send(200, card)
        elif path == "/ping":
            self._send(200, {"status": "healthy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"jsonrpc": "2.0", "id": None,
                                    "error": {"code": -32700, "message": "parse error"}})
        req_id = req.get("id")
        method = req.get("method", "")
        if method not in ("message/send", "message/stream"):
            return self._send(200, {"jsonrpc": "2.0", "id": req_id,
                                    "error": {"code": -32601, "message": f"method '{method}' not supported"}})
        msg = (req.get("params") or {}).get("message") or {}
        text = " ".join(p.get("text", "") for p in msg.get("parts", []) if p.get("kind") == "text")
        try:
            reply = handle_finding(text)
        except Exception as e:  # surface failures as agent text, not protocol errors
            reply = f"Remediation agent error: {e}"
        resp = a2a_response(req_id, reply, context_id=msg.get("contextId"), task_id=msg.get("taskId"))
        if method == "message/stream":  # single-shot SSE: one final event
            data = b"data: " + json.dumps(resp).encode() + b"\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send(200, resp)

    def log_message(self, fmt, *args):  # keep CloudWatch logs terse
        print(f"{self.command} {self.path} - {fmt % args}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    print(f"remediation-pr-agent A2A server on 0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
