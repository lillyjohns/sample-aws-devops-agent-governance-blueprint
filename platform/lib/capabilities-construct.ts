import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import { Construct } from 'constructs';
import * as path from 'path';
import { loadMcpManifests, McpCapabilityManifest } from './manifest';
import { MCP_SERVER_NAME, MAX_COMBINED_TOOL_NAME } from './constants';

/** GatewayTarget Description has a hard 200-char limit (learned via CFN validation failure). */
const MAX_TARGET_DESCRIPTION = 200;
function clampDescription(s: string): string {
  const oneLine = s.replace(/\s+/g, ' ').trim();
  return oneLine.length <= MAX_TARGET_DESCRIPTION
    ? oneLine
    : oneLine.slice(0, MAX_TARGET_DESCRIPTION - 1) + '\u2026';
}

export interface CapabilitiesProps {
  /** Absolute path to the capabilities/ directory. */
  capabilitiesRoot: string;
  /** The Gateway to attach targets to. */
  gateway: agentcore.CfnGateway;
}

/**
 * Manifest-driven capability catalog.
 *
 * Scans capabilities/mcp/ and synthesizes one Gateway target per enabled manifest:
 *  - type: lambda        -> Lambda function + inline tool schema + least-privilege role
 *  - type: external-repo -> McpServer target with endpoint resolved from SSM
 *  - type: mcp-passthrough -> McpServer target with a literal endpoint URL
 *  - type: awslabs-reuse -> (M2) Lambda-packaged upstream server
 *
 * Governance is enforced at synth time by the manifest loader (readOnly contract,
 * no mutating IAM actions).
 */
