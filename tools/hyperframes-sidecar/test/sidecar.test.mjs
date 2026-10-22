import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { validatePlan } from '../plan.mjs';
import { composition } from '../templates.mjs';

const example = JSON.parse(readFileSync(new URL('../example-plan.json', import.meta.url)));
test('valid plan survives normalization without input mutation', () => {
  const before = structuredClone(example);
  assert.equal(validatePlan(example, process.cwd(), false).captions.length, 2);
  assert.deepEqual(example, before);
});
for (const [name, change] of [
  ['nonfinite', p => { p.duration = NaN; }],
  ['unknown shader', p => { p.shader = 'wipe'; }],
  ['URL', p => { p.background = { video: 'https://example.com/a.mp4' }; }],
  ['UNC', p => { p.background = { video: '\\\\server\\a.mp4' }; }],
  ['color injection', p => { p.captions[0].style.color = 'red;background:url(https://example.com)'; }],
  ['word interval', p => { p.captions[0].words[0].end = 0.2; }],
  ['word overlap', p => { p.captions[0].words[1].start = 0.5; }],
  ['path order', p => { p.captions[1].path.reverse(); }],
  ['bounds', p => { p.captions[0].box.x = 0.5; }],
  ['double position', p => { p.captions[1].box = p.captions[0].box; }],
  ['fractional fps', p => { p.fps = 29.97; }],
]) test(`refuses ${name}`, () => {
  const p = structuredClone(example); change(p);
  assert.throws(() => validatePlan(p, process.cwd(), false));
});
test('templates escape authored text and embed font bytes', () => {
  const root = mkdtempSync(join(tmpdir(), 'hf-template-'));
  try {
    const font = join(root, 'font.ttf'); writeFileSync(font, 'fake font');
    const p = structuredClone(example);
    p.captions.forEach(e => { e.style.font = font; });
    p.captions[0].words[0].text = '</span><script>alert("x")</script>&';
    const html = composition(validatePlan(p));
    assert.ok(!html.includes('<script>alert'));
    assert.ok(html.includes('&lt;script&gt;'));
    assert.ok(html.includes('data:font/ttf;base64,'));
    assert.ok(html.includes('animation:path1 1.2999999999999998s linear 0s'));
    assert.ok(!/Date\.now|Math\.random|requestAnimationFrame|https?:\/\//.test(html));
  } finally { rmSync(root, { recursive: true }); }
});
test('offline preload blocks fetch, sockets, and TLS before external access', () => {
  const script = `
    const assert = require('node:assert/strict');
    assert.throws(() => fetch('https://example.invalid/'), /Offline render blocked/);
    assert.throws(() => require('node:net').connect(80, '198.51.100.1'), /Offline render blocked/);
    assert.throws(() => require('node:tls').connect({port:443,host:'example.invalid'}), /Offline render blocked/);
  `;
  const result = spawnSync(process.execPath, ['--require', new URL('../offline.cjs', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'), '-e', script], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
});
