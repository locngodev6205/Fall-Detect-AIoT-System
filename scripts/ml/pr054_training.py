"""Reproduce E1 on development. Gate new data before controlled E2 training."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from pr04_experiment import MANIFEST, development, grids, load_pinned
from pr041_ablation import evaluate, fit, training_examples
from ml.features import normalize_sequence, resample_keypoints
from research.collect import check_splits, validate


def added_recording(path, audited):
    rows = [json.loads(line) for line in (path/'trace.jsonl').read_text().splitlines()]
    frames = [row for row in rows if row['kind']=='frame']
    times = np.array([row['stamp'] for row in frames])
    points = np.array([row['pose'] if row['pose'] is not None else np.zeros((17,3))
                       for row in frames],dtype=np.float32)
    if any(row['kind']=='reset' for row in rows) or (np.diff(times)>.25).any():
        raise ValueError('Keep discontinuous recordings outside controlled E2')
    pose = normalize_sequence(resample_keypoints(times,points))
    stamps = times[0]+np.arange(len(pose))/10
    info = audited['trial']
    return (dict(video_id=info['recording'],subject_id=info['subject'],scene_id=info['activity'],
                 event=None,y=0,source_file='private'),stamps,pose,pose[:,2::3].any(axis=1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--v3',type=Path,nargs='*',default=[])
    args = parser.parse_args()
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    _, records = development(args.root,load_pinned(args.root/'annha-v2.1'/'manifest.json',MANIFEST))
    train,val = ([ (row,*grids(row)) for row in records if row['split']==split] for split in ('train','val'))
    configs = {'E1':train}
    if args.v3:
        audited = [validate(path,confirmed=True) for path in args.v3]
        check_splits(audited)
        old_ids = {r['video_id'] for r in records}
        old_subjects = {r['subject_id'] for r in records if r['subject_id']}
        old_sources = {r['source_dataset'] for r in records}
        for item in audited:
            row = item['trial']
            if row['recording'] in old_ids or row['subject'] in old_subjects or row['source'] in old_sources:
                raise ValueError('V3 collides with development recording, subject or source ID')
        extra = [added_recording(path,item) for path,item in zip(args.v3,audited,strict=True)
                 if item['trial']['split']=='train']
        if len({r[0]['subject_id'] for r in extra})<2:
            raise ValueError('BLOCKED_BY_DATA: expansion requires multiple verified Train participants')
        configs['E2'] = train+extra
    args.output.mkdir(mode=0o700)
    results = {}
    for name,data in configs.items():
        inputs = training_examples(data,20,3)
        for seed in (42,43,44):
            model,stats = fit(inputs,20,seed)
            path = args.output/f'{name}-{seed}.pt'
            torch.save(model.state_dict(),path)
            results[f'{name}-{seed}'] = dict(stats, **evaluate(model,val,20,3))
    (args.output/'runs.json').write_text(json.dumps(dict(
        manifest=MANIFEST,epochs=30,window=20,gap=3,threshold=.5,runs=results),indent=2))


if __name__=='__main__':
    main()
