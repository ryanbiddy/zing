"""Save estimated moment choices with the evidence that produced them."""

from copy import deepcopy
from pathlib import Path

from myzing.brief.api import load_brief, save_brief
from myzing.brief.models import Brief

from .state import read


def disclosure(pick):
    def clock(value):
        minutes, seconds = divmod(int(value), 60)
        return f"{minutes}:{seconds:02}"
    return (f"Picked an estimated {pick['end'] - pick['start']:.1f} s moment from {pick['clip_name']} "
            f"at {clock(pick['start'])}-{clock(pick['end'])}. \"{pick['first_sentence']}\" "
            f"To choose another, run zing moments \"{pick['study_path']}\" --target {pick['target']:g} "
            "and replace its must_keep in brief.json.")


class AutoMoments:
    def __init__(self, checkpoints, studies, inputs):
        self.checkpoints, self.studies = checkpoints, studies
        current = load_brief(checkpoints.root / "brief.json").to_dict()
        old = checkpoints.data.get("auto_moments", {})
        base = old["brief"] if current == old.get("applied_brief") else current
        inputs = [base, studies, inputs, "sentence-pauses-v1"]
        key = checkpoints.key(inputs)
        self.data = (deepcopy(old) if checkpoints.resume and checkpoints.matches(old, inputs) else
                     {"key": key, "brief": base, "picks": [], "excluded": []})
        self.data["key"] = key
        self.data.pop("legacy_root", None)
        for pick in self.data["picks"]:
            pick["disclosure"] = disclosure(pick)
        self.save()

    def save(self):
        brief = deepcopy(self.data["brief"])
        brief["must_keep"].extend(m for pick in self.data["picks"] for m in pick["must_keep"])
        self.data["applied_brief"] = brief
        self.checkpoints.data["auto_moments"] = self.data
        self.checkpoints.save()
        save_brief(self.checkpoints.root, Brief.from_dict(brief))

    def pick(self, planned, manifest):
        shortage = next((s for s in planned["summary"]["shortages"]
                         if s["code"] == "long_source_needs_moment" and s.get("suggestions")), None)
        if shortage is None:
            return False
        asset_id = shortage["asset_ids"][0]
        if any(p["asset_id"] == asset_id for p in self.data["picks"]):
            return False
        asset = next(a for a in manifest.assets if a.id == asset_id)
        suggestion = shortage["suggestions"][0]
        from myzing.director.models import ClipStudy
        from myzing.director.selection import constraints
        report = read(planned["comparison_path"])
        brief = Brief.from_dict(report["brief"])
        clips = [ClipStudy.from_dict(c) for c in report["inventory"]]
        keep, _ = constraints(brief, manifest, clips)
        required = sum(b - a for spans in keep.values() for a, b in spans)
        if required + suggestion["end"] - suggestion["start"] > brief.target_length_seconds + 2 / 30:
            if asset_id in self.data["excluded"]:
                return False
            self.data["excluded"].append(asset_id)
            self.save()
            return True  # Preserve the required moment instead of exceeding the edit length.
        pick = {**deepcopy(suggestion), "asset_id": asset_id,
                "clip_name": Path(asset.path).name, "study_path": self.studies[asset_id]["path"],
                "target": brief.target_length_seconds}
        pick["disclosure"] = disclosure(pick)
        self.data["picks"].append(pick)
        self.save()
        return True
