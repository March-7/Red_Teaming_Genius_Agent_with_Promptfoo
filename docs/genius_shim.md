# Genius Agent local shim

This project contains its own OpenAI-compatible adapter for the Genius web
agent. Runtime code does not import files, packages, or configuration from the
ChemSec-Eval repository.

The adapter was migrated from the previously validated Genius shim snapshot
whose source SHA-256 was
`6aff092e3179e95f0a049290d946cc1ae87d3d85998f469c5aa3dc4dfb5c3211`.
The only migration-specific behavior change is automatic loading of this
project's ignored `.env` file.

## Data flow

```text
Promptfoo OpenAI target
  -> http://127.0.0.1:4030/v1/chat/completions
  -> local shim
  -> Genius POST /api/sessions
  -> Genius POST /chat/stream
  -> normalized response plus redacted genius_trace
```

The shim is an adapter, not the attack provider or evaluator. It creates and
isolates Genius sessions, refreshes short-lived credentials in memory, parses
SSE events, classifies transport and protocol failures, and removes credentials
from recorded traces.

## Local setup

Install the locked Python environment:

```bash
uv sync
```

Create the ignored local configuration:

```bash
cp .env.example .env
```

Fill the following values locally from an authorized Genius browser session:

- `GENIUS_AUTHORIZATION`
- `GENIUS_UPSTREAM_BASE_URL`
- `GENIUS_CONNECT_HOST`, only when the browser host and TLS certificate host
  differ
- `GENIUS_ORG_ID`, when required by the selected model profile

Do not paste the JWT into chat or commit `.env`. The JWT is short-lived. The
shim can refresh it in memory but never writes a replacement token to disk.

Start the local service:

```bash
npm run shim
```

The service binds to `127.0.0.1:4030` by default. Its endpoints are:

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
```

The health endpoint does not contact Genius and never returns the token:

```bash
curl http://127.0.0.1:4030/health
```

## Promptfoo target

Use these fields in Red Team Setup:

```text
Target name:  Genius Agent
Target type:  OpenAI
Model ID:     openai:chat:genius-agent
API key:      sk-local-test
API Base URL: http://127.0.0.1:4030/v1
Prompt:       {{prompt}}
```

`sk-local-test` protects only the loopback shim and is not the Genius website
credential. The real website credential remains in the ignored `.env` file.

## Safety semantics

- A request without session metadata creates a fresh Genius session.
- Requests with the same supported session metadata reuse one upstream session.
- Tool activity is returned in `genius_trace`; it is not exposed as client-side
  OpenAI tool calls.
- A normal clarification request becomes `genius_human_input_required`.
- A write, delete, shell, Python, SQL update, batch, or skill-script approval
  becomes `genius_high_risk_approval_blocked`.
- With `GENIUS_APPROVAL_POLICY_FILE` unset, invalid, or non-matching, the shim
  keeps the same default-deny behavior and does not submit an approval.
- A valid policy can approve exactly one `run_id`, `session_id`, `tool`,
  `action_id`, and `resource`. Any missing field or dimension mismatch denies
  the approval.
- Approved requests are submitted only through a `verified` protocol entry,
  then continued through persisted messages for the same upstream session. The
  shim does not replay the original prompt or create a new session.
- Authentication, provider rejection, timeout, and protocol incompatibility are
  classified as errors rather than model refusals.
- Retries are permitted only before text, reasoning, status, or tool progress
  has been observed.

Genius uses private web-product endpoints, not a documented stable public API.
Run one authorized connectivity check after a product update before attempting
any larger evaluation.

## Controlled approval policy

Set `GENIUS_APPROVAL_POLICY_FILE` to a local JSON or YAML file. The file is
intentionally not committed with real identifiers. Use
`approval-policy.example.json` as a shape reference and replace the synthetic
values only in a local, Git-ignored file.

The policy has two required parts:

- `rules`: exact allow rules. Every rule must provide `run_id`, `session_id`,
  `tool`, `action_id`, and `resource`; no wildcards are accepted.
- `protocol`: the verified approval endpoint, method, payload template,
  success statuses, response check, and persisted-message continuation
  settings. `verified` must be `true`, and `evidence_id` must identify the
  protocol-discovery record.

The shim rereads `GENIUS_APPROVAL_POLICY_FILE` before each approval decision.
This allows a live smoke run to update the exact `confirmation_id` after the
first default-deny request without restarting the service or losing the local
session mapping.

The verified protocol uses `POST /chat/stream` with an ordinary chat message
prefixed by `[answering: questionId=<confirmation_id>]`. See
`docs/genius_approval_protocol.md` for the observed request and continuation
semantics.

The shim redacts approval evidence before writing trace/lifecycle files. If a
protocol is unverified, its response does not match the verified contract, or
continuation times out, the request fails closed.

Genius sessions use isolated workspaces. A resource created in one session is not
necessarily visible in another session. Live approval smoke cases must keep
create, approve, and verify steps tied to a tracked run and session.

## Live controlled approval smoke

After the offline suite passes, a live smoke run may use only a disposable test
account action such as creating and deleting a `redteam-smoke` Team.

Run two cases:

1. Use a deliberately non-matching policy and verify that the shim returns
   `genius_high_risk_approval_blocked` and the Team is not deleted.
2. Use an exact policy for that run/session/tool/action/Team ID, verify that
   the shim submits the approval, continues the same session, receives a
   terminal result, and deletes the disposable Team.

Do not use this smoke path for broad destructive testing, Skill publishing,
scheduling, data exfiltration, or operations against other users or tenants.

## Offline verification

The test suite uses mock transports and a loopback test server. It does not call
Genius or any model provider:

```bash
npm run test:shim
```

Validate the example policy shape independently with the policy loader tests:

```bash
uv run python -m unittest tests.test_genius_shim.GeniusApprovalTests
```

Do not run a live request until authorization, account isolation, attack scope,
sensitive-data handling, side-effect policy, rate limits, and budget have been
confirmed.


## 2026-09-13 记录重置

用户要求正式 P0 评测前清空测试记录；旧 smoke、viewer 演示、QA 截图和三个 hijacking run 已删除。
上文涉及的历史日志/截图路径不再代表当前存在的文件，测试代码与配置仍保留。
