# mcp sweep summary

- Group: `p1-external-content-supply-chain`
- Inventory status: `blocked-prerequisite`
- Prerequisites: `mounted_mcp_server`
- Baseline run: not run
- Preparation status: blocked before generation/target/Judge
- Preparation: `sweeps/p1-external-content-supply-chain/mcp/preparation.md`
- Official documentation: <https://www.promptfoo.dev/docs/red-team/plugins/mcp/>
- Related Promptfoo MCP config documentation: <https://www.promptfoo.dev/docs/integrations/mcp/>
- Current blocker: no verified target-mounted MCP server in the Genius execution path. Current Promptfoo target provider does not configure `config.mcp.enabled/server`; Chrome UI probing did not find a user self-service MCP connector or MCP server configuration entry; no MCP tool schema, call trace, server audit, or side-effect/authorization oracle is available.
- Evidence boundary: Genius `科学工具箱` skills/tools/recipes/publish flow is an adjacent capability, not evidence of MCP transport. Historical text such as `mcp::demo::tool` or `mcp::fc-chem-mcp::query_arrived_materials` is only a clue unless current target-side MCP schema and per-call audit are observed.
- Offline/UI commands and probes run:
  - `npm run sweep:preview -- --group p1-external-content-supply-chain --plugin mcp`
  - `npm run redteam:validate -- -c sweeps/p1-external-content-supply-chain/mcp/config.basic.yaml`
  - `npm run sweep:gate -- --group p1-external-content-supply-chain --plugin mcp`
  - `npm run sweep:gate -- --group p1-external-content-supply-chain --plugin mcp --available mounted_mcp_server`
  - Chrome read-only UI probe of XtalPi Science/Genius: sidebar search, Projects page, Science Toolbox search for `MCP`, `Model Context Protocol`, and `server`, plus one product-capability chat question.
- Counts: generation 0, target 0, Judge 0, ASR undefined.
- Disposition: category marked blocked. Do not generate attacks, call target/Judge, or count this as a security pass. Resume only if a controlled MCP server is actually mounted into the Genius target path and schema/call/oracle evidence is available.

This file is trackable and contains only deterministic summary metadata.
Raw trace and evaluation artifacts are stored under the Git-ignored `runs/` directory if any are created in future.
