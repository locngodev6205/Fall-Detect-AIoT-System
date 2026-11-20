"""Private, consent-gated hard-negative collection and V3 validation."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from ml.features import SHAPE, SPEC
from .diagnostics import Trace
from .streaming import CHECKPOINT_SHA

ACTIVITIES = ('bend-light','bend-deep','pick-up','hold-bend','sit-down','stand-up',
              'walking','turn','sit-stand','lie-down','leave-reenter')
IDENT = re.compile(r'[A-Za-z0-9_-]{1,64}')


@dataclass(frozen=True)
class Trial:
    recording: str
    subject: str
    session: str
    source: str
    camera_setup: str
    activity: str
    split: str
    consent: bool
    retention_days: int
    label: str = 'UNVERIFIED'
    height_cm: float | None = None
    angle_degrees: float | None = None

    def check(self):
        if any(not IDENT.fullmatch(value) for value in
               (self.recording,self.subject,self.session,self.source,self.camera_setup)):
            raise ValueError('Use pseudonymous IDs')
        if (self.activity not in ACTIVITIES or self.split not in ('train','evaluation')
                or self.consent is not True or type(self.retention_days) is not int
                or not 1 <= self.retention_days <= 365
                or self.label not in ('UNVERIFIED','NO_FALL','EXCLUDED')):
            raise ValueError('Invalid activity, split, label or consent/retention metadata')
        for v in (self.height_cm, self.angle_degrees):
            if v is not None and not math.isfinite(v):
                raise ValueError('Invalid measured camera setup')


def validate(directory, *, confirmed=False):
    manifest = json.loads((directory/'manifest.json').read_text())
    if manifest['version'] != 3 or manifest['schema'] != SPEC.schema_version:
        raise ValueError('Unknown V3 schema')
    trial = Trial(**manifest['trial'])
    trial.check()
    decision = directory/'label.json'
    if decision.exists():
        label = json.loads(decision.read_text())
        if label['trace_sha256'] != manifest['trace_sha256']:
            raise ValueError('Label checksum does not match trace')
        trial = Trial(**{**asdict(trial), 'label':label['label']})
        trial.check()
    if confirmed and trial.label != 'NO_FALL':
        raise ValueError('Only verified NO_FALL trials are eligible for expansion')
    content = (directory/'trace.jsonl').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest['trace_sha256'] or digest != (directory/'sha256').read_text().strip():
        raise ValueError('Trace checksum mismatch')
    header, *records = [json.loads(line) for line in content.splitlines()]
    if (header.get('kind') != 'header' or header.get('version') != 1 or header.get('pose') is not True
            or header.get('schema') != SPEC.schema_version or header.get('checkpoint') != CHECKPOINT_SHA
            or header.get('scenario') != trial.activity):
        raise ValueError('Trace provenance mismatch')
    frames = [r for r in records if r['kind']=='frame']
    if any(r['kind'] not in ('frame','reset') for r in records) or len(frames)<2:
        raise ValueError('Missing frames or invalid record')
    times = np.array([r['stamp'] for r in frames])
    if not np.isfinite(times).all() or (np.diff(times)<=0).any() or not 1.9 <= times[-1]-times[0]<=61:
        raise ValueError('Invalid timestamps or duration')
    identity = hashlib.sha256()
    # Pose-only identity also detects rewrapped copies with altered timestamps.
    valid = scored = 0
    for row in frames:
        if type(row['pose_valid']) is not bool or 'pose' not in row:
            raise ValueError('Missing pose completeness data')
        pose = np.zeros(SHAPE,dtype='<f4') if row['pose'] is None else np.asarray(row['pose'],dtype='<f4')
        if pose.shape != SHAPE or not np.isfinite(pose).all() or ((pose[:,2]<0)|(pose[:,2]>1)).any():
            raise ValueError('Invalid pose')
        identity.update(pose.tobytes())
        valid += row['pose_valid']
        scored += sum(w['score'] is not None for w in row['windows'])
    if confirmed and (not valid or not scored):
        raise ValueError('No usable human pose or scored window')
    device = manifest['device']
    if (any(type(device[k]) is not int or device[k]<=0 for k in ('width','height'))
            or not device.get('mediapipe') or not 0 < device['throughput_fps'] < math.inf):
        raise ValueError('Missing device provenance')
    return dict(trial=asdict(trial), trace_sha256=digest, pose_identity=identity.hexdigest(),
                frames=len(frames), missing=len(frames)-valid, scored=scored,
                start=float(times[0]),end=float(times[-1]),duration=float(times[-1]-times[0]),
                recorded_fps=float((len(times)-1)/(times[-1]-times[0])))


def check_splits(records):
    groups, recordings, digests, poses = {},set(),set(),set()
    for row in records:
        m = row['trial']
        for field in ('subject','session','source','camera_setup'):
            key = (field,m[field])
            if groups.setdefault(key,m['split']) != m['split']:
                raise ValueError(f'Cross-split {field}: {m[field]}')
        for index,key in ((recordings,m['recording']),(digests,row['trace_sha256']),
                          (poses,row['pose_identity'])):
            if key in index:
                raise ValueError('Duplicate recording or trace/pose content')
            index.add(key)


def start(args):
    from .benchmark import benchmark
    from .guided_test import vnc_preview
    from .streaming import load_model
    import torch

    trial = Trial(**json.loads(args.metadata.read_text()))
    trial.check()
    if not args.consent_pose or trial.label != 'UNVERIFIED':
        raise ValueError('Collection requires explicit pose consent and UNVERIFIED label')
    torch.set_num_threads(2)
    model = load_model(args.checkpoint)
    with Trace(args.output,scenario=trial.activity,include_pose=True) as trace, vnc_preview(args.preview) as preview:
        metrics = benchmark(args.camera,model,0,live=True,limit=args.seconds,preview=preview,trace=trace)
    device = {k:metrics[k] for k in ('width','height','throughput_fps','mediapipe','opencv','complexity')}
    manifest = dict(version=3,schema=SPEC.schema_version,trial=asdict(trial),device=device,
                    trace_sha256=(args.output/'sha256').read_text().strip())
    with (args.output/'manifest.json').open('x') as stream:
        json.dump(manifest,stream,indent=2,allow_nan=False)
    print(json.dumps(validate(args.output)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--camera', type=int, default=0)
    prep.add_argument('--checkpoint', type=Path, required=True)
    label = sub.add_parser('label')
    label.add_argument('directory', type=Path)
    label.add_argument('--verified', choices=('NO_FALL','EXCLUDED'), required=True)
    run = sub.add_parser('start')
    run.add_argument('--metadata',type=Path,required=True)
    run.add_argument('--output',type=Path,required=True)
    run.add_argument('--checkpoint',type=Path,required=True)
    run.add_argument('--consent-pose',action='store_true')
    run.add_argument('--preview',action='store_true')
    run.add_argument('--camera',type=int,default=0)
    run.add_argument('--seconds',type=int,choices=range(30,61),default=30)
    check = sub.add_parser('validate')
    check.add_argument('directories',type=Path,nargs='+')
    check.add_argument('--confirmed',action='store_true')
    args = parser.parse_args()
    if args.command == 'start':
        start(args)
    elif args.command == 'prepare':
        from .streaming import load_model
        from .guided_test import prepare
        load_model(args.checkpoint)
        result = prepare(args.camera)
        print(json.dumps(result))
        if not result['ready']:
            raise SystemExit(2)
    elif args.command == 'label':
        row = validate(args.directory)
        with (args.directory/'label.json').open('x') as out:
            json.dump(dict(label=args.verified, trace_sha256=row['trace_sha256']),out)
    else:
        rows = [validate(path,confirmed=args.confirmed) for path in args.directories]
        check_splits(rows)
        print(json.dumps(rows,indent=2))


if __name__ == '__main__':
    main()
