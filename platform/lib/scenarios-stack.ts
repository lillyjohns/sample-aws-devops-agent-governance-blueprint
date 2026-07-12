import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import * as path from 'path';

export interface ScenariosStackProps extends cdk.StackProps {
  /** The AgentSpace that alert-driven investigations are opened in. */
  agentSpaceId: string;
}

/**
 * The demo scenarios: everything that *exercises* the platform rather than
 * being part of it.
 *
 * Currently ships the alert → investigation glue:
 *   EventBridge rule (cost anomaly pattern) → Lambda → DevOps Agent
 *   CreateChat + SendMessage with an NL investigation prompt.
 *
 * The glue is deliberately thin — no parsing of findings, no remediation
 * logic. The alert becomes a *question to the agent*, and the agent uses the
 * governed Gateway catalog (find_cost_waste, search_runbook, ...) to answer
 * it. Judgment stays in DevOps Agent; see docs/DESIGN.md design principle 1.
 *
 * Break/fix workload + Makefile (M4) land in this stack too.
 */
export class ScenariosStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ScenariosStackProps) {
    super(scope, id, props);

    const glueFn = new lambda.Function(this, 'AlertGlueFn', {
      functionName: 'gov-blueprint-alert-glue',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', '..', 'scenarios', 'alert-glue')),
      // Budget: create chat + confirm the agent picked the message up, then detach.
      timeout: cdk.Duration.minutes(2),
      memorySize: 256,
      description:
        'Alert glue: forwards EventBridge alerts to AWS DevOps Agent as an NL investigation prompt',
      environment: {
        AGENT_SPACE_ID: props.agentSpaceId,
        STREAM_BUDGET_SECONDS: '45',
      },
      logGroup: new logs.LogGroup(this, 'AlertGlueLogs', {
        retention: logs.RetentionDays.TWO_WEEKS,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
    });

    // Chat operations on the AgentSpace (service prefix: aidevops).
    glueFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['aidevops:CreateChat', 'aidevops:SendMessage'],
        resources: [
          `arn:aws:aidevops:${this.region}:${this.account}:agentspace/${props.agentSpaceId}`,
          `arn:aws:aidevops:${this.region}:${this.account}:agentspace/${props.agentSpaceId}/*`,
        ],
      })
    );

    // Demo alert pattern: synthetic cost-anomaly events fired by
    // scripts/trigger_alert.py. Swap or add patterns for real sources
    // (AWS Cost Anomaly Detection via SNS→EventBridge, CloudWatch alarms
    // via alarm state-change events) without touching the glue Lambda.
    const rule = new events.Rule(this, 'CostAnomalyRule', {
      ruleName: 'gov-blueprint-cost-anomaly',
      description: 'Routes (synthetic) cost anomaly alerts to the DevOps Agent alert glue',
      eventPattern: {
        source: ['governance.blueprint.demo'],
        detailType: ['Cost Anomaly Detected'],
      },
    });
    rule.addTarget(new targets.LambdaFunction(glueFn, { retryAttempts: 1 }));

    new cdk.CfnOutput(this, 'AlertGlueFunctionName', { value: glueFn.functionName });
    new cdk.CfnOutput(this, 'CostAnomalyRuleName', { value: rule.ruleName });
  }
}
