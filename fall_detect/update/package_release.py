#!/usr/bin/env python3
"""Build only the Pi runtime from the checked-out release commit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tarfile


def build(version, commit, output, root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    if not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}', version) or not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Invalid version or commit')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    model = root / 'models/fall_detection_transformer.tflite'
    manifest = {'version': version, 'commit': commit, 'target': 'linux-arm64',
        'runtime_sha256': hashlib.sha256((root / 'requirements.txt').read_bytes()).hexdigest(),
        'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest()}
    files = []
    for name in ('edge', 'modules', 'update'):
        files.extend(p for p in (root / name).rglob('*.py') if '__pycache__' not in p.parts)
    features = root / 'ml/features.py'
    if features.is_file():
        files.append(features)
    files += [root / 'config.py', root / 'requirements.txt', root / 'run_edge.sh']
    bundle = output / 'annha-pi.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        for file in sorted(files):
            if file.is_symlink():
                raise ValueError('Unexpected source symlink')
            archive.add(file, arcname=str(file.relative_to(root)), recursive=False)
        content = json.dumps(manifest, sort_keys=True).encode()
        import io
        info = tarfile.TarInfo('release.json')
        info.size = len(content)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(content))
    manifest.update(bytes=bundle.stat().st_size, sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
    if manifest['bytes'] > 64 * 1024 * 1024:
        raise ValueError('Bundle is larger than 64 MiB')
    (output / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('version')
    parser.add_argument('commit')
    parser.add_argument('output')
    args = parser.parse_args()
    build(args.version, args.commit, args.output)
