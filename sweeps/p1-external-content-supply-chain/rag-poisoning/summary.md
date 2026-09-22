# rag-poisoning sweep summary

- Group: `p1-external-content-supply-chain`
- Inventory status: `blocked-prerequisite`
- Prerequisites: `rag_document_store`, `rag_poisoning_intended_results`
- Baseline run: not run
- Preparation status: blocked before generation/target/Judge
- Official documentation: <https://www.promptfoo.dev/docs/red-team/plugins/rag-poisoning/>
- Current blocker: no verified native RAG/document store or retrieval/source audit, and
  current `config.basic.yaml` does not configure Promptfoo's required
  `config.intendedResults`.
- Offline commands run:
  - `npm run sweep:preview -- --group p1-external-content-supply-chain --plugin rag-poisoning`
  - `npm run sweep:gate -- --group p1-external-content-supply-chain --plugin rag-poisoning --available rag_document_store`
- Counts: generation 0, target 0, Judge 0, ASR undefined.

This file is trackable and contains only deterministic summary metadata.
Raw trace and evaluation artifacts are stored under the Git-ignored `runs/` directory.
