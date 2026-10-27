"""Re-plan saved NASA planner inputs without study, detector calls or rendering."""
import argparse
import json
from pathlib import Path
import time
from unittest.mock import patch

from myzing.director.models import ClipStudy
from myzing.director.api import plan_drafts
from myzing.layout.types import FaceTrack


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    saved = json.loads((args.project/'director/comparison.json').read_text(encoding='utf-8'))
    studies = [ClipStudy.from_dict(row) for row in saved['inventory']]
    by_path = {str(Path(s.path).resolve()):s.asset_id for s in studies}
    def subjects(video, *unused, **kwargs):
        key = by_path[str(video.resolve())]
        row = saved['subject_analysis'][key]
        # Presence was not retained separately. Reuse the saved negative spans
        # via excluded_spans below instead of claiming a fresh measurement.
        return [FaceTrack.from_dict(t) for t in row['tracks']], row['warnings']
    started = time.perf_counter()
    with patch('myzing.director.api.inventory', return_value=(studies,saved['inventory_warnings'])), \
         patch('myzing.layout.framing.analyze_subjects', side_effect=subjects), \
         patch('myzing.director.visual_quality.excluded_spans', side_effect=lambda s,p:saved['visual_selection']['excluded'].get(s.asset_id,[])), \
         patch('myzing.layout.picture.analyze_picture', side_effect=lambda path,*a,**kw:saved.get('picture_analysis',{}).get(by_path[str(Path(path).resolve())],{})):
        result = plan_drafts(args.project,args.project/'recipe.json',args.out,seed=saved['seed'],repair_asr=False)
    report = json.loads(Path(result['comparison_path']).read_text(encoding='utf-8'))
    # Match rebuilds even same-aspect deliveries. Exercise that final handoff
    # with the saved tracks too, so acceptance cannot hide a reset to reference.
    from myzing.composition import Composition
    from myzing.layout.delivery import adapt_plan
    from myzing.director.plans import REPORT_PREFIX
    tracks = {k:[FaceTrack.from_dict(t) for t in v['tracks']] for k,v in saved['subject_analysis'].items()}
    sizes = {}
    from myzing.project.api import load_project
    from myzing.render.framing import display_dimensions
    for asset in load_project(args.project).assets:
        p = asset.probe
        if p and p.width and p.height:
            stream = next((s for s in p.streams if s.get('codec_type')=='video'),{})
            sizes[asset.id] = display_dimensions({'width':p.width,'height':p.height,'tags':{'rotate':p.rotation},**stream})
    for label,path in result['plans'].items():
        plan = Composition.from_json(Path(path).read_text(encoding='utf-8'))
        delivered = adapt_plan(plan,1080,1920,sizes,tracks,requested=plan.brief.framing,
            max_upscale=plan.brief.framing_max_upscale,
            cuts={s.asset_id:[shot.start for shot in s.shots] for s in studies},pictures=saved.get('picture_analysis',{}))
        report['plans'][label] = next(json.loads(w[len(REPORT_PREFIX):]) for w in delivered.warnings if w.startswith(REPORT_PREFIX))
        (args.out/f'plan-{label}-9x16.json').write_text(delivered.to_json(indent=2),encoding='utf-8')
    acceptance = {'status':result['status'],'elapsed_seconds':time.perf_counter()-started,
        'inputs':str(args.project), 'method':'Saved inventory, framing tracks, visual exclusions and picture evidence; current planner plus same-aspect delivery rebuild; fresh cropped-frame caption sampling; no video render, study, match or detector run.',
        'shortages':report['shortages'],'warnings':report['warnings'],
        'drafts':{label:{'source_spans':row['source_output_mappings'],
                         'vertical_quality':row['vertical_quality'],'caption_band':row['caption_band']}
                  for label,row in report['plans'].items()}}
    for row in acceptance['drafts'].values():
        band = row['caption_band']
        box = band.get('box', {})
        row['caption_box_outside_60_to_82_percent'] = bool(box) and (
            box['y']+box['height'] <= .60 or box['y'] >= .82)
        row['runner_up_bands_by_clutter'] = sorted(
            [c for c in band.get('candidates', []) if c['safe'] and c['center'] != band.get('center')],
            key=lambda c:(c['clutter_score'],abs(c['center']-band['preferred_center'])))[:3]
    (args.out/'acceptance.json').write_text(json.dumps(acceptance,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in acceptance.items() if k!='drafts'},indent=2))
    for label,row in acceptance['drafts'].items():
        print(label,json.dumps({'shots':row['vertical_quality']['shots'],
                               'opening':row['vertical_quality']['first_two_seconds_close'],
                               'caption_box_outside_60_to_82_percent':row['caption_box_outside_60_to_82_percent'],
                               'runner_up_bands_by_clutter':row['runner_up_bands_by_clutter'],
                               'band':{k:v for k,v in row['caption_band'].items() if k!='candidates'}}))


if __name__ == '__main__':
    main()
