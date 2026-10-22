"""zing project init|scan|status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.study.proc import MediaError
from .api import init_project, project_status, scan_project
from .models import ProjectError
from .references import resolve_reference, study_reference


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing project", description="Inventory local clips for a reference.")
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="create a local project; reference study is deferred")
    init.add_argument("--reference", required=True)
    init.add_argument("--clips", type=Path, required=True)
    init.add_argument("--out", type=Path, required=True)
    init.add_argument("--supplied-by", default="user")
    init.add_argument("--license", default="user-supplied")
    init.add_argument("--json", action="store_true")
    find = sub.add_parser("find-reference", help="list peer search results without choosing one")
    find.add_argument("query")
    find.add_argument("--json", action="store_true")
    resolve = sub.add_parser("resolve-reference", help="verify kept media, or supply a local file")
    resolve.add_argument("project", type=Path)
    resolve.add_argument("--file", type=Path)
    resolve.add_argument("--json", action="store_true")
    study = sub.add_parser("study-reference", help="study the verified reference file without web fallback")
    study.add_argument("project", type=Path)
    study.add_argument("--workspace", type=Path)
    study.add_argument("--json", action="store_true")
    for action in ("scan", "status"):
        child = sub.add_parser(action, help="update inventory" if action == "scan" else "inspect inventory without writing")
        child.add_argument("project", type=Path)
        child.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "find-reference":
            from myzing.uoink_bridge import search_references

            result = search_references(args.query)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            elif not result["ok"]:
                print(result["error"])
            else:
                for candidate in result["results"]:
                    print(f"{candidate['item_ref']}  {candidate['title']}")
                print(f"{len(result['results'])} result(s). No reference selected.")
            return 0 if result["ok"] else 1
        if args.action == "study-reference":
            result = study_reference(args.project, workspace=args.workspace)
            print(json.dumps(result, indent=2) if args.json else f"Reference study: {result['breakdown_path']}")
            return 0
        if args.action == "init":
            root = args.out
            init_project(args.reference, args.clips, root, supplied_by=args.supplied_by, license=args.license)
        else:
            root = args.project
            if args.action == "scan":
                scan_project(root)
            elif args.action == "resolve-reference":
                resolve_reference(root, file=args.file)
        result = project_status(root)
    except (ProjectError, OSError, MediaError) as exc:
        print(f"zing project: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"project: {result['manifest_path']}")
        print("  " + ", ".join(f"{n} {state}" for state, n in result["counts"].items()))
        ref = result["reference"]
        print(f"  reference: {ref['value']} ({ref['state']})")
        if ref.get("resolution"):
            resolution = ref["resolution"]
            print(f"  {resolution['reason'] or resolution['path']}")
            if resolution["state"] == "unresolved":
                print("  Use 'zing project resolve-reference <project> --file FILE' to continue locally.")
        for asset in result["assets"]:
            detail = ", ".join(asset["flags"]) or asset["error"] or asset["orientation"] or ""
            pending = "; scan required" if asset["needs_scan"] else ""
            print(f"  {asset['state']}: {asset['path']} (revision {asset['revision']}{pending}) {detail}")
        if result["lock"]:
            print(f"  {result['lock']}")
    return 1 if args.action == "resolve-reference" and result["reference"]["state"] == "unresolved" else 0
