"""Kiểm thử USB Webcam và truyền hình trực tiếp (Live Stream) lên Web UI AnNhà.

Chạy trực tiếp trên Raspberry Pi 4:
    cd ~/test/fall_detect
    python3 test_camera_stream.py
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time

try:
    import cv2
except ImportError:
    print("❌ LỖI: Chưa cài đặt thư viện 'opencv-python'.")
    print("👉 Hãy chạy: pip install opencv-python-headless (hoặc sudo apt-get install -y python3-opencv)")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("❌ LỖI: Chưa cài đặt thư viện 'websockets'.")
    print("👉 Hãy chạy: pip install websockets")
    sys.exit(1)

# Thêm thư mục gốc fall_detect vào sys.path để import edge
ROOT_DIR = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tests" else Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from edge.client.device_client import DeviceClient  # noqa: E402
from edge.client.live_streamer import LiveStreamer  # noqa: E402


def load_env_edge(path: Path) -> dict[str, str]:
    env = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("'\"")
    return env


def main() -> None:
    env_file = ROOT_DIR / ".env.edge"
    env_data = load_env_edge(env_file)
    base_url = env_data.get("ANNHA_BASE_URL", "http://10.241.104.36:8188").rstrip("/")
    token = env_data.get("DEVICE_TOKEN", "").strip()

    if not token:
        print(f"❌ Không tìm thấy DEVICE_TOKEN trong {env_file}")
        print("👉 Hãy đảm bảo file .env.edge đã có ANNHA_BASE_URL và DEVICE_TOKEN hợp lệ.")
        return

    print("====================================================================")
    print(" KIỂM THỬ USB WEBCAM VÀ TRUYỀN HÌNH TRỰC TIẾP LÊN WEB ANNHÀ")
    print("====================================================================")
    print(f"  • Backend URL : {base_url}")
    print(f"  • Token       : {token[:16]}... ({len(token)} ký tự)")

    # 1. Mở Camera USB
    print("\n[1/3] Đang kết nối tới USB Webcam (/dev/video0)...")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Không thể mở Camera USB (index 0).")
        print("👉 Hãy kiểm tra:")
        print("   1. Webcam đã cắm chặt vào cổng USB của Pi chưa? Chạy 'ls -l /dev/video*' để kiểm tra.")
        print("   2. Nếu cổng là /dev/video1 hoặc khác, có thể thử index 1.")
        return

    # Thiết lập độ phân giải chuẩn cho đường truyền mượt trên Pi
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"  ✅ Camera mở thành công: {width}x{height} px")

    # 2. Khởi tạo DeviceClient (để gửi heartbeat cho Web hiển thị 'Trực tuyến')
    print("\n[2/3] Bật Heartbeat báo 'Trực tuyến'...")
    client = DeviceClient(base_url, token, cache_dir=ROOT_DIR / "edge_cache").start()
    hb = client.send_heartbeat(observation="clear", camera_ok=True, speaker_ok=True, sensors_ok=True)
    if hb:
        print("  ✅ Báo trạng thái Trực tuyến thành công!")
    else:
        print("  ⚠️ Gửi heartbeat cảnh báo lỗi xác thực, kiểm tra lại base_url và token.")

    # 3. Khởi tạo LiveStreamer đẩy ảnh JPEG qua WebSocket /ws/device/frames
    print("\n[3/3] Bắt đầu truyền luồng video WebSocket (/ws/device/frames)...")
    streamer = LiveStreamer(base_url, token, fps_limit=5.0).start()

    print("\n" + "=" * 68)
    print(" 🚀 ĐANG TRUYỀN HÌNH TRỰC TIẾP TỪ USB WEBCAM LÊN WEB!")
    print(f" 👉 Hãy mở trình duyệt trên máy tính/điện thoại:")
    print(f"    {base_url}/#/cameras")
    print(" 👉 Nhấp vào Camera của bạn để xem Live Video.")
    print("    (Nhấn Ctrl + C để dừng phát luồng)")
    print("=" * 68 + "\n")

    frame_count = 0
    t0 = time.time()
    last_hb_time = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("⚠️ Không đọc được khung hình từ webcam, đang thử lại...")
                time.sleep(0.2)
                continue

            elapsed = time.time() - t0
            fps = frame_count / elapsed if elapsed > 0 else 0

            # Vẽ OSD FPS ở góc dưới bên phải
            h_f, w_f = frame.shape[:2]
            box_w, box_h = 180, 32
            bx1, by1 = max(10, w_f - box_w - 15), max(10, h_f - box_h - 15)
            cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (18, 28, 36), -1)
            cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (0, 230, 150), 1)
            cv2.putText(frame, f"FPS: {fps:4.1f}", (bx1 + 14, by1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 180), 1, cv2.LINE_AA)

            # Nén sang JPEG chất lượng 70% để tiết kiệm băng thông và truyền mượt
            ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok_enc:
                jpeg_bytes = buf.tobytes()
                streamer.update_frame_jpeg(jpeg_bytes)
                frame_count += 1

                # In log tiến độ mỗi 10 frames (~2 giây)
                if frame_count % 10 == 0:
                    print(f"  🎥 Đã truyền {frame_count:4d} frames | Tốc độ: {fps:4.1f} FPS | Cỡ frame: {len(jpeg_bytes)/1024:.1f} KB")

            # Gửi heartbeat định kỳ mỗi 10 giây
            if time.time() - last_hb_time >= 10.0:
                client.send_heartbeat(observation="clear", camera_ok=True, speaker_ok=True, sensors_ok=True)
                last_hb_time = time.time()

            # Giới hạn ~5 khung hình/giây
            time.sleep(0.18)

    except KeyboardInterrupt:
        print("\n🛑 Người dùng bấm dừng test.")
    finally:
        print("Đang giải phóng camera và đóng kết nối...")
        cap.release()
        streamer.stop()
        client.stop()
        print("✅ Hoàn tất kiểm thử Camera USB.")


if __name__ == "__main__":
    main()
