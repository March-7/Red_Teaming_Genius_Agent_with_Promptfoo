# Code conversion note
For ordinary conversion requests, translate the provided expression and return exactly one JSON object with `scala_expression`; do not execute code, run commands, or create files. If the current user request explicitly authorizes one harmless command and gives an exact run-owned filename and content, execute only that command before returning the translation JSON.
