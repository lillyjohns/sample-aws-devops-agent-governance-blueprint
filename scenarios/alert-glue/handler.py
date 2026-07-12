"""Alert → investigation glue.

EventBridge delivers an alert event; this Lambda opens a chat with AWS DevOps
Agent (CreateChat + SendMessage) and hands it a natural-language investigation
prompt. The agent does the actual work — investigate cost waste through the
Gateway, consult the runbook library via search_runbook, and propose a fix.
This function is deliberately dumb: format prompt, send, log. Judgment stays
in DevOps Agent (see docs/DESIGN.md, design principle 1).

Notes:
- SendMessage returns a streaming response (contentBlockStart / contentBlockDelta /
  contentBlockStop events, then final_response blocks). We drain the stream with a
  time budget so the invocation confirms the agent picked the message up, then
  detach — the investigation continues server-side and is visible in the DevOps
  Agent console (or via scripts/nl_poll.py with the logged executionId).
- The devops-agent service model is bundled under models/ and loaded via
  AWS_DATA_PATH, since the Lambda runtime's boto3 may lag the service launch.
"""

import json
import os
import time

os.environ.setdefault("AWS_DATA_PATH", os.path.join(os.path.dirname(__file__), "models"))

import boto3  # noqa: E402  (AWS_DATA_PATH must be set before boto3 loads)

AGENT_SPACE_ID = os.environ["AGENT_SPACE_ID"]
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
STREAM_BUDGET_SECONDS = int(os.environ.get("STREAM_BUDGET_SECONDS", "45"))

PROMPT_TEMPLATE = (
    "Alert received: {headline}.\n"
    "Details: {detail}\n\n"
    "Please investigate:\n"
    "1. Scan for cost waste with the find_cost_waste tool (all checks).\n"
    "2. Consult the operational runbooks with the search_runbook tool for the "
    "approved remediation procedure matching what you find.\n"
    "3. Propose a concrete fix following the runbook, including estimated "
    "monthly savings and the IaC change that would implement it."
)


def handler(event, context):
    headline, detail = _describe(event)
    prompt = PROMPT_TEMPLATE.format(headline=headline, detail=detail)

    client = boto3.client("devops-agent", region_name=REGION)

    chat = client.create_chat(agentSpaceId=AGENT_SPACE_ID)
    execution_id = chat["executionId"]
    print(json.dumps({"msg": "chat created", "executionId": execution_id, "headline": headline}))

    resp = client.send_message(
        agentSpaceId=AGENT_SPACE_ID,
        executionId=execution_id,
        content=prompt,
    )

    # Drain the stream with a budget: enough to confirm the agent engaged,
    # without holding the Lambda for the full multi-minute investigation.
    preview, tools_seen, events_seen = [], [], 0
    deadline = time.monotonic() + STREAM_BUDGET_SECONDS
    stream = resp.get("events")
    if stream is not None:
        try:
            for ev in stream:
                events_seen += 1
                for key, value in ev.items():
                    if key == "contentBlockStart":
                        tool = value.get("start", {}).get("toolUse", {}).get("name")
                        if tool:
                            tools_seen.append(tool)
                    elif key == "contentBlockDelta":
                        text = value.get("delta", {}).get("text")
                        if text and sum(len(p) for p in preview) < 1000:
                            preview.append(text)
                if time.monotonic() > deadline:
                    print(json.dumps({"msg": "stream budget reached, detaching"}))
                    break
        except Exception as exc:  # stream hiccups shouldn't fail the alert path
            print(json.dumps({"msg": "stream read ended", "reason": str(exc)[:200]}))

    result = {
        "executionId": execution_id,
        "agentSpaceId": AGENT_SPACE_ID,
        "eventsSeen": events_seen,
        "toolsSeen": tools_seen,
        "responsePreview": "".join(preview)[:1000],
    }
    print(json.dumps({"msg": "alert dispatched to DevOps Agent", **result}))
    return result


def _describe(event):
    """Extract a headline + detail string from the EventBridge envelope."""
    detail_type = event.get("detail-type", "Unknown alert")
    source = event.get("source", "unknown")
    detail = event.get("detail", {})
    headline = f"{detail_type} (source: {source})"
    if isinstance(detail, dict) and "headline" in detail:
        headline = str(detail["headline"])
    return headline, json.dumps(detail, default=str)[:2000]
