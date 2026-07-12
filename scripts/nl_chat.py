#!/usr/bin/env python3
"""Headless NL chat with AWS DevOps Agent (CreateChat + SendMessage streaming)."""
import argparse
import json
import os
import sys

import boto3


def load_env_file(path):
    """Load simple `export KEY=value` lines into os.environ."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            os.environ[k] = v.strip("'\"")


def extract_text(events):
    """Pull final_response text blocks from the streaming event list."""
    texts = []
    for ev in events:
        blk = ev.get("contentBlockDelta", {})
        delta = blk.get("delta", {})
        if "text" in delta:
            texts.append(delta["text"])
    return "".join(texts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="ap-northeast-1")
    ap.add_argument("--agent-space", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--chat-id", default=None, help="Continue existing chat")
    ap.add_argument("--env-file", default=None, help="Load AWS creds from env file")
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    c = boto3.Session().client("devops-agent", region_name=args.region)

    execution_id = args.chat_id
    if not execution_id:
        chat = c.create_chat(agentSpaceId=args.agent_space)
        execution_id = chat["executionId"]
        print(f"[executionId: {execution_id}]", file=sys.stderr)

    resp = c.send_message(
        agentSpaceId=args.agent_space,
        executionId=execution_id,
        content=args.message,
    )

    stream = resp.get("events")
    full_text = []
    tool_calls = []
    if stream is not None:
        for event in stream:
            # Each event is a dict with one key
            for k, v in event.items():
                if k == "contentBlockDelta":
                    d = v.get("delta", {})
                    if "text" in d:
                        full_text.append(d["text"])
                    pj = d.get("jsonDelta", {}).get("partialJson")
                    if pj:
                        tool_calls.append(pj)
                elif k == "contentBlockStart":
                    start = v.get("start", {})
                    tu = start.get("toolUse")
                    if tu:
                        print(f"[tool: {tu.get('name')}]", file=sys.stderr)
    else:
        print(json.dumps(resp, default=str)[:2000])
        return

    print("".join(full_text))
    print(f"\n[executionId: {execution_id}]", file=sys.stderr)


if __name__ == "__main__":
    main()
