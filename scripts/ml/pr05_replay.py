"""Measure development-only window parity, event metrics and pose benchmark."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from pr04_experiment import MANIFEST, development, load_pinned
from pr041_ablation import summarize
from ml.dataset import read_keypoints_csv
from ml.features import SPEC, normalize_sequence, resample_keypoints
from research.benchmark import benchmark, quantiles
from research.streaming import SIZE, STRIDE, EventEngine, Stream, load_model, valid_window


def offline(stamps, poses, model, confirmations=1):
    cuts = np.flatnonzero(np.diff(stamps)>SPEC.max_gap_s)+1
    for times, raw in zip(np.split(stamps,cuts),
                          np.split(poses,cuts)):
        engine = EventEngine(confirmations=confirmations)
        samples = normalize_sequence(resample_keypoints(times,raw))
        missing_run = 0
        for end_index, vector in enumerate(samples):
            missing_run = 0 if vector[2::3].any() else missing_run + 1
            if missing_run == SIZE:
                engine.person_lost()
            start = end_index-SIZE+1
            if start < 0 or start % STRIDE:
                continue
            inputs = samples[start:start+SIZE]
            mask = inputs[:,2::3].any(axis=1)
            end = times[0]+(start+SIZE-1)/SPEC.sample_rate_hz
            if valid_window(mask):
                score = model(inputs)
                events = engine.update(end,score)
            else:
                engine.unavailable()
                score,events = None,()
            yield times[0]+start/SPEC.sample_rate_hz,end,mask,inputs,score,events


def alerts(windows, arrival=False):
    return [row.arrival if arrival else stamp for row in windows
            for name,stamp in row.events if name=='simulated_alert']


def evaluate_alerts(event, stamps, coverage):
    if event is None:
        return dict(tp=0,fn=0,fp=len(stamps),early=0,late=0,duplicate=0,adl=bool(stamps),
                    event=None,delay=None,covered=None)
    a,b = event
    end = min(a+3,b+1)
    matched = [t for t in stamps if a<=t<=end]
    early = sum(int(t<a) for t in stamps)
    late = sum(int(t>end) for t in stamps)
    duplicate = max(0,len(matched)-1)
    return dict(tp=int(bool(matched)),fn=int(not matched),fp=early+late+duplicate,
                early=early,late=late,duplicate=duplicate,adl=False,event=event,
                covered=coverage,delay=matched[0]-a if matched else None)


def coverage(event, times):
    return bool(event and any(event[0]<=t<=min(event[0]+3,event[1]+1) for t in times))


def replay(rows, model):
    totals = dict(windows=0,scored=0,resets=0,max_score_delta=0.,max_tensor_delta=0.)
    delays, results = [], {'offline': [], 'grid': [], 'arrival': [], 'two_confirmations': []}
    for row in rows:
        stamps,poses = read_keypoints_csv(Path(row['keypoint_csv']))
        expected = list(offline(stamps,poses,model))
        stream, alternate = Stream(model), Stream(model, confirmations=2)
        actual, two = [], []
        for stamp,pose in zip(stamps,poses,strict=True):
            actual.extend(stream.push(stamp,pose))
            if row['split']=='val':
                two.extend(alternate.push(stamp,pose))
        totals['resets'] += len(stream.resets)-1
        for (start,end,mask,inputs,score,events), window in zip(expected,actual,strict=True):
            assert abs(start-window.start)<1e-8 and abs(end-window.end)<1e-8
            assert np.array_equal(mask,window.mask)
            totals['max_tensor_delta'] = max(totals['max_tensor_delta'],float(np.max(abs(inputs-window.inputs))))
            assert events==window.events and (score is None)==(window.score is None)
            if score is not None:
                totals['max_score_delta'] = max(totals['max_score_delta'],abs(score-window.score))
                totals['scored'] += 1
                delays.append((window.arrival-window.end)*1000)
            totals['windows'] += 1
        if row['split']=='val':
            event = row['event']
            grid = [w.end for w in actual if w.score is not None]
            arrivals = [w.arrival for w in actual if w.score is not None]
            expected_alerts = [stamp for *_, events in expected for name, stamp in events
                               if name=='simulated_alert']
            modes = dict(offline=(expected_alerts, grid), grid=(alerts(actual),grid),
                         arrival=(alerts(actual,True),arrivals),
                         two_confirmations=(alerts(two),grid))
            for key,(detected, valid) in modes.items():
                results[key].append(dict(**evaluate_alerts(event,detected,coverage(event,valid)),
                                         action=row['scene_id'],subject=row['subject_id'],id=row['video_id']))
    assert totals['max_tensor_delta']<1e-6 and totals['max_score_delta']<1e-6
    return dict(**totals, recordings=len(rows), grid_to_arrival_ms=quantiles(delays),
                metrics={mode:summarize(items) for mode,items in results.items()},details=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('checkpoint',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--video',action='store_true')
    args=parser.parse_args()
    torch.set_num_threads(2)
    model=load_model(args.checkpoint)
    _, rows=development(args.root,load_pinned(args.root/'annha-v2.1'/'manifest.json',MANIFEST))
    if not args.video:
        result=replay(rows,model)
    else:
        # Deterministic subject rotation, one development clip per action/subject pair.
        actions=('Fall forward','Fall left','Fall right','Fall backwards','Fall sitting',
                 'Sit down','Pick up object','Walk')
        selected=[next(row for row in rows if row['split']=='val' and row['scene_id']==action
                       and row['subject_id']==str((6,7,9)[i%3])) for i,action in enumerate(actions)]
        result={}
        for complexity in (0,1):
            details=[]
            for row in selected:
                perf=benchmark(row['source_file'],model,complexity)
                item=dict(perf,**evaluate_alerts(row['event'],[w[0] for w in perf['alerts']],
                                                  coverage(row['event'],perf['score_grid'])),
                          id=row['video_id'],action=row['scene_id'])
                details.append(item)
                print(complexity,row['video_id'],perf['frames'],flush=True)
            result[complexity]=dict(metrics=summarize(details),details=details)
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2)


if __name__=='__main__':
    main()
