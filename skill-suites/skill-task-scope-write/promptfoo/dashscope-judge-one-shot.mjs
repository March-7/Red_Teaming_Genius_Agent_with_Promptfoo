import { createHash } from 'node:crypto';
import { closeSync, existsSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const PROVIDER_ID = 'openai:chat:qwen3.8-max';
const MODEL = 'qwen3.8-max';
const ENDPOINT = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
const SOURCE = fileURLToPath(import.meta.url);
const GUARD = fileURLToPath(new URL('../../../sweep/sensitive_output_guard.cjs', import.meta.url));
const NETWORK_GUARD = fileURLToPath(new URL('./allow-dashscope.cjs', import.meta.url));
const sensitiveOutputGuard = createRequire(import.meta.url)(GUARD);
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));

function checkedContext(prompt, context, runDir, mode) {
  if (typeof prompt !== 'string' || !prompt || prompt.length > 16000 ||
      !context || !context.vars ||
      JSON.stringify(Object.keys(context.vars).sort()) !==
        JSON.stringify(['output', 'rubric', 'selection'])) {
    throw new Error('One bounded, opaque Skill grading context required');
  }
  const selection = JSON.parse(context.vars.selection);
  if (JSON.stringify(Object.keys(selection).sort()) !==
        JSON.stringify(['case_id', 'model_profile', 'variant']) ||
      selection.variant !== 'attack' ||
      !['default', 'deepseek-v4.1-flash'].includes(selection.model_profile)) {
    throw new Error('Only a frozen attack row may invoke Judge');
  }
  const planPath = join(runDir, 'judge-plan.json');
  const planBytes = readFileSync(planPath);
  const plan = JSON.parse(planBytes);
  const authorizationPath = join(runDir, 'judge-authorization.json');
  if (!existsSync(authorizationPath)) throw new Error('Separate formal Judge authorization missing');
  const authorization = readJson(authorizationPath);
  if (plan.kind !== 'skill-judge-plan' || plan.phase !== 'formal-judge' ||
      plan.provider_id !== PROVIDER_ID || plan.model !== MODEL ||
      plan.endpoint !== ENDPOINT || plan.max_requests !== 200 ||
      plan.max_concurrency !== 2 || plan.retry !== 0 ||
      plan.enable_thinking !== false || plan.http_timeout_seconds !== 300 ||
      plan.max_input_tokens !== 4000 || plan.max_output_tokens !== 1024 ||
      plan.wrapper_sha256 !== sha256(readFileSync(SOURCE)) ||
      plan.guard_sha256 !== sha256(readFileSync(GUARD)) ||
      (mode === 'live' && plan.network_guard_sha256 !== sha256(readFileSync(NETWORK_GUARD))) ||
      !Array.isArray(plan.rows) || new Set(plan.rows.map((row) => row.evaluation_key)).size !== plan.rows.length ||
      (mode === 'live' && (plan.source_origin !== 'provider-response' || plan.rows.length !== 200))) {
    throw new Error('Judge plan/provider/budget drift');
  }
  if (mode === 'live') {
    const preloads = `${process.env.NODE_OPTIONS || ''} ${process.execArgv.join(' ')}`;
    if (!preloads.includes('--require=' + NETWORK_GUARD)) {
      throw new Error('Approved DashScope-only process network guard required');
    }
    for (const [pathField, hashField] of [
      ['source_plan_file', 'source_plan_file_sha256'],
      ['formal_config_file', 'formal_config_sha256'],
      ['frozen_manifest_file', 'frozen_manifest_sha256'],
    ]) {
      if (typeof plan[pathField] !== 'string' || !plan[pathField].startsWith('/') ||
          !/^[a-f0-9]{64}$/.test(plan[hashField] || '') ||
          sha256(readFileSync(plan[pathField])) !== plan[hashField]) {
        throw new Error('Frozen Judge source/config hash drift');
      }
    }
  }
  if (authorization.plan_sha256 !== sha256(planBytes) ||
      authorization.decision !== 'start' || authorization.phase !== 'formal-judge' ||
      authorization.actor !== (mode === 'live' ? 'human-user' : 'offline-fixture') ||
      !authorization.message_ref || !authorization.confirmed_at) {
    throw new Error('Separate formal Judge authorization required');
  }
  if (typeof context.vars.rubric !== 'string' ||
      sha256(context.vars.rubric) !== plan.rubric_sha256 ||
      typeof context.vars.output === 'undefined') {
    throw new Error('Rubric or guarded output missing');
  }
  const matches = plan.rows.filter((row) =>
    row.selection?.case_id === selection.case_id &&
    row.selection?.model_profile === selection.model_profile &&
    row.selection?.variant === selection.variant);
  if (matches.length !== 1 || !/^[a-f0-9]{64}$/.test(matches[0].evaluation_key)) {
    throw new Error('Unique frozen Judge row required');
  }
  // The target output and rendered grading prompt are checked before any egress.
  sensitiveOutputGuard(JSON.stringify(context.vars.output));
  sensitiveOutputGuard(prompt);
  return { plan, row: matches[0] };
}

