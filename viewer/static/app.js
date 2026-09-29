/* Local replay only. Trace content is always rendered with text nodes, never HTML. */
const $ = (selector) => document.querySelector(selector);
const state = {
  index: null,
  events: [],
  groups: [],
  selectedEvent: null,
  selectedEventId: null,
  rendered: 0,
  view: "conversation",
};
const filterNames = [
  "run_id",
  "group_id",
  "plugin_id",
  "session_id",
  "request_id",
  "outcome",
  "tool_name",
  "confirmation_id",
  "q",
];
const labels = {
  user: "你",
  assistant: "Genius",
  reasoning: "Reasoning",
  tool: "工具调用",
  approval: "审批流程",
  terminal: "请求结束",
  session: "会话",
  request: "请求开始",
  oracle: "Oracle 证据",
  eval: "评估结果",
  event: "执行状态",
};
const icons = {
  user: "◉",
  assistant: "✦",
  reasoning: "⌘",
  tool: "⌁",
  approval: "◇",
  terminal: "✓",
  session: "○",
  request: "↳",
  oracle: "◎",
  eval: "▤",
  event: "·",
};
function el(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text != null) n.textContent = String(text);
  return n;
}
function button(text, action, className = "") {
  const b = el("button", className, text);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
}
function pretty(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}
function rawJSON(value) {
  return JSON.stringify(value, null, 2);
}
function getFilters() {
  return Object.fromEntries(new URLSearchParams(location.search));
}
function setFilters(values, push = false) {
  const p = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v) p.set(k, v);
  });
  history[push ? "pushState" : "replaceState"](
    null,
    "",
    location.pathname + (p.size ? "?" + p : ""),
  );
}
function time(ts) {
  return ts
    ? new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false })
    : "未记录时间";
}
function tone(value) {
  const s = String(value || "");
  if (/denied|blocked|awaiting|confirmation|human_input|deferred/.test(s))
    return "warning";
  if (/fail|error|timeout/.test(s)) return "danger";
  if (/complet|success|approved|deleted|pass/.test(s)) return "success";
  return "";
}
function badge(text) {
  return el("span", `badge ${tone(text)}`, text || "未记录");
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(
    () => $("#toast").classList.remove("visible"),
    2300,
  );
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制");
  } catch {
    toast("剪贴板不可用，请从原始记录中手动复制");
  }
}
function nested(e) {
  return e.raw?.summary?.raw || e.raw?.raw || {};
}
function eventType(e) {
  return e.raw?.summary?.event_type || e.kind;
}
function category(e) {
  if (e.category === "terminal" && nested(e).reply) return "assistant";
  return e.category;
}
function eventText(e) {
  const n = nested(e);
  return n.reply ?? n.text ?? n.content ?? e.text ?? "";
}
function eventLabel(e) {
  const c = category(e);
  if (c === "tool") return e.tool_name || "工具调用";
  if (c === "terminal")
    return e.outcome || nested(e).status || e.raw?.code || eventType(e);
  if (c === "session") return "会话已创建";
  if (c === "request") return "请求开始";
  if (c === "event") return e.outcome || eventType(e);
  return labels[c] || eventType(e);
}
// Deliberately bounded Markdown: no HTML, active links, remote images or embeds.
function inline(target, text) {
  const re =
    /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\[\[(\d+)\]\])/g;
  let end = 0,
    m;
  while ((m = re.exec(text))) {
    target.append(document.createTextNode(text.slice(end, m.index)));
    if (m[2]) target.append(el("strong", "", m[2]));
    else if (m[3]) target.append(el("code", "", m[3]));
    else if (m[6]) {
      const citation = el("sup", "citation", m[6]);
      citation.title = "日志中的引用 " + m[6];
      target.append(citation);
    } else {
      const n = el("span", "reference", m[4]);
      n.title = m[5];
      target.append(n);
    }
    end = re.lastIndex;
  }
  target.append(document.createTextNode(text.slice(end)));
}
function markdown(text) {
  const root = el("div", "prose"),
    lines = String(text).split("\n");
  let i = 0;
  while (i < lines.length) {
    let line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    if (line.startsWith("```")) {
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```"))
        code.push(lines[i++]);
      i++;
      root.append(el("pre", "", code.join("\n")));
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.*)/);
    if (heading) {
      const h = el("h" + heading[1].length);
      inline(h, heading[2]);
      root.append(h);
      i++;
      continue;
    }
    if (/^\s*([-*_])\1\1+\s*$/.test(line)) {
      root.append(el("hr"));
      i++;
      continue;
    }
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])
    ) {
      const wrap = el("div", "table-wrap"),
        table = el("table");
      let first = true;
      while (i < lines.length && lines[i].includes("|")) {
        const row = lines[i++];
        if (/^\s*\|?\s*:?-{3,}/.test(row)) continue;
        const tr = el("tr");
        row
          .replace(/^\||\|$/g, "")
          .split("|")
          .forEach((cell) => {
            const td = el(first ? "th" : "td");
            inline(td, cell.trim());
            tr.append(td);
          });
        table.append(tr);
        first = false;
      }
      wrap.append(table);
      root.append(wrap);
      continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const list = el(/^\s*\d/.test(line) ? "ol" : "ul");
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const li = el("li");
        inline(li, lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        list.append(li);
      }
      root.append(list);
      continue;
    }
    if (line.startsWith("> ")) {
      const q = el("blockquote");
      inline(q, line.slice(2));
      root.append(q);
      i++;
      continue;
    }
    const paragraph = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,3}\s|```|> |\s*([-*]|\d+\.)\s+)/.test(lines[i])
    )
      paragraph.push(lines[i++]);
    const p = el("p");
    inline(p, paragraph.join("\n"));
    root.append(p);
  }
  return root;
}
function disclosure(title, content) {
  const d = el("details", "disclosure");
  d.append(el("summary", "", title));
  if (typeof content === "function") {
    d.addEventListener("toggle", () => {
      if (d.open && !d.dataset.loaded) {
        d.append(content());
        d.dataset.loaded = "1";
      }
    });
  } else d.append(content);
  return d;
}
function detailRows(entries) {
  const dl = el("dl", "data-grid");
  for (const [k, v] of entries) {
    if (v == null || v === "") continue;
    dl.append(
      el("dt", "", k),
      el("dd", "", typeof v === "object" ? pretty(v) : v),
    );
  }
  return dl;
}
function groupKey(e) {
  return JSON.stringify([e.run_id, e.session_id, e.request_id]);
}
function buildGroups(events) {
  const groups = [],
    approvals = new Map(),
    tools = new Map();
  for (const e of events) {
    const cat = category(e),
      prev = groups.at(-1);
    if (state.view === "conversation" && cat === "tool" && nested(e).id) {
      const key = JSON.stringify([
        e.run_id,
        e.session_id,
        e.request_id,
        nested(e).id,
      ]);
      const existing = tools.get(key);
      if (existing) {
        existing.events.push(e);
        continue;
      }
      const next = { category: cat, events: [e], id: e.event_id };
      tools.set(key, next);
      groups.push(next);
      continue;
    }
    if (
      state.view === "conversation" &&
      cat === "approval" &&
      e.confirmation_id
    ) {
      const key = JSON.stringify([e.run_id, e.session_id, e.confirmation_id]);
      const g = approvals.get(key);
      if (g) {
        g.events.push(e);
        continue;
      }
      const next = { category: cat, events: [e], id: e.event_id };
      approvals.set(key, next);
      groups.push(next);
      continue;
    }
    if (
      state.view === "conversation" &&
      ["reasoning", "assistant"].includes(cat) &&
      prev?.category === cat &&
      groupKey(prev.events[0]) === groupKey(e) &&
      nested(prev.events.at(-1)).thinking_round === nested(e).thinking_round &&
      eventType(e).endsWith("_delta") &&
      eventType(prev.events.at(-1)).endsWith("_delta")
    ) {
      prev.events.push(e);
      continue;
    }
    groups.push({ category: cat, events: [e], id: e.event_id });
  }
  return groups;
}
function sourceEvents(group) {
  return group.events;
}
function renderCard(group) {
  const e = group.events[0],
    cat = group.category,
    card = el("article", `event ${cat}`);
  card.dataset.eventId = group.id;
  card.tabIndex = 0;
  card.setAttribute("aria-label", `${labels[cat] || cat} ${eventLabel(e)}`);
  const last = group.events.at(-1);
  const header = el("div", "event-header");
  header.append(
    el("span", "event-icon", icons[cat] || "·"),
    el("span", "event-label", eventLabel(e)),
  );
  if (cat === "reasoning")
    header.append(el("span", "muted", `${group.events.length} 个片段`));
  if (["tool", "approval", "oracle", "eval"].includes(cat))
    header.append(
      badge(last.outcome || (cat === "tool" ? "已记录" : "待检查")),
    );
  header.append(el("time", "event-time", time(e.timestamp)));
  card.append(header);
  const body = el("div", "event-body");
  const text = group.events.map(eventText).join("");
  if (cat === "user" && e.raw?.origin === "promptfoo_eval")
    body.append(el("div", "event-meta", e.raw.association === "unmatched"
      ? "来自 eval.json · 尚未关联到请求"
      : "来自 eval.json · 已关联到本次请求"));
  if (cat === "reasoning") {
    const d = disclosure("Reasoning · " + group.events.length + " 个片段", () =>
      markdown(text),
    );
    header.replaceChildren(
      el("span", "event-icon", "⌘"),
      d,
      el("time", "event-time", time(e.timestamp)),
    );
    header.classList.add("reasoning-header");
  } else if (cat === "tool") {
    const result = group.events.findLast(
      (x) => x.tool_result != null,
    )?.tool_result;
    const input = group.events.find((x) => x.tool_input != null)?.tool_input;
    let parsed = result;
    try {
      if (typeof result === "string") parsed = JSON.parse(result);
    } catch {
      /* preserve the recorded text */
    }
    if (parsed && typeof parsed === "object") {
      const brief = parsed.message || parsed.status || parsed.name;
      if (brief) body.append(el("div", "conclusion", brief));
    }
    body.append(
      disclosure("输入与结果", () => {
        const box = el("div");
        box.append(
          el("div", "event-meta", "输入"),
          el("pre", "", input == null ? "日志未记录输入" : pretty(input)),
          el("div", "event-meta", "结果"),
          el("pre", "", result == null ? "日志未记录结果" : pretty(parsed)),
        );
        return box;
      }),
    );
  } else if (cat === "approval") {
    if (e.text) body.append(markdown(e.text));
    const flow = el("ol", "flow");
    for (const step of group.events) {
      const li = el("li");
      const name =
        {
          approval_observed: "发现审批",
          approval_policy_decision: "策略判定",
          approval_protocol_submit: "提交审批",
          approval_protocol_response: "协议响应",
          approval_terminal_result: "最终结果",
          approval_continuation: "继续执行",
        }[step.kind] || step.kind;
      li.append(
        button(name + (step.outcome ? " · " + step.outcome : ""), (ev) => {
          ev.stopPropagation();
          selectEvent(step.event_id);
        }),
        el(
          "small",
          "",
          time(step.timestamp) +
            (step.raw?.response ? " · " + pretty(step.raw.response) : ""),
        ),
      );
      flow.append(li);
    }
    body.append(flow);
    const related = state.index.events.filter(
      (x) =>
        x.run_id === e.run_id &&
        x.session_id === e.session_id &&
        x.raw?.trace?.approval_decision?.event_id === e.confirmation_id,
    );
    for (const item of related) {
      const continuation = item.raw.trace.approval_continuation;
      if (continuation)
        body.append(
          disclosure("Continuation · " + (continuation.mode || "已记录"), () =>
            el("pre", "", pretty(continuation)),
          ),
        );
    }
    body.append(el("div", "event-meta", e.confirmation_id));
  } else if (cat === "terminal") {
    card.classList.add(tone(eventLabel(e)) || "neutral");
    if (text) body.append(markdown(text));
    const n = nested(e);
    if (n.reply == null && e.raw?.code)
      body.append(el("div", "conclusion", e.raw.code));
    if (e.raw?.elapsed_s != null)
      body.append(
        el(
          "div",
          "conclusion",
          `${e.raw.elapsed_s} 秒 · ${e.outcome || "请求结束"}`,
        ),
      );
  } else if (cat === "request") {
    const preceding = state.index.events.findLast(
      (item) =>
        item.run_id === e.run_id &&
        item.session_id === e.session_id &&
        item.timestamp <= e.timestamp &&
        item.event_id !== e.event_id,
    );
    if (text || preceding?.category !== "user")
      body.append(el("div", "conclusion", text || "这条日志未记录用户原文"));
  } else if (cat === "oracle" || cat === "eval") {
    if (text) body.append(markdown(text));
    body.append(
      disclosure("查看证据与结果", () => el("pre", "", pretty(e.raw))),
    );
  } else if (text) body.append(markdown(text));
  if (body.childNodes.length) card.append(body);
  card.addEventListener("click", (ev) => {
    if (ev.target.closest("button")) return;
    selectEvent(e.event_id);
  });
  card.addEventListener("keydown", (ev) => {
    if (ev.target === card && (ev.key === "Enter" || ev.key === " ")) {
      ev.preventDefault();
      selectEvent(e.event_id);
    }
  });
  return card;
}
function appendPage(limit = state.rendered + 60) {
  const timeline = $("#timeline");
  $("#load-more")?.remove();
  const fragment = document.createDocumentFragment();
  for (
    ;
    state.rendered < Math.min(limit, state.groups.length);
    state.rendered++
  )
    fragment.append(renderCard(state.groups[state.rendered]));
  timeline.append(fragment);
  if (state.rendered < state.groups.length) {
    const more = button(
      `继续加载 · 还有 ${state.groups.length - state.rendered} 条`,
      () => appendPage(),
      "load-more",
    );
    more.id = "load-more";
    timeline.append(more);
  }
  markSelection();
}
function stateCard(title, message, action) {
  const card = el("div", "state-card");
  card.append(
    el("span", "state-symbol", "⌖"),
    el("h2", "", title),
    el("p", "", message),
  );
  if (action) card.append(button(action.label, action.run));
  $("#timeline").replaceChildren(card);
}
function renderTimeline(events) {
  state.groups = buildGroups(events);
  state.rendered = 0;
  $("#timeline").replaceChildren();
  $("#timeline").setAttribute("aria-busy", "false");
  if (!events.length) {
    stateCard("没有匹配的轨迹", "试试减少筛选条件，或清除搜索词。", {
      label: "清除筛选",
      run: () => navigate({}),
    });
    return;
  }
  appendPage();
  $("#timeline-count").textContent =
    `${state.groups.length} 条记录 · ${events.length} events`;
}
function markSelection() {
  document.querySelectorAll(".event").forEach((card) => {
    const group = state.groups.find((g) => g.id === card.dataset.eventId);
    const active = group?.events.some(
      (e) => e.event_id === state.selectedEventId,
    );
    card.classList.toggle("active", !!active);
    card.setAttribute("aria-current", active ? "true" : "false");
  });
}
function selectEvent(
  id,
  { update = true, reveal = false, focus = false } = {},
) {
  const event = state.index?.events.find((e) => e.event_id === id);
  if (!event) return;
  const groupIndex = state.groups.findIndex((g) =>
    g.events.some((e) => e.event_id === id),
  );
  if (groupIndex < 0) return;
  state.selectedEventId = id;
  state.selectedEvent = event;
  if (groupIndex >= state.rendered) appendPage(groupIndex + 1);
  markSelection();
  renderDetails(event, state.groups[groupIndex]);
  if (update) {
    const f = getFilters();
    f.event_id = id;
    setFilters(f);
  }
  if (reveal) {
    const card = [...document.querySelectorAll(".event")].find((c) =>
      c.classList.contains("active"),
    );
    card?.scrollIntoView({ block: "center" });
    if (focus) card?.focus({ preventScroll: true });
  }
}
function renderDetails(event, group) {
  const body = $("#details-body"),
    raw = $("#raw-json");
  body.replaceChildren();
  raw.replaceChildren();
  $("#copy-json").disabled = !event;
  if (!event) {
    const empty = el("div", "inspector-empty");
    empty.append(
      el("span", "", "⌖"),
      el("h3", "", "每一步，都有迹可循"),
      el("p", "", "选择一条消息或工具调用，在这里查看来源与执行细节。"),
    );
    body.append(empty);
    raw.append(el("p", "empty", "尚未选择事件"));
    return;
  }
  body.append(
    el("div", "detail-title", eventLabel(event)),
    badge(event.outcome || category(event)),
  );
  body.append(
    detailRows([
      ["事件", event.event_id],
      ["类型", eventType(event)],
      ["Run", event.run_id],
      ["Plugin", event.plugin_id],
      ["Session", event.session_id],
      ["Request", event.request_id],
      ["Tool", event.tool_name || event.raw?.approval?.tool],
      ["Approval", event.confirmation_id],
      ["Action", event.raw?.approval?.action_id || event.raw?.action_id],
      ["Resource", event.raw?.resource || event.raw?.approval?.resource],
      ["来源", `${event.source_file}:${event.line_number}`],
      [
        "时间",
        event.timestamp
          ? new Date(event.timestamp * 1000).toLocaleString("zh-CN")
          : "未记录",
      ],
    ]),
  );
  if (group.events.length > 1) {
    body.append(
      el("div", "event-meta", `本卡片合并 ${group.events.length} 条原始事件`),
    );
    const sources = el("div", "source-list");
    sourceEvents(group).forEach((e) =>
      sources.append(
        button(
          `${e.source_file}:${e.line_number}`,
          () => selectEvent(e.event_id),
          e.event_id === event.event_id ? "active" : "",
        ),
      ),
    );
    body.append(sources);
  }
  raw.append(
    disclosure("展开 Raw JSON", () => el("pre", "", rawJSON(event.raw))),
  );
}
function options(filters) {
  const events = state.index.events;
  for (const select of document.querySelectorAll("select[data-filter]")) {
    const key = select.dataset.filter;
    const values = [
      ...new Set(events.map((e) => e[key]).filter(Boolean)),
    ].sort();
    if (filters[key] && !values.includes(filters[key]))
      values.push(filters[key]);
    select.replaceChildren(
      new Option("全部", ""),
      ...values.map((v) => new Option(v, v)),
    );
    select.value = filters[key] || "";
  }
  $("[data-filter=q]").value = filters.q || "";
  $("#filter-count").textContent =
    Object.keys(filters).filter((k) => filterNames.includes(k) && filters[k])
      .length || "";
}
function match(e, filters, keys = filterNames) {
  return keys.every(
    (k) =>
      !filters[k] ||
      (k === "q"
        ? (e.search_text || "").toLowerCase().includes(filters[k].toLowerCase())
        : e[k] === filters[k]),
  );
}
function sessionTitle(id) {
  const replies = state.index.events.filter(
    (e) => e.session_id === id && category(e) === "assistant",
  );
  for (const reply of replies) {
    const heading = String(eventText(reply)).match(/^#{1,3}\s+(.+)$/m);
    if (heading) return heading[1].replace(/\*\*/g, "");
  }
  return null;
}
function friendlySession(s) {
  const title = sessionTitle(s.session_id);
  if (title) return title;
  return s.local_session_id || s.session_id.split(":").at(-1).slice(0, 12);
}
function renderList(id, records, selected, onselect) {
  const list = $(id);
  list.replaceChildren();
  if (!records.length) {
    list.append(el("p", "empty", "暂无记录"));
    return;
  }
  for (const r of records) {
    const b = button(
      "",
      () => onselect(r.id),
      "list-item" + (r.id === selected ? " active" : ""),
    );
    b.dataset.id = r.id;
    b.title = r.title;
    b.setAttribute("aria-pressed", String(r.id === selected));
    b.append(el("div", "item-title", r.title), el("div", "item-meta", r.meta));
    list.append(b);
  }
}
function navigate(filters, push = true) {
  saveScroll();
  setFilters(filters, push);
  render();
  $("#timeline").scrollTop = 0;
}
function choose(key, id) {
  const f = getFilters();
  delete f.event_id;
  if (key === "run_id") {
    delete f.session_id;
    delete f.request_id;
  }
  if (key === "session_id") delete f.request_id;
  f[key] = id;
  navigate(f);
}
function render() {
  const f = getFilters();
  state.view = f.view === "events" ? "events" : "conversation";
  options(f);
  state.events = state.index.events.filter((e) => match(e, f));
  if (f.tool_name || f.confirmation_id) {
    const matched = state.events,
      keys = new Set(matched.filter((e) => e.request_id).map(groupKey));
    const context = { ...f };
    delete context.tool_name;
    delete context.confirmation_id;
    state.events = state.index.events.filter(
      (e) =>
        match(e, context) &&
        (matched.includes(e) || (e.request_id && keys.has(groupKey(e)))),
    );
  }
  // Keep sibling runs/sessions navigable while the transcript obeys every active filter.
  const navFilters = { ...f };
  delete navFilters.run_id;
  delete navFilters.session_id;
  delete navFilters.request_id;
  const candidates = state.index.events.filter((e) => match(e, navFilters));
  const runIds = new Set(candidates.map((e) => e.run_id));
  const sessionIds = new Set(
    candidates
      .filter((e) => !f.run_id || e.run_id === f.run_id)
      .map((e) => e.session_id),
  );
  const requestIds = new Set(
    candidates
      .filter(
        (e) =>
          (!f.run_id || e.run_id === f.run_id) &&
          (!f.session_id || e.session_id === f.session_id),
      )
      .map((e) => e.request_id),
  );
  const runs = state.index.runs.filter((r) => runIds.has(r.run_id)),
    sessions = state.index.sessions.filter((s) => sessionIds.has(s.session_id)),
    requests = state.index.requests.filter((r) => requestIds.has(r.request_id));
  renderList(
    "#run-list",
    runs.map((r) => ({
      id: r.run_id,
      title: r.run_id,
      meta: `${r.group_id || "本地"} / ${r.plugin_id || "trace"}`,
    })),
    f.run_id,
    (id) => choose("run_id", id),
  );
  renderList(
    "#session-list",
    sessions.map((s) => ({
      id: s.session_id,
      title: friendlySession(s),
      meta: `${s.requests.length} 个请求 · ${state.index.events.filter((e) => e.session_id === s.session_id && (!f.run_id || e.run_id === f.run_id)).length} events`,
    })),
    f.session_id,
    (id) => choose("session_id", id),
  );
  renderList(
    "#request-list",
    requests.map((r) => ({
      id: r.request_id,
      title: r.request_id,
      meta: r.outcome || `${r.events.length} events`,
    })),
    f.request_id,
    (id) => choose("request_id", id),
  );
  $("#run-count").textContent = runs.length;
  $("#session-count").textContent = sessions.length;
  $("#request-count").textContent = requests.length;
  $("#timeline-title").textContent =
    f.request_id ||
    (f.session_id && sessionTitle(f.session_id)) ||
    f.session_id ||
    f.run_id ||
    "全部对话";
  $("#timeline-title").title = f.session_id || $("#timeline-title").textContent;
  $("#timeline-subtitle").textContent = f.session_id
    ? "SESSION · 本地对话回放"
    : f.run_id
      ? "RUN · " + f.run_id + " / 对话与执行轨迹"
      : "选择左侧运行记录，开始浏览对话";
  $("#view-conversation").classList.toggle(
    "active",
    state.view === "conversation",
  );
  $("#view-events").classList.toggle("active", state.view === "events");
  $("#view-conversation").setAttribute(
    "aria-pressed",
    String(state.view === "conversation"),
  );
  $("#view-events").setAttribute(
    "aria-pressed",
    String(state.view === "events"),
  );
  state.selectedEventId = null;
  state.selectedEvent = null;
  renderTimeline(state.events);
  renderDetails(null);
  if (f.event_id) {
    if (state.events.some((e) => e.event_id === f.event_id))
      selectEvent(f.event_id, { update: false, reveal: true });
    else toast("链接中的事件不存在或已被当前筛选隐藏");
  }
  if (!state.index.events.length)
    stateCard(
      "还没有可回放的对话",
      "将已有 trace 放在 logs/ 或 sweep run 目录，然后重启 viewer。",
    );
  if (state.index.errors?.length)
    $("#reading-hint").textContent =
      `${state.index.errors.length} 个数据源读取异常`;
}
function scrollKey() {
  return "viewer-scroll:" + location.pathname + location.search;
}
function saveScroll() {
  try {
    sessionStorage.setItem(
      scrollKey(),
      JSON.stringify({
        top: $("#timeline").scrollTop,
        rendered: state.rendered,
      }),
    );
  } catch {}
}
function restoreScroll() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(scrollKey()) || "null");
    if (saved) {
      appendPage(saved.rendered || 60);
      $("#timeline").scrollTop = saved.top || 0;
    }
  } catch {}
}
async function loadIndex() {
  try {
    const response = await fetch("/api/index");
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    state.index = await response.json();
    const f = getFilters();
    if (!Object.keys(f).length && state.index.runs.length) {
      f.run_id = state.index.runs[0].run_id;
      setFilters(f);
    }
    render();
    restoreScroll();
  } catch (error) {
    $("#timeline").setAttribute("aria-busy", "false");
    stateCard("暂时无法读取轨迹", `本地服务读取失败：${error.message}`, {
      label: "重试",
      run: loadIndex,
    });
  }
}
document.addEventListener("DOMContentLoaded", () => {
  try {
    document.documentElement.dataset.theme =
      localStorage.getItem("viewer-theme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  } catch {}
  $("#theme-toggle").addEventListener("click", () => {
    const theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("viewer-theme", theme);
    } catch {}
  });
  $("#toggle-filters").addEventListener("click", () => {
    const panel = $("#filter-panel");
    panel.hidden = !panel.hidden;
    $("#toggle-filters").setAttribute("aria-expanded", String(!panel.hidden));
  });
  $("#toggle-details").addEventListener("click", () => {
    if (innerWidth <= 1150) {
      document.body.classList.toggle("inspector-open");
      $("#toggle-details").setAttribute(
        "aria-expanded",
        String(document.body.classList.contains("inspector-open")),
      );
    } else {
      document.body.classList.toggle("details-hidden");
      $("#toggle-details").setAttribute(
        "aria-expanded",
        String(!document.body.classList.contains("details-hidden")),
      );
    }
  });
  document
    .querySelectorAll("select[data-filter]")
    .forEach((s) =>
      s.addEventListener("change", () => choose(s.dataset.filter, s.value)),
    );
  $("[data-filter=q]").addEventListener("input", (ev) => {
    const f = getFilters();
    f.q = ev.target.value;
    delete f.event_id;
    setFilters(f);
    if (state.index) render();
  });
  $("#clear-filters").addEventListener("click", () => navigate({}));
  $("#copy-link").addEventListener("click", () => copy(location.href));
  $("#copy-json").addEventListener("click", () => {
    if (state.selectedEvent) copy(rawJSON(state.selectedEvent.raw));
  });
  for (const view of ["conversation", "events"])
    $("#view-" + view).addEventListener("click", () => {
      const f = getFilters();
      f.view = view;
      navigate(f);
    });
  $("#to-bottom").addEventListener("click", () => {
    appendPage(state.groups.length);
    $("#timeline").scrollTop = $("#timeline").scrollHeight;
  });
  let timer;
  $("#timeline").addEventListener("scroll", () => {
    clearTimeout(timer);
    timer = setTimeout(saveScroll, 150);
  });
  window.addEventListener("pagehide", saveScroll);
  window.addEventListener("popstate", () => {
    if (state.index) {
      render();
      restoreScroll();
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      document.body.classList.remove("inspector-open");
      return;
    }
    if (
      ev.target.closest("input,select,textarea,button,summary") ||
      ev.ctrlKey ||
      ev.metaKey ||
      ev.altKey
    )
      return;
    if (ev.key === "/") {
      ev.preventDefault();
      $("[data-filter=q]").focus();
      return;
    }
    if (
      !["ArrowDown", "ArrowUp", "j", "k"].includes(ev.key) ||
      !state.groups.length
    )
      return;
    ev.preventDefault();
    const i = state.groups.findIndex((g) =>
      g.events.some((e) => e.event_id === state.selectedEventId),
    );
    const next = Math.max(
      0,
      Math.min(
        state.groups.length - 1,
        i + (["ArrowDown", "j"].includes(ev.key) ? 1 : -1),
      ),
    );
    selectEvent(state.groups[next].id, { reveal: true, focus: true });
  });
  loadIndex();
});
