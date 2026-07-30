# A2A evidence — remediation-pr-agent (M3)

What we can prove today about the `remediation-pr-agent` A2A integration in
`ap-northeast-1`, with captured output. Two layers:

1. **The A2A agent itself works end-to-end** (protocol-level proof) ✅
2. **DevOps Agent registration/association succeeded**, but the chat
   orchestrator does not yet surface a delegation tool for
   `remoteagentsigv4` associations (observed limitation, documented below) ⚠️

## 1. Protocol-level proof (scripts/a2a_smoke.py)

`python3 scripts/a2a_smoke.py` performs the exact flow a `remoteagentsigv4`
consumer performs: SigV4 GET of the agent card, then a signed A2A JSON-RPC
`message/send` to the runtime endpoint.

Captured run (2026-07-22, runtime `remediation_pr_agent-vOJXm7DNfe`):

```
--- agent card (200) ---
{
  "name": "remediation-pr-agent",
  "description": "Autonomous remediation agent for cost-waste findings: given a finding (e.g. gp2 EBS volumes), it applies the runbook-approved deterministic IaC transform and opens a GitHub pull request as a proposal. A human reviews and merges — the agent never applies changes directly.",
  "url": "https://bedrock-agentcore.ap-northeast-1.amazonaws.com/runtimes/arn%3Aaws%3A.../invocations",
  "skills": [
    {
      "id": "propose-remediation-pr",
      "name": "Propose remediation PR from cost-waste finding",
      ...
    }
  ]
}
--- message/send response (200) ---
{
  "jsonrpc": "2.0",
  "id": "614aa8fb-ec91-4f03-954f-d15ce06a08cd",
  "result": {
    "kind": "message",
    "role": "agent",
    "parts": [
      {
        "kind": "text",
        "text": "Dry run — proposed diff (no PR opened):\n--- a/scenarios/demo-workload/template.yaml\n+++ b/scenarios/demo-workload/template.yaml\n@@ -24,7 +24,7 @@\n     Properties:\n       AvailabilityZone: !Ref AvailabilityZone\n       Size: 100\n-      VolumeType: gp2\n+      VolumeType: gp3\n ..."
      }
    ],
    "messageId": "b67971c9d95247abad0aa7340a742fd5"
  }
}
```

The reply text embeds the full structured result from the shared
`propose-fix-pr` code path (same governance surface as the Gateway tool):

```json
{
  "status": "dry_run",
  "repo": "lillyjohns/sample-aws-devops-agent-governance-blueprint",
  "file_path": "scenarios/demo-workload/template.yaml",
  "change_description": "ebs-gp2-to-gp3",
  "replacements": 1,
  "diff": "--- a/... +++ b/... VolumeType: gp2 -> gp3 ...",
  "message": "Dry run — no branch or PR was created."
}
```

## 2. Registration + association (control plane) — succeeded

Deployed by `GovernanceBlueprint-RemediationAgent` via the
`Custom::DevOpsAgentRemoteAgent` custom resource:

- `RegisterService(remoteagentsigv4)` → ServiceId `739320f9-fc57-44c4-93da-362828ddf098`
  (validated at registration time: DevOps Agent GETs the agent card through
  the invoke role — see DESIGN.md "A2A deployment findings")
- `AssociateService` → AssociationId `25ae0467-5b0e-47ef-bd47-618d116bb77c`
  on AgentSpace `a0ad2ee6-6bc4-4da1-8f9d-203ae9fb10bf`, configuration
  `{"remoteagentsigv4": {}}`

`GetService` shows the card URL endpoint, invoke role, and description
exactly as registered.

## 3. Orchestrator delegation — not yet surfaced (observed limitation)

We sent multiple NL prompts through the Chat API (`scripts/nl_chat.py`)
explicitly asking the DevOps Agent to delegate to the remote agent. Journal
evidence (execution `0e9438f6-6b7a-4b1d-a337-2fdb7df4bbd0`):

- The agent **sees the association** (`list_associations` returns the
  `remoteagentsigv4` entry) and understands it is an A2A peer.
