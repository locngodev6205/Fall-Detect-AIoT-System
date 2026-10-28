#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: notifier.py
Mô tả:
  Quản lý hệ thống ghi log và phát đi các cảnh báo đa kênh (MQTT Broker, Telegram Bot)
  cho cả sự kiện Té Ngã (Fall) và Nằm Bất Động Kéo Dài (Immobility).
"""

import os
import json
import time
import requests

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class Notifier:
    def __init__(
        self,
        device_id="RPi4-LivingRoom",
        enable_mqtt=True,
        mqtt_broker="localhost",
        mqtt_port=1883,
        mqtt_topic="smartfall/alerts",
        enable_telegram=False,
        telegram_token="",
        telegram_chat_id="",
        log_file="fall_detection_log.txt",
        target_audience="elderly"
    ):
        self.device_id = device_id
        self.log_file = log_file
        self.target_audience = target_audience

        # Cấu hình MQTT
        self.enable_mqtt = enable_mqtt and MQTT_AVAILABLE
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.mqtt_topic = mqtt_topic
        self.mqtt_client = None

        if self.enable_mqtt:
            self._init_mqtt()

        # Cấu hình Telegram
        self.enable_telegram = enable_telegram
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

    def _init_mqtt(self):
        try:
            self.mqtt_client = mqtt.Client(client_id=f"{self.device_id}_EdgeClient")
            self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, keepalive=60)
            self.mqtt_client.loop_start()
            self.log(f"Đã kết nối thành công tới MQTT Broker: {self.mqtt_broker}:{self.mqtt_port}")
        except Exception as e:
            self.log(f"CẢNH BÁO: Không thể kết nối tới MQTT Broker ({self.mqtt_broker}:{self.mqtt_port}): {e}")
            self.mqtt_client = None

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

    def send_fall_alert(self, confidence_float, confidence_pct_str):
        """Gửi cảnh báo té ngã đồng thời qua MQTT và Telegram."""
        message = f"🚨 PHÁT HIỆN TÉ NGÃ! Độ tin cậy: {confidence_pct_str}"
        self.log(message)

        # 1. Gửi tin nhắn qua Telegram
        self.send_telegram(message)

        # 2. Xuất payload qua MQTT
        if self.mqtt_client:
            payload = {
                "device_id": self.device_id,
                "event": "FALL_DETECTED",
                "confidence": float(confidence_float),
                "confidence_pct": confidence_pct_str,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "local_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            try:
                self.mqtt_client.publish(self.mqtt_topic, json.dumps(payload), qos=1)
                self.log(f"Đã bắn tin nhắn MQTT Fall Alert tới topic: {self.mqtt_topic}")
            except Exception as e:
                self.log(f"Lỗi publish MQTT fall alert: {e}")

    def send_immobility_alert(self, duration_seconds):
        """Gửi cảnh báo bất động kéo dài qua MQTT và Telegram."""
        immobile_msg = f"⚠️ CẢNH BÁO BẤT ĐỘNG! Đối tượng ({self.target_audience}) nằm im {duration_seconds:.0f}s!"
        self.log(immobile_msg)

        # 1. Gửi Telegram
        self.send_telegram(immobile_msg)

        # 2. Gửi MQTT
        if self.mqtt_client:
            payload = {
                "device_id": self.device_id,
                "target_audience": self.target_audience,
                "event": "PROLONGED_IMMOBILITY_DETECTED",
                "immobility_duration_s": int(duration_seconds),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "local_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            }
            try:
                self.mqtt_client.publish(self.mqtt_topic, json.dumps(payload), qos=1)
                self.log(f"Đã bắn MQTT Immobility Alert: bất động {duration_seconds:.1f}s")
            except Exception as e:
                self.log(f"Lỗi publish MQTT immobility alert: {e}")

    def send_telegram(self, message):
        """Gửi tin nhắn Telegram bằng Bot API."""
        if not self.enable_telegram or not self.telegram_token or not self.telegram_chat_id:
            return

        if self.telegram_token == "YOUR_TELEGRAM_BOT_TOKEN" or self.telegram_chat_id == "YOUR_TELEGRAM_CHAT_ID":
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
        """Ngắt kết nối MQTT client khi tắt chương trình."""
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
