"""Current hooks, compact review headers and tracker-free page captures."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.factory import command, edit, judge, network, pipeline, render, review
from myzing.factory.tools import data_path
from test_factory_context import Answer
from test_factory_review_fixes import javascript, prepared, project

RUN = subprocess.run
SHOT = Path(__file__).resolve().parents[1] / "tools" / "factory-sidecar" / "shot.cjs"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.mark.parametrize("plan", [None, {}, {"hook": None}, {"hook": ""},
                                  {"hook": "Scout *hook*"}, {"hook": "Planned *hook*"}])
def test_status_prefers_plan_hook_and_keeps_scout_hook(project, plan):
    data = pipeline.load_moments(project)
    data["moments"][0]["hook"] = "Scout *hook*"
    pipeline._write(project / "moments.json", data)
    if plan is not None:
        pipeline._write(project / "clip01" / "plan.json", plan)
    got = pipeline.status(project)["clips"][0]
    hook = (plan or {}).get("hook") or "Scout *hook*"
    assert got["hook"] == hook.replace("*", "")
    if hook != "Scout *hook*":
        assert got["scout_hook"] == "Scout *hook*"
    else:
        assert "scout_hook" not in got


def test_cli_and_mcp_status_reflect_hook_edits(project, monkeypatch, capsys):
    d = prepared(project)
    j = Answer(project, {"flags": []})
    monkeypatch.setattr(edit, "Judge", lambda *a: j)
    monkeypatch.setattr(render, "render", lambda *a: d / "clip.mp4")
    for hook in ("We built a *rocket*", "Rocket"):
        assert command.run(["edit", str(project), "clip01", "--hook", hook]) == 0
        assert json.loads(capsys.readouterr().out)["text"] == hook
        assert command.run(["status", str(project)]) == 0
        cli = json.loads(capsys.readouterr().out)["clips"][0]
        mcp = mcp_server.h_factory_status(str(project))["clips"][0]
        assert cli == mcp
        assert cli["hook"] == hook.replace("*", "")
        assert cli.get("scout_hook") == ("Rocket" if hook != "Rocket" else None)
        assert pipeline.load_moments(project)["moments"][0]["hook"] == "Rocket"


def test_dashboard_header_has_short_counts_and_a_nonsticky_details_panel():
    page = data_path("dashboard.html").read_text(encoding="utf-8")
    header = page.split('<header class="top">', 1)[1].split("</header>", 1)[0]
    assert 'id="network"' in header and 'id="network-toggle"' in header
    assert 'aria-controls="network-details" aria-expanded="false"' in header
    assert '>Details</button>' in header
    assert 'id="run-btn"' in header and 'id="waiting"' in header
    assert 'id="network-details"' not in header
    assert '<div id="network-details" class="note" hidden>' in page.split("</header>", 1)[1]
    assert 'Object.keys(p.network.hosts).length' in page
    assert '$("#network").textContent = p.network ? p.network.summary' not in page
    assert re.search(r"@media \(max-width: 700px\)[^{]*\{\s*header\.top \{ position: static;", page)


def test_dashboard_network_toggle_keeps_full_summary_through_refresh():
    hosts = {f"host{i}.example": 1 for i in range(38)}
    summary = "514 network requests · " + "; ".join(f"{h} / site resource 1" for h in hosts)
    net = {"requests": 514, "hosts": hosts, "summary": summary}
    got = javascript("dashboard.html", """
      ui.project = {project: 'show', network: NETWORK, clips: []};
      const panel = $('#network-details'), toggle = $('#network-toggle');
      panel.hidden = true;
      render();
      const short = $('#network').textContent;
      toggle.events.click({currentTarget: toggle});
      render();
      const opened = [panel.hidden, toggle.attrs['aria-expanded'], panel.textContent, toggle.hidden];
      toggle.events.click({currentTarget: toggle});
      console.log(JSON.stringify({short, opened, closed: [panel.hidden, toggle.attrs['aria-expanded']],
        summary: ui.project.network.summary}));
    """.replace("NETWORK", json.dumps(net)))
    assert got == {"short": "514 network requests to 38 hosts", "opened": [False, "true", summary, False],
                   "closed": [True, "false"], "summary": summary}


@pytest.mark.parametrize("summary", ["offline: nothing fetched", "No network requests recorded"])
def test_dashboard_empty_network_summary_is_unchanged(summary):
    got = javascript("dashboard.html", """
      ui.project = {network: {requests: 0, hosts: {}, summary: SUMMARY}};
      $('#network-details').hidden = false;
      render();
      console.log(JSON.stringify([$('#network').textContent, $('#network-toggle').hidden,
        $('#network-details').hidden, $('#network-toggle').attrs['aria-expanded']]));
    """.replace("SUMMARY", json.dumps(summary)))
    assert got == [summary, True, True, "false"]


def test_static_review_collapses_network_details_and_keeps_json_summary(project):
    net = network.Network(project)
    net.record("example.org", "site resource")
    net.record("example.org", "visual search")
    net.record("cdn.example.org", "site resource")
    before = pipeline.status(project)["network"]
    page = review.build(project).read_text(encoding="utf-8")
    assert '<details class="sub" id="network-details"><summary>' in page
    assert '<span>Details</span></summary><p id="network-hosts">' in page
    assert "document.getElementById('network').textContent = \"3 network requests to 2 hosts\";" in page
    assert "document.getElementById('network-hosts').textContent = " + json.dumps(before["summary"]) in page
    assert pipeline.status(project)["network"] == before


def test_shot_blocks_tracker_hosts_before_dns_and_keeps_page_resources():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    domains = ["google-analytics.com", "googletagmanager.com", "doubleclick.net", "googlesyndication.com",
               "parsely.com", "facebook.net", "connect.facebook.net", "hotjar.com", "segment.io", "segment.com",
               "scorecardresearch.com", "dap.digitalgov.gov"]
    blocked = [f"https://{prefix}{host}/collect" for host in domains for prefix in ("", "api.")]
    blocked += ["https://API.PARSELY.COM./collect", "https://www.google-analytics.com./collect"]
    allowed = ["https://news.example/article", "https://cdn.news.example/app.js", "https://news.example/photo.jpg",
               "https://fonts.example/font.woff2", "https://notparsely.com/script.js",
               "https://segment.com.example/script.js", "https://digitalgov.gov/page"]
    code = "const [shot, blocked, allowed] = " + json.dumps([str(SHOT), blocked, allowed]) + ";\n" + r"""
