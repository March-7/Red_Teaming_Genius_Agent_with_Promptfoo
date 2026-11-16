#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { createHash } from 'node:crypto';
import { I as CloudConfig, n as fetchWithRetries } from '../../node_modules/promptfoo/dist/src/fetch-tOnj-VPG.js';

const sha256 = (value) => createHash('sha256').update(value).digest('hex');

export function taskPayload(mode, input) {
  if (mode === 'create') {
    const required = ['case_id', 'row_id', 'case_nonce', 'prompt', 'goal', 'purpose'];
    if (Object.keys(input).sort().join(',') !== required.sort().join(',') ||
        required.some((key) => typeof input[key] !== 'string' || !input[key])) {
      throw new Error('exact synthetic receiver creation input required');
    }
    return { task: 'create-web-page', testCaseId: input.row_id,
      evalId: input.case_nonce, prompt: input.prompt, goal: input.goal,
      purpose: input.purpose, useLlm: false, preferSmallModel: true };
  }
  if (mode === 'query') {
    if (Object.keys(input).sort().join(',') !== ['eval_id', 'uuid'].join(',') ||
        typeof input.uuid !== 'string' || !input.uuid ||
        typeof input.eval_id !== 'string' || !input.eval_id) {
      throw new Error('exact receiver tracking query required');
    }
    return { task: 'get-web-page-tracking', uuid: input.uuid, evalId: input.eval_id };
  }
  throw new Error('receiver mode must be create or query');
}

function args(argv) {
  const value = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i]?.startsWith('--') || !argv[i + 1]) throw new Error('paired receiver arguments required');
    value[argv[i].slice(2)] = argv[i + 1];
  }
  if (!['create', 'query'].includes(value.mode) || !value.input || !value.output) {
    throw new Error('--mode create|query --input FILE --output NEW_FILE required');
  }
  return value;
}

async function main() {
  const options = args(process.argv.slice(2));
  const inputPath = path.resolve(options.input);
  const outputPath = path.resolve(options.output);
  if (fs.existsSync(outputPath)) throw new Error('new receiver output path required; zero retry');
  const rawInput = fs.readFileSync(inputPath);
  const input = JSON.parse(rawInput.toString('utf8'));
  const payload = taskPayload(options.mode, input);
  let response;
  let environment = 'live';
  const fixture = process.env.PROMPTFOO_RECEIVER_FIXTURE;
  if (fixture) {
    environment = 'offline-fixture';
    response = JSON.parse(fs.readFileSync(path.resolve(fixture), 'utf8'));
  } else {
    const cloud = new CloudConfig();
    const apiKey = cloud.getApiKey();
    const apiHost = cloud.getApiHost();
    const teams = cloud.config.teams || {};
    const organizationIds = Object.keys(teams);
    const organizationId = cloud.getCurrentOrganizationId() ||
      (organizationIds.length === 1 ? organizationIds[0] : undefined);
    const teamId = organizationId ?
      (cloud.getCurrentTeamId(organizationId) || teams[organizationId]?.currentTeamId) : undefined;
    if (!apiKey || !apiHost || !teamId) throw new Error('Promptfoo Cloud team authentication required');
    const request = await fetchWithRetries(apiHost.replace(/\/+$/, '') + '/api/v1/task', {
      method: 'POST', headers: { 'Content-Type': 'application/json',
        'x-promptfoo-team-id': teamId }, body: JSON.stringify(payload),
    }, 60000);
    if (!request.ok) throw new Error(`receiver task HTTP ${request.status}`);
    response = await request.json();
  }
  if (options.mode === 'create') {
    if (typeof response.uuid !== 'string' || !response.uuid ||
        typeof response.fullUrl !== 'string' || !response.fullUrl.startsWith('https://')) {
      throw new Error('receiver page identity missing');
    }
    const usage = response.tokenUsage;
    if (usage && Object.values(usage).some((value) => typeof value === 'number' && value !== 0)) {
      throw new Error('useLlm=false receiver creation unexpectedly used generation tokens');
    }
  } else if (typeof response.wasExfiltrated !== 'boolean' ||
             !Number.isInteger(response.exfilCount) || !Array.isArray(response.exfilRecords)) {
    throw new Error('receiver tracking response invalid');
  }
  const output = { schema_version: 1, kind: `skill-pilot-receiver-${options.mode}`,
    environment, input_sha256: sha256(rawInput), request_sha256: sha256(JSON.stringify(payload)),
    response, management_calls: 1, generation_calls: 0, judge_calls: 0, retry: 0 };
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  process.stdout.write(JSON.stringify({ kind: output.kind, environment,
    management_calls: 1, generation_calls: 0, judge_calls: 0 }) + '\n');
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
