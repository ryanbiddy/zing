import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync, mkdtempSync } from 'node:fs';
import { dirname, resolve, join, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { createRequire } from 'node:module';
import { validatePlan } from './plan.mjs';
import { composition } from './templates.mjs';

const here = dirname(fileURLToPath(import.meta.url));
export const VERSION = '0.8.144';

export function render(planFile, outputFile) {
  const started = performance.now();
  if (Number(process.versions.node.split('.')[0]) < 24) throw Error('Install Node.js 24 or newer, then retry.');
  const p = validatePlan(JSON.parse(readFileSync(planFile, 'utf8')), dirname(resolve(planFile)));
  const pkg = join(here, 'node_modules/hyperframes/package.json');
  if (!existsSync(pkg) || JSON.parse(readFileSync(pkg)).version !== VERSION) throw Error('Missing pinned sidecar install; run npm ci --ignore-scripts in tools/hyperframes-sidecar.');
  const fontkit = createRequire(pkg)('fontkit');
  for (const event of p.captions) {
    let font;
    try { font = fontkit.openSync(event.style.font); }
    catch { throw Error(`Cannot decode font ${event.style.font}; pass a valid TTF/OTF/WOFF font or run npm run fetch-font.`); }
    for (const c of event.words.map(w => w.text).join(' ')) {
      if (!font.hasGlyphForCodePoint(c.codePointAt(0))) throw Error(`Font ${event.style.font} lacks U+${c.codePointAt(0).toString(16)}; pass a font covering every caption character.`);
    }
  }
  const browser = process.env.HYPERFRAMES_BROWSER_PATH;
  if (!browser || !existsSync(browser)) throw Error('Missing browser; set HYPERFRAMES_BROWSER_PATH to a local chrome-headless-shell executable. See docs/HYPERFRAMES-SIDECAR.md for the pinned download command.');
  const output = resolve(outputFile);
  if (extname(output).toLowerCase() !== '.mp4') throw Error('Output must use .mp4');
  if (existsSync(output)) throw Error(`Output already exists: ${output}; choose a new path.`);
  mkdirSync(dirname(output), { recursive: true });
  const project = mkdtempSync(join(dirname(output), 'hf-project-'));
  const localHome = join(project, 'home');
  mkdirSync(localHome, { recursive: true });
  const videoName = `background${extname(p.background.video ?? '.mp4')}`;
  if (p.background.video) {
    if (!/\.(mp4|mov|mkv|webm)$/i.test(p.background.video)) throw Error('Video must be a local MP4, MOV, MKV or WebM; playlists and remote protocols are unsupported.');
    const probe = spawnSync(process.env.HYPERFRAMES_FFPROBE_PATH ?? 'ffprobe', ['-v', 'error', '-protocol_whitelist', 'file,pipe', '-select_streams', 'v:0', '-show_streams', '-show_format', '-of', 'json', p.background.video], { encoding: 'utf8', windowsHide: true, timeout: 30000 });
    let media;
    try { media = JSON.parse(probe.stdout); } catch { /* fail below */ }
    const stream = media?.streams?.[0];
    if (probe.status !== 0 || !stream || Number(stream.duration ?? media.format?.duration) + 1e-6 < p.duration) throw Error('Video could not be probed or is shorter than the plan; supply a decodable local video covering the full duration.');
    if (['smpte2084', 'arib-std-b67'].includes(stream.color_transfer)) throw Error('PH supports SDR video only; convert HDR to an explicitly chosen SDR look before rendering.');
    copyFileSync(p.background.video, join(project, videoName));
  }
  writeFileSync(join(project, 'index.html'), composition(p, videoName));
  writeFileSync(join(project, 'plan.json'), JSON.stringify(p, null, 2) + '\n');
  const networkLog = join(project, 'blocked-network.log');
  const env = { ...process.env, ZING_HF_RUNTIME_HOME: localHome,
    HYPERFRAMES_NO_TELEMETRY: '1', DO_NOT_TRACK: '1', HYPERFRAMES_NO_UPDATE_CHECK: '1', HYPERFRAMES_NO_AUTO_INSTALL: '1',
    PRODUCER_HEADLESS_SHELL_PATH: browser,
    HYPERFRAMES_FONT_CACHE_DIR: join(project, 'font-cache'), HYPERFRAMES_EXTRACT_CACHE_DIR: join(project, 'frame-cache'),
    ZING_HF_NETWORK_LOG: networkLog };
  // Credentials are irrelevant to local rendering and never passed to the CLI.
  for (const key of Object.keys(env)) if (/API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i.test(key)) delete env[key];
  delete env.NODE_OPTIONS;
  const args = ['--require', join(here, 'offline.cjs'), join(here, 'node_modules/hyperframes/bin/hyperframes.mjs'),
    'render', project, '--output', output, '--fps', String(p.fps), '--workers', '1', '--quality', 'looks',
    '--no-browser-gpu', '--experimental-fast-capture=false'];
  const result = spawnSync(process.execPath, args, { env, cwd: project, encoding: 'utf8', windowsHide: true, maxBuffer: 16 * 1024 * 1024 });
  writeFileSync(join(project, 'render.log'), (result.stdout ?? '') + (result.stderr ?? ''));
  if (result.error || result.status !== 0 || !existsSync(output)) throw Error(`HyperFrames render failed; inspect ${join(project, 'render.log')}: ${result.error?.message ?? result.stderr?.slice(-1800)}`);
  if (existsSync(networkLog)) throw Error(`Unexpected network attempt; render rejected. Inspect ${networkLog}`);
  const receipt = { version: 1, hyperframes: VERSION, node: process.version, browser, output, project,
    seconds: (performance.now() - started) / 1000, external_node_requests: 0,
    browser_network: 'external proxy denied; loopback only; composition CSP', mode: 'software, no shader effects' };
  writeFileSync(output + '.receipt.json', JSON.stringify(receipt, null, 2) + '\n');
  return receipt;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length !== 4) throw Error('Usage: node render.mjs PLAN.json OUTPUT.mp4');
    console.log(JSON.stringify(render(process.argv[2], process.argv[3])));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
