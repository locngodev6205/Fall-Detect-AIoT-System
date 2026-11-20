"""Generate development-only review figures and benchmark the standalone prototype."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from pr04_experiment import MANIFEST, development, load_pinned, make_model, starts
from pr041_ablation import StreamingGRU
from ml.dataset import read_keypoints_csv


def review(root, prior, run):
    import cv2
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    baseline = json.loads((prior/'validation-scan.json').read_text())['short20_mask']['gru']
    errors = {r['id'] for r in baseline['recordings'] if bool(r['y']) != r['detected']}
    scores = json.loads((run/'results.json').read_text())['runs']['full-E4-42']['recordings']
    manifest = load_pinned(root/'annha-v2.1'/'manifest.json', MANIFEST)
    _, rows = development(root, manifest)
    records = {r['video_id']: r for r in rows if r['split']=='val'}
    benchmark = []
    model = make_model(torch,'gru',20)
    model.load_state_dict(torch.load(run/'full-E4-42.pt',weights_only=True,map_location='cpu'))
    model.eval()
    torch.set_num_threads(2)
    summaries = []
    for saved in scores:
        row = records[saved['id']]
        native_time, native_pose = read_keypoints_csv(Path(row['keypoint_csv']))
        streamer = StreamingGRU(model,20,3)
        for stamp,pose in zip(native_time,native_pose):
            start = time.perf_counter_ns()
            emitted = streamer.push(float(stamp),pose)
            benchmark.append(((time.perf_counter_ns()-start)/1e6, len(emitted)))
        if saved['id'] not in errors:
            continue
        points = saved['scores']
        event = saved['event']
        x,p = zip(*points) if points else ([],[])
        checks = [i for i,(stamp,_) in enumerate(points)
                  if not event or event[0] <= stamp <= min(event[0]+3,event[1]+1)]
        peak = max((points[i] for i in checks), key=lambda t:t[1], default=None)
        fig, ax = plt.subplots(figsize=(8,3))
        ax.plot(x,p,'.-',label='Eligible windows')
        ax.axhline(.5,color='crimson',linestyle='--',label='Threshold')
        if event:
            ax.axvspan(*event,alpha=.15,label='Annotated fall')
        ax.set(xlabel='Clip time (s)', ylabel='P(Fall)', ylim=(0,1), title=saved['id'])
        ax.legend(loc='best',fontsize=8)
        name = saved['id'].split(':')[-1]
        fig.tight_layout()
        fig.savefig(run/f'{name}-probability.png',dpi=150)
        plt.close(fig)
        if peak:
            target = peak[0]
            indices = (native_time >= target-1.9) & (native_time<=target)
            confidence = native_pose[indices,:,2]
            frame_stamps = (max(0,target-.9),max(0,target-.45),target)
            capture = cv2.VideoCapture(row['source_file'])
            fig,axes = plt.subplots(1,3,figsize=(9,2.5))
            try:
                for stamp,ax in zip(frame_stamps,axes):
                    capture.set(cv2.CAP_PROP_POS_MSEC,1000*stamp)
                    ok,image=capture.read()
                    if ok:
                        ax.imshow(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
                    ax.set_title(f'{stamp:.2f} s')
                    ax.axis('off')
            finally:
                capture.release()
            fig.savefig(run/f'{name}-frames.png',dpi=140)
            plt.close(fig)
            summaries.append(dict(id=saved['id'], peak=peak, scores_in_match=len(checks),
                                  mean_visibility=float(confidence.mean()),
                                  native_empty=int((confidence==0).all(axis=1).sum()),
                                  native_frames=len(confidence)))
    lat=np.array(benchmark)
    return dict(errors=summaries, updates=len(lat), scores=int(lat[:,1].sum()),
                update_p50_ms=float(np.median(lat[:,0])),update_p95_ms=float(np.percentile(lat[:,0],95)),
                scored_p50_ms=float(np.median(lat[lat[:,1]>0,0])),
                scored_p95_ms=float(np.percentile(lat[lat[:,1]>0,0],95)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for item in ('root','prior','run'):
        parser.add_argument(item,type=Path)
    args=parser.parse_args()
    with (args.run/'review.json').open('x') as stream:
        json.dump(review(args.root,args.prior,args.run),stream,indent=2)


if __name__=='__main__':
    main()
