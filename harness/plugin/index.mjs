/** Closed proof-agent tool surface for DeepSeek Harness 0.1.2-rc.1. */
import { spawn } from 'node:child_process';
import { writeFile } from 'node:fs/promises';

export const name = 'mathai-review-tools';
export const inject = ['tools'];
const MODEL = 'labs-leanstral-1-5';
const string = { type: 'string' };
const strings = { type: 'array', items: string };
const object = { type: 'object', additionalProperties: true };

export const operations = {
  read_context: {
    description: 'Read current argument specification, exact revision, pending questions and candidate review state.',
    properties: {}, required: [],
  },
  queue_questions: {
    description: 'Queue several targeted questions for the human. Returns immediately; no answer or approval is inferred.',
    properties: { revision: string, questions: { type: 'array', items: { type: 'object', properties: { prompt: string, consequence: string }, required: ['prompt', 'consequence'], additionalProperties: false } } },
    required: ['revision', 'questions'],
  },
  create_branch: {
    description: 'Create an isolated provisional branch against the current revision with explicit hypothetical assumptions.',
    properties: { revision: string, question_ids: strings, hypotheses: strings },
    required: ['revision', 'question_ids', 'hypotheses'],
  },
  submit_candidate: {
    description: 'Store immutable candidate Lean text and review packet provisionally. Packet must enumerate every supported definition, type, hypothesis and internal have with context and dependency IDs. This does not approve any statement. Changed sources require a trusted human-prepared review baseline before execution.',
    properties: { revision: string, source: string, packet: object, filename: string, branch: string },
    required: ['revision', 'source', 'packet'],
  },
  check_candidate: {
    description: 'Run the fixed trusted checker on a stored candidate. Passing is independent of human approval. Arbitrary commands and supplied evidence are not accepted.',
    properties: { candidate: string }, required: ['candidate'],
  },
};

export function controllerCall(operation, args, signal, env = process.env) {
  if (!Object.hasOwn(operations, operation)) throw new Error('Unknown controller operation');
  for (const key of ['MATHAI_PYTHON', 'MATHAI_CONTROLLER', 'MATHAI_STATE']) {
    if (!env[key]) throw new Error(`Missing trusted configuration: ${key}`);
  }
  const childEnv = Object.fromEntries(Object.entries(env).filter(([key]) =>
    !/KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i.test(key)));
  return new Promise((resolve, reject) => {
    const child = spawn(env.MATHAI_PYTHON, [env.MATHAI_CONTROLLER, '--state', env.MATHAI_STATE, 'agent-rpc'], {
      cwd: env.MATHAI_WORKDIR, env: childEnv, stdio: ['pipe', 'pipe', 'pipe'], signal,
    });
    let stdout = '', stderr = '';
    const timeout = setTimeout(() => child.kill('SIGTERM'), 135_000);
    child.stdout.on('data', data => {
      stdout += data;
      if (stdout.length > 4_000_000) child.kill('SIGTERM');
    });
    child.stderr.on('data', data => { stderr = (stderr + data).slice(-4000); });
    child.once('error', error => { clearTimeout(timeout); reject(error); });
    child.once('close', code => {
      clearTimeout(timeout);
      try {
        const value = JSON.parse(stdout);
        if (code !== 0) reject(new Error(value.error || 'Controller rejected request'));
        else resolve(value);
      } catch (error) { reject(new Error('Controller returned no valid bounded result')); }
    });
    child.stdin.on('error', () => {});
    // The chosen operation wins over any unexpected argument of the same name.
    child.stdin.end(JSON.stringify({ ...args, operation }));
  });
}

export async function apply(ctx) {
  const allowed = Object.keys(operations).map(op => 'mathai_' + op);
  ctx.tools.guard(exec => allowed.includes(exec.name) ? undefined : 'Only the closed argument-review tool surface is allowed');
  for (const [operation, spec] of Object.entries(operations)) {
    ctx.tools.register({
      name: 'mathai_' + operation,
      description: spec.description,
      parameters: { type: 'object', properties: spec.properties, required: spec.required, additionalProperties: false },
      output: { schema: object, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
      execute: (args, exec) => controllerCall(operation, args, exec.signal),
    });
  }
  let requests = 0;
  const limit = Number(process.env.MATHAI_MAX_REQUESTS || '8');
  if (!Number.isInteger(limit) || limit < 1 || limit > 32) throw new Error('Request budget must be 1..32');
  ctx.on('agent/request', async (_event, next) => {
    if (process.env.MATHAI_OFFLINE === '1') throw new Error('Offline smoke test: inference prohibited');
    if (++requests > limit) throw new Error('Explicit request budget exhausted; no paid fallback');
    const config = await next();
    if (config.provider !== 'mistral' || config.model !== MODEL) throw new Error('Only the approved Leanstral route is allowed');
    return config;
  });
  if (process.env.MATHAI_SELFTEST_OUTPUT) {
    // Startup evidence: real registry surface and fixed controller IPC; no model.
    const context = await controllerCall('read_context', {}, new AbortController().signal);
    await writeFile(process.env.MATHAI_SELFTEST_OUTPUT, JSON.stringify({
      kind: 'offline-runtime-smoke', inference_calls: 0,
      tool_names: ctx.tools.schemas().map(tool => tool.name).sort(),
      revision: context.revision, model: MODEL,
    }, null, 2));
  }
}
