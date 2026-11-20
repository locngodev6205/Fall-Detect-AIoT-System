"""Read only pinned V2.1 development sources and summarize usable E4 windows."""
import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from pr04_experiment import MANIFEST, development, grids, load_pinned, starts
from ml.dataset import read_keypoints_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    _, rows = development(args.root,load_pinned(args.root/'annha-v2.1'/'manifest.json',MANIFEST))
    groups=defaultdict(list)
    for row in rows:
        times, pose = read_keypoints_csv(Path(row['keypoint_csv']))
        stamps,_,valid=grids(row)
        _,usable=starts(stamps,valid,20,row['event'],3)
        groups[(row['split'],'Fall' if row['y'] else row['scene_id'] or 'ADL unspecified')].append(dict(
            subject=row['subject_id'],source=row['source_dataset'],camera=row['camera_id'],
            duration=float(times[-1]-times[0]),windows=len(usable),samples=len(stamps),
            missing=int((~valid).sum()),visibility_mean=float(pose[...,2].mean())))
    output = []
    for (split,activity), rows in sorted(groups.items()):
        output.append(dict(split=split,activity=activity,recordings=len(rows),
            known_subjects=len({(r['source'],r['subject']) for r in rows if r['subject']}),
            unknown_subject_recordings=sum(not r['subject'] for r in rows),
            cameras=len({(r['source'],r['camera']) for r in rows if r['camera']}),
            sources=sorted({r['source'] for r in rows}),
            duration_quantiles=np.percentile([r['duration'] for r in rows],[0,50,100]).tolist(),
            visibility_quantiles=np.percentile([r['visibility_mean'] for r in rows],[0,50,100]).tolist(),
            **{k:sum(r[k] for r in rows) for k in ('windows','missing','samples')}))
    with args.output.open('x') as out:
        json.dump(output,out,indent=2)


if __name__=='__main__':
    main()
