const $ = (selector) => document.querySelector(selector);
const state = { data: null, visible: [], selected: null };
function node(tag, className, text) { const n = document.createElement(tag); if (className) n.className = className; if (text != null) n.textContent = String(text); return n; }
function pill(text, kind) { return node("span", "pill " + (kind || ""), text); }
function params() { return Object.fromEntries(new URLSearchParams(location.search)); }
function setParams(next) { const u = new URL(location.href); u.search = new URLSearchParams(next).toString(); history.replaceState(null, "", u); }
function quadrant(family) { const q = state.data.quadrants; if (q.a_and_b.includes(family.family_id)) return "a_and_b"; if (q.a_only.includes(family.family_id)) return "a_only"; if (q.b_only.includes(family.family_id)) return "b_only"; return "neither"; }
function quadrantLabel(value) { return {all:"全部",a_and_b:"A∩B",a_only:"A-only",b_only:"B-only",neither:"Neither"}[value] || value; }
function sourceIds(family) { return family.source_details.map((x) => x.source_id); }
function option(value, label) { const o = node("option", "", label); o.value = value; return o; }
function filters() { return { q: $("#risk-search").value.trim().toLowerCase(), quadrant: $("#quadrant-filter").value, source: $("#source-filter").value }; }
function renderMetrics() {
  const c = state.data.counts, grid = $("#metric-grid"); grid.replaceChildren();
  [["12","公开来源",""],["274","原始条目",""],[String(c.family_count),"归一化 family",""],[String(c.observed_success),"A · 已成功","amber"],[String(c.source_faithful_testable),"B · 真实可测","featured"],[String(state.data.taxonomy_cell_count),"MalSkill cells",""]].forEach((x) => { const m=node("div","metric "+x[2]); m.append(node("strong","",x[0]),node("span","",x[1])); grid.append(m); });
}
function setupFilters() {
  const q=$("#quadrant-filter"); q.replaceChildren(option("all","全部象限"),option("b_only","B-only · 真实可测"),option("a_and_b","A∩B"),option("a_only","A-only"),option("neither","Neither"));
  const s=$("#source-filter"); s.replaceChildren(option("","全部来源"));
  [...new Set(state.data.families.flatMap(sourceIds))].sort().forEach((x) => s.append(option(x,x)));
  const p=params(); $("#risk-search").value=p.q || ""; q.value=p.quadrant || "b_only"; s.value=p.source || "";
}
function applyFilters() {
  const f=filters(); state.visible=state.data.families.filter((x) => {
    const hay=[x.family_id,x.label,x.impact,...sourceIds(x),...x.source_anchors.flatMap((a)=>[a.label,a.raw_key])].join(" ").toLowerCase();
    return (!f.q || hay.includes(f.q)) && (f.quadrant==="all" || quadrant(x)===f.quadrant) && (!f.source || sourceIds(x).includes(f.source));
  }).sort((a,b)=>a.label.localeCompare(b.label));
  setParams({...(f.q?{q:f.q}:{}),...(f.quadrant!=="b_only"?{quadrant:f.quadrant}:{}),...(f.source?{source:f.source}:{}),...(state.selected?{family:state.selected}: {})});
  renderList(); const selected=state.visible.find((x)=>x.family_id===state.selected); if(selected)renderDetail(selected); else selectFamily(state.visible[0]?.family_id || null);
}
function renderList() {
  $("#visible-count").textContent=state.visible.length+" 个类别"; const list=$("#risk-list"); list.replaceChildren();
  if (!state.visible.length) { list.append(node("p","empty-state","没有匹配的风险类别")); return; }
  state.visible.forEach((family) => { const b=node("button","risk-card"+(family.family_id===state.selected?" active":"")); b.type="button"; b.dataset.family=family.family_id; b.append(node("h3","",family.label),node("code","",family.family_id)); const foot=node("div","risk-card-foot"); foot.append(pill(quadrantLabel(quadrant(family)), quadrant(family)==="b_only"?"green":"amber"),pill(family.source_details.length+" sources","")); b.append(foot); b.addEventListener("click",()=>selectFamily(family.family_id,true)); list.append(b); });
}
function heading(text) { return node("h3","",text); }
function evidence(title,text) { const c=node("div","evidence-card"); c.append(node("h4","",title),node("p","",text)); return c; }
function renderDetail(family) {
  const detail=$("#risk-detail"); detail.replaceChildren(); if (!family) { const empty=node("div","empty-state"); empty.append(node("span","","◎"),node("h2","","没有匹配类别"),node("p","","调整筛选条件后再试。")); detail.append(empty); return; }
  const head=node("div","detail-head"), copy=node("div"); copy.append(node("p","eyebrow","RISK TRAJECTORY"),node("h2","",family.label),node("code","",family.family_id)); const badges=node("div","badge-stack"); badges.append(pill(quadrantLabel(quadrant(family)),quadrant(family)==="b_only"?"green":"amber"),pill(family.material_harm.toUpperCase(),family.material_harm==="high"?"red":"amber"),pill(family.fidelity_status,"")); head.append(copy,badges); detail.append(head);
  const sources=node("section","detail-section"); sources.append(heading("来源锚点")); const chips=node("div","source-chips"); family.source_details.forEach((s)=>{const a=node("a","source-chip",s.source_id+" · "+s.pinned_ref);a.href=s.repository_url;a.target="_blank";a.rel="noreferrer";chips.append(a);}); sources.append(chips); const anchors=node("div","source-anchor-list"); family.source_anchors.slice(0,8).forEach((a)=>{const x=node("div","source-anchor");x.append(node("strong","",a.label),node("small","",a.raw_key+" · "+a.axis));anchors.append(x);}); if(family.source_anchors.length>8)anchors.append(node("small","muted","另 "+(family.source_anchors.length-8)+" 条来源映射，机器索引中完整保留。")); sources.append(anchors); detail.append(sources);
  if (family.trajectory) { const t=family.trajectory,u=t.upstream_chain, sec=node("section","detail-section"); sec.append(heading("五步攻击链")); const chain=node("div","chain"); [["CARRIER",u.carrier],["TRIGGER",u.trigger],["ACTION",u.action],["SINK",u.sink],["EFFECT",u.effect]].forEach((x)=>{const c=node("div","chain-step");c.append(node("span","",x[0]),node("p","",x[1]));chain.append(c);}); sec.append(chain); detail.append(sec); const adapt=node("section","detail-section");adapt.append(heading("Genius 适配与评分"));const grid=node("div","evidence-grid");grid.append(evidence("GENIUS PATH",t.genius_adaptation_path),evidence("SUCCESS ORACLE",t.oracle),evidence("IMPACT LIMIT",t.impact_limit),evidence("RESIDUAL",t.residual_disposition),evidence("A TRACK",t.success_evidence),evidence("B TRACK",t.source_testability));adapt.append(grid);detail.append(adapt); const fidelity=node("section","detail-section");fidelity.append(heading("来源忠实度与缺失证据"));const ul=node("ul","fidelity-list");t.fidelity_delta.forEach((x)=>ul.append(node("li","",x)));fidelity.append(ul,evidence("MISSING EVIDENCE",t.missing_evidence));detail.append(fidelity); }
}
function selectFamily(id, focus) { state.selected=id; const family=state.data.families.find((x)=>x.family_id===id); renderList(); renderDetail(family); const p=params(); if(id)p.family=id;else delete p.family; setParams(p); if(focus) $("#risk-detail").scrollTop=0; }
function bind() { ["#risk-search","#quadrant-filter","#source-filter"].forEach((s)=>$(s).addEventListener(s==="#risk-search"?"input":"change",applyFilters)); $("#clear-risk-filters").addEventListener("click",()=>{$("#risk-search").value="";$("#quadrant-filter").value="b_only";$("#source-filter").value="";applyFilters();}); $("#theme-toggle").addEventListener("click",()=>{const next=document.documentElement.dataset.theme==="dark"?"light":"dark";document.documentElement.dataset.theme=next;localStorage.setItem("risk-theme",next);}); window.addEventListener("popstate",()=>location.reload()); }
async function load() { try { const response=await fetch("/api/dual-gate"); if(!response.ok)throw new Error("双轨数据不可用"); state.data=await response.json(); renderMetrics(); setupFilters(); bind(); const p=params(); state.selected=p.family||null; applyFilters(); if(!state.selected&&state.visible.length)selectFamily(state.visible[0].family_id); } catch(error) { const empty=node("div","empty-state"); empty.append(node("span","","!"),node("h2","","无法加载风险轨迹"),node("p","",error.message)); $("#risk-detail").replaceChildren(empty); } }
document.documentElement.dataset.theme=localStorage.getItem("risk-theme")||"light"; load();
