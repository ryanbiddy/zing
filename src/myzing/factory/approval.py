"""A local guest approval page with clips, transcripts and copyable answers."""
from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from .render import suffix
from .review import _load


def build(project: Path, out: Path | None = None) -> Path:
    ep = Path(project)
    if not ep.is_dir():
        raise ValueError("project folder does not exist")
    out = Path(out) if out is not None else ep / "approval.html"
    src, cfg = _load(ep / "source.json"), _load(ep / "factory.json")
    moments = _load(ep / "moments.json").get("moments", [])
    e = html.escape
    cards = []
    for i, m in enumerate(moments, 1):
        d = ep / f"clip{i:02d}"
        video = d / f"clip{suffix('9x16', cfg.get('pack', 'zing'))}.mp4"
        if not video.is_file():
            continue
        plan, words, context = _load(d / "plan.json"), _load(d / "words.json"), _load(d / "context.json")
        hook = plan.get("hook", m.get("hook", "")).replace("*", "")
        transcript = " ".join(w["w"] for w in words.get("words", []))
        path = quote(Path(os.path.relpath(video, out.parent)).as_posix())
        near = context.get("text") or context               # context.json keeps the window text under "text"
        around = "".join(f'<h3>{label}</h3><p class="text">{e(near[key])}</p>'
                         for key, label in (("before", "Before the clip"), ("after", "After the clip")) if near.get(key))
        around = f"<details><summary>What was said around the clip</summary>{around}</details>" if around else ""
        cards.append(f"""
<article data-clip="clip{i:02d}">
  <video src="{e(path)}#t=0.5" aria-label="Clip {i}" controls playsinline preload="metadata"></video>
  <div class="meta">
    <p class="n">Clip {i}</p>
    <h2>{e(hook)}</h2>
    <h3>Full transcript</h3><p class="text">{e(transcript) if transcript else 'Transcript unavailable.'}</p>
    {around}
    <fieldset><legend>Approve this clip?</legend>
      <label><input type="radio" name="clip{i:02d}" value="Yes"> Yes</label>
      <label><input type="radio" name="clip{i:02d}" value="No"> No</label>
    </fieldset>
    <label for="comment{i}">Comment</label><textarea id="comment{i}" name="comment{i}" rows="3"></textarea>
  </div>
</article>""")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guest approval</title>
<style>
:root{{--bg:#0b0f1a;--fg:#eef1f7;--muted:#9aa3b5;--line:#232a3a;--yel:#FFD23F}}
@media (prefers-color-scheme:light){{:root{{--bg:#f6f7fa;--fg:#121620;--muted:#566074;--line:#dfe3ea}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 80px}}
h1{{font-size:28px;margin:0 0 4px}} .sub,.n{{color:var(--muted)}} .n{{margin:0;font-size:13px}}
article{{display:grid;grid-template-columns:240px minmax(0,1fr);gap:24px;padding:22px 0;border-top:1px solid var(--line)}}
video{{width:240px;aspect-ratio:9/16;background:#000;border-radius:14px}}
h2{{font-size:22px;margin:2px 0 6px;overflow-wrap:anywhere}} h3{{font-size:15px;margin:16px 0 4px}}
.text{{white-space:pre-wrap;overflow-wrap:anywhere;margin:0 0 12px}}
fieldset{{border:0;padding:0;margin:16px 0 8px}} fieldset label{{display:inline-flex;gap:6px;align-items:center;min-height:44px;margin-right:16px;cursor:pointer}}
textarea{{display:block;box-sizing:border-box;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--bg);color:var(--fg);font:inherit;resize:vertical}}
input{{accent-color:var(--yel)}} :focus-visible{{outline:2px solid var(--yel);outline-offset:3px}}
#bar{{display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:16px 0;border-top:1px solid var(--line)}}
button{{font:700 14px system-ui;padding:12px 16px;border-radius:10px;border:0;background:var(--yel);color:#081233;cursor:pointer}}
@media (max-width:700px){{article{{grid-template-columns:1fr}} video{{width:100%;max-width:340px}}}}
</style></head><body><main>
<h1>Guest approval</h1><p id="project">{e(src.get('name', ep.name))}</p>
<p class="sub">Watch each clip and choose Yes or No. Add a comment if needed. Copy your answers and send them to the person who shared this pack. Nothing is sent from this page.</p>
<form id="answers">{''.join(cards) if cards else '<p>No rendered 9x16 clips yet.</p>'}</form>
<div id="bar"><button id="copy" type="button">Copy my answers</button><span id="status" role="status"></span></div>
<div id="result" hidden><label for="text">Your answers</label><textarea id="text" rows="10" readonly></textarea></div>
<noscript>Enable JavaScript to copy your answers.</noscript>
</main><script>
document.getElementById('answers').onsubmit = ev => ev.preventDefault();
document.getElementById('copy').onclick = async () => {{
  const answers = Array.from(document.querySelectorAll('article')).map(el => {{
    const vote = el.querySelector('input:checked');
    const comment = el.querySelector('textarea').value.trim();
    return el.dataset.clip + ' — ' + (vote ? vote.value : (comment ? 'Comment' : 'No answer')) + '\\n' +
      el.querySelector('h2').textContent + (comment ? '\\nComment\\n' + comment : '');
  }});
  const text = 'Guest approval\\n' + document.getElementById('project').textContent + '\\n\\n' + answers.join('\\n\\n');
  const output = document.getElementById('text');
  output.value = text;
  document.getElementById('result').hidden = false;
  try {{
    await navigator.clipboard.writeText(text);
    document.getElementById('status').textContent = 'Copied.';
  }} catch (e) {{
    output.focus(); output.select();
    document.getElementById('status').textContent = 'Select and copy your answers below.';
  }}
}};
</script></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
