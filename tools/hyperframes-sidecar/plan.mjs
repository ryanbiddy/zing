// PH v1 is an adapter input, not Zing's future composition v2.
import { isAbsolute, resolve } from 'node:path';
import { statSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

function object(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error(`${label}: expected object`);
  const unknown = Object.keys(value).filter(k => !keys.includes(k));
  if (unknown.length) throw Error(`${label}: unsupported fields ${unknown.join(', ')}`);
}
function number(value, lo, hi, label) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < lo || value > hi) {
    throw Error(`${label}: expected finite number in [${lo}, ${hi}]`);
  }
}
function color(value, label) {
  if (typeof value !== 'string' || !/^#[0-9a-fA-F]{6}$/.test(value)) throw Error(`${label}: use #RRGGBB`);
}
function asset(value, base, label, checkFiles) {
  if (typeof value !== 'string' || !value || /[\x00-\x1f]/.test(value) || /^(?:[a-z]+:)?\/\//i.test(value) || /^(?:https?|data|file):/i.test(value) || value.startsWith('\\\\')) {
    throw Error(`${label}: use a local file path, not a URL or network share`);
  }
  const path = isAbsolute(value) ? value : resolve(base, value);
  if (checkFiles) {
    try { if (!statSync(path).isFile()) throw Error(); }
    catch { throw Error(`${label}: missing file ${path}; supply an existing local file (see docs/HYPERFRAMES-SIDECAR.md)`); }
  }
  return path;
}
function box(value, label) {
  object(value, ['x', 'y', 'width', 'height'], label);
  for (const key of ['x', 'y', 'width', 'height']) number(value[key], 0, 1, `${label}.${key}`);
  if (!value.width || !value.height || value.x + value.width > 1 + 1e-9 || value.y + value.height > 1 + 1e-9) throw Error(`${label}: box must fit within the frame`);
}

export function planRate(value) {
  const parts = typeof value === 'string' && /^[1-9][0-9]*\/[1-9][0-9]*$/.test(value)
    ? value.split('/').map(Number) : [value, 1];
  if (!parts.every(n => Number.isSafeInteger(n) && n > 0 && n <= 2147483647)) {
    throw Error('fps: use an integer or an exact numerator/denominator string');
  }
  const rate = parts[0] / parts[1];
  number(rate, 1, 120, 'fps');
  return { numerator: parts[0], denominator: parts[1], value: rate };
}

export function validatePlan(input, base = process.cwd(), checkFiles = true) {
  const p = structuredClone(input);
  object(p, ['version', 'width', 'height', 'fps', 'duration', 'background', 'captions'], 'plan');
  if (p.version !== 1) throw Error('plan.version: only PH version 1 is supported');
  for (const k of ['width', 'height']) {
    number(p[k], 2, 4096, k);
    if (p[k] % 2) throw Error(`${k}: use an even integer for H.264`);
  }
  const rate = planRate(p.fps).value;
  number(p.duration, 1 / rate, 600, 'duration');
  if (Math.abs(p.duration * rate - Math.round(p.duration * rate)) > 1e-7) throw Error('duration: must be a whole number of frames');
  object(p.background, ['color', 'video', 'transparent'], 'background');
  if (Object.keys(p.background).length !== 1) throw Error('background: choose exactly one of color, video or transparent');
  if ('transparent' in p.background) {
    if (p.background.transparent !== true) throw Error('background.transparent: must be true');
  } else if ('color' in p.background) color(p.background.color, 'background.color');
  else p.background.video = asset(p.background.video, base, 'background.video', checkFiles);
  if (!Array.isArray(p.captions)) throw Error('captions: expected array');
  for (const [i, e] of p.captions.entries()) {
    const label = `captions[${i}]`;
    object(e, ['start', 'end', 'template', 'words', 'box', 'path', 'style'], label);
    number(e.start, 0, p.duration, `${label}.start`);
    number(e.end, 0, p.duration, `${label}.end`);
    if (e.end <= e.start) throw Error(`${label}: end must follow start`);
    if (!['phrase-highlight', 'kinetic'].includes(e.template)) throw Error(`${label}: unknown template`);
    if (('box' in e) === ('path' in e)) throw Error(`${label}: choose exactly one box or path`);
    if (e.box) box(e.box, `${label}.box`);
    else {
      if (!Array.isArray(e.path) || e.path.length < 2) throw Error(`${label}.path: need at least two keyframes`);
      let previous = -1;
      for (const k of e.path) {
        object(k, ['time', 'box'], `${label}.path`);
        number(k.time, e.start, e.end, `${label}.path.time`);
        if (k.time <= previous) throw Error(`${label}.path: times must increase`);
        box(k.box, `${label}.path.box`); previous = k.time;
      }
      if (e.path[0].time !== e.start || e.path.at(-1).time !== e.end) throw Error(`${label}.path: first/last times must match event start/end`);
    }
    const s = e.style;
    object(s, ['font', 'font_sha256', 'size', 'color', 'highlight', 'outline_color', 'outline_width', 'box_color'], `${label}.style`);
    s.font = asset(s.font, base, `${label}.style.font`, checkFiles);
    if ('font_sha256' in s) {
      if (typeof s.font_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(s.font_sha256)) throw Error(`${label}: invalid font SHA-256`);
      if (checkFiles && createHash('sha256').update(readFileSync(s.font)).digest('hex') !== s.font_sha256) throw Error(`${label}: font SHA-256 mismatch; restore the declared font file`);
    }
    if (!/\.(ttf|otf|woff2?)$/i.test(s.font)) throw Error(`${label}.style.font: use TTF, OTF, WOFF or WOFF2`);
    number(s.size, 1, 512, `${label}.style.size`);
    number(s.outline_width, 0, 20, `${label}.style.outline_width`);
    for (const key of ['color', 'highlight', 'outline_color']) color(s[key], `${label}.style.${key}`);
    if ('box_color' in s) color(s.box_color, `${label}.style.box_color`);
    if (!Array.isArray(e.words) || !e.words.length) throw Error(`${label}.words: need at least one word`);
    let previous = e.start;
    for (const w of e.words) {
      object(w, ['text', 'start', 'end'], `${label}.words`);
      if (typeof w.text !== 'string' || !w.text.trim() || /[\x00-\x1f]/.test(w.text)) throw Error(`${label}.words: text must be nonempty without control characters`);
      number(w.start, e.start, e.end, `${label}.word.start`);
      number(w.end, e.start, e.end, `${label}.word.end`);
      if (w.end <= w.start || w.start < previous) throw Error(`${label}.words: intervals must be positive, ordered and nonoverlapping`);
      previous = w.end;
    }
  }
  return p;
}
