"""Predeclared event policies on pinned development data only."""
import argparse
import json
from pathlib import Path

import torch

from pr04_experiment import MANIFEST, development, load_pinned
from pr041_ablation import summarize
from pr05_replay import alerts, coverage, evaluate_alerts
from ml.dataset import read_keypoints_csv
from research.diagnostics import Trace, replay
from research.streaming import EventEngine, Stream, load_model


class Hysteresis(EventEngine):
    def update(self, stamp, score):
        if self.state == 'COOLDOWN' and score >= .35:
            return ()
        return super().update(stamp, score)


POLICIES = {
    'baseline': EventEngine,
    'two_confirmations': lambda: EventEngine(confirmations=2),
    'hysteresis_rearm_035': Hysteresis,
    'cooldown_4s': lambda: EventEngine(cooldown=4),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root','checkpoint','output'):
        parser.add_argument(name,type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    model = load_model(args.checkpoint)
    _, rows = development(args.root,load_pinned(args.root/'annha-v2.1'/'manifest.json',MANIFEST))
    args.output.mkdir(mode=0o700)
    results, audit = {}, []
    for row in rows:
        times, poses = read_keypoints_csv(Path(row['keypoint_csv']))
        missing = ~(poses[...,2]>0).any(axis=1)
        a = dict(id=row['video_id'],subject=row['subject_id'],action=row['scene_id'],source=row['source_dataset'],
                 split=row['split'],fall=bool(row['y']),missing=int(missing.sum()),frames=len(missing))
        audit.append(a)
        if row['split'] != 'val':
            continue
        engines = {}
        for name,factory in POLICIES.items():
            stream = Stream(model)
            stream.engine = factory()
            engines[name] = stream
        path = args.output/'trace-pickup'
        pickup = row['video_id']=='caucafall:PickupobjectS9'
        from contextlib import nullcontext
        with (Trace(path, scenario='development-pickup',include_pose=True) if pickup else nullcontext()) as trace:
            windows={name:[] for name in engines}
            for t,p in zip(times,poses,strict=True):
                for name,stream in engines.items():
                    new=stream.push(float(t),p)
                    windows[name].extend(new)
                    if trace is not None and name=='baseline':
                        trace.frame(stream,float(t),p,bool((p[:,2]>0).any()),float(t),new)
        for name,w in windows.items():
            scores=[(v.end,v.score) for v in w if v.score is not None]
            marks=alerts(w)
            outcome=evaluate_alerts(row['event'],marks,coverage(row['event'],[t for t,_ in scores]))
            results.setdefault(name,[]).append(dict(outcome,id=a['id'],subject=a['subject'],action=a['action'],
                                                    windows=len(w),scored=len(scores),scores=scores,alerts=marks,
                                                    masks=[v.mask.tolist() for v in w]))
    experiment={}
    for k,items in results.items():
        experiment[k]=dict(total=summarize(items), details=items,
                           subjects={s:summarize([r for r in items if r['subject']==s])
                                     for s in sorted({r['subject'] for r in items})})
    result=dict(experiment=experiment,dataset=audit,trace_parity=replay(args.output/'trace-pickup'/'trace.jsonl',model))
    (args.output/'results.json').write_text(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
