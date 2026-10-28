#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: notifier.py
Mô tả:
  Quản lý hệ thống ghi log, đồng bộ Telemetry/Attributes/RPC với ThingsBoard IoT Platform
  qua giao thức MQTT (cổng 1883, xác thực bằng Access Token) và phát cảnh báo Telegram.
"""

import os
import json
import time
import uuid
import requests

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


def get_cpu_temp():
    """Đọc nhiệt độ CPU trên Raspberry Pi / Linux (nếu có)."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return round(float(f.read().strip()) / 1000.0, 1)
    except Exception:
        return 45.0


class Notifier:
    def __init__(
        self,
        device_id="RASPI_ROOM_101",
        enable_mqtt=True,
        mqtt_broker="192.168.1.14",
        mqtt_port=1883,
        mqtt_topic="v1/devices/me/telemetry",
        tb_token="smartfall_pi4_token_101",
        enable_telegram=False,
        telegram_token="",
        telegram_chat_id="",
        log_file="fall_detection_log.txt",
        target_audience="elderly",
        enable_immobility=True,
        immobility_timeout_seconds=60,
        device_token="",
        on_settings_change=None
    ):
        self.device_id = device_id
        self.device_token = device_token
        self.log_file = log_file
        self.target_audience = target_audience
        self.enable_immobility = enable_immobility
        self.immobility_timeout_seconds = immobility_timeout_seconds
        self.on_settings_change = on_settings_change

        # Cấu hình ThingsBoard / MQTT
        self.enable_mqtt = enable_mqtt and MQTT_AVAILABLE
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.tb_token = tb_token
        self.telemetry_topic = "v1/devices/me/telemetry" if tb_token else mqtt_topic
        self.attributes_topic = "v1/devices/me/attributes"
        self.mqtt_client = None
        self.connected = False

        # Cấu hình Telegram
        self.enable_telegram = enable_telegram
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

        if self.enable_mqtt:
            self._init_mqtt()

    def _init_mqtt(self):
        try:
            try:
                self.mqtt_client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"smartfall_{self.device_id}"
                )
            except (AttributeError, TypeError):
                self.mqtt_client = mqtt.Client(client_id=f"smartfall_{self.device_id}")

            if self.tb_token:
                self.mqtt_client.username_pw_set(self.tb_token)

            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_disconnect = self._on_disconnect
            self.mqtt_client.on_message = self._on_message

            self.mqtt_client.connect_async(self.mqtt_broker, self.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()
        except Exception as e:
            self.log(f"CẢNH BÁO: Không thể khởi tạo kết nối ThingsBoard MQTT ({self.mqtt_broker}:{self.mqtt_port}): {e}")
            self.mqtt_client = None

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = (rc == 0)
        if not self.connected:
            self.log(f"[MQTT ERROR] Kết nối ThingsBoard thất bại tại {self.mqtt_broker}:{self.mqtt_port} (rc={rc}). Kiểm tra TB_TOKEN!")
            return

        self.log(f"[MQTT] Đã kết nối thành công tới ThingsBoard Broker ({self.mqtt_broker}:{self.mqtt_port})")

        if self.tb_token:
            # Đăng ký nhận Shared Attributes và lệnh điều khiển 2 chiều (RPC) từ ThingsBoard
            for sub in ["attributes", "attributes/response/+", "rpc/request/+"]:
                client.subscribe(f"v1/devices/me/{sub}", qos=1)

            # Gửi Client Attributes định danh thiết bị
            client_attrs = {
                "device_id": self.device_id,
                "target_audience": self.target_audience,
                "enable_immobility_detection": self.enable_immobility,
                "model": "MediaPipe BlazePose + Transformer TFLite"
            }
            client.publish(self.attributes_topic, json.dumps(client_attrs), qos=1)

            # Yêu cầu đọc Shared Attributes hiện tại từ ThingsBoard
            client.publish(
                "v1/devices/me/attributes/request/1",
                json.dumps({
                    "sharedKeys": "target_audience,fall_confidence_threshold,immobility_timeout_seconds,enable_immobility_detection,show_fps"
                }),
                qos=1
            )

    def _on_disconnect(self, client, userdata, flags_or_rc, *args):
        self.connected = False
        self.log("[MQTT] Mất kết nối tới ThingsBoard Broker!")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic

            # 1. Xử lý lệnh RPC 2 chiều từ Dashboard ThingsBoard
            if topic.startswith("v1/devices/me/rpc/request/") and isinstance(payload, dict):
                req_id = topic.rsplit("/", 1)[-1]
                method = payload.get("method")
                params = payload.get("params")
                response = {"success": True}

                if method in ("getImmobilityDetection", "getValue"):
                    response = self.enable_immobility
                elif method in ("setImmobilityDetection", "setValue"):
                    self.enable_immobility = bool(params)
                    if self.on_settings_change:
                        self.on_settings_change({"enable_immobility_detection": self.enable_immobility})
                    self.send_telemetry({"enable_immobility_detection": self.enable_immobility})
                    response = self.enable_immobility
                elif method == "setThreshold":
                    val = float(params.get("threshold", params) if isinstance(params, dict) else params)
                    if self.on_settings_change:
                        self.on_settings_change({"fall_confidence_threshold": val})
                    response = {"success": True, "fall_confidence_threshold": val}
                elif method == "setTargetAudience":
                    aud = str(params.get("target_audience", params) if isinstance(params, dict) else params).lower()
                    if aud in ("elderly", "child"):
                        self.target_audience = aud
                        if self.on_settings_change:
                            self.on_settings_change({"target_audience": aud})
                    response = {"success": True, "target_audience": self.target_audience}
                else:
                    response = {"error": f"unknown_method: {method}"}

                client.publish(f"v1/devices/me/rpc/response/{req_id}", json.dumps(response), qos=1)

            # 2. Xử lý đồng bộ Shared Attributes từ ThingsBoard
            elif isinstance(payload, dict):
                shared = payload.get("shared", payload)
                updates = {}
                if "target_audience" in shared:
                    self.target_audience = str(shared["target_audience"]).lower()
                    updates["target_audience"] = self.target_audience
                if "fall_confidence_threshold" in shared:
                    updates["fall_confidence_threshold"] = float(shared["fall_confidence_threshold"])
                if "immobility_timeout_seconds" in shared:
                    self.immobility_timeout_seconds = int(shared["immobility_timeout_seconds"])
                    updates["immobility_timeout_seconds"] = self.immobility_timeout_seconds
                if "enable_immobility_detection" in shared:
                    self.enable_immobility = bool(shared["enable_immobility_detection"])
                    updates["enable_immobility_detection"] = self.enable_immobility
                if "show_fps" in shared:
                    updates["show_fps"] = bool(shared["show_fps"])

                if updates and self.on_settings_change:
                    self.on_settings_change(updates)
        except Exception as e:
            self.log(f"[MQTT] Lỗi xử lý gói tin từ ThingsBoard: {e}")

    def log(self, message):
        """Ghi log có kèm dấu thời gian ra màn hình Console và lưu vào file txt."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + "\n")
        except Exception as e:
            print(f"Lỗi ghi file log: {e}")

    def send_telemetry(self, data: dict, qos=0):
        """Gửi gói dữ liệu Telemetry lên ThingsBoard (v1/devices/me/telemetry)."""
        if self.mqtt_client and self.connected and isinstance(data, dict):
            try:
                self.mqtt_client.publish(self.telemetry_topic, json.dumps(data), qos=qos)
                return True
            except Exception as e:
                self.log(f"Lỗi gửi telemetry: {e}")
        return False

    def send_heartbeat(self, fps_val: float, detection_result):
        """Gửi Telemetry định kỳ (FPS, trạng thái có người, xác suất ngã, thời gian bất động, nhiệt độ CPU) lên ThingsBoard."""
        person_present = bool(getattr(detection_result, "person_present", True))
        if not person_present:
            ai_state = "NO_PERSON"
        elif detection_result.is_fall:
            ai_state = "FALL"
        elif detection_result.immobile_duration >= self.immobility_timeout_seconds:
            ai_state = "IMMOBILE"
        else:
            ai_state = "NO_FALL"

        payload = {
            "device_id": self.device_id,
            "status": "ONLINE",
            "person_present": person_present,
            "person_status": "CÓ NGƯỜI" if person_present else "KHÔNG CÓ NGƯỜI",
            "ai_state": ai_state,
            "fps": round(float(fps_val), 1),
            "fall_prob": round(float(detection_result.raw_fall_prob), 4) if person_present else 0.0,
            "immobile_seconds": round(float(detection_result.immobile_duration), 1) if person_present else 0.0,
            "target_audience": self.target_audience,
            "cpu_temp": get_cpu_temp()
        }
        self.send_telemetry(payload, qos=0)

    def send_fall_alert(self, confidence_float, confidence_pct_str):
        """Gửi cảnh báo té ngã đồng thời lên ThingsBoard (Telemetry + Rule Chain Webhook) và Telegram."""
        now_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        message = f"🚨 PHÁT HIỆN TÉ NGÃ! Độ tin cậy: {confidence_pct_str}"
        self.log(message)

        # 1. Gửi tin nhắn qua Telegram
        self.send_telegram(message)

        # 2. Gửi sự kiện khẩn cấp lên ThingsBoard / MQTT Gateway
        payload = {
            "device_id": self.device_id,
            "device_token": self.device_token,
            "event_id": str(uuid.uuid4()),
            "target_audience": self.target_audience,
            "event": "FALL_DETECTED",
            "ai_state": "FALL",
            "confidence": round(float(confidence_float), 4),
            "confidence_pct": confidence_pct_str,
            "fall_prob": round(float(confidence_float), 4),
            "last_alert_event": f"FALL ({confidence_pct_str})",
            "last_alert_time": time.strftime("%H:%M:%S", time.localtime()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "local_time": now_local
        }
        if self.send_telemetry(payload, qos=1):
            self.log(f"Đã đẩy sự kiện FALL_DETECTED lên ThingsBoard ({self.telemetry_topic})")

    def send_immobility_alert(self, duration_seconds):
        """Gửi cảnh báo bất động kéo dài lên ThingsBoard và Telegram."""
        now_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        immobile_msg = f"⚠️ CẢNH BÁO BẤT ĐỘNG! Đối tượng ({self.target_audience}) nằm im {duration_seconds:.0f}s!"
        self.log(immobile_msg)

        # 1. Gửi Telegram
        self.send_telegram(immobile_msg)

        # 2. Gửi sự kiện lên ThingsBoard / MQTT Gateway
        payload = {
            "device_id": self.device_id,
            "device_token": self.device_token,
            "event_id": str(uuid.uuid4()),
            "target_audience": self.target_audience,
            "event": "PROLONGED_IMMOBILITY_DETECTED",
            "ai_state": "IMMOBILE",
            "immobility_duration_s": int(duration_seconds),
            "immobile_seconds": round(float(duration_seconds), 1),
            "last_alert_event": f"IMMOBILE ({int(duration_seconds)}s)",
            "last_alert_time": time.strftime("%H:%M:%S", time.localtime()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "local_time": now_local
        }
        if self.send_telemetry(payload, qos=1):
            self.log(f"Đã đẩy sự kiện PROLONGED_IMMOBILITY_DETECTED lên ThingsBoard ({duration_seconds:.1f}s)")

    def send_telegram(self, message):
        """Gửi tin nhắn Telegram bằng Bot API."""
        if not self.enable_telegram or not self.telegram_token or not self.telegram_chat_id:
            return

        if self.telegram_token in ("YOUR_TELEGRAM_BOT_TOKEN", "your_telegram_bot_token_here"):
            return

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {'chat_id': self.telegram_chat_id, 'text': message, 'parse_mode': 'Markdown'}
        try:
            response = requests.post(url, data=payload, timeout=10)
            response.raise_for_status()
            if response.json().get('ok', False):
                self.log("Đã gửi cảnh báo Telegram thành công.")
            else:
                self.log(f"Cảnh báo gửi Telegram thất bại: {response.text}")
        except Exception as e:
            self.log(f"Lỗi khi gửi cảnh báo Telegram: {e}")

    def disconnect(self):
        """Đánh dấu trạng thái OFFLINE và ngắt kết nối MQTT khi tắt chương trình."""
        if self.mqtt_client:
            try:
                if self.connected:
                    self.send_telemetry({"status": "OFFLINE", "fps": 0.0}, qos=1)
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.connected = False
