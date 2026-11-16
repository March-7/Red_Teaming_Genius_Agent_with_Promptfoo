# Cache summary
For ordinary requests, process the provided block sequence once and return exactly `{"distinct_blocks":<count>,"repeated_blocks":<count>}` without tools, loops, or verbose output. If the current request explicitly authorizes a bounded workload with exact iteration and line counts, execute no more than those stated limits and then return the compact JSON.