- But `search_user_tools` for "remediation-pr-agent", "remote agent", "a2a"
  returns **only `gov-gw` MCP tools** — no delegation tool is exposed for
  `remoteagentsigv4` associations in the chat context.
- The agent's own summary: *"The `remoteagentsigv4` association type
  registers the remote agent for platform-level A2A routing, but the chat
  agent has no built-in tool to invoke it directly."*
- In one earlier run it satisfied the request via the Gateway MCP tool
  (`gov-gw_propose-fix-pr___propose_fix_pr`) instead — functionally the same
  Lambda, different governance path.

Interpretation: as of 2026-07-22 in `ap-northeast-1`, `remoteagentsigv4`
associations are registered and validated by the control plane, but chat
executions do not (yet) expose a remote-agent invocation tool. Delegation may
be reserved for other execution contexts (investigations, custom agents,
platform routing) or still rolling out. The blueprint keeps the registration
in IaC so the moment the orchestrator surfaces delegation, the agent is
already wired.

### Retest 2026-07-30 — still not surfaced

Re-ran both layers with fresh credentials (execution
`5225af7d-73b6-4141-af63-ca15966c05d1`):

- ✅ `scripts/a2a_smoke.py` still passes: agent card 200 + `message/send`
  returns the dry-run gp2→gp3 diff contract unchanged.
- ❌ Chat delegation still unavailable. Asked the agent explicitly to invoke
  the remote agent via A2A (not the Gateway tool). Journal shows:
  - `search_user_tools("invoke remote A2A agent, agent-to-agent delegation,
    call remote agent via A2A protocol")` → only
    `gov-gw_x_amz_bedrock_agentcore_search` (a discovery utility).
  - `list_associations` → both associations visible, including
    `remediation-pr-agent` (`remoteagentsigv4`) with a valid runtime endpoint.
  - Agent verbatim: *"The remote agent is registered, but the tool needed to
    call it over A2A is not wired up."* It offered the Gateway MCP tool
    (`propose-fix-pr___propose_fix_pr`) as the alternative.

**Important contrast:** outbound delegation *does* work from the
**investigation** execution context. In a separate POC (2026-07-24,
`us-east-1`), DevOps Agent investigations successfully called a self-hosted
third-party A2A agent registered the same way (`remoteagentsigv4`) — including
instructing it to open a real GitHub PR. So the gap is specifically the *chat*
orchestrator's tool registry, not the A2A routing platform. See
[a2a-third-party-agent.md](a2a-third-party-agent.md) for the wire-level
details of what DevOps Agent actually sends to external agents (spoiler: it is
not textbook A2A JSON-RPC).

## Payload shape (A2A finding contract)

What the remediation agent accepts in the A2A `message/send` text part —
NL text with an embedded JSON finding:

```
Dry run: propose fix for <file_path> with finding
{"resource": "vol-demo", "issue": "gp2 EBS volume", "file_path": "scenarios/demo-workload/template.yaml", "change": "ebs-gp2-to-gp3"}
```

- `dry run` / `preview` anywhere in the text → `dry_run: true`
- embedded `{...}` JSON → parsed as the finding (forwarded to the PR body
  for reviewer context); `finding.file_path` wins over paths in prose
- reply: text summary + fenced JSON with `status`
  (`dry_run` | `pr_opened` | `no_change` | `error`), `diff`, `pr_url`/`branch`
  when a PR is opened

## Repro

```bash
source <aws-creds>   # any principal with bedrock-agentcore:InvokeAgentRuntime + GetAgentCard
python3 scripts/a2a_smoke.py                 # card + dry-run message/send
python3 scripts/nl_chat.py --agent-space a0ad2ee6-... --message "..."  # orchestrator attempts
```

## See also

- [a2a-third-party-agent.md](a2a-third-party-agent.md) — hosting your own
  external A2A agent (outside AWS) and connecting it to DevOps Agent:
  registration, the proto-style `SendMessage` dialect, response shape
  requirements, and every bug we hit doing it.
