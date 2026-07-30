<h1 align="center">AWS DevOps Agent Governance Blueprint</h1>

<p align="center">Start with AWS DevOps Agent the governed way — and have a home ready for every agent that comes after it.</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT--0-yellow.svg" alt="License: MIT-0"></a>
  <a href="https://aws.amazon.com/cdk/"><img src="https://img.shields.io/badge/AWS_CDK-TypeScript-blue.svg" alt="AWS CDK"></a>
  <a href="https://docs.aws.amazon.com/devopsagent/latest/userguide/what-is.html"><img src="https://img.shields.io/badge/AWS-DevOps_Agent-orange.svg" alt="AWS DevOps Agent"></a>
  <a href="https://docs.aws.amazon.com/bedrock-agentcore/"><img src="https://img.shields.io/badge/Bedrock-AgentCore-purple.svg" alt="Amazon Bedrock AgentCore"></a>
  <a href="#"><img src="https://img.shields.io/badge/Status-Design_Spec-teal.svg" alt="Status: Design Spec"></a>
</p>

<p align="center">
  <strong>One gateway. One catalog. One set of rules — for your first agent and your fiftieth.</strong>
</p>

> **Note:** This repository is a work-in-progress sample. The platform core (Gateway + capability catalog + DevOps Agent binding) **deploys and is verified working** in `ap-northeast-1`; the PR agent and demo scenarios are in progress — see [Roadmap](#roadmap). Demo/sample application for learning purposes, not intended for production use.

An extensible AI platform blueprint built on [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/what-is.html) and [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/), shipped with a complete **cost-optimization reference implementation**: DevOps Agent autonomously finds cost waste and remediates it via GitHub Pull Requests — with a human merge as the approval gate.

---

## Table of Contents

- [Why this sample](#why-this-sample)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Two lifecycle mechanisms](#two-lifecycle-mechanisms)
- [Capability types: MCP and A2A](#capability-types-mcp-and-a2a)
- [Cost-optimization reference implementation](#cost-optimization-reference-implementation)
- [Governance](#governance)
- [Entry points](#entry-points)
- [Demo walkthrough](#demo-walkthrough)
- [Deployability](#deployability)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Design deep-dive](#design-deep-dive)
- [Roadmap](#roadmap)
- [Cost estimate](#cost-estimate)
- [Clean up](#clean-up)
- [Security](#security)
- [Contributing](#contributing)
- [License](#license)

---

## Why this sample

The most common blocker to adopting AI agents today isn't capability — it's **fear of mixing agents in the environment**: who owns them, what can they touch, how do you stop sprawl before it starts, and what happens to the custom glue when native features ship?

This blueprint answers that for three situations:

| You are… | This blueprint gives you |
|:--|:--|
| **Adopting your first agent** (AWS DevOps Agent) | A governed starting point: one gateway, isolated write path, human-in-the-loop by construction — working out of the box with a cost-optimization reference implementation |
| **Worried about the agents that come next** | A **capability catalog** where every future tool and agent lands the same governed way — manifest, owner, least-privilege IAM, declared retirement condition. Growth without sprawl |
| **Already running agents or MCP servers** | An **add-on path**: register what you have (`external-repo` MCP servers, `external-agent` A2A agents) without redeploying or rewriting it — your existing investment joins the governed catalog as-is |

And it is **designed to shrink as DevOps Agent grows**: every custom component declares the native capability that will retire it. Decommissioning is `enabled: false` or removing one A2A connection — never a re-architecture. Custom glue never becomes legacy debt.

> **Design principle: Gateway is for tools. DevOps Agent is for judgment. Governance is for both.**

## How it works

| Step | What happens |
|:----:|:-------------|
| **1** | Cost waste appears — a scheduled **"Daily Cost Sweep"** agent finds it, or a [Cost Anomaly Detection](https://docs.aws.amazon.com/cost-management/latest/userguide/manage-ad.html) alarm fires → SNS → webhook |
| **2** | **AWS DevOps Agent** investigates, pulling evidence through the [AgentCore Gateway](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html)'s MCP tools (spend data, rightsizing, IaC location, pricing) |
| **3** | DevOps Agent delegates remediation to the **Remediation-PR Agent** via [A2A](https://docs.aws.amazon.com/devopsagent/latest/userguide/configuring-integrations-and-knowledge-connecting-remote-a2a-agents.html) with a structured finding |
| **4** | The PR agent maps the finding to the owning CDK block, generates the diff, validates it with [`cdk validate`](https://aws.amazon.com/blogs/devops/ship-infrastructure-faster-with-cloudformation-and-cdk-pre-deployment-validation-on-every-stack-operation/), and opens a GitHub PR — with estimated **$ savings** in the description |
| **5** | *(Optional)* DevOps Agent's [release readiness review](https://docs.aws.amazon.com/devopsagent/latest/userguide/release-management-release-readiness-code-review.html) reviews the PR — **one agent proposes, another reviews** |
| **6** | A human merges. That's the approval gate — human-in-the-loop via normal code review, no custom approval UI |

**Phase 2 (when DevOps Agent ships native PR remediation):** deregister the A2A connection. Everything else stays.

## Architecture

![Architecture](architecture.png)

| Component | Role |
|:----------|:-----|
| **AWS DevOps Agent** (Agent Space) | The brain: investigations, scheduled custom SRE agents, memories, skills, dashboards |
| **AgentCore Gateway** (single) | The stable contract: one endpoint, SigV4, semantic tool search; all capability lives behind it |
| **MCP targets** (manifest-driven) | Cost Explorer + Pricing ([awslabs](https://github.com/awslabs/mcp), reused), `find_cost_waste`, `locate_iac_source`, `generate_cost_report` (custom Lambdas) |
| **Remediation-PR Agent** (AgentCore Runtime) | Phase-1 A2A sub-agent: structured finding → IaC diff → validated GitHub PR. **Decommissionable by design** |
| **Demo workload + break/fix CLI** | Canned cost-waste scenarios (`make break-scenario-N` / `make restore`) |

## Two lifecycle mechanisms

The platform's extensibility story in two moves:

**➕ Add a capability** — drop a folder with a `manifest.yaml` under `capabilities/mcp/`, run `cdk deploy`. The CDK construct scans the directory, synthesizes the Gateway target and least-privilege IAM. DevOps Agent and every other client discover the new tools automatically via semantic search. No DevOps Agent config change, no console click.

**➖ Retire a capability** — every manifest declares its retirement condition:

```yaml
retirement: >
  Decommission if AWS DevOps Agent gains native idle-resource detection.
```

When that day comes: `enabled: false`, `cdk deploy`. Same mechanism retires the Remediation-PR Agent (deregister its A2A connection) when native PR support ships. **Custom glue never becomes legacy debt.**

## Capability types: MCP and A2A

DevOps Agent's extension surface is exactly two protocols — and the platform treats both as first-class, manifest-driven capability types:

| | `capabilities/mcp/` | `capabilities/a2a/` |
|:--|:--|:--|
| Shape | Tool — the **caller** reasons | Agent — the **callee** reasons |
| Routing | Shared AgentCore Gateway (SigV4) | A2A registration with DevOps Agent |
| Credentials | Read-only, least-privilege, per target | Own isolated credentials (may write) |
| Example | `find_cost_waste`, `locate_iac_source` | Remediation-PR Agent |

**Rule of thumb:** "look something up" → MCP tool. "Go do something requiring judgment or a write" → A2A agent. Full decision guide in [docs/DESIGN.md](docs/DESIGN.md#mcp-vs-a2a-choosing-your-extension-type).

### Bring your existing agents and tools

Already have agents or MCP servers running? They join the catalog **without being redeployed or rewritten**:

- **`type: external-repo`** (MCP) — an MCP server that lives in its own repository with its own deploy story. The blueprint *registers* it as a Gateway target (endpoint via SSM, auth handshake documented) — it doesn't deploy it
- **`type: external-agent`** (A2A) — an agent you already operate (on AgentCore Runtime or elsewhere), registered as an A2A connection for DevOps Agent to delegate to

The onboarding contract is the same for everything in the catalog: a manifest with an **owner**, **declared permissions**, and a **retirement condition** — reviewed as a git PR. That's what makes "more and more agents coming" a non-event instead of sprawl.

Other MCP manifest types: `lambda` (your code, deployed by this blueprint) and `awslabs-reuse` (upstream servers).

## Cost-optimization reference implementation

The platform ships with cost optimization as its worked example — inherently periodic (fits scheduled agents), measurable (PRs state their $ savings), and safely demoable (waste is cheap to fake and fix).

| Gateway target | Type | Purpose |
|:---------------|:-----|:--------|
| Cost Explorer MCP | awslabs, reused | Spend data, anomalies, forecasts |
| AWS Pricing MCP | awslabs, reused | Price lookups → *"saves ~$47/month"* in every PR |
| `find_cost_waste` | custom Lambda | Compute Optimizer + Trusted Advisor + idle heuristics in one purposeful tool |
| `locate_iac_source` | custom Lambda | **Resource ARN → owning IaC block** — the capability DevOps Agent lacks today |
| `generate_cost_report` | custom Lambda | xlsx → S3 presigned URL, for every client (chat, IDE, scheduled) |
| `search_runbook` | custom Lambda | Keyword search over the team's runbook library (markdown in S3, seeded from the capability folder) — the agent consults *approved* remediation procedures instead of improvising |
| `opensearch` *(disabled)* | external-repo | Second-domain proof: registers an [independently-deployed OpenSearch MCP server](https://github.com/lillyjohns/devopsagent-opensearch-mcp) — zero new tool code |

Deliberately **not** on the Gateway: CloudWatch/CloudTrail (DevOps Agent has them natively) and GitHub **write** credentials (isolated in the PR agent — a shared write path would let any IDE client open PRs). Rationale in [docs/DESIGN.md](docs/DESIGN.md).

## Governance

The platform covers the enterprise agent-platform pillars at sample scale — **structural mechanisms, not machinery**:

- **Policy-as-code:** the manifest — `readOnly` enforced at synth, least-privilege IAM per target, versioned tools, declared retirement conditions
- **Registry & catalog:** `capabilities/` is a reviewable, git-owned tool/agent catalog; adding or retiring a capability is a reviewed PR
- **Enforcement plane:** one authenticated Gateway entry point; writes isolated to one agent; every write lands as a human-reviewed PR (HITL by design)
- **Anti-sprawl:** no shadow tools (capability ⇔ folder in git), no integration chaos (one Gateway, one protocol), no cost blindness (per-capability cost tags + dashboard)

The full pillar-by-pillar mapping — including what's deliberately **out of scope** (multi-account, multi-tenancy, eval pipelines) and the graduation path to the enterprise reference architecture — is in **[docs/GOVERNANCE.md](docs/GOVERNANCE.md)**.

## Entry points

| Entry point | What you get |
|:------------|:-------------|
| **DevOps Agent console** (primary) | Investigations, timelines, Agent Spaces, dashboards — no custom frontend to build or maintain |
| **Kiro / Claude via MCP** | Gateway tools in your IDE; pair with DevOps Agent's [remote MCP endpoint](https://docs.aws.amazon.com/devopsagent/latest/userguide/accessing-devops-agent-connect-to-devops-agent-remote-servers.html) for investigations (two wiring options in [docs/DESIGN.md](docs/DESIGN.md#entry-points-and-ide-wiring)) |
| **Demo CLI** | `make break-scenario-N` / `make restore` |

## Demo walkthrough

~15 minutes end-to-end:

```bash
make break-scenario-2          # create an idle NAT gateway
# → CloudWatch alarm fires → webhook → DevOps Agent investigates
# → A2A delegation → Remediation-PR Agent
# → GitHub PR appears: CDK diff + cdk validate report + "$32.85/month savings"
# → (optional) DevOps Agent release readiness review comments on the PR
# → you review & merge → pipeline applies → fixed
make restore                   # or reset everything

# Bonus — from Kiro/Claude:
# "Generate this month's cost report" → xlsx via presigned URL
```

Scenarios: oversized EC2 instance · idle NAT gateway · unattached EBS volumes · gp2→gp3 migration.

### Alert → investigation (live today)

The first slice of the demo loop is deployed and working: an alert becomes a
*question to the agent*, and the agent answers it with the governed catalog.

```bash
python3 scripts/trigger_alert.py --watch
# → EventBridge rule matches the (synthetic) cost anomaly event
# → alert-glue Lambda opens a DevOps Agent chat (CreateChat + SendMessage)
#   with an NL prompt: "Alert received: … investigate, consult the runbook, propose a fix"
# → DevOps Agent calls find_cost_waste through the Gateway,
#   pulls the approved procedure via search_runbook,
#   and proposes a runbook-compliant fix with estimated savings
# → follow along in the DevOps Agent console (executionId is in the glue logs)
```

The glue is ~100 lines and deliberately dumb — no parsing, no remediation
logic. Swap the demo event pattern for a real source (Cost Anomaly Detection
via SNS→EventBridge, CloudWatch alarm state changes) without touching the
Lambda. Judgment stays in DevOps Agent; runbooks keep it *governed* judgment.

### Finding → runbook → pull request (live today)

The write path of the loop is deployed and working — the full
"cost waste found → approved procedure → fix proposed as a PR" story:

```bash
python3 scripts/nl_chat.py --agent-space <id> --message \
  "We found a gp2 EBS volume defined in scenarios/demo-workload/template.yaml. \
   Consult the runbook and open a PR to fix it."
# → DevOps Agent calls search_runbook → finds 'gp2 to gp3 EBS Volume Migration'
# → the runbook says: fix it in the IaC via propose_fix_pr, never in the console
# → DevOps Agent calls propose_fix_pr (change_description: ebs-gp2-to-gp3)
# → a real GitHub PR appears against scenarios/demo-workload/template.yaml
# → a human reviews the diff + the attached finding, and merges
```

Executed live against this repo: the agent consulted the runbook and opened
[PR #1](https://github.com/lillyjohns/sample-aws-devops-agent-governance-blueprint/pull/1)
— gp2→gp3 diff, finding JSON in the body, left open for human review.

Three governance properties make this write path acceptable on a shared platform:

1. **Write-as-proposal.** The tool cannot change any environment — it can only
   *propose* a change as a PR. The merge button is the human-in-the-loop gate.
2. **Deterministic transforms only.** The diff comes from a fixed registry keyed
   by `change_description` (`ebs-gp2-to-gp3`); the tool refuses anything not in
   the registry. The agent supplies the judgment (*what* to fix, per the
   runbook); the tool executes an approved change. Adding a new transform is a
   reviewed git PR, like every capability change.
3. **Declared, scoped credential.** The manifest declares the write in the open
   (`externalWrite: {system: github, gate: human-review}`) — the synth-time
   validator rejects any manifest whose gate isn't `human-review`. The GitHub
   token is a fine-grained PAT in an SSM SecureString; the construct grants the
   Lambda read access to exactly that one parameter. It never appears in git,
   in the template, or on the shared Gateway.

The demo target is [`scenarios/demo-workload/`](scenarios/demo-workload/) — a
deliberately wasteful CFN template (gp2 volume, oversized instance) that serves
as the source-of-truth IaC. It is never deployed by the blueprint; the point is
the IaC-level fix.

## Retiring a capability (live walkthrough)

"Designed to shrink" is a mechanism here, not a slogan — this walkthrough was
executed against the live deployment. `propose-fix-pr` declares its exit
condition up front:

```yaml
retirement: >
  Retire when AWS DevOps Agent gains native PR-creation for cost findings —
  this tool exists only to close the propose-fix loop until then.
```

When that day comes, retirement is a one-line config change (or
`make retire-diff CAP=propose-fix-pr` / `make retire` / `make restore`):

```yaml
# capabilities/mcp/propose-fix-pr/manifest.yaml
enabled: false
```

`cdk diff` shows the platform shrinking — the Gateway target, the Lambda, its
IAM (including the scoped SSM token grant), *and* the Agent Space allowlist
entry all leave together, because the allowlist is derived from the catalog at
synth time and can never drift from it:

```text
Stack GovernanceBlueprint-Platform
Resources
[-] AWS::IAM::Role Capabilities/propose-fix-pr-fn/ServiceRole destroy
[-] AWS::IAM::Policy Capabilities/propose-fix-pr-fn/ServiceRole/DefaultPolicy destroy
[-] AWS::Lambda::Function Capabilities/propose-fix-pr-fn destroy
[-] AWS::Lambda::Permission Capabilities/propose-fix-pr-fn/propose-fix-pr-gateway-invoke destroy
[-] AWS::BedrockAgentCore::GatewayTarget Capabilities/propose-fix-pr-target destroy

Outputs
[~] Output EnabledCapabilities: {"Value":"find-cost-waste, generate-report, propose-fix-pr, search-runbook"}
                            to {"Value":"find-cost-waste, generate-report, search-runbook"}

Stack GovernanceBlueprint-DevOpsAgent
[~] AWS::DevOpsAgent::Association GatewayAssociation
 └─ [~] Configuration.MCPServerSigV4.Tools
     └─ @@ -2,6 +2,5 @@
        [ ]   "x_amz_bedrock_agentcore_search",
        [ ]   "find-cost-waste___find_cost_waste",
        [ ]   "generate-report___generate_cost_report",
        [-]   "propose-fix-pr___propose_fix_pr",
        [ ]   "search-runbook___search_runbook"
```

After `cdk deploy`, the live Gateway confirms it (verified via a SigV4
`tools/list` call):

```text
['find-cost-waste___find_cost_waste', 'generate-report___generate_cost_report',
 'search-runbook___search_runbook', 'x_amz_bedrock_agentcore_search']
propose_fix_pr present: False
```

No re-architecture, no orphaned IAM, no stale allowlist entry, no console
visit. The reverse (`enabled: true`, deploy) restores it just as cleanly —
which is how this repo was left. The same one-move retirement applies to A2A
capabilities: deregistering the connection *is* the decommission.

## Deployability

Target: **single `cdk deploy`** (~95% today, tracked in [Roadmap](#roadmap)).

| Piece | Status |
|:------|:-------|
| Agent Space, account association | ✅ [`AWS::DevOpsAgent::AgentSpace`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-agentspace.html) / [`Association`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_DevOpsAgent.html) |
| Gateway registered as MCP server in DevOps Agent | ✅ [`AWS::DevOpsAgent::Service`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-service.html) (`mcpserversigv4`) |
| AgentCore Gateway, targets, Runtime; workload; alarms; webhook Lambda | ✅ CDK |
| GitHub credential for `propose_fix_pr` | ✅ SSM SecureString (`/governance-blueprint/github-token`, seeded once via `aws ssm put-parameter`) — deliberately **not** DevOps Agent's OAuth GitHub integration, which [cannot be provisioned via CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-service.html) |
| Webhook + auth, A2A registration, scheduled agent definition | ⚠️ post-deploy script/console — custom-resource candidates (June 2026 Asset APIs + repo-importable skills look promising) |

## Testing

Three layers, from free to live:

| Layer | What it proves | Run |
|:------|:---------------|:----|
| **Governance unit tests** | The manifest gate rejects write capabilities, mutating IAM actions, and malformed packs — and every real manifest in the repo passes it | `cd platform && npm test` |
| **Synth assertion tests** | Deployed shape without touching AWS: Gateway auth + both MCP protocol versions, `GATEWAY_IAM_ROLE`-only targets, `aidevops.amazonaws.com` trust with confused-deputy conditions, least-privilege scoping, project tagging, the 64-char tool-name budget, and the catalog-derived tool allowlist | (included in `npm test`) |
| **Live E2E smoke test** | The deployed platform end-to-end, exactly the way DevOps Agent calls it: SigV4-signed MCP `initialize` → `tools/list` → `tools/call` for every capability, CSV artifact download — and optionally plants a real unattached EBS volume, verifies the waste detector finds it, and cleans it up | `python3 scripts/e2e_test.py --region <region> [--plant-waste]` |

The E2E script reads the Gateway URL from the CloudFormation outputs — no configuration needed. Exit code 0 means everything passed:

```text
[PASS] stack GovernanceBlueprint-Platform healthy — UPDATE_COMPLETE
[PASS] stack GovernanceBlueprint-DevOpsAgent healthy — CREATE_COMPLETE
[PASS] GatewayUrl output present
[PASS] MCP initialize handshake
[PASS] tools/list exposes catalog
[PASS] find_cost_waste returns well-formed result — 0 findings
[PASS] generate_cost_report returns downloadable CSV
[PASS] search_runbook ranks the NAT gateway runbook first — 'Idle NAT Gateway Remediation' score=5.5
[PASS] search_runbook include_content returns full markdown
[PASS] gp2 runbook instructs the agent to use propose_fix_pr
[PASS] propose_fix_pr dry_run returns the gp2→gp3 diff without opening a PR — 1 replacement(s), no PR opened
[PASS] propose_fix_pr rejects unapproved change_description
[PASS] planted EBS volume detected as waste — vol-09a4ae5e174e41588
       cleaned up vol-09a4ae5e174e41588

13 passed, 0 failed
```

## Project structure

Planned layout (see [Roadmap](#roadmap)):

```
.
├── platform/                    # the reusable core
│   ├── lib/                     #   CDK stacks: Gateway, DevOps Agent binding, A2A slot
│   └── constructs/              #   manifest-driven Capabilities construct
├── capabilities/                # drop-in capability packs (the catalog)
│   ├── mcp/                     #   tool-shaped → shared Gateway
│   │   ├── cost-explorer/       #     awslabs reuse
│   │   ├── pricing/             #     awslabs reuse
│   │   ├── find-cost-waste/     #     manifest.yaml + lambda/
│   │   ├── locate-iac-source/   #     manifest.yaml + lambda/
│   │   ├── generate-report/     #     manifest.yaml + lambda/
│   │   ├── search-runbook/      #     manifest.yaml + lambda/ + runbooks/ (data pack → S3)
│   │   ├── opensearch/          #     external-repo, enabled: false
│   │   └── examples/
│   │       └── s3-storage-class/ #    the "write your own Lambda target" tutorial
│   └── a2a/                     #   agent-shaped → A2A registration
│       └── remediation-pr-agent/ #    minimal A2A agent — decommissionable by design
├── scenarios/                   # break/fix demo workload + Makefile
│   └── alert-glue/              #   EventBridge alert → DevOps Agent chat (deployed by Scenarios stack)
├── docs/
│   ├── DESIGN.md                # design rationale & decision log
│   ├── GOVERNANCE.md            # pillar mapping, scope boundaries, graduation path
│   ├── a2a-evidence.md          # A2A proof + chat-delegation gap (verified 2026-07-30)
│   ├── a2a-third-party-agent.md # BYO self-hosted A2A agent: wire dialect, bugs, checklist
│   └── architecture.dot         # diagram source (graphviz)
└── scripts/
    └── deploy.sh                # cdk deploy + post-deploy wire-up
```

## Design deep-dive

The full rationale lives in **[docs/DESIGN.md](docs/DESIGN.md)**:

- The Gateway-as-contract pattern and manifest schema
- Why DevOps Agent is *not* behind the Gateway (and when the opposite is right)
- Gateway routing vs registering MCPs directly with DevOps Agent
- Why GitHub write access never joins the shared Gateway
- CDK-only decision and Terraform (`awscc`) notes
- Complete decision log with alternatives considered

## Roadmap

- [x] **M1 — Platform core:** manifest-driven `Capabilities` CDK construct (synth-time governance validation), Gateway stack, DevOps Agent binding (`AgentSpace` + `Service` + `Association` with tool allowlist) — **deployed & verified in ap-northeast-1, 100% CloudFormation, zero console steps**
- [ ] **M2 — Capability packs:** `find_cost_waste` ✅, `generate_cost_report` ✅, `search_runbook` ✅ (live, tested through the Gateway); remaining: awslabs reuse packaging (Cost Explorer, Pricing), `locate_iac_source`, OpenSearch endpoint wiring
- [x] **M3 — Remediation-PR Agent:** minimal A2A agent on AgentCore Runtime (CodeConfiguration zip, no container), `remoteagentsigv4` registration + association via a `Custom::DevOpsAgentRemoteAgent` custom resource (the CFN Service/Association types don't cover remote agents yet) — **deployed & A2A-verified in ap-northeast-1** (`scripts/a2a_smoke.py`, [docs/a2a-evidence.md](docs/a2a-evidence.md)). Known gap: chat executions don't surface a delegation tool for `remoteagentsigv4` associations yet (service-side; evidence §3, re-verified 2026-07-30). Delegation **does** work from investigation executions — a self-hosted third-party A2A agent was successfully invoked end-to-end (incl. PR creation); wire-level dialect notes and a working checklist in [docs/a2a-third-party-agent.md](docs/a2a-third-party-agent.md)
- [ ] **M4 — Scenarios:** alert → investigation glue ✅ (Scenarios stack: EventBridge → CreateChat/SendMessage, `scripts/trigger_alert.py`); remaining: break/fix workload + Makefile + walkthrough docs
- [ ] **M5 — Hardening:** custom resources for post-deploy steps, `examples/s3-storage-class`, optional AWS Agent Registry auto-publish, AWS-icon architecture diagram, cost estimate table
- [ ] Verify: A2A finding payload shape ✅ (NL text + embedded JSON finding — [docs/a2a-evidence.md](docs/a2a-evidence.md)) · NL delegation from chat once the orchestrator surfaces remote-agent tools · scheduled-agent-as-code via repo-imported skills · native PR capability scope (Phase-2 trigger)

## Cost estimate

Will be documented per-stack before M4 (pattern: [interactive demo's cost table](https://github.com/aws-samples/sample-aws-devops-agent-interactive-demo#cost-estimate)). Main drivers: AWS DevOps Agent subscription, AgentCore Gateway/Runtime, the deliberately-wasteful demo workload (EC2, NAT GW, EBS — a few $/day; `make restore` tears the waste down).

> ⚠️ This sample intentionally creates billable waste to demo against. Always run `make restore` and `cdk destroy` when done.

## Clean up

```bash
make restore          # undo any active break scenarios
bash scripts/destroy.sh   # cdk destroy all stacks (planned)
```

Post-cleanup manual checks: Agent Space webhook config, A2A registrations, GitHub App installations (if any were added manually).

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for security issue notifications.

Security posture highlights:

- All Gateway targets **read-only, enforced at synth time**; per-target least-privilege IAM from manifests
- The only write path (GitHub PRs) is isolated in a dedicated agent with its own scoped credential — and lands as a *proposal* gated by human review
- Webhooks HMAC-signed / API-key authenticated; Gateway auth via SigV4

## Contributing

Contributions welcome — the manifest system is designed for community capability packs. See [CONTRIBUTING.md](CONTRIBUTING.md), including how to submit a new MCP target with its retirement condition.

## References

- [How Thomson Reuters built an Agentic Platform Engineering Hub with Amazon Bedrock AgentCore](https://aws.amazon.com/blogs/machine-learning/how-thomson-reuters-built-an-agentic-platform-engineering-hub-with-amazon-bedrock-agentcore/)
- [aws-samples/sample-aws-devops-agent-interactive-demo](https://github.com/aws-samples/sample-aws-devops-agent-interactive-demo)
- [AWS DevOps Agent: custom SRE agents, BYO sub-agents, MCP/A2A (June 2026)](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-devops-agent-custom-agents/)
- [`AWS::DevOpsAgent::*` CloudFormation reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_DevOpsAgent.html)
- [CloudFormation/CDK pre-deployment validation](https://aws.amazon.com/blogs/devops/ship-infrastructure-faster-with-cloudformation-and-cdk-pre-deployment-validation-on-every-stack-operation/)
- [Open source MCP servers for AWS (awslabs/mcp)](https://github.com/awslabs/mcp)

## License

This sample is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
