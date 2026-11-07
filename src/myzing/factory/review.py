"""Local review page for one episode's clip pack: every shape, the fact check, credits, copy and Post/No ratings."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .campaign import RIGHTS
from .postcopy import FIELDS
from .render import SHAPES, suffix
from .network import summary


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def build(project: Path, pack: str | None = None) -> Path:
    ep = Path(project)
    cfg = _load(ep / "factory.json")
    pack = pack or cfg.get("pack", "zing")
    src = _load(ep / "source.json")
    moments = _load(ep / "moments.json").get("moments", [])
    e = html.escape
    cards = []
    for i, m in enumerate(moments, 1):
        d = ep / f"clip{i:02d}"
        videos = [(shape, f"clip{i:02d}/clip{suffix(shape, pack)}.mp4") for shape in SHAPES
                  if (d / f"clip{suffix(shape, pack)}.mp4").is_file()]
        try:
            checked = _load(d / "brief_check.json")
            if not videos and not checked:
                continue
            plan, post = _load(d / "plan.json"), _load(d / "post.json")
            mix: dict[str, int] = {}
            for s in plan.get("shots", []):
                k = s["layout"] + (f" · {s['graphic']['kind']}" if s.get("graphic") else "")
                mix[k] = mix.get(k, 0) + 1
            credits = sorted({v.get("credit", "") for v in plan.get("visuals", {}).values() if v.get("credit")})
            unclear = sorted({v.get("rights", "unknown") for v in plan.get("visuals", {}).values()} - {"cleared", "attribution"})
            mm, ss = divmod(int(m.get("start", 0)), 60)
            players = "".join(f'<video class="s{shape}" src="{e(path)}" controls playsinline preload="metadata"></video>'
                              for shape, path in videos)
            copy = "".join(f"<dt>{e(k.replace('_', ' '))}</dt><dd>{e(post[k])}</dd>" for k in FIELDS if k in post)
            flags = "".join(f'<p class="tag warn">{e(text)}</p>' for text in checked.get("errors", [])
                            + [f["why"] for f in checked.get("flags", [])])
            cards.append(f"""
<article>
  <div class="vids">{players}</div>
  <div class="meta">
    <p class="n">Clip {i} · {mm}:{ss:02d} in the episode · score {e(str(m.get('score', '')))}/10</p>
    <h2>{e(m['hook'].replace('*', ''))}</h2>
    <p class="why">{e(m.get('why', ''))}</p>
    {f'<p class="tag warn">Check the brief</p>{flags}' if flags else ''}
    <p class="tag">{len(plan.get('shots', []))} shots: {e(', '.join(f'{v}× {k}' for k, v in mix.items()))}</p>
    <p class="tag ok">Fact check: {e('; '.join(plan.get('fact_check', [])))}</p>
    {f'<p class="tag warn">Sensitive subject ({e(plan.get("sensitive_reason", ""))}): review before posting</p>' if plan.get("sensitive") else ''}
    {f'<p class="tag warn">Check rights before posting: {e(", ".join(unclear))}</p>' if unclear else ''}
    {f'<p class="tag">Visuals: {e(" | ".join(credits))}</p>' if credits else ''}
    <div class="rate" data-clip="{e(ep.name)}/clip{i:02d}"><button data-v="post">Post</button><button data-v="fix">Post with edits</button><button data-v="no">No</button><input placeholder="why (optional)"></div>
    <dl>{copy}</dl>
  </div>
