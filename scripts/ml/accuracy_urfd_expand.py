"""Extend the locked multi-source Train bundle with five verified URFD cam0 recordings."""
import argparse
import csv
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile
import cv2
import mediapipe as mp
import numpy as np
from pr04_experiment import starts, SPEC
from ml.features import extract_keypoints, normalize_sequence, resample_keypoints
from ml.integrity import decoded_video_digest
from urfd_rgb import pack_rgb, read_sync
if not __debug__:
    raise RuntimeError("Run without -O so input integrity checks remain enabled")

cv2.setNumThreads(1)
parser = argparse.ArgumentParser(description="Prepare the frozen URFD expansion used for the matched CTR-GCN ablation")
parser.add_argument("data", type=Path, help="PR-03 and accuracy-pose research data root")
parser.add_argument("downloads", type=Path, help="Directory containing the official URFD RGB ZIP and sync CSV files")
parser.add_argument("work", type=Path, help="New output directory, outside Git")
args = parser.parse_args()
work, data = args.work.resolve(), args.data.resolve()
work.mkdir(mode=0o700)
bundle = work / 'bundle-frozen'
bundle.mkdir(mode=0o700)
v2=data/'verified-expansion-v2'
up = v2 / 'upstream'
v21=data/'verified-expansion-v21'
multi=data/'accuracy-pose-v1/multisource-v1'
old=json.loads((multi/'manifest.json').read_text())
v21_manifest=json.loads((v21/'annha-v2.1/manifest.json').read_text())
gmd=json.loads((data/'accuracy-pose-v1/stability/independent/cohort.json').read_text())
def hash_file(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()
assert hash_file(multi/'manifest.json') == 'c8b28b135b5d1b4054bafb07effc3395588d9cac1553b826458636fe2ed34864'
assert hash_file(v21/'annha-v2.1/manifest.json') == '3c2b4f2930ad678a7fb6cf8621d67916f3a416300d07c590b8d8c7ba92b28dd3'
assert hash_file(v21/'locked-raw-test-inventory.json') == '4a33a4bf6d42e6df891fcaeafb5d7231807b5b64b1ce3f4a5d8972970c0d7fd2'
assert hash_file(v2/'annha-v2.0/manifest.json') == '40f8a04b140dea7e8738ba06ec38a9d54c03ada0bfd350621081883ccb81e1fb'
assert hash_file(data/'accuracy-pose-v1/stability/independent/cohort.json') == '462913c2cd43d2bc4dddf79c5dc3f94869c8d15dbbdbf5a4a663d3270e185280'
asset=Path(mp.__file__).parent/'modules/pose_landmark/pose_landmark_full.tflite'
assert (mp.__version__,hash_file(asset))==('0.10.14',old['pose_asset_sha256'])
baseline={r['video_id']:r for r in old['recordings']}
pinned_v20=json.loads((v2/'annha-v2.0/manifest.json').read_text())
protected={
    r['video_id']: r for r in pinned_v20['sources'] if r.get('split') == 'test'
}
for r in v21_manifest['sources'] + v21_manifest['group_context']:
    if r.get('split') in ('test','val'):
        protected[r['video_id']]=r
raw=json.loads((v21/'locked-raw-test-inventory.json').read_text())
for row in raw['recordings']:
    protected.setdefault(row['video_id'], row)
gmd_media=data/'accuracy-pose-v1/stability/independent/media'
for row in gmd['recordings']:
    media=gmd_media/row['file']
    if hash_file(media)!=row['source_sha256']:
        raise ValueError(f"GMD pilot media checksum mismatch: {row['video_id']}")
    protected[row['video_id']]=dict(row, video_sha256=row['source_sha256'], source_file=str(media))

def fingerprints(row):
    video=row.get('expected_video_sha256') or row.get('video_sha256')
    decoded=row.get('decoded_sha256')
    if not decoded:
        decoded=decoded_video_digest(row['source_file'])
    return video, decoded

with ThreadPoolExecutor(max_workers=3) as workers:
    protected_hashes=list(workers.map(fingerprints, protected.values()))
protected_video, protected_decoded=map(set, zip(*protected_hashes))
protected_groups={r.get('group_id') or r.get('group') for r in protected.values()}
seen_video={r['video_sha256'] for r in baseline.values()}
seen_decoded={r['decoded_sha256'] for r in baseline.values()}
seen_groups={r['group_id'] for r in baseline.values()}
for row in baseline.values():
    media=multi/row['feature_file']
    if hash_file(media)!=row['feature_sha256']:
        raise ValueError(f"Base pose cache checksum mismatch: {row['video_id']}")
    shutil.copyfile(media,bundle/media.name)
label0=defaultdict(list)
with (up/'urfall-cam0-falls.csv').open() as f:
    for row in csv.reader(f):
        if row and int(row[2]) == 0:
            label0[row[0]].append(int(row[1]))
rows={r['video_id']:r for r in csv.DictReader((v2/'sources-official.csv').open())}
INPUT_SHA256 = {'adl-23': ('7729d235f786dd38551d2d6f5c93847995ff8c4208295c05d12202185897b447', 'e5046c1147987fb1f3f5bb63c5da90497561461350e6208789ea33d7a8de182e'), 'adl-08': ('9a3557ece96aeef5d3e0dadebc8f714cf7952f700284d0420b883a4648edb28a', 'bf844f014431343f057061959c4203553878ba142168aedfda800b4bea0507d3'), 'fall-02': ('8918e078c85f821ae897b8041ae789bdec7ba2f264a3e83b4fb22cf9443180e7', 'a254fe2a53402149db758c9048a971eaa5149772fda9992bcb835f4edcb069fa'), 'fall-04': ('032be8d9424e99d58a16067d2e6363c2aa3904753b485aca3daecf7541d59e52', 'bc37f51337f9aa68777c96b873517565fc1245393d42ce735e37db5083abbebb'), 'fall-06': ('0b082bed28949dc3c3812c4c3c0ca8a75cb478ba02484800da6cb699499b2401', '95f4dd835d4a1a0782ece31561d8ec00cd9ed1b210eb914afd74e77b9e7b9b7c')}
result=[]
for clip, feature_number in zip(('adl-23','adl-08','fall-02','fall-04','fall-06'), range(52,57)):
    try:
        key='urfd:'+clip
        existing=rows.get(key)
        root=up if existing else args.downloads
        archive=root/(clip+'-cam0-rgb.zip')
        sync=root/(clip+'-data.csv')
        if (hash_file(archive), hash_file(sync)) != INPUT_SHA256[clip]:
            raise ValueError("URFD source archive/sync checksum mismatch")
        with ZipFile(archive) as f: assert f.testzip() is None
        times=np.array(read_sync(sync))/1000
        if existing:
            media=Path(existing['source_file'])
            assert hash_file(media)==existing['expected_video_sha256']
        else:
            media=work/(clip+'-official.mp4')
            if not media.exists(): pack_rgb(archive,sync,media)
        # Only use original recording's cam0 and the publisher's annotated frame IDs.
        event=None
        if clip.startswith('fall'):
            ids=label0[clip]
            assert ids and ids==list(range(ids[0],ids[-1]+1)) and ids[-1]+1<=len(times)
            event=[float(times[ids[0]-1]),float(times[ids[-1]-1])]
            if existing: assert np.allclose(event,[float(existing['event_start']),float(existing['event_end'])],atol=1e-8)
        video_sha=hash_file(media)
        decoded=decoded_video_digest(media)
        group='urfd:'+clip
        if (key in baseline or key in protected or group in (seen_groups | protected_groups)
                        or video_sha in (seen_video | protected_video) or decoded in (seen_decoded | protected_decoded)):
            raise ValueError(f"Recording, group, raw or decoded video overlaps another recording: {key}")
        seen_video.add(video_sha)
        seen_decoded.add(decoded)
        seen_groups.add(group)
        cap=cv2.VideoCapture(str(media))
        poses=[]
        try:
            with mp.solutions.pose.Pose(model_complexity=1) as estimator:
                while True:
                    ok,frame=cap.read()
                    if not ok: break
                    poses.append(extract_keypoints(estimator.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).pose_landmarks))
        finally: cap.release()
        assert len(poses)==len(times), (len(poses),len(times))
        points=np.asarray(poses,dtype=np.float32)
        assert np.isfinite(points).all()
        points[...,2]=np.clip(points[...,2],0,1)
        normalized=normalize_sequence(resample_keypoints(times,points))
        count=len(starts(np.arange(len(normalized)) / SPEC.sample_rate_hz,normalized[:,2::3].any(axis=1),20,event,3)[1])
        row=dict(video_id=key,dataset='urfd',release='official cam0 RGB / PR-03 clock',license='CC BY-NC-SA 4.0',
                        split='train',subject=None,group_id='urfd:'+clip,camera='cam0',event=event,y=int(event is not None),scene_id=None,
                        annotation_source='URFD official cam0 frame label 0 plus exact sync PTS' if event else 'URFD official ADL collection row and RGB ZIP',
                        annotation_version='URFD official',video_sha256=video_sha,decoded_sha256=decoded,
                        source_ref=f'https://fenix.ur.edu.pl/mkepski/ds/data/{clip}-cam0-rgb.zip')
        details=dict(row,windows=count,frames=len(times),duration_s=float(times[-1]),archive_sha256=hash_file(archive),sync_sha256=hash_file(sync),
                        annotation_sha256=hash_file(up/'urfall-cam0-falls.csv') if event else None,pose_model=old['model'],
                        mediapipe=mp.__version__,pose_asset_sha256=old['pose_asset_sha256'])
        if count:
            name=f"{feature_number:03d}.npz"
            file=bundle/name
            np.savez_compressed(file,stamps=times,points=points)
            row.update(feature_file=name,feature_sha256=hash_file(file))
            row.update({k:details[k] for k in ('archive_sha256','sync_sha256','annotation_sha256')})
            row.update(media_duration_s=details['duration_s'],training_windows=count)
            baseline[key]=row
        else:
            raise ValueError('No windows for the frozen training recording')
        result.append(details)
    except Exception as exc:
        raise RuntimeError(f'Could not verify and prepare {clip}') from exc
    print(result[-1],flush=True)
    (work/'audit.json').write_text(json.dumps(result,indent=2))
old['recordings']=list(baseline.values())
old['not_in_bundle']+=['V2.0 locked Test']
old['expansion']={'base_bundle_sha256':hash_file(multi/'manifest.json'),'protected_recordings':len(protected),
                  'excluded_locked_urfd':['urfd:adl-16','urfd:fall-12'],
                  'manifest_frame_labels_sha256':hash_file(up/'urfall-cam0-falls.csv')}
(bundle/'manifest.json').write_text(json.dumps(old,indent=2,allow_nan=False)+'\n')
print('protected rows',len(protected),'bundle',len(baseline),'manifest sha',hash_file(bundle/'manifest.json'),flush=True)
