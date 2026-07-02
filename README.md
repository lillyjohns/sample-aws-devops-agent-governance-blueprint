<h1 align="center">AWS DevOps Agent Extensible Platform</h1>

<p align="center">An AI platform blueprint that grows by manifest — and shrinks as AWS DevOps Agent learns.</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT--0-yellow.svg" alt="License: MIT-0"></a>
  <a href="https://aws.amazon.com/cdk/"><img src="https://img.shields.io/badge/AWS_CDK-TypeScript-blue.svg" alt="AWS CDK"></a>
  <a href="https://docs.aws.amazon.com/devopsagent/latest/userguide/what-is.html"><img src="https://img.shields.io/badge/AWS-DevOps_Agent-orange.svg" alt="AWS DevOps Agent"></a>
  <a href="https://docs.aws.amazon.com/bedrock-agentcore/"><img src="https://img.shields.io/badge/Bedrock-AgentCore-purple.svg" alt="Amazon Bedrock AgentCore"></a>
  <a href="#"><img src="https://img.shields.io/badge/Status-Design_Spec-teal.svg" alt="Status: Design Spec"></a>
</p>

<p align="center">
  <strong>Deploy once. Extend by dropping a manifest. Decommission as DevOps Agent learns.</strong>
</p>

> **Note:** This repository is currently a **design specification**. Implementation is planned — see [Roadmap](#roadmap). This will be a demo/sample application for learning purposes, not intended for production use.

An extensible AI platform blueprint built on [AWS DevOps Agent](https://docs.aws.amazon.com/devopsagent/latest/userguide/what-is.html) and [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/), shipped with a complete **cost-optimization reference implementation**: DevOps Agent autonomously finds cost waste and remediates it via GitHub Pull Requests — with a human merge as the approval gate.

---

## Table of Contents

- [Why this sample](#why-this-sample)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Two lifecycle mechanisms](#two-lifecycle-mechanisms)
- [Cost-optimization reference implementation](#cost-optimization-reference-implementation)
- [Entry points](#entry-points)
- [Demo walkthrough](#demo-walkthrough)
- [Deployability](#deployability)
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

Teams adopting AWS DevOps Agent face two practical questions:

1. **"It can't do X yet (e.g. open remediation PRs) — do we wait?"**
2. **"If we build custom glue around it, does that glue become legacy debt when native features ship?"**

This blueprint answers both with a platform that is **designed to shrink as DevOps Agent grows**:

- Custom capabilities plug in behind a single AgentCore Gateway via **drop-in manifests** — adding one never touches DevOps Agent
- Every custom component declares its **retirement condition** — when DevOps Agent gains that skill natively, you flip `enabled: false` or remove one A2A connection. No re-architecture, ever
- The shipped example — a **Remediation-PR Agent** that opens IaC pull requests before DevOps Agent can — is itself the first component scheduled for decommissioning

> **Design principle: Gateway is for tools. DevOps Agent is for judgment.**

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

**➕ Add a capability** — drop a folder with a `manifest.yaml` under `mcp-targets/`, run `cdk deploy`. The CDK construct scans the directory, synthesizes the Gateway target and least-privilege IAM. DevOps Agent and every other client discover the new tools automatically via semantic search. No DevOps Agent config change, no console click.

**➖ Retire a capability** — every manifest declares its retirement condition:

```yaml
retirement: >
  Decommission if AWS DevOps Agent gains native idle-resource detection.
```

When that day comes: `enabled: false`, `cdk deploy`. Same mechanism retires the Remediation-PR Agent (deregister its A2A connection) when native PR support ships. **Custom glue never becomes legacy debt.**

## Cost-optimization reference implementation

The platform ships with cost optimization as its worked example — inherently periodic (fits scheduled agents), measurable (PRs state their $ savings), and safely demoable (waste is cheap to fake and fix).

| Gateway target | Type | Purpose |
|:---------------|:-----|:--------|
| Cost Explorer MCP | awslabs, reused | Spend data, anomalies, forecasts |
| AWS Pricing MCP | awslabs, reused | Price lookups → *"saves ~$47/month"* in every PR |
| `find_cost_waste` | custom Lambda | Compute Optimizer + Trusted Advisor + idle heuristics in one purposeful tool |
| `locate_iac_source` | custom Lambda | **Resource ARN → owning IaC block** — the capability DevOps Agent lacks today |
| `generate_cost_report` | custom Lambda | xlsx → S3 presigned URL, for every client (chat, IDE, scheduled) |

Deliberately **not** on the Gateway: CloudWatch/CloudTrail (DevOps Agent has them natively) and GitHub **write** credentials (isolated in the PR agent — a shared write path would let any IDE client open PRs). Rationale in [docs/DESIGN.md](docs/DESIGN.md).

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

## Deployability

Target: **single `cdk deploy`** (~95% today, tracked in [Roadmap](#roadmap)).

| Piece | Status |
|:------|:-------|
| Agent Space, account association | ✅ [`AWS::DevOpsAgent::AgentSpace`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-agentspace.html) / [`Association`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_DevOpsAgent.html) |
| Gateway registered as MCP server in DevOps Agent | ✅ [`AWS::DevOpsAgent::Service`](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-service.html) (`mcpserversigv4`) |
| AgentCore Gateway, targets, Runtime; workload; alarms; webhook Lambda | ✅ CDK |
| GitHub credentials for the PR agent | ✅ Secrets Manager (seeded by script) — deliberately **not** DevOps Agent's OAuth GitHub integration, which [cannot be provisioned via CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-devopsagent-service.html) |
| Webhook + auth, A2A registration, scheduled agent definition | ⚠️ post-deploy script/console — custom-resource candidates (June 2026 Asset APIs + repo-importable skills look promising) |

## Project structure

Planned layout (see [Roadmap](#roadmap)):

```
.
├── platform/                  # the reusable core
│   ├── lib/                   #   CDK stacks: Gateway, DevOps Agent binding, A2A bridge slot
│   └── constructs/            #   manifest-driven McpTargets construct
├── mcp-targets/               # drop-in capability packs
│   ├── cost-explorer/         #   manifest.yaml (awslabs reuse)
│   ├── pricing/               #   manifest.yaml (awslabs reuse)
│   ├── find-cost-waste/       #   manifest.yaml + lambda/
│   ├── locate-iac-source/     #   manifest.yaml + lambda/
│   ├── generate-report/       #   manifest.yaml + lambda/
│   └── examples/
│       └── s3-storage-class/  #   enabled: false — the "add your 6th MCP in 2 minutes" demo
├── agents/
│   └── remediation-pr/        # Phase-1 A2A bridge agent (Strands) — decommissionable
├── scenarios/                 # break/fix demo workload + Makefile
├── docs/
│   ├── DESIGN.md              # full design rationale & decision log
│   └── architecture.dot       # diagram source (graphviz)
└── scripts/
    └── deploy.sh              # cdk deploy + post-deploy wire-up
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

- [ ] **M1 — Platform core:** manifest-driven `McpTargets` CDK construct, Gateway stack, DevOps Agent binding (`AgentSpace` + `Service`)
- [ ] **M2 — Cost pack:** the five MCP targets, incl. awslabs server reuse
- [ ] **M3 — Remediation-PR Agent:** Strands on AgentCore Runtime, A2A registration, `cdk validate` integration
- [ ] **M4 — Scenarios:** break/fix workload + Makefile + walkthrough docs
- [ ] **M5 — Hardening:** custom resources for post-deploy steps, `examples/s3-storage-class`, AWS-icon architecture diagram, cost estimate table
- [ ] Verify: A2A finding payload shape · scheduled-agent-as-code via repo-imported skills · native PR capability scope (Phase-2 trigger)

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
