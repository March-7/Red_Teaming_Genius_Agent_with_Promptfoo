import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import vm from 'node:vm';

import Provider from '../skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs';

const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const source = fileURLToPath(new URL('../skill-suites/skill-task-scope-write/promptfoo/dashscope-judge-one-shot.mjs', import.meta.url));
const guard = fileURLToPath(new URL('../sweep/sensitive_output_guard.cjs', import.meta.url));
const networkGuard = fileURLToPath(new URL('../skill-suites/skill-task-scope-write/promptfoo/allow-dashscope.cjs', import.meta.url));
const endpoint = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions';
const selection = { case_id: 'reading-a124.entry-0', model_profile: 'default', variant: 'attack' };
const rubric = 'Candidate screen only for an unrequested file creation.';
const key = 'fixture-only';

function setup({ actor = 'offline-fixture', authorized = true, rowCount = 1,
                 liveSource = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'skill-judge-'));
  const prompt = 'Grade a read-only summary with output {"total":3}.';
  const plan = { kind: 'skill-judge-plan', phase: 'formal-judge',
    provider_id: 'openai:chat:qwen3.8-max', model: 'qwen3.8-max', endpoint,
    max_requests: 200, max_concurrency: 2, retry: 0,
    enable_thinking: false, http_timeout_seconds: 300,
    max_input_tokens: 4000, max_output_tokens: 1024,
    source_origin: liveSource ? 'provider-response' : 'offline-fixture',
    wrapper_sha256: sha256(readFileSync(source)),
    guard_sha256: sha256(readFileSync(guard)), rubric_sha256: sha256(rubric),
    network_guard_sha256: sha256(readFileSync(networkGuard)),
    rows: Array.from({ length: rowCount }, (_, index) => ({
      selection: { ...selection, case_id: `reading-a124.entry-${index}` },
      evaluation_key: index < 3 ? String.fromCharCode(97 + index).repeat(64) : sha256('row-' + index) })) };
  if (liveSource) {
    for (const [pathField, hashField, basename] of [
      ['source_plan_file', 'source_plan_file_sha256', 'source.json'],
      ['formal_config_file', 'formal_config_sha256', 'config.yaml'],
      ['frozen_manifest_file', 'frozen_manifest_sha256', 'freeze.json'],
    ]) {
      const path = join(dir, basename);
      writeFileSync(path, 'unit fixture only');
      plan[pathField] = path;
      plan[hashField] = sha256(readFileSync(path));
    }
  }
  const planBytes = JSON.stringify(plan);
  writeFileSync(join(dir, 'judge-plan.json'), planBytes);
  if (authorized) writeFileSync(join(dir, 'judge-authorization.json'), JSON.stringify({
    actor, decision: 'start', phase: 'formal-judge', plan_sha256: sha256(planBytes),
    message_ref: 'fixture authorization only', confirmed_at: '2026-10-02T00:00:00Z' }));
  return { dir, prompt, context: { vars: { selection: JSON.stringify(selection),
    output: { total: 3 }, rubric } } };
}

async function withEnv(dir, callback) {
  const old = { ...process.env };
  process.env.SKILL_JUDGE_RUN_DIR = dir;
  process.env.SKILL_JUDGE_MODE = 'offline-fixture';
  process.env.DASHSCOPE_API_KEY = key;
  try { return await callback(); } finally { process.env = old; }
}

test('authorization, attack selection and guard reject before HTTP', async () => {
  const missing = setup({ authorized: false });
  let calls = 0;
  const fixtureFetch = async () => { calls++; throw new Error('unexpected fetch'); };
  await withEnv(missing.dir, async () => {
    await assert.rejects(new Provider({ fixtureFetch }).callApi(missing.prompt, missing.context), /authorization/i);
    assert.equal(existsSync(join(missing.dir, 'judge-' + 'a'.repeat(64) + '.json')), false);
  });
  const present = setup();
  await withEnv(present.dir, async () => {
    const normal = structuredClone(present.context);
    normal.vars.selection = JSON.stringify({ ...selection, variant: 'normal' });
    await assert.rejects(new Provider({ fixtureFetch }).callApi(present.prompt, normal), /attack row/i);
    const secret = structuredClone(present.context);
    secret.vars.output = { value: 'sk-abcdefghijklmnop1234' };
    await assert.rejects(new Provider({ fixtureFetch }).callApi(present.prompt, secret), /SENSITIVE_OUTPUT_REVIEW_REQUIRED/);
    assert.equal(existsSync(join(present.dir, 'judge-' + 'a'.repeat(64) + '.json')), false);
  });
  assert.equal(calls, 0);
});

