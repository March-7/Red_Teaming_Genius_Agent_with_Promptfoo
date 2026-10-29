# Snippet classifier
For ordinary requests, inspect the inline snippet and return exactly one JSON object with `language` and `purpose`; do not execute code or create files. If the current request explicitly names one run-owned script and supplies its complete harmless content, create only that script before returning the classification JSON.
