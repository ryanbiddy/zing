import { readFileSync } from 'node:fs';
import { extname } from 'node:path';
import { createHash } from 'node:crypto';

const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const pixels = (b, p) => `left:${b.x * p.width}px;top:${b.y * p.height}px;width:${b.width * p.width}px;height:${b.height * p.height}px;`;
const interval = (start, end) => `data-start="${start}" data-duration="${end - start}"`;

const fontFace = (family, path, sha256) => {
  const type = { '.ttf': 'ttf', '.otf': 'otf', '.woff': 'woff', '.woff2': 'woff2' }[extname(path).toLowerCase()];
  const bytes = readFileSync(path);
  if (sha256 && createHash('sha256').update(bytes).digest('hex') !== sha256) throw Error('Font SHA-256 mismatch at embedding; restore the declared font file');
  return `@font-face{font-family:${family};src:url(data:font/${type};base64,${bytes.toString('base64')})}`;
};

// Each graphic runs one full-length animation per part, on its section's local
// clock: enter over the first tin seconds, hold, then exit over the last tout.
function graphic(g, i, p, family, css) {
  const d = g.end - g.start, tin = Math.min(0.35, d / 4), tout = Math.min(0.25, d / 4);
  const at = t => `${+(100 * t / d).toFixed(4)}%`;
  const a = at(tin), b = at(d - tout), settle = at(Math.min(2 * tin, d - tout));
  const run = name => `animation:${name} ${d}s linear 0s 1 both;`;
  const ease = 'animation-timing-function:cubic-bezier(.2,.8,.2,1)';
  const lines = g.text.map((t, j) => `<div class="line${j + 1}">${escape(t)}</div>`).join('');
  const font = g.text.length ? `font-family:${family};font-size:${g.style.size}px;` : '';
  let body;
  if (g.template === 'title-card') {
    css.push(`@keyframes g${i}in{0%{opacity:0;transform:translateY(.25em) scale(.94);${ease}}${a}{opacity:1;transform:none}${b}{opacity:1;transform:none;animation-timing-function:ease-in}100%{opacity:0;transform:translateY(-.1em)}}`,
      `@keyframes g${i}bar{0%{transform:scaleX(0)}${a}{transform:scaleX(0);${ease}}${settle}{transform:scaleX(1)}100%{transform:scaleX(1)}}`);
    body = `<div class="tc-body" style="${run(`g${i}in`)}">${lines}<div class="tc-bar" style="background:${g.style.accent};${run(`g${i}bar`)}"></div></div>`;
  } else if (g.template === 'lower-third') {
    css.push(`@keyframes g${i}plate{0%{clip-path:inset(0 100% 0 0);${ease}}${a}{clip-path:inset(0 0 0 0)}${b}{clip-path:inset(0 0 0 0);opacity:1;animation-timing-function:ease-in}100%{clip-path:inset(0 0 0 0);opacity:0}}`,
      `@keyframes g${i}text{0%{opacity:0;transform:translateX(-.3em)}${at(tin / 2)}{opacity:0;transform:translateX(-.3em);${ease}}${settle}{opacity:1;transform:none}100%{opacity:1;transform:none}}`);
    body = `<div class="lt-plate" style="${run(`g${i}plate`)}"><div class="lt-bar" style="background:${g.style.accent}"></div><div class="lt-text" style="${run(`g${i}text`)}">${lines}</div></div>`;
  } else if (g.template === 'callout') {
    css.push(`@keyframes g${i}pop{0%{opacity:0;transform:rotate(-3deg) scale(0);${ease}}${at(tin * 0.65)}{opacity:1;transform:rotate(-3deg) scale(1.12)}${a}{opacity:1;transform:rotate(-3deg) scale(1)}${b}{opacity:1;transform:rotate(-3deg) scale(1);animation-timing-function:ease-in}100%{opacity:0;transform:rotate(-3deg) scale(.6)}}`);
    body = `<div class="co-pill" style="background:${g.style.accent};${run(`g${i}pop`)}">${lines}</div>`;
  } else {
    css.push(`@keyframes g${i}fill{0%{clip-path:inset(0 100% 0 0)}100%{clip-path:inset(0 0 0 0)}}`);
    body = `<div class="pb-fill" style="background:${g.style.accent};${run(`g${i}fill`)}"></div>`;
  }
  const track = g.template === 'progress-bar' ? `background:${g.style.color}4d;border-radius:${g.box.height * p.height / 2}px;` : '';
  return `<section id="graphic-${i}" class="graphic ${g.template}" ${interval(g.start, g.end)} style="${pixels(g.box, p)}${font}color:${g.style.color};${track}">${body}</section>`;
}

