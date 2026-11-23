"""Replay research pose CSV through the live detector without any notification transport."""
import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.immobility import ImmobilityDetector

JOINTS = ("Nose", "Left Eye", "Right Eye", "Left Ear", "Right Ear", "Left Shoulder",
          "Right Shoulder", "Left Elbow", "Right Elbow", "Left Wrist", "Right Wrist",
          "Left Hip", "Right Hip", "Left Knee", "Right Knee", "Left Ankle", "Right Ankle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pose_csv", type=Path)
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    frames = {}
    with args.pose_csv.open(newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = float(row["Timestamp"])
            points = frames.setdefault(stamp, np.zeros((17, 3), dtype=np.float32))
            points[JOINTS.index(row["Keypoint"])] = [float(row[key]) for key in ("X", "Y", "Confidence")]
    detector = ImmobilityDetector(args.seconds)
    transitions = []
    states = set()
    for stamp, points in sorted(frames.items()):
        reading = detector.update(stamp, points)
        states.add(reading.state.value)
        if reading.transition:
            transitions.append(dict(stamp=stamp, state=reading.state.value, duration_s=reading.duration_s))
    print(json.dumps(dict(frames=len(frames), states=sorted(states), transitions=transitions)))


if __name__ == "__main__":
    main()
