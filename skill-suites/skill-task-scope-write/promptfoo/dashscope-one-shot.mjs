import { createHash } from 'node:crypto';
import { closeSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PROVIDER_ID = 'openai:chat:qwen3.8-max';
const MODEL = 'qwen3.8-max';
const BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1';
const SUBMITTED_FIELDS = ['risk_contract', 'skill_template', 'legitimate_task_requirements'];
const EXECUTION_PATH = fileURLToPath(import.meta.url);

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function readJson(path) {
  return JSON.parse(readFileSync(path, 'utf8'));
}

function requirePlan(runDir, jobId, prompt, mode) {
  const planPath = join(runDir, 'generation-plan.json');
  const planBytes = readFileSync(planPath);
  const plan = JSON.parse(planBytes);
  const authorization = readJson(join(runDir, 'generation-authorization.json'));
  const configPath = join(runDir, 'provider-config.json');
  const config = readJson(configPath);
  if (plan.schema_version !== 1 || plan.kind !== 'skill-generation-plan' ||
      plan.phase !== 'C-generation' || plan.provider_id !== PROVIDER_ID ||
      plan.model !== MODEL || plan.api_base_url !== BASE_URL ||
      plan.provider_config_sha256 !== sha256(readFileSync(configPath)) ||
      config.provider_id !== PROVIDER_ID || config.model !== MODEL ||
      config.api_base_url !== BASE_URL || config.credential_env !== 'DASHSCOPE_API_KEY' ||
      config.settings?.temperature !== 0.7 ||
      config.settings?.enable_thinking !== false ||
      plan.max_requests !== 10 || plan.max_concurrency !== 2 ||
      plan.retry !== 0 || plan.max_input_tokens !== 4000 ||
      plan.max_output_tokens !== 8000 ||
      plan.http_timeout_seconds !== 300 || plan.worker_timeout_seconds !== 330 ||
      plan.enable_thinking !== false ||
      plan.execution_code_sha256 !== sha256(readFileSync(EXECUTION_PATH)) ||
      typeof plan.generation_scope_hash !== 'string' ||
      JSON.stringify(plan.submitted_fields) !== JSON.stringify(SUBMITTED_FIELDS) ||
      !Array.isArray(plan.jobs) || new Set(plan.jobs.map((job) => job.job_id)).size !== plan.jobs.length) {
    throw new Error('Generation plan/provider/budget drift');
  }
  if (mode === 'live' && plan.jobs.length !== 10) {
    throw new Error('Ten frozen generation jobs required');
  }
  if (authorization.phase !== 'C-generation' ||
      authorization.plan_sha256 !== sha256(planBytes) ||
      authorization.scope_hash !== plan.generation_scope_hash ||
      authorization.decision !== 'start' ||
      !authorization.message_ref || !authorization.confirmed_at ||
      authorization.actor !== (mode === 'live' ? 'human-user' : 'offline-fixture')) {
    throw new Error('Phase/run/scope-bound generation authorization required');
  }
  const job = plan.jobs.find((item) => item.job_id === jobId);
  if (!job || job.prompt_text !== prompt || job.prompt_sha256 !== sha256(prompt) ||
      !/^[a-z0-9][a-z0-9-]{0,63}$/.test(jobId) ||
      prompt.length > job.max_prompt_chars || job.max_prompt_chars > 16000) {
    throw new Error('Frozen generation job/prompt drift');
  }
  const jobDir = join(runDir, 'jobs', jobId);
  if (job.prompt_qa_origin !== 'offline-fixture' ||
      job.plugin_sha256 !== sha256(readFileSync(join(jobDir, 'plugin.yaml'))) ||
      job.live_config_sha256 !== sha256(readFileSync(join(jobDir, 'live-config.yaml')))) {
    throw new Error('Frozen Promptfoo plugin or live config drift');
  }
  if (typeof job.expected_skill_key !== 'string' ||
      typeof job.effect_artifact_name !== 'string') {
    throw new Error('Frozen Skill identity/target missing');
  }
  return { plan, job };
}

function validateGeneratedPackage(output, job) {
  const lines = output.trim().split(/\r?\n/);
  if (lines.length !== 1 || !lines[0].startsWith('PromptBlock: ')) {
    throw new Error('Exactly one Prompt JSON package per job required');
  }
  if (lines[0].slice('PromptBlock: '.length).includes('PromptBlock:')) {
    throw new Error('Generated package contains a nested PromptBlock marker');
  }
  const packageValue = JSON.parse(lines[0].slice('PromptBlock: '.length));
  const fields = Object.keys(packageValue).sort();
  if (JSON.stringify(fields) !== JSON.stringify(
        ['attack', 'effect_artifact_name', 'normal', 'skill_key', 'tasks']) ||
      packageValue.skill_key !== job.expected_skill_key ||
      packageValue.effect_artifact_name !== job.effect_artifact_name ||
      typeof packageValue.normal !== 'string' || !packageValue.normal.trim() ||
      typeof packageValue.attack !== 'string' ||
      !packageValue.attack.startsWith(packageValue.normal) ||
      packageValue.normal.includes(job.effect_artifact_name) ||
      !packageValue.attack.includes(job.effect_artifact_name) ||
      !Array.isArray(packageValue.tasks) || packageValue.tasks.length !== 10 ||
      packageValue.tasks.some((task) =>
        !task || typeof task !== 'object' || Array.isArray(task) ||
        JSON.stringify(Object.keys(task).sort()) !== JSON.stringify(
          ['allowed_behavior', 'attack_goal', 'failure_criterion', 'initial_state',
           'task_id', 'user_task_template']) ||
        typeof task.task_id !== 'string' || !/^entry-[0-9]$/.test(task.task_id) ||
        typeof task.user_task_template !== 'string' ||
        task.user_task_template.split('{resource_name}').length !== 2 ||
        task.user_task_template.includes(job.effect_artifact_name) ||
        task.user_task_template.includes('{record_id}') ||
        typeof task.allowed_behavior !== 'string' || !task.allowed_behavior.trim() ||
        typeof task.failure_criterion !== 'string' || !task.failure_criterion.trim() ||
        typeof task.attack_goal !== 'string' || !task.attack_goal.trim() ||
        !task.initial_state || typeof task.initial_state !== 'object' ||
        JSON.stringify(Object.keys(task.initial_state).sort()) !==
          JSON.stringify(['artifact_state', 'other_artifacts']) ||
        task.initial_state.artifact_state !== null ||
        !Array.isArray(task.initial_state.other_artifacts) ||
        task.initial_state.other_artifacts.length !== 0) ||
      new Set(packageValue.tasks.map((task) => task.task_id)).size !== 10 ||
      new Set(packageValue.tasks.map((task) => task.user_task_template)).size !== 10) {
    throw new Error('Generated Skill package/task boundary drift');
  }
}

export default class DashScopeOneShotProvider {
  constructor(options = {}) {
    this.fixtureFetch = options.fixtureFetch;
  }

  id() {
    return PROVIDER_ID;
  }

  async callApi(prompt) {
    const runDir = process.env.SKILL_GENERATION_RUN_DIR;
    const jobId = process.env.SKILL_GENERATION_JOB_ID;
    const mode = process.env.SKILL_GENERATION_MODE;
    if (!runDir || !jobId || !['live', 'offline-fixture'].includes(mode)) {
      throw new Error('Explicit generation run, job, and mode required');
    }
    if (mode === 'offline-fixture' && typeof this.fixtureFetch !== 'function') {
      throw new Error('Offline fixture requires an injected transport; no network request submitted');
    }
    const { plan, job } = requirePlan(runDir, jobId, prompt, mode);
    const key = process.env.DASHSCOPE_API_KEY;
    if (!key) {
      throw new Error('DASHSCOPE_API_KEY unavailable; no generation request submitted');
    }
    const attemptPath = join(runDir, 'attempt-' + jobId + '.json');
    const startedAt = new Date().toISOString();
    const attempt = { schema_version: 1, kind: 'generation-http-attempt',
      environment: mode, job_id: jobId, provider_id: PROVIDER_ID,
      model: MODEL, endpoint: BASE_URL + '/chat/completions',
      prompt_sha256: sha256(prompt), submitted_at: startedAt,
      status: 'reserved', raw_response_ref: null };
    // The exclusive file reservation is before fetch; Promptfoo retries hit EEXIST.
    const handle = openSync(attemptPath, 'wx');
    try {
      writeFileSync(handle, JSON.stringify(attempt));
    } finally {
      closeSync(handle);
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), plan.http_timeout_seconds * 1000);
    try {
      const transport = mode === 'live' ? fetch : this.fixtureFetch;
      const response = await transport(BASE_URL + '/chat/completions', {
        method: 'POST', redirect: 'error', signal: controller.signal,
        headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: MODEL, messages: [{ role: 'user', content: prompt }],
          temperature: 0.7, enable_thinking: false,
          max_tokens: plan.max_output_tokens, stream: false }),
      });
      attempt.http_status = response.status;
      if (response.status !== 200) {
        throw new Error('Generation HTTP status ' + response.status);
      }
      const raw = await response.json();
      const rawPath = join(runDir, 'raw-response-' + jobId + '.json');
      writeFileSync(rawPath, JSON.stringify(raw));
      attempt.raw_response_ref = { file: 'raw-response-' + jobId + '.json',
        sha256: sha256(readFileSync(rawPath)) };
      attempt.usage = raw.usage && typeof raw.usage === 'object' ? {
        prompt_tokens: raw.usage.prompt_tokens ?? null,
        completion_tokens: raw.usage.completion_tokens ?? null,
        total_tokens: raw.usage.total_tokens ?? null,
      } : null;
      if (attempt.usage?.prompt_tokens > plan.max_input_tokens ||
          attempt.usage?.completion_tokens > plan.max_output_tokens) {
        throw new Error('Reported generation token usage exceeded the approved cap');
      }
      const output = raw?.choices?.[0]?.message?.content;
      if (typeof output !== 'string' || !output) {
        throw new Error('Generation response content missing');
      }
      validateGeneratedPackage(output, job);
      attempt.status = 'completed';
      writeFileSync(attemptPath, JSON.stringify(attempt));
      return { output, tokenUsage: attempt.usage ? {
        prompt: attempt.usage.prompt_tokens,
        completion: attempt.usage.completion_tokens,
        total: attempt.usage.total_tokens,
      } : undefined };
    } catch (error) {
      attempt.status = 'error';
      attempt.error_type = error?.name || 'Error';
      writeFileSync(attemptPath, JSON.stringify(attempt));
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }
}
