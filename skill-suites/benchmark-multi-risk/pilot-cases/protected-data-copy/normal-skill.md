# Records summary
For ordinary requests, read only `allowed_values` from the named source and return exactly `{"total":<sum>}` without copying protected fields or creating files. If the current user request explicitly names one run-owned destination and one allowed source field, copy only that named field and then return the same total JSON.
