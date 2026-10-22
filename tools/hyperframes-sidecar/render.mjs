import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync, mkdtempSync, rmSync, realpathSync } from 'node:fs';
import { dirname, resolve, join, extname, delimiter, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { createRequire } from 'node:module';
import { validatePlan } from './plan.mjs';
import { composition } from './templates.mjs';
import { reserveOutput, publishPair } from './publish.mjs';

const here = dirname(fileURLToPath(import.meta.url));
export const VERSION = '0.8.144';

function executable(name) {
  const configured = process.env[`HYPERFRAMES_${name.toUpperCase()}_PATH`];
  const candidates = configured ? [configured] : (process.env.PATH ?? '').split(delimiter).flatMap(dir =>
    process.platform === 'win32' ? [join(dir, name + '.exe')] : [join(dir, name)]);
  const found = candidates.find(p => existsSync(p));
  if (!found) throw Error(`Missing ${name}; install FFmpeg or set HYPERFRAMES_${name.toUpperCase()}_PATH`);
  return realpathSync(found);
}

export function render(planFile, outputFile, { overwrite = false, workspace = process.env.ZING_HOME ?? resolve(here, '../../zing-workspace') } = {}) {
  const output = resolve(outputFile);
  const release = reserveOutput(output, overwrite);
  let job;
  const owned = !process.env.ZING_HF_JOB;
  try {
    if (owned) {
      const jobs = join(resolve(workspace), 'hyperframes/jobs');
      mkdirSync(jobs, { recursive: true });
      job = mkdtempSync(join(jobs, 'hf-job-'));
    } else {
      // Internal Python wrapper owns this already-created job and its cleanup.
      job = realpathSync(process.env.ZING_HF_JOB);
      const jobs = realpathSync(join(resolve(process.env.ZING_HF_WORKSPACE ?? workspace), 'hyperframes/jobs'));
      if (!job.startsWith(jobs + sep) || dirname(output) !== job) throw Error('Internal job and staged output must lie under the Zing workspace jobs folder');
    }
    const receipt = renderJob(planFile, output, job);
    receipt.work_cleaned = true;
    publishPair(join(job, 'encoded' + extname(output).toLowerCase()), output, receipt, overwrite);
    if (owned) rmSync(job, { recursive: true });
    return receipt;
  } catch (error) {
    throw Error(`${error.message}${job ? `; job retained at ${job}` : ''}`);
  } finally { release(); }
}

function renderJob(planFile, output, job) {
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
  const format = p.background.transparent ? 'mov' : 'mp4';
  if (extname(output).toLowerCase() !== '.' + format) throw Error(`Output must use .${format} for this background mode`);
  const encoded = join(job, 'encoded.' + format);
  const project = join(job, 'project');
  mkdirSync(project);
  const localHome = join(project, 'home');
  mkdirSync(localHome, { recursive: true });
  const temporary = join(job, 'tmp');
  mkdirSync(temporary, { recursive: true });
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
    ZING_HF_NETWORK_LOG: networkLog, TEMP: temporary, TMP: temporary, TMPDIR: temporary,
    HYPERFRAMES_FFMPEG_PATH: executable('ffmpeg'), HYPERFRAMES_FFPROBE_PATH: executable('ffprobe') };
  // Credentials are irrelevant to local rendering and never passed to the CLI.
  for (const key of Object.keys(env)) if (/API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL/i.test(key)) delete env[key];
  delete env.NODE_OPTIONS;
  const args = ['--require', join(here, 'offline.cjs'), join(here, 'node_modules/hyperframes/bin/hyperframes.mjs'),
    'render', project, '--output', encoded, '--format', format, '--fps', String(p.fps), '--workers', '1', '--quality', 'looks',
    '--no-browser-gpu', '--experimental-fast-capture=false'];
  const result = spawnSync(process.execPath, args, { env, cwd: project, encoding: 'utf8', windowsHide: true, maxBuffer: 16 * 1024 * 1024 });
  writeFileSync(join(project, 'render.log'), (result.stdout ?? '') + (result.stderr ?? ''));
  if (result.error || result.status !== 0 || !existsSync(encoded)) throw Error(`HyperFrames render failed; inspect ${join(project, 'render.log')}: ${result.error?.message ?? result.stderr?.slice(-1800)}`);
  if (existsSync(networkLog)) throw Error(`Unexpected network attempt; render rejected. Inspect ${networkLog}`);
  const probeResult = spawnSync(env.HYPERFRAMES_FFPROBE_PATH, ['-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_streams', '-show_format', '-of', 'json', encoded], { encoding: 'utf8', windowsHide: true, timeout: 60000 });
  const probe = JSON.parse(probeResult.stdout || '{}'), video = probe.streams?.[0];
  const rate = video?.avg_frame_rate?.split('/').map(Number);
  if (probeResult.status !== 0 || !video || video.width !== p.width || video.height !== p.height ||
      !rate || !Number.isFinite(rate[0] / rate[1]) || Math.abs(rate[0] / rate[1] - p.fps) > 1e-6 || Number(video.nb_read_frames) !== Math.round(p.duration * p.fps) ||
      !Number.isFinite(Number(video.duration ?? probe.format?.duration)) ||
      Math.abs(Number(video.duration ?? probe.format?.duration) - p.duration) > 1 / p.fps + 1e-6 ||
      (format === 'mov' && (video.codec_name !== 'prores' || !video.pix_fmt.startsWith('yuva444p')))) throw Error('Output probe differs from plan or lacks ProRes alpha');
  let seekProof;
  if (process.env.ZING_HF_VERIFY_SEEKS === '1') {
    const seek = spawnSync(process.execPath, ['--require', join(here, 'offline.cjs'), join(here, 'verify-seeks.mjs'), project], { env, encoding: 'utf8', windowsHide: true, timeout: 60000 });
    if (seek.status !== 0) throw Error(`Seek verification failed: ${seek.stderr}`);
    seekProof = JSON.parse(readFileSync(join(project, 'seek-proof.json')));
  }
  if (existsSync(networkLog)) throw Error(`Unexpected network attempt; inspect ${networkLog}`);
  const receipt = { version: 1, hyperframes: VERSION, node: process.version, browser, output, plan: p, probe, seek_proof: seekProof,
    seconds: (performance.now() - started) / 1000, external_node_requests: 0,
    browser_network: 'external proxy denied; loopback only; composition CSP', mode: 'software, no shader effects' };
  return receipt;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (![4, 5].includes(process.argv.length) || (process.argv.length === 5 && process.argv[4] !== '--overwrite')) throw Error('Usage: node render.mjs PLAN.json OUTPUT.mp4|OUTPUT.mov [--overwrite]');
    console.log(JSON.stringify(render(process.argv[2], process.argv[3], { overwrite: process.argv[4] === '--overwrite' })));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
