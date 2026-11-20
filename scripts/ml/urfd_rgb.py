#!/usr/bin/env python3
"""Package official URFD RGB PNGs as a lossless video on their sync timeline."""
import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile


def read_sync(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        rows = [(int(row[0]), int(row[1])) for row in csv.reader(stream) if row]
    indices = [index for index, _ in rows]
    timestamps = [ms for _, ms in rows]
    if not rows or indices != list(range(1, len(rows) + 1)):
        raise ValueError('URFD synchronization frame IDs must be contiguous and one-based')
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError('URFD synchronization timestamps must be strictly increasing')
    return [value - timestamps[0] for value in timestamps]


def pack_rgb(archive, sync, output):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    times = read_sync(sync)
    with TemporaryDirectory(prefix='annha-urfd-') as folder, ZipFile(archive) as source:
        root = Path(folder)
        matches = {}
        for name in source.namelist():
            match = re.fullmatch(r'.*-(\d+)\.png', Path(name).name)
            if match:
                index = int(match[1])
                if index in matches:
                    raise ValueError('Duplicate RGB frame ID')
                matches[index] = name
        if sorted(matches) != list(range(1, len(times) + 1)):
            raise ValueError('RGB archive frame IDs differ from synchronization file')
        script = ['ffconcat version 1.0']
        for index, name in sorted(matches.items()):
            frame = f'{index:06}.png'
            (root / frame).write_bytes(source.read(name))
            script.extend([f'file {frame}', 'option framerate 1000'])
            if index < len(times):
                script.append(f'duration {(times[index] - times[index-1])/1000:.3f}')
        (root / 'frames.ffconcat').write_text('\n'.join(script)+'\n')
        candidate = root / 'video.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','concat','-safe','0','-i','frames.ffconcat',
                        '-fps_mode','vfr','-c:v','libx264rgb','-threads','2','-crf','0',
                        '-video_track_timescale','1000','video.mp4'], cwd=root, check=True)
        probe = subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
                                         '-show_entries','frame=best_effort_timestamp_time','-of','json',str(candidate)])
        actual = [round(float(frame['best_effort_timestamp_time']) * 1000)
                  for frame in json.loads(probe)['frames']]
        if actual != times:
            raise ValueError('Encoded RGB frame timestamps differ from official synchronization')
        import shutil
        with candidate.open('rb') as inp, output.open('xb') as dst:
            shutil.copyfileobj(inp, dst)
    return len(times)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('sync', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print('Preserved RGB frames:', pack_rgb(args.archive, args.sync, args.output))


if __name__ == '__main__':
    main()
