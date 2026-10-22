// Opt-in proof against the pinned browser runtime, including backward seeks.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
// Proof-only use of a bundled export: tied to the exact 0.8.144 lockfile.
import { buildChromeArgs } from './node_modules/hyperframes/dist/src-VUJ2FUFK.js';
const require = createRequire(new URL('./node_modules/hyperframes/package.json', import.meta.url));
const puppeteer = require('puppeteer-core');
const project = process.argv[2];
const plan = JSON.parse(readFileSync(join(project, 'plan.json')));
const runtime = readFileSync(new URL('./node_modules/hyperframes/dist/hyperframe-runtime.js', import.meta.url), 'utf8');
const html = readFileSync(join(project, 'index.html'), 'utf8').replace(/<video\b[^>]*><\/video>/g, '');
const browser = await puppeteer.launch({
  executablePath: process.env.HYPERFRAMES_BROWSER_PATH, headless: true,
  args: [...buildChromeArgs({ width: plan.width, height: plan.height, captureMode: 'screenshot' }, { mode: 'software' }),
    '--disable-background-networking', '--proxy-server=http://127.0.0.1:9'],
});
try {
  const page = await browser.newPage();
  page.on('pageerror', e => console.error('page:', e.message));
  page.on('console', m => { if (m.type() === 'error') console.error('console:', m.text()); });
  await page.setViewport({ width: plan.width, height: plan.height });
  await page.setOfflineMode(true);
  await page.setContent(html);
  await page.addScriptTag({ content: runtime });
  await page.waitForFunction(() => Boolean(window.__player?.renderSeek), { timeout: 15000 });
  await page.evaluate(() => document.fonts.ready);
  const capabilities = await page.evaluate(() => ({
    webgl: Boolean(document.createElement('canvas').getContext('webgl')),
    webgl2: Boolean(document.createElement('canvas').getContext('webgl2')),
    fonts: [...document.fonts].map(f => ({ family: f.family, status: f.status })),
  }));
  if (capabilities.fonts.some(f => f.status !== 'loaded')) throw Error('Font did not load');
  const hashes = new Map();
  const samples = [];
  for (const frame of [6, 18, 30, 48, 54, 60, 72, 84, 30, 6, 84, 54, 18, 72, 48, 60]) {
    const time = frame / plan.fps;
    const state = await page.evaluate(async t => {
      window.__player.renderSeek(t, { exact: true });
      await window.__hfWaitForSeekCompletion?.();
      return [...document.querySelectorAll('.caption')].map(element => {
        const b = element.getBoundingClientRect();
        return { x: b.x, y: b.y, width: b.width, height: b.height };
      });
    }, time);
    // Flush style/layout before screenshot, as the CLI capture path does.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const animations = await page.evaluate(() => document.getAnimations().map(a => a.playState));
    if (animations.some(state => state === 'running')) throw Error('Caption animation was not paused after seeking');
    const hash = createHash('sha256').update(await page.screenshot()).digest('hex');
    if (hashes.has(frame) && hashes.get(frame) !== hash) throw Error(`Nondeterministic caption pixels at frame ${frame}`);
    hashes.set(frame, hash);
    for (const [i, e] of plan.captions.entries()) {
      if (time < e.start || time >= e.end) continue;
      let expected = e.box;
      if (e.path) {
        const right = e.path.findIndex(k => k.time >= time);
        const b = e.path[Math.max(1, right)], a = e.path[Math.max(1, right) - 1];
        const t = (time - a.time) / (b.time - a.time);
        expected = Object.fromEntries(Object.keys(a.box).map(k => [k, a.box[k] + (b.box[k] - a.box[k]) * t]));
      }
      for (const key of ['x', 'y', 'width', 'height']) {
        const scale = ['x', 'width'].includes(key) ? plan.width : plan.height;
        if (Math.abs(state[i][key] - expected[key] * scale) > 1) throw Error(`Caption geometry mismatch at frame ${frame}, ${key}`);
      }
    }
    samples.push({ frame, hash, boxes: state });
  }
  const result = { version: 1, caption_layer_only: true, offline_browser: true, capabilities, repeated_frames: hashes.size, samples };
  writeFileSync(join(project, 'seek-proof.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} finally { await browser.close(); }
