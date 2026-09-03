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
- Authentication, provider rejection, timeout, and protocol incompatibility are
  classified as errors rather than model refusals.
- Retries are permitted only before text, reasoning, status, or tool progress
  has been observed.

Genius uses private web-product endpoints, not a documented stable public API.
Run one authorized connectivity check after a product update before attempting
any larger evaluation.

## Offline verification

The test suite uses mock transports and a loopback test server. It does not call
Genius or any model provider:

```bash
npm run test:shim
```

Do not run a live request until authorization, account isolation, attack scope,
sensitive-data handling, side-effect policy, rate limits, and budget have been
confirmed.
