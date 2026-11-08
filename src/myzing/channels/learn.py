"""Local learning reports and measured examples for the scout."""
from __future__ import annotations

from pathlib import Path
from statistics import mean, median

from myzing.factory import postcopy, scout
from myzing.factory.pipeline import _read, _write
from myzing.playbook.common import number, utc_now

from . import bandit, outcomes, queue, registry


def ips(rows: list[dict]) -> dict:
    rows = [r for r in rows if bandit.usable(r) and number(r.get("propensity")) and 0 < r["propensity"] <= 1]
    result = {"n": len(rows), "baseline": "always name_claim"}
    if len(rows) < 20:
        return {**result, "reason": "Fewer than 20 unmasked rewards have a propensity."}
    supported = [r for r in rows if "name_claim" in r.get("arms", {}).get("title_candidates", [])]
    result["supported_n"] = len(supported)
    if len(supported) < 20:
        return {**result, "reason": "Fewer than 20 rows record name_claim as an allowed choice."}
    baseline = [r for r in supported if bandit.value(r, "title_pattern") == "name_claim"]
    if not baseline:
        return {**result, "reason": "No name_claim rewards were observed in the supported rows."}
    logged = mean(r["reward"] for r in supported)  # the logged policy's importance weight is p / p
    estimate = sum(r["reward"] / r["propensity"] for r in baseline) / len(supported)
    return {**result, "logged_policy_mean_reward": logged, "baseline_ips_mean_reward": estimate,
            "difference": logged - estimate, "baseline_posts": len(baseline)}


def learn(slug: str) -> dict:
    channel = registry.load(slug)
    prior, rows = bandit.prior(channel), outcomes.read(slug)
    defaults = {"archetype": scout.ARCHETYPES, "title_pattern": postcopy.PATTERNS,
                "length": ("short", "mid", "long"), "density": ("light", "heavy"),
                "pack": (channel["factory"].get("pack", "zing"),), "hour": tuple(range(24))}
    dimensions, summary = {}, []
    for dimension in bandit.DIMENSIONS:
        candidates = list(dict.fromkeys([*defaults[dimension], *[bandit.value(r, dimension) for r in rows
                                                                if bandit.value(r, dimension) is not None]]))
        stats = bandit.posterior(dimension, candidates, rows, prior)
        chances = bandit.best(stats)
        dimensions[dimension] = {str(v): {**s, "probability_best": chances[v]} for v, s in stats.items()}
        for value, stat in stats.items():
            if stat["n"]:
                ratio = mean(2 ** r["reward"] for r in rows if bandit.usable(r) and bandit.value(r, dimension) == value)
                label = str(value).replace("_", " ") if dimension == "archetype" else f"{dimension.replace('_', ' ')} {value}"
                summary.append(f"{label} clips averaged about {ratio:.1f}x the channel's typical views over {stat['n']} posts.")
    series = sorted({bandit.value(r, "series") for r in rows if bandit.usable(r) and bandit.value(r, "series")})
    for ident in series:
        rewards = [r["reward"] for r in rows if bandit.usable(r) and bandit.value(r, "series") == ident]
        summary.append(f"Series {ident} had {len(rewards)} posts with median reward {median(rewards):.2f}.")
        ratio = 2 ** median(rewards)                    # a reward is log2 of views over the channel's typical views
        verdict = "beat" if ratio > 1.05 else "trailed" if ratio < 0.95 else "matched"
        summary.append(f"Series {ident} {verdict} the channel's typical views, about {ratio:.1f}x over {len(rewards)} post{'s' * (len(rewards) != 1)}.")
    result = {"schema_version": 1, "channel": slug, "updated_at": utc_now(), "dimensions": dimensions,
              "ips": ips(rows), "summary": summary or ["No unmasked rewards yet. Track more posted clips."]}
    _write(registry.directory(slug) / "learned.json", result)
    return result


def steer(slug: str) -> str:
    channel = registry.load(slug)
    rows = [r for r in outcomes.read(slug) if bandit.usable(r)]
    newest = lambda r: bandit.when(r, "posted_at")
    best = sorted(rows, key=lambda r: (r["reward"], newest(r)), reverse=True)[:min(5, (len(rows) + 1) // 2)]
    worst = sorted((r for r in rows if r not in best), key=lambda r: (-r["reward"], newest(r)), reverse=True)[:5]
    projects = {r["id"]: Path(r["project"]) / r["clip"] for r in queue.read(slug)}
    lines = ["WHAT WORKED ON THIS CHANNEL"]
    for label, clips in (("Higher results", best), ("Lower results", worst)):
        if clips:
            lines.append(label)
        for row in clips:
            d = projects.get(row["id"], registry.directory(slug) / "projects" / row["id"])
            hook = _read(d / "plan.json", {}).get("hook")
            if not hook:
                moments = _read(d.parent / "moments.json", {}).get("moments", [])
                i = int(d.name.removeprefix("clip")) - 1
                hook = moments[i].get("hook") if 0 <= i < len(moments) else None
            hook = " ".join((hook or row["id"]).replace("*", "").split())
            lines.append(f"- {hook} | {bandit.value(row, 'archetype') or 'other'} | "
                         f"about {2 ** row['reward']:.1f}x the channel's typical views")
    if not rows:
        lines.append("No measured results yet.")
    lines.extend(bandit.prior(channel).get("guidance", []))
    return "\n".join(lines)