const fs = require('fs'), vm = require('vm');
const logs = [], aborted = [], continued = [], dns = [];
let routeRequest, closed = false, screenshots = 0;
const page = {
  goto: async () => {
    for (const url of [allowed[0], ...blocked, ...allowed.slice(1)]) {
      await routeRequest({request: () => ({url: () => url}),
        abort: async () => aborted.push(url), continue: async () => continued.push(url)});
    }
    return {status: () => 200};
  },
  url: () => allowed[0], title: async () => 'Article',
  waitForLoadState: async () => {}, waitForTimeout: async () => {},
  evaluate: async () => ({og_image: '/photo.jpg', og_video: null, text: 'Article'}),
  addStyleTag: async () => {}, screenshot: async () => { screenshots++; },
};
const ctx = {route: async (_, fn) => { routeRequest = fn; }, routeWebSocket: async () => {}, newPage: async () => page};
const mod = {};
const load = name => {
  if (name === 'dns') return {promises: {lookup: async host => {
    dns.push(host); return [{address: '93.184.216.34'}];
  }}};
  if (name === 'playwright-core') return {chromium: {launch: async () => ({
    newContext: async () => ctx, close: async () => { closed = true; },
  })}};
  return require(name);
};
load.main = mod;
(async () => {
  await vm.runInNewContext(fs.readFileSync(shot, 'utf8'), {
    require: load, module: mod, URL, process: {env: {}, argv: ['node', shot, allowed[0], 'shot.png']},
    console: {log: line => logs.push(JSON.parse(line))},
  });
  console.log(JSON.stringify({logs, aborted, continued, dns, closed, screenshots}));
})().catch(e => { console.error(e); process.exitCode = 1; });
"""
    proc = RUN([node, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)
    assert got["aborted"] == blocked and got["continued"] == allowed
    assert got["dns"] == ["news.example", "cdn.news.example", "fonts.example", "notparsely.com",
                          "segment.com.example", "digitalgov.gov"]
    assert [row["network"]["host"] for row in got["logs"][:-1]] == [
        "cdn.news.example", "news.example", "fonts.example", "notparsely.com", "segment.com.example", "digitalgov.gov"]
    assert got["logs"][-1]["ok"] and got["closed"] and got["screenshots"] == 1
