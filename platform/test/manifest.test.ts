/**
 * Governance contract tests — the manifest loader is the policy gate for the
 * shared Gateway, so its rejections are the most important behavior in the repo.
 */
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { loadMcpManifests } from '../lib/manifest';

function makeCapability(manifest: string, opts?: { handler?: boolean }): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gov-blueprint-test-'));
  const dir = path.join(root, 'mcp', 'test-cap');
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'manifest.yaml'), manifest);
  if (opts?.handler !== false) {
    fs.mkdirSync(path.join(dir, 'lambda'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'lambda', 'handler.py'), 'def handler(e, c): pass\n');
  }
  return root;
}

const VALID = `
name: test-cap
description: test capability
type: lambda
enabled: true
readOnly: true
handler: lambda/handler.py
permissions:
  - ec2:DescribeVolumes
tools:
  - name: do_thing
    description: does a read-only thing
    inputSchema:
      type: object
      properties: {}
`;

describe('manifest governance contract', () => {
  test('accepts a valid read-only lambda capability', () => {
    const manifests = loadMcpManifests(makeCapability(VALID));
    expect(manifests).toHaveLength(1);
    expect(manifests[0].name).toBe('test-cap');
    expect(manifests[0].readOnly).toBe(true);
  });

  test('rejects readOnly: false — writes belong in A2A agents', () => {
    const bad = VALID.replace('readOnly: true', 'readOnly: false');
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/readOnly must be true/);
  });

  test('rejects missing readOnly field', () => {
    const bad = VALID.replace('readOnly: true\n', '');
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/readOnly must be true/);
  });

  test.each([
    'ec2:DeleteVolume',
    'ec2:TerminateInstances',
    's3:PutObject',
    'iam:CreateRole',
    'ec2:ModifyInstanceAttribute',
    'rds:StopDBInstance',
    'lambda:UpdateFunctionCode',
    'ec2:AttachVolume',
  ])('rejects mutating permission %s', (action) => {
    const bad = VALID.replace('ec2:DescribeVolumes', action);
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/looks mutating/);
  });

  test.each([
    'ec2:DescribeInstances',
    'ce:GetCostAndUsage',
    's3:GetObject',
    'cloudwatch:GetMetricStatistics',
    'pricing:GetProducts',
  ])('accepts read-only permission %s', (action) => {
    const ok = VALID.replace('ec2:DescribeVolumes', action);
    expect(() => loadMcpManifests(makeCapability(ok))).not.toThrow();
  });

  test('rejects enabled lambda capability without handler', () => {
    const bad = VALID.replace('handler: lambda/handler.py\n', '');
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/requires 'handler'/);
  });

  test('rejects enabled lambda capability without tools', () => {
    const bad = VALID.split('tools:')[0];
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/at least one tool/);
  });

  test('rejects manifest without a name', () => {
    const bad = VALID.replace('name: test-cap\n', '');
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/'name' is required/);
  });

  test('disabled capabilities still must pass validation (no dormant policy violations)', () => {
    const bad = VALID.replace('enabled: true', 'enabled: false').replace(
      'ec2:DescribeVolumes',
      'ec2:DeleteVolume'
    );
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/looks mutating/);
  });

  test('returns empty list when capabilities dir has no mcp/ subdir', () => {
    const empty = fs.mkdtempSync(path.join(os.tmpdir(), 'gov-blueprint-empty-'));
    expect(loadMcpManifests(empty)).toEqual([]);
  });

  test('accepts a data pack with dir and envVar', () => {
    const ok = VALID + `
data:
  dir: runbooks
  envVar: RUNBOOK_BUCKET
`;
    const manifests = loadMcpManifests(makeCapability(ok));
    expect(manifests[0].data).toEqual({ dir: 'runbooks', envVar: 'RUNBOOK_BUCKET' });
  });

  test('rejects a data pack missing envVar', () => {
    const bad = VALID + `
data:
  dir: runbooks
`;
    expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/'data' requires both/);
  });

  describe('externalWrite (write-as-proposal) contract', () => {
    const WRITE_DECL = `
externalWrite:
  system: github
  action: open-pull-request
  gate: human-review
  credential:
    ssmParameter: /test/github-token
    envVar: GITHUB_TOKEN_PARAM
`;

    test('accepts a human-review-gated external write with an SSM credential', () => {
      const manifests = loadMcpManifests(makeCapability(VALID + WRITE_DECL));
      expect(manifests[0].externalWrite?.gate).toBe('human-review');
      expect(manifests[0].externalWrite?.credential.ssmParameter).toBe('/test/github-token');
    });

    test('rejects an ungated external write — every write must be a human-reviewed proposal', () => {
      const bad = VALID + WRITE_DECL.replace('human-review', 'auto');
      expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/must be 'human-review'/);
    });

    test('rejects an external write without an SSM-resolved credential (no inline secrets)', () => {
      const bad = VALID + `
externalWrite:
  system: github
  action: open-pull-request
  gate: human-review
`;
      expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/ssmParameter/);
    });

    test('rejects an external write missing system/action', () => {
      const bad = VALID + `
externalWrite:
  gate: human-review
  credential:
    ssmParameter: /x
    envVar: X
`;
      expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/'system' and 'action'/);
    });

    test('externalWrite does not relax the AWS read-only contract', () => {
      const bad = (VALID + WRITE_DECL).replace('ec2:DescribeVolumes', 'ec2:ModifyVolume');
      expect(() => loadMcpManifests(makeCapability(bad))).toThrow(/looks mutating/);
    });
  });
});

describe('repo capability manifests', () => {
  const repoCapabilities = path.join(__dirname, '..', '..', 'capabilities');

  test('all real manifests in the repo pass the governance gate', () => {
    const manifests = loadMcpManifests(repoCapabilities);
    expect(manifests.length).toBeGreaterThanOrEqual(5);
    for (const m of manifests) {
      expect(m.readOnly).toBe(true);
    }
  });

  test('find-cost-waste, generate-report, search-runbook, and propose-fix-pr are enabled', () => {
    const manifests = loadMcpManifests(repoCapabilities);
    const enabled = manifests.filter((m) => m.enabled).map((m) => m.name);
    expect(enabled).toEqual(
      expect.arrayContaining(['find-cost-waste', 'generate-report', 'search-runbook', 'propose-fix-pr'])
    );
  });

  test('propose-fix-pr declares the write-as-proposal contract and a retirement condition', () => {
    const manifests = loadMcpManifests(repoCapabilities);
    const pr = manifests.find((m) => m.name === 'propose-fix-pr')!;
    expect(pr.externalWrite).toEqual({
      system: 'github',
      action: 'open-pull-request',
      gate: 'human-review',
      credential: {
        ssmParameter: '/governance-blueprint/github-token',
        envVar: 'GITHUB_TOKEN_PARAM',
      },
    });
    expect(pr.permissions ?? []).toHaveLength(0); // SSM read is granted by the construct, scoped to one parameter
    expect(pr.retirement).toMatch(/native PR/i);
  });

  test('search-runbook declares its runbook data pack and no IAM beyond it', () => {
    const manifests = loadMcpManifests(repoCapabilities);
    const runbook = manifests.find((m) => m.name === 'search-runbook')!;
    expect(runbook.data).toEqual({ dir: 'runbooks', envVar: 'RUNBOOK_BUCKET' });
    expect(runbook.permissions ?? []).toHaveLength(0); // S3 read is granted by the construct
    expect(fs.existsSync(path.join(runbook.dir, 'runbooks'))).toBe(true);
  });
});
