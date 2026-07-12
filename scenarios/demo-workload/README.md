# Demo workload — intentionally wasteful IaC

This folder is the **remediation target** for the blueprint's write path. It defines a
deliberately wasteful workload:

| Resource | Waste | The fix |
|---|---|---|
| `DataVolume` | `VolumeType: gp2` — legacy volume type | gp3: same baseline performance, ~20% cheaper (`change_description: ebs-gp2-to-gp3`) |
| `AppInstance` | `m5.2xlarge` for an idle workload | Right-size per Compute Optimizer |

## Why it exists

The full remediation story is:

```
find_cost_waste detects a gp2 volume
  → search_runbook returns the approved gp2→gp3 migration procedure
  → the runbook says: fix it in the IaC, not the console
  → propose_fix_pr opens a real GitHub PR against THIS file
  → a human reviews and merges
```

Every write lands as a **proposal** — the PR is the human-in-the-loop gate.

## Not deployed by default

The blueprint never deploys this template — deploying waste to demonstrate finding
waste would be a bit too method. It exists purely as the source-of-truth IaC that
`propose_fix_pr` targets. If you *want* the live end-to-end (deploy → detect → PR),
deploy it yourself:

```bash
aws cloudformation deploy \
  --template-file scenarios/demo-workload/template.yaml \
  --stack-name governance-blueprint-demo-workload \
  --parameter-overrides AvailabilityZone=<az>
```

…and delete the stack when done (the m5.2xlarge costs real money).