</article>""")
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            cards.append(f'<article><p class="tag warn">Clip {i} could not be reviewed: {e(str(exc))}</p></article>')
    network_text = json.dumps(summary(ep)["summary"]).replace("<", "\\u003c")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Clip Pack</title>
<style>
:root{{--bg:#0b0f1a;--fg:#eef1f7;--muted:#9aa3b5;--line:#232a3a;--yel:#FFD23F;--ok:#5fd08f;--warn:#e8a33d}}
@media (prefers-color-scheme:light){{:root{{--bg:#f6f7fa;--fg:#121620;--muted:#566074;--line:#dfe3ea;--ok:#0b6b3a;--warn:#9a5b00}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 80px}}
h1{{font-size:28px;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 24px}}
article{{display:grid;grid-template-columns:auto 1fr;gap:24px;padding:22px 0;border-top:1px solid var(--line)}}
.vids{{display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}}
video{{background:#000;border-radius:14px}} .s9x16{{width:240px;aspect-ratio:9/16}} .s4x5{{width:280px;aspect-ratio:4/5}} .s1x1{{width:300px;aspect-ratio:1}} .s16x9{{width:420px;aspect-ratio:16/9}}
h2{{font-size:22px;margin:2px 0 6px}} .n{{color:var(--muted);margin:0;font-size:13px}}
.why{{margin:0 0 10px}} .tag{{color:var(--muted);font-size:13px;margin:2px 0}} .ok{{color:var(--ok)}} .warn{{color:var(--warn);font-weight:600}}
.rate{{display:flex;gap:8px;margin:12px 0 0;flex-wrap:wrap}} .rate button{{font:600 14px system-ui;padding:8px 14px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--fg);cursor:pointer}} .rate button.on{{background:var(--yel);color:#081233;border-color:var(--yel)}} .rate input{{flex:1;min-width:160px;padding:8px 10px;border-radius:9px;border:1px solid var(--line);background:transparent;color:var(--fg)}}
#bar{{position:sticky;bottom:0;display:flex;gap:14px;align-items:center;justify-content:flex-end;padding:12px 0;background:var(--bg);border-top:1px solid var(--line)}} #bar button{{font:700 14px system-ui;padding:10px 16px;border-radius:10px;border:0;background:var(--yel);color:#081233;cursor:pointer}}
dl{{margin:14px 0 0;display:grid;grid-template-columns:120px 1fr;gap:6px 12px;font-size:14px}}
dt{{color:var(--muted);text-transform:capitalize}} dd{{margin:0;white-space:pre-wrap}}
@media (max-width:900px){{article{{grid-template-columns:1fr}} video{{width:100%!important;max-width:340px}}}}
</style></head><body><main>
<h1>Clip pack: {e(src.get('name', ep.name))}</h1>
<p class="sub">Rights · {e(RIGHTS.get(cfg.get('rights'), RIGHTS['unknown']))}</p>
<p class="sub" id="network"></p>
<p class="sub">Made by zing factory: scout, cut, plan, find visuals, vision pick, fact check, render, copy. Local review only; nothing is posted.</p>
{''.join(cards)}
<div id="bar"><span id="count"></span><button id="copy">Copy my ratings</button></div>
</main>
<script>
document.getElementById('network').textContent = {network_text};
const KEY = 'zing-ratings-' + location.pathname;
let R = {{}}; try {{ R = JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch (e) {{}}
function save() {{ try {{ localStorage.setItem(KEY, JSON.stringify(R)); }} catch (e) {{}} paint(); }}
function paint() {{
  document.querySelectorAll('.rate').forEach(el => {{
    const r = R[el.dataset.clip] || {{}};
    el.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === r.v));
    const inp = el.querySelector('input'); if (document.activeElement !== inp) inp.value = r.why || '';
  }});
  const vals = Object.values(R).filter(r => r.v);
  document.getElementById('count').textContent = `${{vals.length}} rated · ${{vals.filter(r => r.v === 'post').length}} post as-is`;
}}
document.querySelectorAll('.rate').forEach(el => {{
  el.querySelectorAll('button').forEach(b => b.onclick = () => {{ R[el.dataset.clip] = {{...(R[el.dataset.clip] || {{}}), v: b.dataset.v}}; save(); }});
  el.querySelector('input').oninput = ev => {{ R[el.dataset.clip] = {{...(R[el.dataset.clip] || {{}}), why: ev.target.value}}; save(); }};
}});
document.getElementById('copy').onclick = async () => {{
  const text = 'Zing ratings ' + JSON.stringify(R);
  try {{ await navigator.clipboard.writeText(text); document.getElementById('copy').textContent = 'Copied'; }}
  catch (e) {{ document.getElementById('count').textContent = text; }}
}};
paint();
</script></body></html>"""
    out = ep / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
