"""Kiểm thử tự động Nhóm 1: Giao thức Arduino USB Serial, PTY giả lập phần cứng & Auto-Mock."""
from __future__ import annotations

import os
import pty
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.sensors.arduino_bridge import (  # noqa: E402
    ArduinoBridge,
    camera_delta,
    format_telemetry_readings,
    parse_sensor_line,
)


class Group1SensorBridgeTests(unittest.TestCase):
    def test_parse_json_and_csv_and_ignore_protocol_lines(self) -> None:
        # Dòng JSON hợp lệ
        parsed = parse_sensor_line('{"temp":28.5,"hum":64.2,"gas":182,"gas_warmup":0,"pan":95,"tilt":88}')
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertAlmostEqual(parsed["temp"], 28.5)
        self.assertAlmostEqual(parsed["hum"], 64.2)
        self.assertAlmostEqual(parsed["gas"], 182.0)
        self.assertFalse(parsed["gas_warmup"])
        self.assertEqual(parsed["pan"], 95)
        self.assertEqual(parsed["tilt"], 88)

        # Dòng JSON lỗi DHT11 (null -> quality="error", tuyệt đối không thành 0)
        err_line = parse_sensor_line('{"temp":null,"hum":null,"gas":210,"gas_warmup":1}')
        readings = format_telemetry_readings(err_line)
        self.assertIsNone(readings["temperature"]["value"])
        self.assertEqual(readings["temperature"]["quality"], "error")
        self.assertIsNone(readings["humidity"]["value"])
        self.assertEqual(readings["humidity"]["quality"], "error")
        self.assertEqual(readings["gas"]["value"], 210.0)
        self.assertEqual(readings["gas"]["quality"], "warming_up")

        # Dự phòng CSV nếu teammate xuất dạng dấu phẩy
        csv_parsed = parse_sensor_line("29.4, 67.0, 195")
        self.assertIsNotNone(csv_parsed)
        assert csv_parsed is not None
        self.assertAlmostEqual(csv_parsed["temp"], 29.4)
        self.assertAlmostEqual(csv_parsed["hum"], 67.0)
        self.assertAlmostEqual(csv_parsed["gas"], 195.0)

        # Bỏ qua các dòng ACK điều khiển của Arduino
        for proto in ("READY", "PONG", "OK SERVO 90 90", "OK MOVE -5 0", "ERR OUT_OF_RANGE", "STATUS PAN=90 TILT=90 TARGET_PAN=90 TARGET_TILT=90 MOVING=0"):
            self.assertIsNone(parse_sensor_line(proto))

    def test_calibrated_camera_delta(self) -> None:
        # Theo hiệu chuẩn CameraPanTilt: PAN_DIRECTION=-1 (RIGHT = -deg, LEFT = +deg), TILT_DIRECTION=1
        self.assertEqual(camera_delta("RIGHT", 6, pan_direction=-1, tilt_direction=1), (-6, 0))
        self.assertEqual(camera_delta("LEFT", 6, pan_direction=-1, tilt_direction=1), (6, 0))
        self.assertEqual(camera_delta("UP", 5, pan_direction=-1, tilt_direction=1), (0, 5))
        self.assertEqual(camera_delta("DOWN", 5, pan_direction=-1, tilt_direction=1), (0, -5))

    def test_auto_fallback_to_mock_when_port_missing(self) -> None:
        bridge = ArduinoBridge(port="/dev/ttyUSB_DOES_NOT_EXIST_99", baudrate=115200)
        bridge.start()
        try:
            self.assertFalse(bridge.is_hardware_connected)
            self.assertEqual(bridge.active_mode, "mock")

            readings = bridge.get_telemetry_readings()
            self.assertEqual(readings["temperature"]["quality"], "valid")
            self.assertEqual(readings["humidity"]["quality"], "valid")
            self.assertEqual(readings["gas"]["quality"], "valid")
            self.assertGreater(readings["temperature"]["value"], 20.0)

            # Kiểm tra kẹp giới hạn cơ khí Servo [30..150] và [45..135]
            state = bridge.send_servo(999, 10)
            self.assertEqual(state["pan"], 150)
            self.assertEqual(state["tilt"], 45)

            state = bridge.center()
            self.assertEqual((state["pan"], state["tilt"]), (90, 90))

            state = bridge.detach()
            self.assertFalse(state["enabled"])
        finally:
            bridge.stop()

    def test_virtual_pty_arduino_serial_end_to_end(self) -> None:
        try:
            import serial  # noqa: F401
        except ImportError:
            self.skipTest("pyserial chưa được cài trong môi trường hiện tại")

        master_fd, slave_fd = pty.openpty()
        slave_name = os.ttyname(slave_fd)
        stop_evt = threading.Event()
        received_cmds: list[str] = []

        def fake_arduino_firmware() -> None:
            os.write(master_fd, b"READY\r\n")
            buf = b""
            pan, tilt = 90, 90
            while not stop_evt.is_set():
                try:
                    chunk = os.read(master_fd, 64)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    cmd = raw_line.decode("ascii", errors="ignore").strip()
                    if not cmd:
                        continue
                    received_cmds.append(cmd)
                    if cmd == "PING":
                        os.write(master_fd, b"PONG\r\n")
                    elif cmd.startswith("SERVO:"):
                        p_s, t_s = cmd[6:].split(",")
                        pan, tilt = int(p_s), int(t_s)
                        os.write(master_fd, f"OK SERVO {pan} {tilt}\r\n".encode())
                    elif cmd.startswith("MOVE "):
                        _, dp_s, dt_s = cmd.split()
                        pan += int(dp_s)
                        tilt += int(dt_s)
                        os.write(master_fd, f"OK MOVE {dp_s} {dt_s}\r\n".encode())
                    elif cmd == "CENTER":
                        pan, tilt = 90, 90
                        os.write(master_fd, b"OK CENTER\r\n")
                    elif cmd == "DETACH":
                        os.write(master_fd, b"OK DETACH\r\n")
                    elif cmd == "SENSORS":
                        os.write(
                            master_fd,
                            f'{{"temp":30.2,"hum":61.5,"gas":245,"gas_warmup":0,"pan":{pan},"tilt":{tilt}}}\r\n'.encode(),
                        )

        fw_thread = threading.Thread(target=fake_arduino_firmware, daemon=True)
        fw_thread.start()

        bridge = ArduinoBridge(port=slave_name, baudrate=115200)
        try:
            bridge.start()
            self.assertTrue(bridge.is_hardware_connected)
            # Đẩy 1 dòng JSON bất đồng bộ từ Arduino lên Pi
            os.write(master_fd, b'{"temp":29.6,"hum":63.0,"gas":188,"gas_warmup":0,"pan":90,"tilt":90}\r\n')
            time.sleep(0.15)

            tel = bridge.get_telemetry_readings()
            self.assertEqual(tel["temperature"]["value"], 29.6)
            self.assertEqual(tel["humidity"]["value"], 63.0)
            self.assertEqual(tel["gas"]["value"], 188.0)

            st = bridge.send_servo(110, 80)
            self.assertEqual((st["pan"], st["tilt"]), (110, 80))

            st = bridge.move_camera("RIGHT", 5)
            self.assertEqual(st["pan"], 105)

            st = bridge.center()
            self.assertEqual((st["pan"], st["tilt"]), (90, 90))

            st = bridge.detach()
            self.assertFalse(st["enabled"])
            self.assertIn("SERVO:110,80", received_cmds)
            self.assertIn("MOVE -5 0", received_cmds)
            self.assertIn("CENTER", received_cmds)
            self.assertIn("DETACH", received_cmds)
        finally:
            stop_evt.set()
            bridge.stop()
            for fd in (master_fd, slave_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass


if __name__ == "__main__":
    unittest.main()
