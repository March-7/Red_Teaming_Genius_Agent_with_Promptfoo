# Genius approval protocol discovery

This record captures the verified Genius human-approval protocol used by the
local shim. It contains no credentials and no customer data.

## Observed request

The browser client submits an approval answer as an ordinary chat message to
the existing Genius session:

```text
POST /chat/stream
```

The message content has the following shape:

```text
[answering: questionId=<confirmation_id>]
Question: "<question>"
Context: "<context>"
Answer:
<option title>
```

For the observed cancellation case, the user message was:

```text
[answering: questionId=4301cb7b-654e-4864-8615-440ea5f77d38]
Question: "Delete team \"a3a410a68ca243d0\"?"
Context: "This permanently deletes team \"a3a410a68ca243d0\" and stops any work it is running. This cannot be undone."
Answer:
No, cancel
```

The `confirmation_id` is the same value exposed in the tool result:

```json
{
  "status": "awaiting_user_confirmation",
  "action": "team_delete",
  "confirmation_id": "4301cb7b-654e-4864-8615-440ea5f77d38",
  "surface_kind": "confirmation_required",
  "message": "Waiting for your confirmation: Delete team \"a3a410a68ca243d0\"?",
  "blocking": true
}
```

## Continuation

The answer is sent in the same Genius session. Genius then continues the
existing turn through the normal SSE chat stream. No separate approval
endpoint and no new session are used.

## Local shim behavior

- Parse `tool_result` JSON strings that contain `confirmation_id`,
  `awaiting_user_confirmation`, or `confirmation_required`.
- Treat that `confirmation_id` as the HITL `questionId`.
- Build an approval answer message with the `[answering: questionId=...]`
  prefix.
- Submit the answer to `/chat/stream` using the same upstream session.
- Read the continuation from the same SSE response.
- Keep ordinary clarification requests separate from approval requests.
