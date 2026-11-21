"""Send one clearly labelled test event with a real laptop webcam photo.

Run from fall_detect: python -m edge.send_test_event --env-file .env.edge.test --send
No network requests or camera access occur without --send.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from .client.device_client import DeviceClient
from .main_edge import load_env_file
from .pairing import _check_url


def credentials(env_path: Path) -> tuple[str, str]:
    load_env_file(env_path)
    filename = '.env.edge.pairing.json' if env_path.name == '.env.edge' else f'.env.edge.pairing-{env_path.name}.json'
    state_path = env_path.with_name(filename)
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    base_url = (os.getenv('ANNHA_BASE_URL') or os.getenv('BACKEND_URL') or state.get('base_url') or '').rstrip('/')
    _check_url(base_url)
    token = os.getenv('DEVICE_TOKEN', '').strip()
    if not token:
        if not state.get('paired') or state.get('base_url', '').rstrip('/') != base_url:
            raise ValueError('Chưa ghép nối với backend này. Chạy main_edge --mock --pair trước.')
        token = state.get('token', '')
    if not token:
        raise ValueError('Thiếu token thiết bị đã ghép nối.')
    return base_url, token


def capture_jpeg(camera_id: int) -> bytes:
    import cv2

    camera = cv2.VideoCapture(camera_id)
    try:
        if not camera.isOpened():
            raise ValueError(f'Không mở được webcam {camera_id}. Kiểm tra quyền camera và ứng dụng đang dùng camera.')
        frame = None
        for _ in range(10):
            ok, current = camera.read()
            if ok:
                frame = current
        if frame is None:
            raise ValueError('Webcam không trả về ảnh. Chưa tạo sự kiện.')
        ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise ValueError('Không mã hóa được JPEG. Chưa tạo sự kiện.')
        return encoded.tobytes()
    finally:
        camera.release()


def send_test_event(client: DeviceClient, jpeg: bytes, kind: str) -> str:
    event = client.send_event(kind=kind, severity='critical', observation='abnormal',
                              reason='KIỂM THỬ THỦ CÔNG: ảnh webcam máy tính; không phải bất thường do AI/cảm biến phát hiện.')
    if not event or not event.get('id'):
        raise ValueError('Chưa xác nhận được event_id. Kiểm tra kết nối và token thiết bị; không upload ảnh sang sự kiện khác.')
    event_id = str(event['id'])
    print(f'Đã tạo sự kiện KIỂM THỬ: {event_id}', flush=True)
    asset = client.upload_evidence(jpeg, internal_event_id=event_id, filename=f'{kind}_test_webcam.jpg')
    if not asset:
        raise ValueError(f'Upload ảnh thất bại cho {event_id}. Sự kiện vẫn tồn tại; cảnh báo có thể được gửi không ảnh.')
    return event_id


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Chụp webcam và gửi một sự kiện KIỂM THỬ kèm ảnh qua API hiện có.')
    parser.add_argument('--env-file', type=Path, default=Path('.env.edge.test'))
    parser.add_argument('--camera-id', type=int, default=0)
    parser.add_argument('--kind', choices=('fall', 'immobility', 'environment', 'device'), default='fall')
    parser.add_argument('--send', action='store_true', help='Cho phép tạo sự kiện thật trên backend và kích hoạt các kênh cảnh báo đã bật.')
    args = parser.parse_args(argv)
    if not args.send:
        print('Chưa gửi gì. Thêm --send để chụp webcam, tạo sự kiện KIỂM THỬ và kích hoạt cảnh báo đã cấu hình.')
        return 0
    try:
        base_url, token = credentials(args.env_file)
        jpeg = capture_jpeg(args.camera_id)
        with tempfile.TemporaryDirectory(prefix='annha-test-event-') as cache:
            client = DeviceClient(base_url, token, cache_dir=cache)
            try:
                event_id = send_test_event(client, jpeg, args.kind)
            finally:
                client.stop()
        print(f'Ảnh đã upload: {base_url}/#/event/{event_id}')
        print('Kiểm tra Email/Telegram và lịch sử gửi trên Web. Upload thành công chưa xác nhận nhà cung cấp đã gửi thông báo.')
        return 0
    except (ImportError, OSError, ValueError, KeyError) as error:
        print(f'Không hoàn tất kiểm thử: {error}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