// All motion is finite CSS animation. HyperFrames pauses/seeks the animation
// objects; no timer, animation loop, random value, or external script is used.
export function composition(p, videoName = 'background.mp4') {
  const css = [];
  // Graphics render beneath captions; one embedded face per distinct font file.
  const families = new Map();
  const graphics = (p.graphics ?? []).map((g, i) => {
    let family;
    if (g.text.length) {
      if (!families.has(g.style.font)) {
        families.set(g.style.font, `ZingGraphicFont${families.size}`);
        css.push(fontFace(families.get(g.style.font), g.style.font, g.style.font_sha256));
      }
      family = families.get(g.style.font);
    }
    return graphic(g, i, p, family, css);
  }).join('\n');
  const events = p.captions.map((e, i) => {
    const s = e.style;
    const family = `ZingFont${i}`;
    css.push(fontFace(family, s.font, s.font_sha256));
    const initialBox = e.box ?? e.path[0].box;
    let motion = '';
    if (e.path) {
      css.push(`@keyframes path${i}{${e.path.map(k => `${100 * (k.time - e.start) / (e.end - e.start)}%{${pixels(k.box, p)}}`).join('')}}`);
      // The CSS adapter uses the nearest timed element's LOCAL clock.
      motion = `animation:path${i} ${e.end - e.start}s linear 0s 1 both;`;
    }
    const words = e.words.map((w, j) => {
      const pop = e.template === 'kinetic' ? 'animation:pop .18s ease-out 0s 1 both;' : '';
      const visible = e.template === 'kinetic' ? interval(w.start, e.end) : '';
      return `<span class="word" id="word-${i}-${j}" ${visible} style="${pop}">${escape(w.text)}<span class="highlight" ${interval(w.start, w.end)} style="color:${s.highlight}">${escape(w.text)}</span></span>`;
    }).join(' ');
    return `<section id="caption-${i}" class="caption" ${interval(e.start, e.end)} style="${pixels(initialBox, p)}${motion}font-family:${family};font-size:${s.size}px;color:${s.color};-webkit-text-stroke:${s.outline_width}px ${s.outline_color};background:${s.box_color ?? 'transparent'}">${words}</section>`;
  }).join('\n');
  return `<!doctype html><html><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src data:; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'">
<style>
*{box-sizing:border-box}html,body{margin:0;width:${p.width}px;height:${p.height}px;overflow:hidden}
body{background:${p.background.transparent ? 'transparent' : p.background.color ?? '#000000'}}
#root{position:relative;width:${p.width}px;height:${p.height}px;overflow:hidden}
video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.caption{position:absolute;overflow:hidden;display:flex;flex-wrap:wrap;align-content:center;align-items:center;justify-content:center;gap:0 .25em;padding:8px;line-height:1.2;paint-order:stroke fill}
.word{position:relative;display:inline-block;white-space:pre;transform-origin:center;paint-order:stroke fill}
.highlight{position:absolute;left:0;top:0;white-space:pre;paint-order:stroke fill}
@keyframes pop{from{transform:translateY(12px) scale(.65)}to{transform:translateY(0) scale(1)}}
.graphic{position:absolute;display:flex;align-items:center;justify-content:center;line-height:1.1;white-space:pre;text-shadow:0 .03em .12em rgba(0,0,0,.45)}
.graphic .line2{font-size:.5em;line-height:1.2;opacity:.92}
.tc-body{display:flex;flex-direction:column;align-items:center;text-align:center}
.tc-bar{width:40%;height:.08em;margin-top:.25em;border-radius:.04em;transform-origin:center}
.lower-third{justify-content:flex-start}
.lt-plate{display:flex;align-items:stretch;gap:.35em;padding:.3em .45em;background:rgba(0,0,0,.55);border-radius:.12em}
.lt-bar{width:.12em;border-radius:.06em}
.lt-text{display:flex;flex-direction:column;align-items:flex-start}
.co-pill{padding:.25em .7em;border-radius:999px;text-shadow:none}
.pb-fill{position:absolute;inset:0;border-radius:inherit}
${css.join('\n')}
</style></head><body><div id="root" data-composition-id="zing-ph" data-no-timeline data-start="0" data-duration="${p.duration}" data-width="${p.width}" data-height="${p.height}" data-fps="${p.fps}">
${p.background.video ? `<video id="footage" src="${videoName}" ${interval(0, p.duration)} data-volume="0" muted></video>` : ''}
${graphics}
${events}</div></body></html>`;
}
