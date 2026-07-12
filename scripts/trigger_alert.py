#!/usr/bin/env python3
"""Fire a synthetic cost-anomaly alert to demo the alert → investigation flow.

Puts a custom event on the default EventBridge bus matching the Scenarios
stack's rule (source=governance.blueprint.demo, detail-type=Cost Anomaly
Detected). The rule invokes the alert-glue Lambda, which opens a DevOps Agent
chat and hands it the investigation prompt.

Usage:
  python3 scripts/trigger_alert.py [--region ap-northeast-1] [--watch]

--watch tails the glue Lambda's log group until the executionId appears, so you
can jump straight to the investigation in the DevOps Agent console (or poll it
with scripts/nl_poll.py).
"""
import argparse
import datetime
import json
import sys
import time

import boto3

SOURCE = "governance.blueprint.demo"
DETAIL_TYPE = "Cost Anomaly Detected"
GLUE_FUNCTION = "gov-blueprint-alert-glue"


def resolve_log_group(region: str) -> str:
    """The glue Lambda uses a CDK-managed log group (custom name), so resolve it
    from the function's logging config instead of assuming /aws/lambda/<name>."""
    lam = boto3.client("lambda", region_name=region)
    cfg = lam.get_function_configuration(FunctionName=GLUE_FUNCTION)
    return cfg.get("LoggingConfig", {}).get("LogGroup") or f"/aws/lambda/{GLUE_FUNCTION}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ap-northeast-1")
    ap.add_argument("--watch", action="store_true", help="tail glue logs until the chat opens")
    args = ap.parse_args()

    detail = {
        "headline": "Cost anomaly: EC2-Other spend up 42% week-over-week",
        "service": "EC2-Other",
        "region": args.region,
        "anomalyScore": 0.87,
        "impact": {"totalImpactUsd": 118.40, "baselineWeeklyUsd": 281.90},
        "detectedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "note": "Synthetic demo event fired by scripts/trigger_alert.py",
    }

    eb = boto3.client("events", region_name=args.region)
    resp = eb.put_events(
        Entries=[{
            "Source": SOURCE,
            "DetailType": DETAIL_TYPE,
            "Detail": json.dumps(detail),
        }]
    )
    if resp.get("FailedEntryCount"):
        print(f"put_events failed: {resp}", file=sys.stderr)
        return 1
    event_id = resp["Entries"][0]["EventId"]
    print(f"Alert fired (event {event_id}): {detail['headline']}")

    if not args.watch:
        print("Tip: --watch tails the glue Lambda logs until the DevOps Agent chat opens.")
        return 0

    log_group = resolve_log_group(args.region)
    print(f"Watching {log_group} for the investigation chat…")
    logs = boto3.client("logs", region_name=args.region)
    start = int((time.time() - 10) * 1000)
    deadline = time.time() + 180
    seen = set()
    while time.time() < deadline:
        try:
            events = logs.filter_log_events(logGroupName=log_group, startTime=start)["events"]
        except logs.exceptions.ResourceNotFoundException:
            events = []
        for ev in events:
            if ev["eventId"] in seen:
                continue
            seen.add(ev["eventId"])
            msg = ev["message"].strip()
            if '"executionId"' in msg or "dispatched" in msg:
                print(f"  {msg[:400]}")
                if "alert dispatched" in msg:
                    print("Investigation started — open the DevOps Agent console to follow along.")
                    return 0
        time.sleep(5)
    print("Timed out waiting for glue logs — check the Lambda console.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
