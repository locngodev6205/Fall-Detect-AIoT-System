#!/usr/bin/env bash
# Read-only preflight or evidence capture. Run as the Edge service account.
set -euo pipefail
mode=${1:?preflight or evidence}
out=${2:?new private output directory}
umask 077
case "$mode" in
  preflight)
    src=${3:?fall_detect directory}
    py=${4:?absolute path to virtualenv Python}
    [[ $(uname -m) == aarch64 ]]
    systemctl show -p Version --value
    "$py" -c 'import sys,cv2,mediapipe; assert sys.prefix != sys.base_prefix'
    free=$(df -Pk /opt | awk 'NR==2 {print $4}')
    (( free >= 393216 ))
    test -r "$src/models/fall_detection_transformer.tflite"
    test -e /dev/video0
    test -s "$src/.env.edge"
    mkdir -m 700 -- "$out"
    cp -- "$src/.env.edge" "$out/"
    for file in "$src/.env" "$src"/.env.edge.pairing*.json; do
      [[ ! -f "$file" ]] || cp -- "$file" "$out/"
    done
    chmod 600 "$out"/.[!.]*
    ls -l /dev/video0
    command -v v4l2-ctl >/dev/null && v4l2-ctl --list-devices
    sha256sum "$src/models/fall_detection_transformer.tflite"
    printf '%s\n' 'Confirm camera preview, inference, audio, sensor readings and paired test backend in the existing UI before bootstrap.'
    ;;
  evidence)
    mkdir -m 700 -- "$out"
    systemctl show annha-edge.service annha-updater.service -p ActiveState -p SubState > "$out/services.txt"
    journalctl -u annha-edge.service -u annha-updater.service --since '-30 min' --no-pager > "$out/systemd.log"
    readlink /opt/annha/current > "$out/current.txt"
    if [[ -f /opt/annha/shared/update-journal.json ]]; then
      cp /opt/annha/shared/update-journal.json "$out/update-journal.json"
      chmod 600 "$out/update-journal.json"
    fi
    ;;
  *) exit 2 ;;
esac
