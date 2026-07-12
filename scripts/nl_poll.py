#!/usr/bin/env python3
"""Poll pending messages from a DevOps Agent execution."""
import argparse
import json
import os
import sys
import time

import boto3


def load_env_file(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ[k] = v.strip("'\"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ap-northeast-1")
    ap.add_argument("--agent-space", required=True)
    ap.add_argument("--execution-id", required=True)
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--watch", type=int, default=0, help="Poll every N sec until messages arrive")
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    c = boto3.Session().client("devops-agent", region_name=args.region)

    while True:
        resp = c.list_pending_messages(
            agentSpaceId=args.agent_space, executionId=args.execution_id
        )
        msgs = resp.get("messages", [])
        if msgs:
            for m in msgs:
                print(json.dumps(m, default=str, indent=2)[:8000])
            return
        if not args.watch:
            print("[no pending messages]")
            return
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