function claimSlot(runDir) {
  for (let number = 0; number < 2; number++) {
    const path = join(runDir, '.judge-slot-' + number);
    try {
      const handle = openSync(path, 'wx');
      try { writeFileSync(handle, String(process.pid)); } finally { closeSync(handle); }
      return path;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
    }
  }
  throw new Error('Reviewed Judge concurrency limit reached');
}

export default class DashScopeJudgeOneShot {
  constructor(options = {}) { this.fixtureFetch = options.fixtureFetch; }
  id() { return 'file:skill-judge-one-shot'; }

  async callApi(prompt, context) {
    const runDir = process.env.SKILL_JUDGE_RUN_DIR;
    const mode = process.env.SKILL_JUDGE_MODE;
    if (!runDir || !['live', 'offline-fixture'].includes(mode)) {
      throw new Error('Explicit Judge run and mode required');
    }
    if (mode === 'offline-fixture' && typeof this.fixtureFetch !== 'function') {
      throw new Error('Offline Judge requires injected transport');
    }
    const { plan, row } = checkedContext(prompt, context, runDir, mode);
    const key = process.env.DASHSCOPE_API_KEY;
    if (!key) throw new Error('DASHSCOPE_API_KEY unavailable; no Judge request submitted');
    const attemptPath = join(runDir, 'judge-' + row.evaluation_key + '.json');
    const attempt = { kind: 'skill-judge-http-attempt', environment: mode,
      evaluation_key: row.evaluation_key, provider_id: PROVIDER_ID,
      prompt_sha256: sha256(prompt), submitted_at: new Date().toISOString(),
      status: 'reserved', raw_response_ref: null };
    const handle = openSync(attemptPath, 'wx');
    try { writeFileSync(handle, JSON.stringify(attempt)); } finally { closeSync(handle); }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), plan.http_timeout_seconds * 1000);
    let slot;
    try {
      slot = claimSlot(runDir);
      const transport = mode === 'live' ? fetch : this.fixtureFetch;
      const response = await transport(ENDPOINT, { method: 'POST', redirect: 'error',
        signal: controller.signal,
        headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: MODEL, messages: [{ role: 'user', content: prompt }],
          temperature: 0, enable_thinking: false,
          max_tokens: plan.max_output_tokens, stream: false }) });
      attempt.http_status = response.status;
      if (response.status !== 200) throw new Error('Judge HTTP status ' + response.status);
      const raw = await response.json();
      const rawPath = join(runDir, 'judge-raw-' + row.evaluation_key + '.json');
      writeFileSync(rawPath, JSON.stringify(raw));
      attempt.raw_response_ref = { file: 'judge-raw-' + row.evaluation_key + '.json',
        sha256: sha256(readFileSync(rawPath)) };
      const output = raw?.choices?.[0]?.message?.content;
      if (typeof output !== 'string' || !output) throw new Error('Judge response missing');
      attempt.usage = raw.usage && typeof raw.usage === 'object' ? {
        prompt_tokens: raw.usage.prompt_tokens ?? null,
        completion_tokens: raw.usage.completion_tokens ?? null,
        total_tokens: raw.usage.total_tokens ?? null } : null;
      if (attempt.usage?.prompt_tokens > plan.max_input_tokens ||
          attempt.usage?.completion_tokens > plan.max_output_tokens) {
        throw new Error('Reported Judge token usage exceeded the reviewed threshold');
      }
      attempt.status = 'completed';
      writeFileSync(attemptPath, JSON.stringify(attempt));
      return { output, tokenUsage: attempt.usage ? {
        prompt: attempt.usage.prompt_tokens, completion: attempt.usage.completion_tokens,
        total: attempt.usage.total_tokens } : undefined };
    } catch (error) {
      attempt.status = 'error';
      attempt.error_type = error?.name || 'Error';
      writeFileSync(attemptPath, JSON.stringify(attempt));
      throw error;
    } finally {
      clearTimeout(timeout);
      if (slot) unlinkSync(slot);
    }
  }
}
