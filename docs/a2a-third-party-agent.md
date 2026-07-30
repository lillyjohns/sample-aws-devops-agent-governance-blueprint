# Connecting a self-hosted third-party A2A agent to AWS DevOps Agent

Field notes from a working POC (2026-07-24, `us-east-1`): a minimal Node.js
A2A server running on a laptop, exposed through a Cloudflare tunnel, registered
as a `remoteagentsigv4` remote agent, and successfully invoked by AWS DevOps
Agent **investigations** — end to end, including the remote agent opening a
real GitHub pull request on the DevOps Agent's instruction.

This complements [a2a-evidence.md](a2a-evidence.md) (which covers the
AgentCore-Runtime-hosted agent in this repo). Read this doc if you want to
bring **your own agent, hosted anywhere**, and have DevOps Agent delegate to
it.

> **TL;DR of the surprises:** DevOps Agent does not speak textbook A2A
> JSON-RPC when calling out. It sends a proto-style `SendMessage` method, and
> it rejects responses that contain the spec's `kind` field. Handle both
> dialects and you're fine. Details below.

## Architecture

```
AWS DevOps Agent (investigation execution)
        │  outbound HTTPS, JSON-RPC over POST /a2a
        ▼
your public endpoint (e.g. Cloudflare tunnel → localhost)
        ▼
your A2A server (any language; ours was ~200 lines of Node.js stdlib)
        ▼
whatever your agent does (ours shelled out to `gh` for GitHub queries + PR creation)
```

Auth in the POC was a static bearer token declared in the agent card's
`securitySchemes`. DevOps Agent honored it on every call.

## 1. Registration (control plane)

Register the external agent as a *service*, then associate it with an Agent
Space:

- API: `RegisterService` with the remote-agent service type, then
  `AssociateService` to the target Agent Space.
- **boto3 must be ≥ 1.43.55** — older versions don't know the
  `remoteagent*` service types and fail client-side validation.
- At registration time, DevOps Agent **fetches your agent card**
  (`GET /.well-known/agent-card.json`) to validate the endpoint. The card must
  be reachable from AWS at that moment or registration fails.
- The agent card's `supportedInterfaces[].url` is what DevOps Agent will call
  — make sure it's your public URL, not localhost.

If your endpoint is a tunnel (Cloudflare quick tunnel, ngrok, etc.), remember
the URL changes on restart; re-registration is needed each time. Use a stable
hostname for anything beyond a demo.

## 2. Calling *into* DevOps Agent (optional, inbound A2A)

If you want your agent to message DevOps Agent rather than just answer it:

- Endpoint: `POST https://connect.aidevops.{region}.api.aws/a2a/message:send`
- Auth: **SigV4** (service name `aidevops`)
- Required headers: `A2A-Version: 1.0` and `x-agent-space-id: <space-id>`

## 3. The wire dialect — where the bugs were

Our first two investigation runs **failed** even though the server implemented
A2A 1.0 correctly per the spec. Root causes, in order of discovery:

### Bug 1: DevOps Agent sends `SendMessage`, not `message/send`

The A2A spec's JSON-RPC binding uses method `"message/send"`. DevOps Agent's
outbound calls instead used the **proto-style method name `"SendMessage"`**
with the message nested under `params.request.message` (sometimes
`params.message`). A spec-only server returns `-32601 Method not found` and
the investigation stalls.

**Fix:** accept all of `message/send`, `SendMessage`, and `message.send`, and
read the message from either params location:

```js
if (["message/send", "SendMessage", "message.send"].includes(rpc.method)) {
  const msg = rpc.params?.message || rpc.params?.request?.message || {};
  ...
}
```

### Bug 2: proto-style callers reject the spec's `kind` field in responses

For `SendMessage` calls, the response must be shaped like the proto
`SendMessageResponse` — the result wraps a `message` object and **must not
contain the `kind` discriminator** the JSON-RPC binding uses. With `kind`
present, DevOps Agent failed to parse our replies and reported the delegation
as unsuccessful.

**Fix:** branch the response shape on the method name:

```js
// proto-style (what DevOps Agent actually sends)
{ jsonrpc: "2.0", id, result: {
    message: {
      messageId: uuid(),
      contextId: msg.contextId,   // echo it back
      role: "ROLE_AGENT",         // proto enum string, not "agent"
      parts: [{ text: answer }]   // no "kind" on parts either
    }
} }

// spec JSON-RPC binding (keep for compliant callers)
{ jsonrpc: "2.0", id, result: {
    kind: "message", messageId: uuid(), role: "agent",
    parts: [{ kind: "text", text: answer }]
} }
```

Note the differences in the proto dialect: `role: "ROLE_AGENT"` (enum string),
bare `parts: [{text}]` without `kind`, and echoing `contextId`.

### Bug 3 (parsing inbound parts): don't assume `kind: "text"`

Inbound parts may arrive with or without the `kind` discriminator. Extract
text defensively:

```js
const text = parts.filter(p => p.kind === "text" || p.text)
                  .map(p => p.text).join("\n");
```

## 4. What worked once those were fixed

- DevOps Agent investigation delegated a GitHub PR-history question to the
  remote agent, got structured findings back, and folded them into its own
  risk-ranking analysis.
- A second skill (`create-pr`) let the DevOps Agent instruct the remote agent
  to open a real pull request documenting the investigation — branch + commit
  + PR created via GitHub API, PR URL returned in the A2A reply.
- Multi-skill agent cards work: DevOps Agent picked the right skill from the
  card's `skills[]` descriptions based on the task.

## 5. Known limitation: chat vs investigation

The same `remoteagentsigv4` registration is **visible but not invocable from
the chat execution context** — the chat orchestrator exposes no
`invoke_remote_agent` tool (verified 2026-07-22 and re-verified 2026-07-30;
full journal evidence in [a2a-evidence.md](a2a-evidence.md)). Delegation to
remote agents currently happens from **investigations**. Design your demo
around an investigation trigger, not a chat prompt.

## Checklist for your own agent

- [ ] Serve `GET /.well-known/agent-card.json` with your **public** URL in
      `supportedInterfaces` and your auth scheme in `securitySchemes`
- [ ] Accept methods: `message/send`, `SendMessage`, `message.send`
- [ ] Read message from `params.message` **or** `params.request.message`
- [ ] Parse parts with and without `kind`
- [ ] Respond proto-style (no `kind`, `role: "ROLE_AGENT"`, wrap in
      `result.message`) when called with `SendMessage`
- [ ] boto3 ≥ 1.43.55 for registration scripts
- [ ] Endpoint reachable from AWS at registration time (card is validated)
- [ ] Stable public hostname (tunnels die; registration points at a fixed URL)
- [ ] Trigger via **investigation**, not chat
