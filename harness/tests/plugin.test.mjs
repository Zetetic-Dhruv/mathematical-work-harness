/** Offline tests of the custom deployment plugin, never model calls. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { apply, operations, controllerCall } from '../plugin/index.mjs';

async function configured() {
  const registered = [], hooks = {};
  let guard;
  const ctx = { tools: { register: spec => registered.push(spec), guard: fn => { guard = fn; } }, on: (name, fn) => { hooks[name] = fn; } };
  await apply(ctx);
  return { registered, hooks, guard };
}

test('only five closed tools are defined', async () => {
  const { registered } = await configured();
  assert.equal(registered.length, 5);
  assert.deepEqual(registered.map(t => t.name), Object.keys(operations).map(op => 'mathai_' + op));
  for (const tool of registered) assert.equal(tool.parameters.additionalProperties, false);
});

test('monotonic guard denies shell, editor, approval and evidence import', async () => {
  const { guard } = await configured();
  for (const name of ['bash', 'str_replace_editor', 'run_code', 'approve', 'mathai_approve', 'import_verification']) assert.equal(typeof guard({ name }), 'string');
  assert.equal(guard({ name: 'mathai_check_candidate' }), undefined);
});

test('offline mode refuses a request before provider dispatch', async () => {
  process.env.MATHAI_OFFLINE = '1';
  try {
    const { hooks } = await configured();
    let reached = false;
    await assert.rejects(hooks['agent/request']({}, async () => { reached = true; }), /inference prohibited/);
    assert.equal(reached, false);
  } finally { delete process.env.MATHAI_OFFLINE; }
});

test('unapproved model or route is refused', async () => {
  const { hooks } = await configured();
  for (const config of [{ provider: 'openai', model: 'labs-leanstral-1-5' }, { provider: 'mistral', model: 'paid-model' }]) await assert.rejects(hooks['agent/request']({}, async () => config), /approved Leanstral/);
});

test('request count is bounded even if the model keeps calling tools', async () => {
  process.env.MATHAI_MAX_REQUESTS = '2';
  try {
    const { hooks } = await configured();
    const config = { provider: 'mistral', model: 'labs-leanstral-1-5' };
    assert.equal(await hooks['agent/request']({}, async () => config), config);
    assert.equal(await hooks['agent/request']({}, async () => config), config);
    await assert.rejects(hooks['agent/request']({}, async () => config), /budget exhausted/);
  } finally { delete process.env.MATHAI_MAX_REQUESTS; }
});

test('invalid request caps fail at plugin load', async () => {
  process.env.MATHAI_MAX_REQUESTS = '0';
  try { await assert.rejects(configured(), /1..32/); }
  finally { delete process.env.MATHAI_MAX_REQUESTS; }
});

test('IPC exposes no human operation or executable selection', () => {
  assert.throws(() => controllerCall('approve', {}, undefined, {}), /Unknown/);
  assert.throws(() => controllerCall('read_context', {}, undefined, {}), /trusted configuration/);
});
