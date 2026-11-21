"""Record private V3 webcam evidence, extract aligned poses, and validate."""
import argparse
from contextlib import ExitStack
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from tempfile import TemporaryDirectory
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fall_detect'))
from research.collect import ACTIVITIES, check_splits
from ml.features import SPEC


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def video_frames(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('Video cannot be opened')
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def verify_video(root):
    m = read(root/'manifest.json')
    if m['version'] != 3 or m['schema'] != SPEC.schema_version or m['consent_video'] is not True:
        raise ValueError('Invalid V3 schema or video consent')
    if any(m.get(k) != identifier(m[k]) for k in ('recording','subject','session','source','camera_setup')):
        raise ValueError('Invalid provenance')
    if m['activity'] not in ACTIVITIES or m['split'] not in ('train','evaluation'):
        raise ValueError('Invalid activity or split')
    if m['video'] not in ('video.mp4','video.avi'):
        raise ValueError('Invalid video filename')
    video = root/m['video']
    if digest(video) != m['video_sha256'] or digest(root/'frames.jsonl') != m['frames_sha256']:
        raise ValueError('Video or frame checksum mismatch')
    frame_rows = rows(root/'frames.jsonl')
    stamps = [r['elapsed_s'] for r in frame_rows if r['kind']=='frame']
    if (len(stamps)<2 or len(stamps)!=m['frame_count'] or not all(math.isfinite(t) for t in stamps)
            or any(b<=a for a,b in zip(stamps,stamps[1:]))):
        raise ValueError('Invalid frame count or timestamps')
    if [r['index'] for r in frame_rows if r['kind']=='frame'] != list(range(len(stamps))):
        raise ValueError('Frame index mismatch')
    return m, video, stamps


def identifier(value):
    from research.collect import IDENT
    if not IDENT.fullmatch(value):
        raise ValueError('Use pseudonymous IDs with letters, numbers, underscores or hyphens')
    return value


def choose_encoder(frame, fps, *, machine=None):
    import cv2
    height, width = frame.shape[:2]
    codecs = [('avc1','video.mp4'), ('mp4v','video.mp4'), ('MJPG','video.avi')]
    if (machine or platform.machine()).lower().startswith(('arm', 'aarch64')):
        codecs = codecs[1:]  # Pi H.264 accepted the probe but dropped frames in webcam capture.
    with TemporaryDirectory(prefix='annha-codec-') as temporary:
        for codec, name in codecs:
            sample = Path(temporary)/name
            encoder = cv2.VideoWriter(str(sample), cv2.VideoWriter_fourcc(*codec), fps, (width,height))
            try:
                if not encoder.isOpened():
                    continue
                for _ in range(8):
                    encoder.write(frame)
            finally:
                encoder.release()
            try:
                if sum(1 for _ in video_frames(sample)) == 8:
                    return codec, name
            except ValueError:
                pass
    raise ValueError('No encoder passed encode/decode verification')


def record(args):
    from research.guided_test import vnc_preview
    import cv2
    if not args.consent_video:
        raise ValueError('Explicit permission required to save video (--consent-video)')
    subject, session = identifier(args.subject), identifier(args.session)
    source, setup = identifier(args.source), identifier(args.camera_setup)
    if args.duration <= 0 or not math.isfinite(args.duration):
        raise ValueError('Duration must be positive')
    name = args.activity+'_'+uuid.uuid4().hex[:12]
    root = args.output/'subjects'/subject/session/name
    root.mkdir(mode=0o700,parents=True)
    cap = cv2.VideoCapture(args.camera)
    writer = None
    preview = ExitStack()
    use_vnc = args.preview and os.environ.get('SDL_VIDEODRIVER') == 'wayland'
    try:
        draw = preview.enter_context(vnc_preview(True)) if use_vnc else None

        def show(frame):
            if draw is not None:
                draw(frame, None)
                return False
            cv2.imshow('AnNha V3',frame)
            return cv2.waitKey(1) & 255 == ord('q')

        fps = cap.get(cv2.CAP_PROP_FPS)
        warmup = deque(maxlen=12)
        for remaining in (3,2,1):
            print(f'Starting in {remaining} s',flush=True)
            deadline = time.monotonic()+1
            while time.monotonic()<deadline:
                ok, frame = cap.read()
                if not ok:
                    raise ValueError('Camera did not return a frame')
                warmup.append(time.monotonic())
                if args.preview:
                    display = frame.copy()
                    cv2.putText(display,str(remaining),(15,45),cv2.FONT_HERSHEY_SIMPLEX,1.5,(0,255,255),2)
                    if show(display):
                        raise ValueError('Cancelled before recording')
        height,width = frame.shape[:2]
        measured = (len(warmup)-1)/(warmup[-1]-warmup[0]) if len(warmup)>1 else fps
        encoded_fps = measured if 1 <= measured <= 120 else 20.
        import numpy as np
        codec, filename = choose_encoder(np.zeros_like(frame), encoded_fps)
        print(f'Encoder: {codec} ({filename})', flush=True)
        writer = cv2.VideoWriter(str(root/filename),cv2.VideoWriter_fourcc(*codec),encoded_fps,(width,height))
        if not writer.isOpened():
            raise ValueError('Could not open verified encoder for this recording')
        captured_at = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()
        capture_cpu_start = time.process_time()
        index = failures = 0
        with (root/'frames.jsonl').open('x') as logs:
            while time.monotonic()-start < args.duration:
                ok, frame = cap.read()
                stamp = time.monotonic()-start
                if ok and frame.shape[:2]==(height,width):
                    writer.write(frame)
                    row=dict(kind='frame',index=index,elapsed_s=stamp,capture_unix_s=time.time())
                    index+=1
                else:
                    failures+=1
                    row=dict(kind='read_error',elapsed_s=stamp)
                logs.write(json.dumps(row)+'\n')
                if ok and args.preview and show(frame):
                    break
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        preview.close()
        if args.preview and not use_vnc:
            cv2.destroyAllWindows()
    duration = time.monotonic()-start
    capture_cpu = time.process_time()-capture_cpu_start
    if sum(1 for _ in video_frames(root/filename)) != index or index<2:
        raise ValueError(f'Incomplete or empty video retained at {root}')
    frame_rows = [r for r in rows(root/'frames.jsonl') if r['kind']=='frame']
    interval = frame_rows[-1]['elapsed_s']-frame_rows[0]['elapsed_s']
    write(root/'manifest.json',dict(version=3,schema=SPEC.schema_version,recording=name,subject=subject,
        session=session,source=source,camera_setup=setup,camera=args.camera,activity=args.activity,
        split=args.split,consent_video=True,consent_pose=args.extract_pose,recorded_at=captured_at,
        width=width,height=height,video=filename,writer_codec=codec,camera_reported_fps=fps if math.isfinite(fps) else None,
        encoding_fps=encoded_fps,actual_fps=(index-1)/interval,frame_count=index,
        duration_s=duration,capture_cpu_seconds=capture_cpu,encoded_duration_s=index/encoded_fps,
        duration_difference_s=index/encoded_fps-interval,
        long_intervals=sum(b['elapsed_s']-a['elapsed_s']>2/encoded_fps for a,b in zip(frame_rows,frame_rows[1:])),
        read_errors=failures,hardware_dropped_frames=None,video_sha256=digest(root/filename),
        frames_sha256=digest(root/'frames.jsonl'),pose_status='PENDING'))
    write(root/'label.json',dict(label='UNVERIFIED',activity=args.activity))
    return root


def extract(root):
    m, video, stamps=verify_video(root)
    m['consent_pose']=True
    m['pose_status']='POSE_EXTRACTION_FAILED'
    write(root/'manifest.json',m)
    import mediapipe as mp
    import cv2
    import numpy as np
    from ml.features import extract_keypoints, normalize_sequence, resample_keypoints
    from research.streaming import SIZE, STRIDE, valid_window

    points=[]
    temporary=root/'pose.partial'
    with temporary.open('w') as out, mp.solutions.pose.Pose(model_complexity=0) as detector:
        for i,(frame,t) in enumerate(zip(video_frames(video),stamps,strict=True)):
            if frame.shape[:2]!=(m['height'],m['width']):
                raise ValueError('Decoded resolution mismatch')
            pose=extract_keypoints(detector.process(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).pose_landmarks)
            valid=bool(normalize_sequence([pose])[0,2::3].any())
            out.write(json.dumps(dict(index=i,elapsed_s=t,landmarks=pose.tolist(),valid=valid,
                                      schema=SPEC.schema_version),allow_nan=False)+'\n')
            points.append(pose)
    valid = normalize_sequence(resample_keypoints(stamps,np.asarray(points)))[:,2::3].any(axis=1)
    temporary.replace(root/'pose.jsonl')
    m.update(pose_status='COMPLETE',pose_extractor=f'MediaPipe {mp.__version__} Lite',
             pose_sha256=digest(root/'pose.jsonl'),pose_from_video_sha256=m['video_sha256'],
             valid_pose_frames=sum(r['valid'] for r in rows(root/'pose.jsonl')),
             usable_windows=sum(valid_window(valid[i:i+SIZE]) for i in range(0,len(valid)-SIZE+1,STRIDE)))
    write(root/'manifest.json',m)


def validate(root, *, confirmed=False):
    import numpy as np
    m,video,stamps=verify_video(root)
    if sum(1 for _ in video_frames(video))!=len(stamps):
        raise ValueError('Decoded video and timestamps differ')
    if m['pose_status']=='COMPLETE':
        if not m['consent_pose'] or m['pose_from_video_sha256']!=m['video_sha256'] or digest(root/'pose.jsonl')!=m['pose_sha256']:
            raise ValueError('Pose provenance mismatch')
        for i,(row,t) in enumerate(zip(rows(root/'pose.jsonl'),stamps,strict=True)):
            pose=np.asarray(row['landmarks'])
            if (row['index']!=i or row['elapsed_s']!=t or row['schema']!=SPEC.schema_version
                    or pose.shape!=(17,3) or not np.isfinite(pose).all()
                    or ((pose[:,2]<0)|(pose[:,2]>1)).any() or type(row['valid']) is not bool):
                raise ValueError('Pose alignment/schema mismatch')
    label=read(root/'label.json')
    if label['activity']!=m['activity'] or label['label'] not in ('UNVERIFIED','EXCLUDED','NO_FALL'):
        raise ValueError('Invalid label')
    if label['label']!='UNVERIFIED' and label.get('video_sha256')!=m['video_sha256']:
        raise ValueError('Label belongs to a different video')
    if confirmed and (label['label']!='NO_FALL' or m['pose_status']!='COMPLETE' or not m['usable_windows']):
        raise ValueError('Need verified NO_FALL and usable aligned poses')
    return dict(m,label=label['label'])


def label_trial(root, verified):
    m = validate(root)
    if m['label'] != 'UNVERIFIED':
        raise ValueError('Recording already reviewed')
    write(root/'label.json',dict(label=verified,activity=m['activity'],video_sha256=m['video_sha256']))


def main():
    mode=sys.argv[1] if len(sys.argv)>1 and sys.argv[1] in ('extract','label','validate') else 'record'
    p=argparse.ArgumentParser(description=__doc__)
    if mode=='record':
        p.add_argument('--output',type=Path,required=True)
        p.add_argument('--subject',required=True)
        p.add_argument('--session',default=datetime.now().strftime('session_%Y%m%d'))
        p.add_argument('--source',required=True)
        p.add_argument('--camera-setup',required=True)
        p.add_argument('--activity',choices=ACTIVITIES,required=True)
        p.add_argument('--camera',type=int,default=0)
        p.add_argument('--duration',type=float,default=30)
        p.add_argument('--split',choices=('train','evaluation'),default='train')
        p.add_argument('--preview',action='store_true')
        p.add_argument('--save-video',action='store_true',help='Recording always saves the camera video')
        p.add_argument('--consent-video',action='store_true')
        modes=p.add_mutually_exclusive_group()
        modes.add_argument('--video-only',action='store_true',help='Default')
        modes.add_argument('--extract-pose',action='store_true',help='Also confirms permission to extract private pose data')
        p.add_argument('--non-interactive',action='store_true')
        a=p.parse_args()
        root=record(a)
        print(root,flush=True)
        if a.extract_pose:
            extract(root)
        if sys.stdin.isatty() and not a.non_interactive:
            choice = input('Review the saved video. Enter NO_FALL, EXCLUDED, or blank to leave unverified: ').strip().upper()
            if choice in ('NO_FALL','EXCLUDED'):
                label_trial(root, choice)
        print(json.dumps(validate(root),indent=2))
    else:
        p.add_argument('--input',type=Path,required=True)
        if mode=='extract':
            p.add_argument('--consent-pose',action='store_true',required=True)
        elif mode=='label':
            p.add_argument('--verified',choices=('NO_FALL','EXCLUDED'),required=True)
        else:
            p.add_argument('--confirmed',action='store_true')
        a=p.parse_args(sys.argv[2:])
        if mode=='extract':
            extract(a.input)
            print(json.dumps(validate(a.input),indent=2))
        elif mode=='label':
            label_trial(a.input, a.verified)
        elif (a.input/'manifest.json').exists():
            print(json.dumps(validate(a.input,confirmed=a.confirmed),indent=2))
        else:
            records=[]
            for path in sorted(a.input.glob('subjects/*/*/*/manifest.json')):
                m=validate(path.parent,confirmed=a.confirmed)
                records.append(dict(trial=m,trace_sha256=m['video_sha256'],
                                    pose_identity=m.get('pose_sha256',m['video_sha256']),
                                    path=path.parent.relative_to(a.input).as_posix()))
            if not records:
                raise ValueError('No recordings')
            check_splits(records)
            write(a.input/'dataset_manifest.json',dict(version=3,recordings=records))
            print(f'Validated {len(records)} recordings')


if __name__=='__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
