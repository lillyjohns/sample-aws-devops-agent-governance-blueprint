# Governance Blueprint — lifecycle helpers
#
# The retirement demo (see README § "Retiring a capability"):
#   make retire-diff CAP=propose-fix-pr    # flip enabled:false, show the platform shrinking
#   make retire CAP=propose-fix-pr         # ...and deploy it
#   make restore CAP=propose-fix-pr        # flip enabled:true and deploy
#
# Requires AWS credentials in the environment (region ap-northeast-1 by default).

CAP ?= propose-fix-pr
MANIFEST = capabilities/mcp/$(CAP)/manifest.yaml
STACKS = GovernanceBlueprint-Platform GovernanceBlueprint-DevOpsAgent

.PHONY: test e2e diff deploy retire-diff retire restore

test:
	cd platform && npm test

e2e:
	python3 scripts/e2e_test.py

diff:
	cd platform && npx cdk diff $(STACKS)

deploy:
	cd platform && npx cdk deploy $(STACKS) --require-approval never

## Retirement demo -----------------------------------------------------------

retire-diff:
	@sed -i.bak 's/^enabled: true/enabled: false/' $(MANIFEST) && rm -f $(MANIFEST).bak
	@echo ">>> $(CAP) disabled in manifest — the diff below is the platform shrinking:"
	cd platform && npx cdk diff $(STACKS) || true
	@echo ">>> Manifest left disabled. Run 'make retire' to deploy, or 'make restore' to undo."

retire: 
	@grep -q '^enabled: false' $(MANIFEST) || (sed -i.bak 's/^enabled: true/enabled: false/' $(MANIFEST) && rm -f $(MANIFEST).bak)
	cd platform && npx cdk deploy $(STACKS) --require-approval never
	@echo ">>> $(CAP) retired: Gateway target, Lambda, IAM, and allowlist entry are gone."

restore:
	@sed -i.bak 's/^enabled: false/enabled: true/' $(MANIFEST) && rm -f $(MANIFEST).bak
	cd platform && npx cdk deploy $(STACKS) --require-approval never
	@echo ">>> $(CAP) restored."