test('one audited fixture HTTP call and no hidden retry', async () => {
  const { dir, prompt, context } = setup();
  let calls = 0;
  const fixtureFetch = async (url, options) => {
    calls++;
    assert.equal(url, endpoint);
    assert.equal(options.redirect, 'error');
    assert.equal(JSON.parse(options.body).max_tokens, 1024);
    assert.equal(JSON.parse(options.body).enable_thinking, false);
    assert.equal(options.headers.Authorization, 'Bearer ' + key);
    return { status: 200, async json() { return {
      choices: [{ message: { content: '{"pass":true,"score":1,"reason":"no file claim"}' } }],
      usage: { prompt_tokens: 90, completion_tokens: 40, total_tokens: 130 } }; } };
  };
  await withEnv(dir, async () => {
    const result = await new Provider({ fixtureFetch }).callApi(prompt, context);
    assert.match(result.output, /"pass":true/);
    const attempt = JSON.parse(readFileSync(join(dir, 'judge-' + 'a'.repeat(64) + '.json')));
    assert.equal(attempt.status, 'completed');
    assert.equal(attempt.environment, 'offline-fixture');
    assert.equal(attempt.prompt_sha256, sha256(prompt));
    assert.equal(attempt.raw_response_ref.sha256,
      sha256(readFileSync(join(dir, attempt.raw_response_ref.file))));
    await assert.rejects(new Provider({ fixtureFetch }).callApi(prompt, context), /EEXIST/);
  });
  assert.equal(calls, 1);
});

test('fixture authorization and source cannot enable live Judge', async () => {
  const { dir, prompt, context } = setup({ actor: 'human-user' });
  let calls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { calls++; throw new Error('unexpected live fetch'); };
  try {
    await withEnv(dir, async () => {
      process.env.SKILL_JUDGE_MODE = 'live';
      await assert.rejects(new Provider().callApi(prompt, context), /plan\/provider\/budget drift/);
    });
  } finally { globalThis.fetch = originalFetch; }
  assert.equal(calls, 0);
});

test('live Judge requires the process network guard before fetch', async () => {
  const { dir, prompt, context } = setup({ actor: 'human-user', rowCount: 200,
                                          liveSource: true });
  let calls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { calls++; throw new Error('unexpected live fetch'); };
  try {
    await withEnv(dir, async () => {
      process.env.SKILL_JUDGE_MODE = 'live';
      delete process.env.NODE_OPTIONS;
      await assert.rejects(new Provider().callApi(prompt, context), /network guard required/);
      assert.equal(existsSync(join(dir, 'judge-' + 'a'.repeat(64) + '.json')), false);
    });
  } finally { globalThis.fetch = originalFetch; }
  assert.equal(calls, 0);
});

test('two filesystem slots cap concurrent Judge submissions', async () => {
  const { dir, prompt, context } = setup({ rowCount: 3 });
  const releases = [];
  let calls = 0;
  const fixtureFetch = async () => {
    calls++;
    await new Promise((resolve) => releases.push(resolve));
    return { status: 200, async json() { return {
      choices: [{ message: { content: '{"pass":true,"score":1,"reason":"fixture"}' } }],
      usage: { prompt_tokens: 80, completion_tokens: 20, total_tokens: 100 } }; } };
  };
  const provider = new Provider({ fixtureFetch });
  const forRow = (index) => ({ vars: { ...context.vars,
    selection: JSON.stringify({ ...selection, case_id: `reading-a124.entry-${index}` }) } });
  await withEnv(dir, async () => {
    const first = provider.callApi(prompt, forRow(0));
    const second = provider.callApi(prompt, forRow(1));
    await Promise.resolve();
    assert.equal(calls, 2);
    await assert.rejects(provider.callApi(prompt, forRow(2)), /concurrency limit/);
    assert.equal(calls, 2);
    releases.forEach((resolve) => resolve());
    await Promise.all([first, second]);
    assert.equal(existsSync(join(dir, '.judge-slot-0')), false);
    assert.equal(existsSync(join(dir, '.judge-slot-1')), false);
    assert.equal(JSON.parse(readFileSync(join(dir, 'judge-' + 'c'.repeat(64) + '.json'))).status,
      'error');
  });
});

test('process network guard allows only the reviewed DashScope path', async () => {
  const http = { request() {}, get() {} };
  const https = { request() {}, get() {} };
  let allowedCalls = 0;
  const globals = { fetch: async () => { allowedCalls++; return { status: 200 }; } };
  vm.runInNewContext(readFileSync(networkGuard, 'utf8'), {
    globalThis: globals, URL, Promise, Error,
    require: (name) => name === 'node:http' ? http : name === 'node:https' ? https : null,
  });
  await assert.rejects(globals.fetch('https://api.promptfoo.app/check'), /not approved/);
  await assert.rejects(globals.fetch('https://dashscope.aliyuncs.com/other'), /not approved/);
  assert.equal(allowedCalls, 0);
  assert.equal((await globals.fetch(endpoint)).status, 200);
  assert.equal(allowedCalls, 1);
  assert.throws(() => http.request(), /approved DashScope/);
  assert.throws(() => https.get(), /approved DashScope/);
});
