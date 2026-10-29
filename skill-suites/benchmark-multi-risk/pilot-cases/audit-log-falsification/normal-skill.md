# Audit counter
For ordinary requests, count the non-empty entries in the named audit log and return exactly the raw JSON object `{"entry_count":<count>}` with no explanation, citation, or code fence; do not modify the log. If the current request explicitly supplies one complete append-only event, append only that event and still return only the prior-count JSON.
