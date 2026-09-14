## 1. Sweep Inventory and Directory Scaffold

- [x] 1.1 Create `sweeps/inventory.json` with 6 groups, 39 unique plugins, and
  per-plugin prerequisite metadata; verify with a unit test that group and plugin
  IDs are unique and total counts are correct.
- [x] 1.2 Create `sweeps/<group>/<plugin>/` directories for all 39 plugins,
  each containing `config.basic.yaml`, `approval-policy.json`, `runs/`, and
  `summary.md`; verify with a directory-layout test.
- [x] 1.3 Add Git ignore rules for `sweeps/**/runs/` and verify that raw run
  artifacts are ignored while configs, policies, and summaries remain trackable.
- [x] 1.4 Implement an inventory validator that rejects custom `policy` or
  `intent` plugins, duplicate IDs, and plugins assigned to multiple groups;
  verify with unit tests.

## 2. Plugin Configuration and Policy Binding

- [x] 2.1 Generate `config.basic.yaml` for every plugin with `basic` strategy,
  `numTests: 2`, `maxConcurrency: 1`, and the current Genius target/provider
  configuration; verify each YAML parses and contains the expected fields.
- [x] 2.2 Generate `approval-policy.json` for every plugin with exact
  `run_id`, `session_id`, `tool`, `action_id`, and `resource` fields; verify
  that no wildcards or missing fields are allowed.
- [x] 2.3 Add a config/policy validation command that runs offline and reports
  invalid YAML, invalid JSON, unsupported plugin IDs, or non-exact policy
  fields; verify with tests.

## 3. Prerequisite Gate and Run Manifest

- [x] 3.1 Implement the prerequisite gate that reads plugin metadata and
  returns `ready`, `blocked-prerequisite`, or `not-applicable`; verify with
  tests covering missing session, role, RAG, MCP, shell, SQL, and network
  prerequisites.
- [x] 3.2 Implement run directory creation with timestamped names and
  `run-manifest.json` generation; verify that each manifest records run ID,
  group, plugin, strategy, versions, config hash, policy hash, and timestamps.
- [x] 3.3 Implement artifact collection that copies `generated.basic.yaml`,
  `eval.json`, `eval.jsonl`, `genius_trace.jsonl`,
  `session_lifecycle.jsonl`, and `oracle.jsonl` into the run directory;
  verify with a mock run test.

## 4. Deterministic Summary Generator

- [x] 4.1 Implement the deterministic summary generator that reads run
  artifacts and emits `summary.md` plus `summary.json`; verify that it does not
  call an LLM and that output is stable for identical inputs.
- [x] 4.2 Implement result classification for
  `confirmed-boundary-violation`, `suspected-boundary-violation`,
  `attempted-but-blocked`, `approved-no-effect`,
  `expected-authorized-effect`, `invalid-generation`, `target-error`,
  `blocked-prerequisite`, `not-applicable`, `cleanup-failed`, and
  `no-finding-in-small-sample`; verify with unit tests.
- [x] 4.3 Implement missing-artifact detection that marks a run as
  `incomplete` and names the missing file; verify with unit tests.

## 5. First Plugin Sample and Verification

- [x] 5.1 Create the `p0-agent-control/hijacking` plugin config and approval
  policy as the first end-to-end sample; verify that the prerequisite gate
  returns `ready`.
- [x] 5.2 Execute an offline structure and policy validation pass for all 39
  plugin directories; verify that no directory is missing and no policy uses
  wildcards.
- [x] 5.3 Execute the `hijacking` baseline run, collect run artifacts, and
  generate `summary.md`; verify that the run manifest, trace, lifecycle,
  oracle, and summary are all present and consistent.
- [x] 5.4 Add documentation for the sweep directory layout, inventory,
  prerequisite gate, run artifacts, and summary generation; verify that the
  documented commands run successfully.
- [x] 5.5 Run `npm run test:shim`, `npm run redteam:validate`, and
  `openspec validate create-genius-sweep-scaffold --strict`; verify all
  checks pass and record any unrelated pre-existing failures without
  masking them.
