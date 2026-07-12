# Design Deep-Dive

This document contains the full design rationale for the platform. For the overview, quick start, and demo flow, see the [README](../README.md).

## Table of Contents

- [Design principles](#design-principles)
- [The Gateway as a contract](#the-gateway-as-a-contract)
- [MCP vs A2A: choosing your extension type](#mcp-vs-a2a-choosing-your-extension-type)
- [Manifest schema](#manifest-schema)
- [Contract rules](#contract-rules)
- [Gateway routing vs direct MCP registration](#gateway-routing-vs-direct-mcp-registration)
- [MCP target selection](#mcp-target-selection)
- [Entry points and IDE wiring](#entry-points-and-ide-wiring)
- [Decision log](#decision-log)
- [Terraform notes](#terraform-notes)
- [Open items](#open-items)

## Design principles

1. **Gateway is for tools. DevOps Agent is for judgment.**
   Dumb capabilities (Cost Explorer queries, report generation, IaC lookups) live behind a single AgentCore Gateway. The reasoning loop — what to investigate, what to recommend, when to delegate — stays in DevOps Agent. Every client (agents *and* humans) is a consumer of the same Gateway.

2. **Designed to shrink.**
   Every custom component declares its **retirement condition** — the native DevOps Agent capability that makes it obsolete. Decommissioning is a config change (`enabled: false` or deregistering an A2A connection), never a re-architecture. Custom glue should never become legacy debt.

3. **Read-only by default. Writes are isolated.**
   All Gateway targets are read-only (enforced at synth time). The only write path — GitHub PRs — lives in a dedicated agent with its own credentials, and every write lands as a *proposal* (a PR) gated by human review.

## The Gateway as a contract

The Gateway endpoint is the **stable contract** between DevOps Agent and your tooling. DevOps Agent is registered to the Gateway **once**; everything behind it is pluggable.

```
DevOps Agent ──(registered once: AWS::DevOpsAgent::Service, never changes)──► AgentCore Gateway
                                                                                │
                                              targets added/removed/upgraded freely
                                              (no DevOps Agent change, no console click)
```

1. **One-time binding (CDK):** a single `AWS::DevOpsAgent::Service` resource (`ServiceType: mcpserversigv4`) points DevOps Agent at the Gateway URL. This resource never changes after first deploy.
2. **Pluggable targets — config-driven:** each MCP is a folder + manifest under `capabilities/mcp/`. CDK scans the directory and synthesizes one Gateway target per manifest. **Adding an MCP = drop a folder, `cdk deploy`.**
3. **Discovery is handled by the platform:** the Gateway's semantic tool search means DevOps Agent (and every other client) finds new tools automatically. The tool *list* is not part of the contract — only the endpoint + auth are.

## MCP vs A2A: choosing your extension type

AWS DevOps Agent's extension surface is exactly two protocols — **MCP** (tools) and **A2A** (agents). This platform treats both as first-class capability types under `capabilities/`:

```
capabilities/
├── mcp/      # tool-shaped: stateless calls, routed through the shared Gateway
└── a2a/      # agent-shaped: the callee itself reasons; registered with DevOps Agent
```

| | MCP capability | A2A capability |
|---|---|---|
| Shape | Deterministic tool — the *caller* reasons over results | Autonomous agent — the *callee* reasons (multi-step, stateful) |
| Routing | Behind the shared AgentCore Gateway | Direct A2A registration with DevOps Agent |
| Credentials | Per-target least-privilege IAM, read-only | Own isolated credentials (may hold write access) |
| Who benefits | Every Gateway client (DevOps Agent, IDEs, other agents) | The delegating agent only |
| Example here | `find_cost_waste`, `locate_iac_source` | Remediation-PR Agent |
| Rule of thumb | "Look something up / compute something" | "Go do something that requires judgment or a write" |

**Decision test:** if the capability needs to make multiple dependent decisions, hold its own credentials, or perform writes — it's an A2A agent. Otherwise make it an MCP tool; tools are cheaper, safer, and shared by all clients.

Both types share the same lifecycle philosophy: manifest, owner, declared retirement condition, retirable by config.

### Onboarding existing agents (`type: external-agent`)

Teams that already run agents shouldn't have to rewrite or redeploy them to join the governed catalog. An A2A manifest with `type: external-agent` registers an agent you already operate as a delegation target for DevOps Agent:

```yaml
# capabilities/a2a/my-existing-agent/manifest.yaml
name: my-existing-agent
description: What DevOps Agent may delegate to this agent, and when
type: external-agent          # vs type: runtime (deployed by this blueprint)
enabled: false                # opt-in
owner: team-y
endpoint:
  ssmParameter: /platform/a2a/my-existing-agent/endpoint
auth: <its existing auth>
scope: >                     # governance: what this agent is allowed to be asked to do
  Delegated remediation of X only; no direct data access via this platform.
retirement: >
  Decommission if DevOps Agent gains native X.
```

The blueprint owns **registration and governance** (the manifest is the reviewed, auditable record of the agent's existence, owner, scope, and exit condition); the owning team keeps **build, deploy, and operations**. Same split as `external-repo` for MCP servers — together these are the "add-on path" for organizations with existing agent investments.

## Manifest schema

```yaml
# capabilities/mcp/find-cost-waste/manifest.yaml
name: find-cost-waste
description: Detect idle/oversized resources (Compute Optimizer, Trusted Advisor, heuristics)
type: lambda                # lambda | awslabs-reuse | mcp-passthrough | external-repo
enabled: true
handler: lambda/handler.py  # for type: lambda
# ref: <container/package ref>   # for type: awslabs-reuse
# endpoint + auth               # for type: mcp-passthrough
retirement: >               # the "designed to shrink" clause
  Decommission if AWS DevOps Agent gains native idle-resource detection.
tools:
  - name: find_cost_waste
    version: 1              # breaking change ⇒ new tool name (find_cost_waste_v2)
permissions:                # least-privilege IAM synthesized per target
  - compute-optimizer:Get*
  - trustedadvisor:Describe*
  - ec2:Describe*
readOnly: true              # write tools are rejected on the shared Gateway
```

### `type: external-repo` — referencing independently-deployed MCP servers

Real-world MCP servers often live in their own repositories with their own deployment stories (awslabs servers, internal team repos). The platform does not *deploy* these — it *registers* them as Gateway targets and documents the handshake:

```yaml
# capabilities/mcp/opensearch/manifest.yaml
name: opensearch
description: Query OpenSearch clusters (logs/search analytics) during investigations
type: external-repo
enabled: false              # opt-in: requires the external deploy first
source: https://github.com/lillyjohns/devopsagent-opensearch-mcp
deploy: agentcore           # deployed by ITS repo's mechanism, not this one
endpoint:
  ssmParameter: /platform/mcp/opensearch/endpoint   # filled after external deploy
auth: cognito-jwt
retirement: >
  Decommission if AWS DevOps Agent gains native OpenSearch/log-analytics tooling.
readOnly: true
```

Contract for external repos: the external repo owns build/deploy/upgrade; this platform owns registration, auth handshake (endpoint + credentials via SSM/Secrets Manager), and lifecycle (enable/retire). This mirrors how DevOps Agent itself imports skills from external repositories.

The shipped `opensearch` pack doubles as the proof that the manifest system works for a **second domain** beyond cost — with zero new tool code in this repo.

## Contract rules

- **Tool names + schemas are the API surface.** Additive changes are fine; breaking changes require a versioned tool name (`find_cost_waste_v2`).
- **Every Gateway target is read-only by default.** `readOnly: true` is enforced at synth time — write capabilities never join the shared Gateway.
- **Per-target least-privilege IAM**, declared in the manifest and synthesized by CDK.
- **Every target declares a retirement condition** in its manifest — the native capability that would make it obsolete.

## Gateway routing vs direct MCP registration

DevOps Agent *can* register MCP servers directly — but per-MCP registration scales badly:

| | Direct registration | Gateway as contract |
|---|---|---|
| Adding an MCP | Touches DevOps Agent config every time (N `DevOpsAgent::Service` resources) | Drop a folder, `cdk deploy` — DevOps Agent untouched |
| Other clients (Kiro/Claude, PR agent, future agents) | Get nothing — benefits DevOps Agent only | Get every new tool for free |
| Auth, throttling, audit | Per-MCP, scattered | One place |
| OAuth-backed services | `AWS::DevOpsAgent::Service` **cannot** register them (console-only) | Gateway absorbs whatever auth each backend needs, presents uniform SigV4 upstream |

## MCP target selection

Selection criteria for what belongs behind the Gateway:
(a) not already native to DevOps Agent, (b) needed by multiple clients, (c) safe to expose to *every* Gateway client.

| MCP target | Type | Purpose | Retirement condition |
|---|---|---|---|
| Cost Explorer MCP | awslabs, reused | Spend data, anomalies, forecasts | — (upstream-maintained) |
| AWS Pricing MCP | awslabs, reused | Price lookups so PRs state *"saves ~$47/month"* | — (upstream-maintained) |
| `find_cost_waste` | custom Lambda | One purposeful tool wrapping Compute Optimizer + Trusted Advisor cost checks + idle-resource heuristics (NAT GW bytes, unattached EBS, gp2 inventory) | Native idle-resource detection |
| `locate_iac_source` | custom Lambda | **Resource ARN → owning IaC block** (tags + Resource Explorer + scoped read-only repo search). The hardest problem in the sample, promoted to a first-class tool | Native IaC state awareness |
| `generate_cost_report` | custom Lambda | xlsx (openpyxl) → S3 → presigned URL, available to every client | Native artifact generation |
| `opensearch` | external-repo, disabled by default | Log/search analytics from an independently-deployed [OpenSearch MCP server](https://github.com/lillyjohns/devopsagent-opensearch-mcp); proves the second-domain story | Native OpenSearch tooling |

**Documented option (not shipped):** registering DevOps Agent's own MCP endpoint (`start_investigation`, `get_investigation_status`) as a Gateway passthrough target for the single-endpoint IDE story — see [Entry points](#entry-points-and-ide-wiring). Kept out of the default deployment to avoid circular-routing confusion in a sample.

**Deliberately NOT behind the Gateway:**

- **CloudWatch / CloudTrail / logs MCPs** — DevOps Agent investigates with these natively; duplicating them adds cost and tool-selection confusion for zero new capability.
- **GitHub write access** — write credentials on a shared Gateway would let any connected IDE client silently open PRs. Write stays a *private* capability of the Remediation-PR Agent (own runtime, own secret). Least privilege by architecture; the Gateway exposes read-only `locate_iac_source` instead.

**Curated tools over raw API mirrors:** fewer, purposeful tools (`find_cost_waste` vs three raw APIs) improve LLM tool selection. Reusing awslabs MCP servers (Cost Explorer, Pricing) shows composition over reinvention.

## Entry points and IDE wiring

Kiro/Claude → Gateway alone gets **raw tools only** — no DevOps Agent judgment. Two documented wiring options:

- **Option 1 (simplest):** the IDE connects to *both* the Gateway (tools) and DevOps Agent's own headless MCP endpoint (judgment) — e.g. the Kiro power for AWS DevOps Agent.
- **Option 2 (single endpoint):** register DevOps Agent's MCP endpoint as one more Gateway target (`start_investigation`, `get_investigation_status`) so the Gateway is the only connection the IDE needs. The *client's* LLM decides when to offload to DevOps Agent.

## AWS Agent Registry integration (optional)

The git-based `capabilities/` catalog is the **definition plane**: what exists, who owns it, what it may do, when it retires — versioned, reviewable, deployable. [AWS Agent Registry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html) (preview) adds the **discovery plane**: an organization-wide, searchable catalog with an approval workflow, queryable by humans and agents (it exposes its own MCP endpoint).

They compose rather than compete:

- **Auto-publish on deploy** (optional, `cdk.json` flag, off by default): the same construct that scans manifests emits one registry record per enabled capability, plus records for the Gateway and the PR agent. The manifest stays the source of truth; the Registry is a *projection* of it
- **Retirement propagates**: `enabled: false` → record deprecated — consumers *see* that a capability has been retired
- Registry approval workflow can layer org-level curation on top of the git PR review

Caveats: preview service; publish step is likely a CFN custom resource calling the Registry API (no guaranteed CFN types yet). Scheduled for M5.

## Decision log

| Decision | Alternatives considered | Why |
|---|---|---|
| DevOps Agent as orchestrator (console = primary UX) | Custom frontend + Gateway fronting everything (Thomson Reuters pattern); putting DevOps Agent *behind* the Gateway | A custom frontend demotes DevOps Agent to just-another-tool and forces rebuilding Agent Spaces, timelines, dashboards, incident-skip, memories. TR's pattern fits a multi-team enterprise hub, not a single-account sample. It also muddies the decommission story — the sample only reads cleanly if DevOps Agent is the brain. |
| A2A sub-agent for PR work (not EventBridge handoff) | Structured recommendation events on EventBridge | A2A makes decommissioning literally "remove one connection". EventBridge handoff would work but is a weaker upgrade story. |
| Excel reporting as a Gateway MCP tool | Client-side generation in Claude cowork | Behind the Gateway, *every* client gets it (scheduled agents included); client-side means reports only exist when a human with Claude asks. |
| Curated MCP tools over raw API mirrors | One MCP target per AWS API | Fewer, purposeful tools improve LLM tool selection; awslabs reuse shows composition over reinvention. |
| GitHub write creds private to PR agent | GitHub read/write MCP on the shared Gateway | Anyone connected to the Gateway could open PRs. Read-only IaC lookup is shared; the write path is isolated with its own secret. |
| CDK-only (no parallel Terraform implementation) | CDK + Terraform dual-ship; platform CDK + workload Terraform | One language, one toolchain, one `deploy.sh`. The manifest-driven Gateway construct is a CDK construct — that's where the effort belongs. Mixed-IaC repos confuse the clone-and-deploy experience. Terraform is a documented extension path (see below). |
| CLI break/fix instead of web dashboard | Interactive dashboard like the networking demo | Less code to maintain, fits the DevOps audience, keeps focus on the agent pattern rather than UI. |
| Platform-first framing, cost as reference implementation | Pure cost-optimization sample; pure generic framework | A pure cost sample buries the reusable machinery; a pure framework isn't demoable. Cost is the "demo cartridge" that proves the platform in 15 minutes. |
| `capabilities/{mcp,a2a}/` — A2A as a first-class type | PR agent as a one-off under `agents/` | DevOps Agent's extension surface is exactly MCP + A2A; a platform sample should teach the *choice* between them, not just showcase one instance. |
| Governance as docs + structural mechanisms, not machinery | Implementing policy engine, eval pipelines, multi-account governance | Pillars get pages, not pipelines. Manifest-as-policy + git-as-approval-workflow are real mechanisms; faking Cedar/evals in a sample would be worse than pointing at AgentCore Policy/Evaluations. See [GOVERNANCE.md](GOVERNANCE.md). |
| OpenSearch as the external-repo example | Inventing a second toy domain | An [independently-deployed, working MCP server](https://github.com/lillyjohns/devopsagent-opensearch-mcp) proves the second-domain + external-repo story with zero new tool code. |
| Governance-blueprint framing (start safe + grow governed + add-on path) | Pure extensibility framing | The customer blocker is fear of mixing agents in the environment, not lack of mechanism. Three personas: first agent, more agents coming, agents already running. `external-repo`/`external-agent` are the add-on path. |
| AWS Agent Registry as optional discovery plane | Git catalog only; Registry as source of truth | Git owns definition (deployable, reviewable); Registry owns org-wide discovery. Auto-publish keeps them in sync; preview status keeps it optional. |
| Runbooks as an S3 data pack + keyword-search tool | OpenSearch/embeddings; Bedrock Knowledge Base; runbooks pasted into agent instructions | The point is the *pattern* — the agent consults approved procedures instead of improvising — not the retrieval tech. Runbooks ship inside the capability folder (`capabilities/mcp/search-runbook/runbooks/`) and seed to S3 at deploy: same drop-a-folder lifecycle as code, reviewed in the same PR. Keyword scoring is ~40 lines; a library big enough to need vector search has outgrown the sample (that's the retirement clause). The generic `data:` manifest key means any future capability can ship reference data the same way. |
| Alert glue = thin Lambda → CreateChat/SendMessage | Parsing findings + driving remediation in the glue; Step Functions orchestration; SNS → email-a-human | Design principle 1: judgment stays in DevOps Agent. The glue turns an alert into a *question to the agent* (~100 lines: format NL prompt, send, log the executionId, detach after a 45 s stream budget). The investigation continues server-side; the console is the UX. Orchestration machinery would duplicate what DevOps Agent already is. Lives in the Scenarios stack because it *exercises* the platform rather than being part of it. |

## Terraform notes

**Using Terraform for your IaC?** Two facts worth knowing:

1. **Provisioning DevOps Agent via Terraform works** through the [AWS Cloud Control (`awscc`) provider](https://registry.terraform.io/providers/hashicorp/awscc/latest) — the `AWS::DevOpsAgent::*` types are in the CloudFormation registry, which `awscc` is generated from. The OAuth-service limitation and post-deploy steps carry over identically.
2. **DevOps Agent reads Terraform** (repo learning, PR reviews on `.tf` diffs) but has no state-file/backend awareness today — which is exactly why `locate_iac_source` exists. The shipped resolver targets CDK; a Terraform resolver (HCL block lookup) is a natural community extension point in the same manifest.

## Deployment findings (verified in ap-northeast-1, 2026-07-03)

Hard-won facts from the first real deployment — all encoded in the CDK code:

1. **DevOps Agent service principal is `aidevops.amazonaws.com`** (not devopsagent/devops-agent). The SigV4 invoke role needs it in the trust policy with confused-deputy conditions (`aws:SourceAccount` + `aws:SourceArn` on `arn:aws:aidevops:<region>:<account>:service/*`).
2. **DevOps Agent negotiates MCP protocol 2025-03-26**; modern IDE clients use 2025-06-18. The Gateway must list **both** in `supportedVersions` — and that property is effectively **create-only** (changing it forces gateway replacement, which also changes the Gateway URL).
3. **64-char combined name limit:** DevOps Agent enforces `len(mcpServerName + '_' + toolName) ≤ 64`. Keep the registered server name short (`gov-gw`) and budget tool names accordingly.
4. **`AWS::DevOpsAgent::Association` requires a typed Configuration** — for the Gateway binding: `Configuration.MCPServerSigV4.Tools` = explicit per-Agent-Space tool allowlist (include `x_amz_bedrock_agentcore_search` so semantic discovery keeps working as capabilities are added).
5. **The full chain is CloudFormation-able:** Gateway + targets + AgentSpace + Service (mcpserversigv4) + Association deployed with zero console steps. The Service resource validates the MCP connection at create time (it calls tools/list — a misconfigured Gateway fails the deploy, which is governance working in your favor).
6. Gateway Lambda targets receive the tool name in `context.client_context.custom['bedrockAgentCoreToolName']` prefixed as `<targetName>___<toolName>`; clients must send the `MCP-Protocol-Version` header on post-initialize calls.
7. **`AWS::BedrockAgentCore::GatewayTarget` `Description` max is 200 chars** — CloudFormation rejects longer values at deploy time (learned from a live `UPDATE_ROLLBACK`: a manifest description + retirement note concatenation hit 254 chars). The capabilities construct now clamps every target description (whitespace-collapsed, truncated with an ellipsis) and a synth test enforces the limit.
8. **Chat API (alert glue):** the `devops-agent` API signs as `aidevops` and exposes `CreateChat` / `SendMessage` / `ListChats` / `ListPendingMessages`. `SendMessage` returns an event stream (`contentBlockStart` → `contentBlockDelta` → `contentBlockStop`, with tool use surfaced in `contentBlockStart.start.toolUse` and text in `delta.text`/`delta.jsonDelta.partialJson`). The investigation keeps running server-side if the client detaches mid-stream — which is exactly what the alert glue does after confirming pickup. Lambda runtimes may not bundle the service model yet; ship it with the function and point `AWS_DATA_PATH` at it.

## Open items

- [ ] Verify A2A delegation payload supports full finding context (resource ARNs, repo hints) or define a thin structured contract
- [ ] Check APIs for webhook/HMAC + A2A registration → wrap as CFN custom resources if possible (June 2026 releases added API-key webhook auth and Asset APIs — likely yes)
- [ ] Verify scheduled SRE agent can be defined via Git-managed skills (June 22 release: skills importable from a repo via SDK/CLI — promising)
- [ ] Confirm exact scope of DevOps Agent native PR capability (which finding types) — affects Phase 2 timeline
- [ ] Redraw diagram with official AWS architecture icons
- [ ] Build the manifest-driven CDK construct (directory scan → Gateway targets + per-target IAM)
- [ ] Ship `examples/s3-storage-class` disabled target as the extensibility demo
- [ ] Constrain Phase 1 IaC mapping to a known repo structure with tagged resources
- [ ] Enable DevOps Agent release readiness reviews on the demo repo so it reviews the PR agent's PRs (agent proposes → agent reviews → human merges)
