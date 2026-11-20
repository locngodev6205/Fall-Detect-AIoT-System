#!/usr/bin/env python3
"""Prepare local pilot review sheets and paired per-frame MediaPipe diagnostics."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
from ml.features import extract_keypoints, normalize_sequence, resample_keypoints, video_frame_timestamp


def save_sheet(images, path, columns=4):
    import cv2

    width, height = 240, 158
    sheet = np.full(((len(images)+columns-1)//columns*height, width*columns, 3), 24, dtype=np.uint8)
    for index, (frame, label) in enumerate(images):
        y, x = index//columns*height, index%columns*width
        ratio = min(width/frame.shape[1], (height-22)/frame.shape[0])
        picture = cv2.resize(frame, (max(1,int(ratio*frame.shape[1])), max(1,int(ratio*frame.shape[0]))))
        sheet[y:y+picture.shape[0], x:x+picture.shape[1]] = picture
        cv2.putText(sheet, label, (x+4,y+height-6), cv2.FONT_HERSHEY_SIMPLEX, .41, (245,245,245), 1)
    if not cv2.imwrite(str(path), sheet):
        raise OSError(f'Could not write {path}')


def sheets(root, output):
    import cv2
    with (root/'recovery-review-queue.csv').open() as stream:
        queue = list(csv.DictReader(stream))
    selected = [r for label in ('Fall','No_Fall') for r in [item for item in queue if item['archive_label']==label][:12]]
    with (output/'pilot-review.csv').open('x',newline='',encoding='utf-8') as stream:
        columns = list(selected[0])+['contact_sheet','review_label','reviewer','event_start_s','impact_s','event_end_s','post_fall','evidence']
        writer = csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for number,row in enumerate(selected,1):
            path = root/'raw-payutch-v1'/row['source_file']
            with path.open('rb') as video:
                if hashlib.file_digest(video,'sha256').hexdigest()!=row['sha256']:
                    raise ValueError(f'Pilot file hash mismatch: {path}')
            cap = cv2.VideoCapture(str(path))
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            chosen = sorted(set(map(int,np.linspace(0,frames-1,12))))
            images = []
            previous = None
            try:
                for index in range(frames):
                    ok,frame = cap.read()
                    if not ok:
                        break
                    previous = video_frame_timestamp(cap.get(cv2.CAP_PROP_POS_MSEC),float(row['fps']),previous)
                    if index in chosen:
                        images.append((frame,f'f{index:04d}  {previous:.3f}s'))
            finally:
                cap.release()
            if not images:
                raise ValueError(f'No pilot frame: {path}')
            name = f'{number:02d}-{row["archive_label"]}-{path.stem}.jpg'
            save_sheet(images,output/name)
            writer.writerow({**row,'contact_sheet':name})
    print('Pilot sheets',len(selected))


def gaps(times, track):
    sampled = resample_keypoints(times, np.asarray(track))
    norm = normalize_sequence(sampled)
    valid = norm[:,2::3].any(axis=1)
    candidates = []
    index = 0
    while index < len(valid):
        if valid[index]:
            index += 1
            continue
        end = index+1
        while end < len(valid) and not valid[end]:
            end += 1
        length = end-index
        if length<=3 and index>0 and end<len(valid):
            hip_a = sampled[index-1, [11,12]]
            hip_b = sampled[end, [11,12]]
            candidates.append({'first_missing_sample':index,'missing_samples':length,
                               'endpoints_separation_seconds':round((length+1)/10,2),
                               'hip_endpoint_distance_image_units':float(np.linalg.norm(hip_a[:,:2].mean(0)-hip_b[:,:2].mean(0)))
                               if np.min([*hip_a[:,2],*hip_b[:,2]]) >= .3 else None,
                               'observed_mask': [True]+[False]*length+[True]})
        index=end
    return candidates


def trace(item):
    import cv2
    import mediapipe as mp
    from contextlib import ExitStack
    root, output, index, row = item
    cv2.setNumThreads(1)
    cap = cv2.VideoCapture(str(root/'raw-payutch-v1'/row['video']))
    config = dict(static_image_mode=False,smooth_landmarks=True,min_detection_confidence=.5,min_tracking_confidence=.5)
    frames, examples, times = [], {}, []
    tracks = {'lite':[], 'full':[]}
    from math import isfinite
    try:
        with ExitStack() as stack:
            pipes = {name:stack.enter_context(mp.solutions.pose.Pose(model_complexity=i,**config))
                     for i,name in enumerate(tracks)}
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                raw = cap.get(cv2.CAP_PROP_POS_MSEC)
                timestamp = video_frame_timestamp(raw,row['fps'],times[-1] if times else None)
                times.append(timestamp)
                rgb = cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
                frame = {'frame':len(frames),'timestamp_s':timestamp,'raw_timestamp_ms':raw if isfinite(raw) else None,
                         'phase':'UNVERIFIED','luma_mean':float(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).mean())}
                for name, pipe in pipes.items():
                    result = pipe.process(rgb)
                    points = extract_keypoints(result.pose_landmarks)
                    tracks[name].append(points)
                    visible = points[:,2] >= .3
                    area = None
                    if visible.any():
                        size = np.ptp(points[visible,:2].clip(0,1),axis=0)
                        area = float(size[0]*size[1])
                    frame[name]={'missing':result.pose_landmarks is None,'keypoints_visible':int(visible.sum()),
                                 'visibility_mean':float(points[:,2].mean()),'visible_pose_bbox_fraction':area}
                failure = ('both' if frame['lite']['missing'] and frame['full']['missing'] else
                           'lite' if frame['lite']['missing'] else 'full' if frame['full']['missing'] else 'neither')
                frame['failure']=failure
                if failure not in examples:
                    examples[failure]=(image,f'f{frame["frame"]:04d} {timestamp:.3f}s {failure}')
                frames.append(frame)
    finally:
        cap.release()
    if not frames:
        raise ValueError(f'No frames: {row["video"]}')
    if any(key!='neither' for key in examples):
        save_sheet(list(examples.values()),output/f'pose-{index:02d}.jpg')
    return {'video':row['video'],'archive_label':row['label'],'scenario_candidate':row['source_candidate'],
            'trace_id':index,'frames':frames,'gaps':{name:gaps(times,track) for name,track in tracks.items()}}


def verified_phase(timestamp, annotation):
    if not annotation or annotation.get('annotation_status') != 'HUMAN_VERIFIED':
        return 'UNVERIFIED'
    label=annotation.get('review_label')
    if label == 'no_fall':
        return 'NORMAL'
    start, end = annotation.get('fall_start_time'), annotation.get('fall_end_time')
    if label != 'fall' or not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not 0 <= start < end < float('inf'):
        return 'UNVERIFIED'
    if timestamp < start:
        return 'BEFORE_FALL'
    if timestamp <= end:
        return 'DURING_FALL'
    return 'AFTER_FALL'


def summarize_phases(root, output, history):
    with (root/'source-groups-mcfd-audit.csv').open() as stream:
        hashes={r['source_file']:r['file_sha256'] for r in csv.DictReader(stream)}
    data=json.loads(history.read_text())
    if data.get('schema') != 'annha-fall-annotation-history-v1':
        raise ValueError('Wrong annotation history schema')
    latest={item['video_sha256']:item for item in data['revisions']}
    rows=json.loads((root/'pose-frame-analysis'/'pose-frame-trace.json').read_text())
    counts={}
    for clip in rows:
        annotation=latest.get(hashes[clip['video']])
        for frame in clip['frames']:
            phase=verified_phase(frame['timestamp_s'],annotation)
            frame['phase']=phase
            totals=counts.setdefault(phase,{'frames':0,'lite_missing':0,'full_missing':0})
            totals['frames']+=1
            for name in ('lite','full'):
                totals[name+'_missing']+=int(frame[name]['missing'])
    with (output/'pose-phase-trace.json').open('x') as stream:
        json.dump({'counts':counts,'videos':rows},stream,allow_nan=False)
    print(counts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('mode',choices=('sheets','trace','phase'))
    parser.add_argument('--history',type=Path)
    args=parser.parse_args()
    if args.mode=='phase' and args.history is None:
        parser.error('phase requires --history')
    args.output.mkdir()
    if args.mode=='sheets':
        sheets(args.root,args.output)
    elif args.mode=='phase':
        summarize_phases(args.root,args.output,args.history)
    else:
        rows=json.loads((args.root/'recovery-paired-pose.json').read_text())
        with ProcessPoolExecutor(max_workers=4) as pool:
            traces=list(pool.map(trace,((args.root,args.output,i,row) for i,row in enumerate(rows,1))))
        with (args.output/'pose-frame-trace.json').open('x') as stream:
            json.dump(traces,stream,allow_nan=False)
        print('Frames',sum(len(x['frames']) for x in traces),
              Counter(f['failure'] for item in traces for f in item['frames']))
        print('Grid gaps', {n:dict(Counter(g['missing_samples'] for t in traces for g in t['gaps'][n])) for n in ('lite','full')})


if __name__=='__main__':
    main()
