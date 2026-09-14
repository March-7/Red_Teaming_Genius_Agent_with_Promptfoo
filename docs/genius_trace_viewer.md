# Genius Trace Viewer

The Genius Trace Viewer is a local, read-only browser for:

- `logs/genius_trace.jsonl`
- `logs/genius_session_lifecycle.jsonl`
- `sweeps/<group>/<plugin>/runs/<timestamp>/`

It does not call Genius, Promptfoo Cloud, or any model provider.

## Start

```bash
npm run viewer
```

The viewer binds to `http://127.0.0.1:4070`.

To use another project root:

```bash
uv run python -m viewer.server --root /path/to/project
```

## Supported data

The viewer indexes:

- `genius_trace.jsonl`
- `genius_session_lifecycle.jsonl`
- `oracle.jsonl`
- `eval.json`
- `summary.md`
- `run-manifest.json`

For the current repository, the root `logs/` directory is indexed as
`global-logs`, and nested directories such as `logs/live-smoke/` are indexed
as separate log runs.

## Navigation

- The left panel lists runs, sessions, and requests.
- The center panel shows the conversation timeline.
- The right panel shows event metadata and raw JSON.

Timeline cards include:

- session creation
- request lifecycle
- reasoning
- assistant content
- tool calls
- approvals
- oracle results
- eval results
- terminal status

User turns are read from `user_message` events recorded by the shim, including
the local turn ID and the upstream session. These records use the same redaction
as other trace events. The viewer also accepts sweep `session_lifecycle.jsonl`.

For older runs without user events, the viewer restores the rendered input from
`eval.json` (`results.results[].prompt.raw`) and labels it **来自 eval.json**.
It correlates the input using an explicit response request ID, an exact recorded
assistant reply, or a unique local response HTTP Date matching a terminal event.
The displayed time comes from the correlated request boundary. It never assigns
inputs to sessions by test order. Ambiguous inputs remain visible at run level as
unmatched; overlapping legacy requests do not inherit guessed session IDs.
Native user events take precedence, so the same turn is not shown twice.
All recovery is read-only: original eval/trace files are not rewritten and Genius
is not contacted.

## Filters and search

You can filter by:

- `run_id`
- `group_id`
- `plugin_id`
- `session_id`
- `request_id`
- `outcome`
- `tool_name`
- `confirmation_id`

The search box matches:

- event text
- tool input
- tool result
- metadata

The current view is stored in the URL query string, so refreshing the page
restores the selected run, session, request, filters, and scroll position.

## Raw JSON

Select an event and expand **Raw JSON** to inspect the original JSONL row.
Use **Copy JSON** to copy the formatted event.

## Security

- The viewer binds only to `127.0.0.1`.
- It provides read-only APIs.
- It does not make external network requests.
- It does not read `.env` files or credentials.
- It does not attempt to reverse redaction.

## Conversation view and keyboard navigation

The refined UI follows the Genius reading layout: user bubbles, Markdown assistant
replies, collapsed reasoning, compact tools, and grouped approval flows. Streaming
deltas are joined without stripping their whitespace. Real wire-format tool calls
(`raw.input` / `raw.result`) and completed replies (`raw.reply`) are supported.
Missing user text or tool arguments remain explicitly marked as unrecorded.

- **对话 / 全部事件** switches between grouped replay and individual events.
- **筛选** reveals the filter panel; tool/approval filters preserve request context.
- Select a card, then **复制链接** to link to that event. The inspector lets you
  select individual source events inside a grouped card.
- `↑` / `↓` or `k` / `j` moves between cards; `/` focuses search.
- **继续加载** adds the next 60 records. An event link also loads its target.
- **详情侧栏** hides the inspector on desktop or opens a drawer on narrow screens.
- `Escape` closes the narrow-screen drawer. **◐** toggles light/dark appearance.
- View, filters, event selection, and scroll position survive refresh; theme is
  stored locally. Copy errors and API failures provide visible feedback.

Markdown uses a safe local subset: headings, paragraphs, lists, blockquotes,
code, tables, and citation numbers. HTML, links, and remote media do not execute
or trigger remote requests. Content Security Policy provides an additional local
resource boundary. The server rejects non-loopback bind addresses.

For the design review and screenshot checklist, see
[genius_trace_viewer_ux_review.md](genius_trace_viewer_ux_review.md).

```bash
# Run the viewer first, then capture real-data visual acceptance screenshots:
node tests/viewer_real_trace_qa.cjs
```

Screenshots and the acceptance record stay in the ignored `logs/viewer-qa/`
directory. Browser tests use the installed Chrome; set `CHROME_PATH` for the
standalone QA scripts when Chrome is installed elsewhere.


## 2026-09-13 记录重置

用户要求正式 P0 评测前清空测试记录；旧 smoke、viewer 演示、QA 截图和三个 hijacking run 已删除。
上文涉及的历史日志/截图路径不再代表当前存在的文件，测试代码与配置仍保留。
