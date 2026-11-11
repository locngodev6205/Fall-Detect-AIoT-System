"""Kiểm thử Nhóm 3: Điều khiển Servo Pan-Tilt (PTZ) từ Web UI + Live Stream Webcam.

Chạy trực tiếp trên Raspberry Pi 4:
    cd ~/test/fall_detect
    python3 test_ptz_web.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT_DIR = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tests" else Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import cv2
except ImportError:
    cv2 = None

from edge.client.device_client import DeviceClient  # noqa: E402
from edge.client.live_streamer import LiveStreamer  # noqa: E402
from edge.sensors.arduino_bridge import ArduinoBridge  # noqa: E402
from edge.tracking.pan_tilt_tracker import PanTiltTracker  # noqa: E402


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
    env_data = load_env_edge(ROOT_DIR / ".env.edge")
    base_url = env_data.get("ANNHA_BASE_URL", "http://10.241.104.36:8188").rstrip("/")
    token = env_data.get("DEVICE_TOKEN", "").strip()

    if not token:
        print("❌ Không tìm thấy DEVICE_TOKEN trong .env.edge")
        return

    print("====================================================================")
    print(" KIỂM THỬ NHÓM 3: ĐIỀU KHIỂN XOAY SERVO PTZ TỪ WEB UI")
    print("====================================================================")
    print(f"  • Backend URL : {base_url}")
    print(f"  • Token       : {token[:16]}...")

    # 1. Kết nối Arduino
    print("\n[1/4] Đang kết nối Arduino Serial...")
    bridge = ArduinoBridge().start()
    bridge.center()
    print("  ✅ Arduino đã sẵn sàng. Đã đưa 2 Servo về góc trung tâm (90°, 90°).")

    # 2. Khởi tạo Tracker
    tracker = PanTiltTracker(bridge=bridge)

    # 3. Mở Webcam USB
    cap = None
    if cv2 is not None:
        print("\n[2/4] Đang mở Camera USB (/dev/video0)...")
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            print("  ✅ Webcam USB mở thành công (640x480).")
        else:
            print("  ⚠️ Không mở được webcam index 0, sẽ bỏ qua luồng video.")
            cap = None

    # 4. Khởi tạo LiveStreamer
    streamer = LiveStreamer(base_url, token, fps_limit=5.0).start()

    # 5. Khởi tạo DeviceClient và đăng ký bộ xử lý lệnh PTZ từ Web
    print("\n[3/4] Đăng ký nhận lệnh PTZ từ Web UI...")
    client = DeviceClient(base_url, token, cache_dir=ROOT_DIR / "edge_cache")

    def handle_command(cmd: dict) -> tuple[bool, str]:
        kind = str(cmd.get("kind") or "")
        payload = cmd.get("payload") or {}
        print(f"\n📩 [LỆNH MỚI TỪ WEB] Loại: {kind} | Nội dung: {payload}")
        if kind in ("ptz_move", "ptz_center"):
            ok, detail = tracker.execute_ptz_command(cmd)
            cur = bridge.get_servo_state()
            print(f"  👉 Kết quả thực thi: {'THÀNH CÔNG' if ok else 'THẤT BÀI'} ({detail}) | Góc hiện tại: Pan={cur.get('pan')}°, Tilt={cur.get('tilt')}°")
            return ok, detail
        return False, f"Không hỗ trợ lệnh: {kind}"

    def handle_config(cfg: dict) -> None:
        smart_modes = cfg.get("smart_modes")
        if smart_modes:
            tracker.update_smart_modes(smart_modes)
            print(f"\n⚙️ [ĐỒNG BỘ CẤU HÌNH WEB] Smart Modes: {smart_modes}")

    client.set_command_handler(handle_command)
    client.on_config_updated(handle_config)
    client.start()

    # Báo online ban đầu
    client.send_heartbeat(observation="clear", camera_ok=True, speaker_ok=True, sensors_ok=True)

    print("\n[4/4] SẴN SÀNG NHẬN ĐIỀU KHIỂN!")
    print("=" * 68)
    print(" 🎮 BẠN HÃY MỞ TRÌNH DUYỆT VÀ THỰC HIỆN:")
    print(f"    1. Vào trang chi tiết camera: {base_url}/#/cameras")
    print("    2. Nhấp vào Camera 'PI của Lộc'")
    print("    3. Nhấn các nút trên cụm D-Pad: [ ⬆ Lên ] [ ⬇ Xuống ] [ ⬅ Trái ] [ ➡ Phải ] [ 🎯 90° ]")
    print("       -> Quan sát 2 Servo cơ học trên giá đỡ xoay theo từng nút nhấn!")
    print("    4. Bật / Tắt các công tắc Chế độ thông minh:")
    print("       • 'Tự động xoay Servo bám người'")
    print("       • 'Phát hiện té ngã AI'")
    print("       • 'Chế độ ban đêm 22:00–06:00'")
    print("=" * 68 + "\n")

    t_last_hb = time.time()
    t_last_tel = time.time()
    fps_frames = 0
    fps_t0 = time.time()
    current_fps = 0.0
    last_fps_log = time.time()

    try:
        while True:
            # 1. Truyền khung hình Webcam lên Web (nếu có webcam)
            if cap is not None:
                ret, frame = cap.read()
                if ret:
                    fps_frames += 1
                    now_f = time.time()
                    if now_f - fps_t0 >= 1.0:
                        current_fps = fps_frames / (now_f - fps_t0)
                        fps_frames = 0
                        fps_t0 = now_f

                    servo_st = bridge.get_servo_state()
                    pan_v = int(servo_st.get("pan", 90))
                    tilt_v = int(servo_st.get("tilt", 90))

                    # Vẽ OSD FPS ở góc dưới bên phải
                    h_f, w_f = frame.shape[:2]
                    box_w, box_h = 320, 32
                    bx1, by1 = max(10, w_f - box_w - 15), max(10, h_f - box_h - 15)
                    cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (18, 28, 36), -1)
                    cv2.rectangle(frame, (bx1, by1), (bx1 + box_w, by1 + box_h), (0, 230, 150), 1)
                    cv2.putText(frame, f"FPS: {current_fps:4.1f} | Pan: {pan_v}d | Tilt: {tilt_v}d", (bx1 + 12, by1 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 180), 1, cv2.LINE_AA)

                    if now_f - last_fps_log >= 2.0:
                        last_fps_log = now_f
                        print(f"  🎥 Live Stream FPS: {current_fps:4.1f} | Servo: Pan={pan_v}°, Tilt={tilt_v}°")

                    ok_enc, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if ok_enc:
                        streamer.update_frame_jpeg(buf.tobytes())

            # 2. Lắng nghe và thực thi ngay lệnh bấm nút từ Web (mỗi 0.25s)
            client.poll_and_execute_commands()

            # 3. Gửi Heartbeat mỗi 10 giây
            now = time.time()
            if now - t_last_hb >= 10.0:
                client.send_heartbeat(observation="clear", camera_ok=True, speaker_ok=True, sensors_ok=True)
                t_last_hb = now

            # 4. Gửi Telemetry cảm biến mỗi 3 giây
            if now - t_last_tel >= 3.0:
                client.send_telemetry(bridge.get_telemetry_readings())
                t_last_tel = now

            time.sleep(0.18)

    except KeyboardInterrupt:
        print("\n🛑 Người dùng bấm dừng test.")
    finally:
        print("Đang dọn dẹp và ngắt kết nối...")
        if cap is not None:
            cap.release()
        streamer.stop()
        client.stop()
        bridge.stop()
        print("✅ Hoàn tất kiểm thử Nhóm 3.")


if __name__ == "__main__":
    main()
