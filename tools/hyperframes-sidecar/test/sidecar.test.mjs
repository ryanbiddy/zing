import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { validatePlan, planRate } from '../plan.mjs';
import { composition } from '../templates.mjs';

const example = JSON.parse(readFileSync(new URL('../example-plan.json', import.meta.url)));
test('valid plan survives normalization without input mutation', () => {
  const before = structuredClone(example);
  assert.equal(validatePlan(example, process.cwd(), false).captions.length, 2);
  assert.deepEqual(example, before);
});
test('exact rational fps survives the plan and HTML contract', () => {
  const p = structuredClone(example);
  p.fps = '30000/1001'; p.duration = 3.003;
  assert.equal(validatePlan(p, process.cwd(), false).fps, '30000/1001');
  assert.deepEqual(planRate(p.fps), { numerator: 30000, denominator: 1001, value: 30000 / 1001 });
  p.duration = 3;
  assert.throws(() => validatePlan(p, process.cwd(), false), /whole number of frames/);
});
for (const fps of [true, '30', '30/0', '-30/1', '30000000000/1000000001', 121]) {
  test(`refuses invalid rate ${fps}`, () => assert.throws(() => planRate(fps), /fps/));
}
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
const font = '../../zing-workspace/hyperframes/fonts/Anton-Regular.ttf';
const style = { font, size: 64, color: '#ffffff', accent: '#ff3d00' };
const withGraphics = () => ({ ...structuredClone(example), graphics: [
  { start: 0, end: 1.5, template: 'title-card', box: { x: 0.1, y: 0.1, width: 0.8, height: 0.4 }, text: ['BIG IDEA', 'small print'], style: { ...style } },
  { start: 0.5, end: 2.5, template: 'lower-third', box: { x: 0.05, y: 0.7, width: 0.6, height: 0.2 }, text: ['Ada Lovelace'], style: { ...style, size: 32 } },
  { start: 1, end: 2, template: 'callout', box: { x: 0.6, y: 0.1, width: 0.35, height: 0.2 }, text: ['WAIT'], style: { ...style, size: 28 } },
  { start: 0, end: 3, template: 'progress-bar', box: { x: 0, y: 0.98, width: 1, height: 0.02 }, text: [], style: { color: '#ffffff', accent: '#ff3d00' } },
] });
test('graphics plan validates every template without input mutation', () => {
  const p = withGraphics(), before = structuredClone(p);
  assert.deepEqual(validatePlan(p, process.cwd(), false).graphics.map(g => g.template), ['title-card', 'lower-third', 'callout', 'progress-bar']);
  assert.deepEqual(p, before);
  assert.equal('graphics' in validatePlan(example, process.cwd(), false), false);
});
for (const [name, change] of [
  ['unknown graphic template', p => { p.graphics[0].template = 'starburst'; }],
  ['unknown graphic field', p => { p.graphics[0].easing = 'bounce'; }],
  ['too many lines', p => { p.graphics[2].text.push('MORE'); }],
  ['missing line', p => { p.graphics[1].text = []; }],
  ['blank line', p => { p.graphics[1].text = ['  ']; }],
  ['control character', p => { p.graphics[1].text = ['a\nb']; }],
  ['font on a textless bar', p => { p.graphics[3].style.font = font; }],
  ['size on a textless bar', p => { p.graphics[3].style.size = 10; }],
  ['text without a font', p => { delete p.graphics[0].style.font; }],
  ['WOFF graphic font', p => { p.graphics[0].style.font = 'a.woff2'; }],
  ['accent injection', p => { p.graphics[0].style.accent = 'red;background:url(https://example.com)'; }],
  ['graphic outside frame', p => { p.graphics[0].box.x = 0.5; }],
  ['graphic interval', p => { p.graphics[0].end = 0; }],
  ['graphic past duration', p => { p.graphics[0].end = 4; }],
  ['graphics not an array', p => { p.graphics = {}; }],
]) test(`refuses ${name}`, () => {
  const p = withGraphics(); change(p);
  assert.throws(() => validatePlan(p, process.cwd(), false));
});
test('graphics render beneath captions with escaped text, shared fonts and seekable CSS', () => {
  const root = mkdtempSync(join(tmpdir(), 'hf-graphics-'));
  try {
    const fontFile = join(root, 'font.ttf'); writeFileSync(fontFile, 'fake font');
    const p = withGraphics();
    p.captions.forEach(e => { e.style.font = fontFile; });
    p.graphics.filter(g => g.text.length).forEach(g => { g.style.font = fontFile; });
    p.graphics[0].text[0] = '</div><script>alert("x")</script>';
    const html = composition(validatePlan(p));
    assert.ok(!html.includes('<script>alert'));
    assert.ok(html.includes('&lt;/div&gt;&lt;script&gt;'));
    assert.equal(html.match(/font-family:ZingGraphicFont\d+;src/g).length, 1);
    assert.ok(html.indexOf('id="graphic-3"') < html.indexOf('id="caption-0"'));
    for (const name of ['g0in', 'g0bar', 'g1plate', 'g1text', 'g2pop', 'g3fill']) assert.ok(html.includes(`@keyframes ${name}{`), name);
    assert.ok(html.includes('id="graphic-0" class="graphic title-card" data-start="0" data-duration="1.5"'));
    assert.ok(html.includes('animation:g3fill 3s linear 0s 1 both;'));
    assert.ok(html.includes('background:#ffffff4d;border-radius:3.6px;'));
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
