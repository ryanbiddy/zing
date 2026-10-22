import { readFileSync } from 'node:fs';
import { extname } from 'node:path';
import { createHash } from 'node:crypto';

const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const pixels = (b, p) => `left:${b.x * p.width}px;top:${b.y * p.height}px;width:${b.width * p.width}px;height:${b.height * p.height}px;`;
const interval = (start, end) => `data-start="${start}" data-duration="${end - start}"`;

// All motion is finite CSS animation. HyperFrames pauses/seeks the animation
// objects; no timer, animation loop, random value, or external script is used.
export function composition(p, videoName = 'background.mp4') {
  const css = [];
  const events = p.captions.map((e, i) => {
    const s = e.style;
    const family = `ZingFont${i}`;
    const type = { '.ttf': 'ttf', '.otf': 'otf', '.woff': 'woff', '.woff2': 'woff2' }[extname(s.font).toLowerCase()];
    const bytes = readFileSync(s.font);
    if (s.font_sha256 && createHash('sha256').update(bytes).digest('hex') !== s.font_sha256) throw Error('Font SHA-256 mismatch at embedding; restore the declared font file');
    css.push(`@font-face{font-family:${family};src:url(data:font/${type};base64,${bytes.toString('base64')})}`);
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
${css.join('\n')}
</style></head><body><div id="root" data-composition-id="zing-ph" data-no-timeline data-start="0" data-duration="${p.duration}" data-width="${p.width}" data-height="${p.height}" data-fps="${p.fps}">
${p.background.video ? `<video id="footage" src="${videoName}" ${interval(0, p.duration)} data-volume="0" muted></video>` : ''}
${events}</div></body></html>`;
}