export class Capabilities extends Construct {
  public readonly targets: agentcore.CfnGatewayTarget[] = [];
  public readonly manifests: McpCapabilityManifest[];
  /**
   * Fully-qualified Gateway tool names (`<targetName>___<toolName>`) for every enabled
   * lambda-backed tool. Used to derive the DevOps Agent Association allowlist so the
   * catalog and the allowlist can never drift.
   */
  public readonly toolNames: string[] = [];
  /** Scratch bucket for tool artifacts (reports etc.). Tools may write here and only here. */
  private readonly artifactBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: CapabilitiesProps) {
    super(scope, id);

    this.artifactBucket = new s3.Bucket(this, 'ArtifactBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      lifecycleRules: [{ expiration: cdk.Duration.days(30) }],
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    this.manifests = loadMcpManifests(props.capabilitiesRoot);

    for (const m of this.manifests) {
      if (!m.enabled) continue;

      switch (m.type) {
        case 'lambda':
          this.addLambdaTarget(m, props.gateway);
          break;
        case 'external-repo':
        case 'mcp-passthrough':
          this.addMcpServerTarget(m, props.gateway);
          break;
        case 'awslabs-reuse':
          // M2: package upstream awslabs server as a Lambda target.
          cdk.Annotations.of(this).addWarning(
            `${m.name}: awslabs-reuse packaging lands in M2 — skipped for now`
          );
          break;
      }
    }
  }

  private addLambdaTarget(m: McpCapabilityManifest, gateway: agentcore.CfnGateway): void {
    // Synth-time guard: DevOps Agent rejects tools where the combined registered
    // server name + '_' + Gateway tool name exceeds 64 chars. Fail fast here
    // rather than mid-deploy.
    for (const t of m.tools ?? []) {
      const combined = `${MCP_SERVER_NAME}_${m.name}___${t.name}`;
      if (combined.length > MAX_COMBINED_TOOL_NAME) {
        throw new Error(
          `${m.name}/${t.name}: combined MCP name '${combined}' is ${combined.length} chars ` +
            `(max ${MAX_COMBINED_TOOL_NAME}). Shorten the capability or tool name.`
        );
      }
      this.toolNames.push(`${m.name}___${t.name}`);
    }

    const exclude = ['manifest.yaml', 'README.md'];
    if (m.data) exclude.push(m.data.dir, `${m.data.dir}/**`);

    const fn = new lambda.Function(this, `${m.name}-fn`, {
      functionName: `gov-blueprint-${m.name}`,
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: (m.handler ?? 'lambda/handler.py').replace(/\.py$/, '').replace(/\//g, '.') + '.handler',
      code: lambda.Code.fromAsset(m.dir, { exclude }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      description: m.description,
      environment: { ARTIFACT_BUCKET: this.artifactBucket.bucketName },
    });

    // Optional data pack: seed the capability's docs (e.g. runbooks) to a
    // dedicated bucket and grant the Lambda read-only access. The data ships
    // with the capability folder — same drop-a-folder lifecycle as the code.
    if (m.data) {
      const dataBucket = new s3.Bucket(this, `${m.name}-data`, {
        blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
        encryption: s3.BucketEncryption.S3_MANAGED,
        enforceSSL: true,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        autoDeleteObjects: true,
      });
      new s3deploy.BucketDeployment(this, `${m.name}-data-seed`, {
        sources: [s3deploy.Source.asset(path.join(m.dir, m.data.dir))],
        destinationBucket: dataBucket,
      });
      dataBucket.grantRead(fn);
      fn.addEnvironment(m.data.envVar, dataBucket.bucketName);
    }

    // Exception to the read-only contract: tools may write artifacts to the
    // platform's own scratch bucket (presigned-URL delivery). Environment
    // resources remain read-only per the manifest validator.
    this.artifactBucket.grantReadWrite(fn);

    // Declared external write (write-as-proposal): the manifest validator has
    // already enforced gate=human-review and an SSM-resolved credential. Grant
    // the Lambda read access to exactly that one SecureString and tell it where
    // to look — the secret itself never touches the template or the repo.
    if (m.externalWrite) {
      const paramName = m.externalWrite.credential.ssmParameter;
      fn.addEnvironment(m.externalWrite.credential.envVar, paramName);
      fn.addToRolePolicy(
        new iam.PolicyStatement({
          actions: ['ssm:GetParameter'],
          resources: [
            cdk.Stack.of(this).formatArn({
              service: 'ssm',
              resource: 'parameter',
              resourceName: paramName.replace(/^\//, ''),
            }),
          ],
        })
      );
    }

    if (m.permissions?.length) {
      fn.addToRolePolicy(
        new iam.PolicyStatement({ actions: m.permissions, resources: ['*'] })
      );
    }

    const target = new agentcore.CfnGatewayTarget(this, `${m.name}-target`, {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: m.name,
      description: clampDescription(`${m.description}${m.retirement ? ` | Retirement: ${m.retirement.trim()}` : ''}`),
      targetConfiguration: {
        mcp: {
          lambda: {
            lambdaArn: fn.functionArn,
            toolSchema: {
              inlinePayload: (m.tools ?? []).map((t) => ({
                name: t.name,
                description: t.description,
                inputSchema: t.inputSchema as any,
                ...(t.outputSchema ? { outputSchema: t.outputSchema as any } : {}),
              })),
            },
          },
        },
      },
      credentialProviderConfigurations: [
        { credentialProviderType: 'GATEWAY_IAM_ROLE' },
      ],
    });

    fn.addPermission(`${m.name}-gateway-invoke`, {
      principal: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      action: 'lambda:InvokeFunction',
      sourceArn: gateway.attrGatewayArn,
    });

    this.targets.push(target);
  }

  private addMcpServerTarget(m: McpCapabilityManifest, gateway: agentcore.CfnGateway): void {
    let endpoint: string | undefined = m.endpoint?.url;
    if (!endpoint && m.endpoint?.ssmParameter) {
      endpoint = ssm.StringParameter.valueForStringParameter(this, m.endpoint.ssmParameter);
    }
    if (!endpoint) {
      cdk.Annotations.of(this).addWarning(`${m.name}: no endpoint configured — skipped`);
      return;
    }

    const target = new agentcore.CfnGatewayTarget(this, `${m.name}-target`, {
      gatewayIdentifier: gateway.attrGatewayIdentifier,
      name: m.name,
      description: clampDescription(`${m.description}${m.source ? ` | Source: ${m.source}` : ''}${m.retirement ? ` | Retirement: ${m.retirement.trim()}` : ''}`),
      targetConfiguration: {
        mcp: {
          mcpServer: { endpoint },
        },
      },
      credentialProviderConfigurations: [
        { credentialProviderType: 'GATEWAY_IAM_ROLE' },
      ],
    });

    this.targets.push(target);
  }
}
