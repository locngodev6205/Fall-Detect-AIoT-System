#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script tự động khởi tạo hạ tầng ThingsBoard cho dự án Fall-Detect-AIoT-System:
1. Tạo Rule Chain riêng: 'SmartFall Rule Chain' (Lưu Telemetry, Attributes, RPC và gọi Webhook tới Backend :8000).
2. Tạo Device Profile riêng: 'SmartFall_Profile' trỏ vào 'SmartFall Rule Chain' (không ảnh hưởng tới dự án SmartFace).
3. Tạo Thiết bị: 'RASPI_ROOM_101' với Access Token cố định: 'smartfall_pi4_token_101'.
4. Khởi tạo Shared Attributes và Telemetry mặc định cho thiết bị.
5. Tạo Dashboard trực quan: 'SmartFall AIoT Monitor' và xuất file cấu hình JSON.
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

TB_URL = os.getenv("TB_URL", "http://127.0.0.1:8080")
TB_USERNAME = os.getenv("TB_USERNAME", "tenant@thingsboard.org")
TB_PASSWORD = os.getenv("TB_PASSWORD", "tenant")

DEVICE_NAME = os.getenv("DEVICE_ID", "RASPI_ROOM_101")
DEVICE_TOKEN = os.getenv("TB_TOKEN", "smartfall_pi4_token_101")
PROFILE_NAME = "SmartFall_Profile"
RULE_CHAIN_NAME = "SmartFall Rule Chain"
DASHBOARD_TITLE = "SmartFall AIoT Monitor"
BACKEND_WEBHOOK_URL = os.getenv("BACKEND_WEBHOOK_URL", "http://host.docker.internal:8000/api/tb-webhook")

OUT_DIR = Path(__file__).resolve().parent


class TBClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.token = self._login(username, password)

    def _login(self, username, password):
        req = urllib.request.Request(
            f"{self.base_url}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))["token"]

    def get(self, path):
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"X-Authorization": f"Bearer {self.token}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def post(self, path, payload):
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-Authorization": f"Bearer {self.token}"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}


def ensure_rule_chain(tb: TBClient):
    rcs = tb.get("/api/ruleChains?pageSize=50&page=0").get("data", [])
    rc = next((r for r in rcs if r["name"] == RULE_CHAIN_NAME), None)
    if not rc:
        rc = tb.post("/api/ruleChain", {
            "name": RULE_CHAIN_NAME,
            "type": "CORE",
            "debugMode": False,
            "configuration": None
        })
        print(f"[+] Đã tạo Rule Chain mới: {RULE_CHAIN_NAME} ({rc['id']['id']})")
    else:
        print(f"[*] Sử dụng Rule Chain hiện có: {RULE_CHAIN_NAME} ({rc['id']['id']})")

    rc_id = rc["id"]
    nodes = [
        {
            "type": "org.thingsboard.rule.engine.telemetry.TbMsgTimeseriesNode",
            "name": "Save Timeseries",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 1,
            "configuration": {
                "defaultTTL": 0,
                "useServerTs": False,
                "processingSettings": {"type": "ON_EVERY_MESSAGE"}
            },
            "additionalInfo": {"layoutX": 800, "layoutY": 150}
        },
        {
            "type": "org.thingsboard.rule.engine.telemetry.TbMsgAttributesNode",
            "name": "Save Client Attributes",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 3,
            "configuration": {
                "processingSettings": {"type": "ON_EVERY_MESSAGE"},
                "scope": "CLIENT_SCOPE",
                "notifyDevice": False,
                "sendAttributesUpdatedNotification": False,
                "updateAttributesOnlyOnValueChange": True
            },
            "additionalInfo": {"layoutX": 800, "layoutY": 50}
        },
        {
            "type": "org.thingsboard.rule.engine.filter.TbMsgTypeSwitchNode",
            "name": "Message Type Switch",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 0,
            "configuration": {"version": 0},
            "additionalInfo": {"layoutX": 350, "layoutY": 220}
        },
        {
            "type": "org.thingsboard.rule.engine.action.TbLogNode",
            "name": "Log RPC from Device",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 0,
            "configuration": {
                "scriptLang": "TBEL",
                "jsScript": "return '\\nIncoming message:\\n' + JSON.stringify(msg) + '\\nIncoming metadata:\\n' + JSON.stringify(metadata);",
                "tbelScript": "return '\\nIncoming message:\\n' + JSON.stringify(msg) + '\\nIncoming metadata:\\n' + JSON.stringify(metadata);"
            },
            "additionalInfo": {"layoutX": 800, "layoutY": 260}
        },
        {
            "type": "org.thingsboard.rule.engine.action.TbLogNode",
            "name": "Log Other",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 0,
            "configuration": {
                "scriptLang": "TBEL",
                "jsScript": "return '\\nIncoming message:\\n' + JSON.stringify(msg) + '\\nIncoming metadata:\\n' + JSON.stringify(metadata);",
                "tbelScript": "return '\\nIncoming message:\\n' + JSON.stringify(msg) + '\\nIncoming metadata:\\n' + JSON.stringify(metadata);"
            },
            "additionalInfo": {"layoutX": 800, "layoutY": 360}
        },
        {
            "type": "org.thingsboard.rule.engine.rpc.TbSendRPCRequestNode",
            "name": "RPC Call Request",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 0,
            "configuration": {"timeoutInSeconds": 60},
            "additionalInfo": {"layoutX": 800, "layoutY": 460}
        },
        {
            "type": "org.thingsboard.rule.engine.profile.TbDeviceProfileNode",
            "name": "Device Profile Node",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 1,
            "configuration": {
                "persistAlarmRulesState": False,
                "fetchAlarmRulesStateOnStart": False
            },
            "additionalInfo": {"layoutX": 150, "layoutY": 220}
        },
        {
            "type": "org.thingsboard.rule.engine.filter.TbJsFilterNode",
            "name": "Check Fall or Immobility Alert",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 0,
            "configuration": {
                "scriptLang": "TBEL",
                "jsScript": "return msg.event === 'FALL_DETECTED' || msg.event === 'PROLONGED_IMMOBILITY_DETECTED';",
                "tbelScript": "return msg.event == 'FALL_DETECTED' || msg.event == 'PROLONGED_IMMOBILITY_DETECTED';"
            },
            "additionalInfo": {
                "description": "Lọc các gói tin cảnh báo khẩn cấp (Té ngã hoặc Bất động kéo dài)",
                "layoutX": 800,
                "layoutY": 570
            }
        },
        {
            "type": "org.thingsboard.rule.engine.rest.TbRestApiCallNode",
            "name": "Forward Alert to SmartFall Backend",
            "debugSettings": None,
            "singletonMode": False,
            "queueName": None,
            "configurationVersion": 3,
            "configuration": {
                "restEndpointUrlPattern": BACKEND_WEBHOOK_URL,
                "requestMethod": "POST",
                "useSimpleClientHttpFactory": False,
                "parseToPlainText": False,
                "ignoreRequestBody": False,
                "enableProxy": False,
                "useSystemProxyProperties": False,
                "proxyScheme": None,
                "proxyHost": None,
                "proxyPort": 0,
                "proxyUser": None,
                "proxyPassword": None,
                "readTimeoutMs": 5000,
                "maxParallelRequestsCount": 0,
                "headers": {"Content-Type": "application/json"},
                "credentials": {"type": "anonymous"},
                "maxInMemoryBufferSizeInKb": 256
            },
            "additionalInfo": {
                "description": "Đẩy cảnh báo sang FastAPI Backend để phát WebSocket thời gian thực",
                "layoutX": 1120,
                "layoutY": 570
            }
        }
    ]

    connections = [
        {"fromIndex": 6, "toIndex": 2, "type": "Success"},
        {"fromIndex": 2, "toIndex": 0, "type": "Post telemetry"},
        {"fromIndex": 2, "toIndex": 1, "type": "Post attributes"},
        {"fromIndex": 2, "toIndex": 3, "type": "RPC Request from Device"},
        {"fromIndex": 2, "toIndex": 4, "type": "Other"},
        {"fromIndex": 2, "toIndex": 5, "type": "RPC Request to Device"},
        {"fromIndex": 2, "toIndex": 7, "type": "Post telemetry"},
        {"fromIndex": 7, "toIndex": 8, "type": "True"}
    ]

    metadata = {
        "ruleChainId": rc_id,
        "firstNodeIndex": 6,
        "nodes": nodes,
        "connections": connections,
        "ruleChainConnections": None
    }
    saved_meta = tb.post("/api/ruleChain/metadata", metadata)
    rc_updated = tb.get(f"/api/ruleChain/{rc_id['id']}")
    export_obj = {"ruleChain": rc_updated, "metadata": saved_meta}
    out_file = OUT_DIR / "smartfall_rule_chain.json"
    out_file.write_text(json.dumps(export_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Đã cấu hình và xuất Rule Chain ra: {out_file}")
    return rc_updated


def ensure_device_profile(tb: TBClient, rule_chain_id):
    profiles = tb.get("/api/deviceProfiles?pageSize=50&page=0").get("data", [])
    prof = next((p for p in profiles if p["name"] == PROFILE_NAME), None)
    payload = {
        "name": PROFILE_NAME,
        "type": "DEFAULT",
        "transportType": "DEFAULT",
        "provisionType": "DISABLED",
        "defaultRuleChainId": rule_chain_id,
        "description": "Device Profile chuyên dụng cho thiết bị biên phát hiện té ngã Raspberry Pi (SmartFall)",
        "profileData": {
            "configuration": {"type": "DEFAULT"},
            "transportConfiguration": {"type": "DEFAULT"},
            "provisionConfiguration": {"type": "DISABLED", "provisionDeviceSecret": None},
            "alarms": None
        }
    }
    if prof:
        payload["id"] = prof["id"]
        payload["createdTime"] = prof["createdTime"]
        payload["tenantId"] = prof["tenantId"]

    saved_prof = tb.post("/api/deviceProfile", payload)
    print(f"[+] Đã cấu hình Device Profile '{PROFILE_NAME}' -> Rule Chain '{RULE_CHAIN_NAME}'")
    return saved_prof


def ensure_device_and_token(tb: TBClient, profile_id):
    devices = tb.get("/api/tenant/devices?pageSize=50&page=0").get("data", [])
    dev = next((d for d in devices if d["name"] == DEVICE_NAME), None)
    payload = {
        "name": DEVICE_NAME,
        "type": PROFILE_NAME,
        "label": "Raspberry Pi 4 - Phòng Giám Sát Té Ngã 101",
        "deviceProfileId": profile_id,
        "additionalInfo": {
            "description": "Thiết bị biên Raspberry Pi chạy MediaPipe + Transformer TFLite phát hiện té ngã & bất động"
        }
    }
    if dev:
        payload["id"] = dev["id"]
        payload["createdTime"] = dev["createdTime"]
        payload["tenantId"] = dev["tenantId"]
        payload["customerId"] = dev.get("customerId")

    saved_dev = tb.post("/api/device", payload)
    dev_id = saved_dev["id"]["id"]

    # Gán Access Token cố định
    creds = tb.get(f"/api/device/{dev_id}/credentials")
    creds["credentialsType"] = "ACCESS_TOKEN"
    creds["credentialsId"] = DEVICE_TOKEN
    creds["credentialsValue"] = None
    tb.post("/api/device/credentials", creds)
    print(f"[+] Đã cấu hình Device '{DEVICE_NAME}' (ID: {dev_id}) với Access Token: '{DEVICE_TOKEN}'")

    # Khởi tạo Shared Attributes
    shared_attrs = {
        "target_audience": "elderly",
        "fall_confidence_threshold": 0.85,
        "immobility_timeout_seconds": 120,
        "enable_immobility_detection": True,
        "show_fps": True
    }
    tb.post(f"/api/plugins/telemetry/DEVICE/{dev_id}/SHARED_SCOPE", shared_attrs)

    # Gửi gói Telemetry mẫu ban đầu để Dashboard hiển thị ngay
    initial_telemetry = {
        "status": "ONLINE",
        "person_present": False,
        "person_status": "KHÔNG CÓ NGƯỜI",
        "ai_state": "NO_PERSON",
        "fps": 16.8,
        "fall_prob": 0.0,
        "immobile_seconds": 0.0,
        "target_audience": "elderly",
        "last_alert_event": "NONE",
        "last_alert_time": "Chưa có cảnh báo"
    }
    tb.post(f"/api/plugins/telemetry/DEVICE/{dev_id}/timeseries/ANY", initial_telemetry)
    print(f"[+] Đã khởi tạo Shared Attributes và Telemetry mặc định cho '{DEVICE_NAME}'")
    return saved_dev


def ensure_dashboard(tb: TBClient, device_id_str: str):
    # Đọc template từ smartface_dashboard.json và tuỳ biến cho SmartFall
    template_path = Path("/mnt/windows/Users/62205/Documents/locngo/school/7th-semester/PBL6/SmartFace-AIoT-Based-Staff-Management-Attendance-System/smartface_dashboard.json")
    base_db = json.loads(template_path.read_text(encoding="utf-8"))

    alias_id = "3e904359-de03-4499-89ef-7b3dbb0e1932"
    base_db["title"] = DASHBOARD_TITLE
    base_db["name"] = DASHBOARD_TITLE
    base_db["configuration"]["description"] = "Dashboard giám sát phát hiện té ngã & bất động thời gian thực trên Raspberry Pi (SmartFall AIoT)"

    # Cập nhật Entity Alias trỏ vào thiết bị RASPI_ROOM_101
    base_db["configuration"]["entityAliases"][alias_id] = {
        "id": alias_id,
        "alias": DEVICE_NAME,
        "filter": {
            "type": "singleEntity",
            "singleEntity": {
                "entityType": "DEVICE",
                "id": device_id_str
            }
        }
    }

    widgets = base_db["configuration"]["widgets"]
    layout_widgets = base_db["configuration"]["states"]["default"]["layouts"]["main"]["widgets"]

    # Xóa 2 widget theo yêu cầu: Đồng hồ FPS và Biểu đồ Thời gian bất động
    for rem_id in ["4642eea0-c3b8-48d7-9f5e-db0078808e4d", "b1a2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"]:
        widgets.pop(rem_id, None)
        layout_widgets.pop(rem_id, None)

    # Widget: Biểu đồ xác suất té ngã P(Fall) (id 3c59e4be-03a5-44c8-ab5f-62b49183941d)
    w_prob = widgets["3c59e4be-03a5-44c8-ab5f-62b49183941d"]
    w_prob["config"]["title"] = "Xác Suất Té Ngã Thời Gian Thực - P(Fall)"
    w_prob["config"]["datasources"][0]["dataKeys"][0]["name"] = "fall_prob"
    w_prob["config"]["datasources"][0]["dataKeys"][0]["label"] = "Xác suất P(Fall)"
    w_prob["config"]["datasources"][0]["dataKeys"][0]["color"] = "#ef4444"
    w_prob["config"]["settings"]["thresholds"] = [
        {
            "thresholdValue": 0.85,
            "thresholdColor": "#ef4444",
            "thresholdName": "Ngưỡng Báo Động Té Ngã (0.85)"
        }
    ]

    # Widget: HTML Status Card (id 30dde395-e4fc-4cc8-bf9b-e5f549e3db81)
    w_card = widgets["30dde395-e4fc-4cc8-bf9b-e5f549e3db81"]
    w_card["config"]["title"] = f"Trạng Thái Giám Sát Phòng ({DEVICE_NAME})"
    w_card["config"]["datasources"][0]["dataKeys"] = [
        {"name": "status", "type": "timeseries", "label": "status", "color": "#10b981", "settings": {}},
        {"name": "person_status", "type": "timeseries", "label": "person_status", "color": "#10b981", "settings": {}},
        {"name": "ai_state", "type": "timeseries", "label": "ai_state", "color": "#38bdf8", "settings": {}},
        {"name": "fps", "type": "timeseries", "label": "fps", "color": "#f59e0b", "settings": {}},
        {"name": "fall_prob", "type": "timeseries", "label": "fall_prob", "color": "#ef4444", "settings": {}},
        {"name": "immobile_seconds", "type": "timeseries", "label": "immobile_seconds", "color": "#f97316", "settings": {}},
        {"name": "target_audience", "type": "timeseries", "label": "target_audience", "color": "#a855f7", "settings": {}},
        {"name": "last_alert_event", "type": "timeseries", "label": "last_alert_event", "color": "#ef4444", "settings": {}},
        {"name": "last_alert_time", "type": "timeseries", "label": "last_alert_time", "color": "#94a3b8", "settings": {}},
        {"name": "cpu_temp", "type": "timeseries", "label": "cpu_temp", "color": "#ef4444", "settings": {}}
    ]
    w_card["config"]["settings"]["cardHtml"] = """<div class="gate-status-card">
  <div class="header-row">
    <div class="device-info">
      <span class="device-name">RASPI_ROOM_101</span>
      <span class="device-model">SmartFall Edge AIoT (MediaPipe + Transformer)</span>
    </div>
    <div class="badge status-badge">● ${status:ONLINE}</div>
  </div>
  
  <div class="telemetry-body">
    <div class="mode-container">
      <div class="mode-label">TRẠNG THÁI AI HIỆN TẠI</div>
      <div class="mode-value">${ai_state:NO_PERSON}</div>
    </div>
    
    <div class="telemetry-badges">
      <div class="badge-item">
        <span class="badge-label">Trong hình:</span>
        <span class="badge-val badge-AWAKE">${person_status:KHÔNG CÓ NGƯỜI}</span>
      </div>
      <div class="badge-item">
        <span class="badge-label">Đối tượng:</span>
        <span class="badge-val badge-AWAKE">${target_audience:elderly}</span>
      </div>
      <div class="badge-item">
        <span class="badge-label">P(Fall):</span>
        <span class="badge-val latch-READY">${fall_prob:0.00}</span>
      </div>
    </div>
  </div>

  <div class="section-divider"></div>

  <div class="hw-section">
    <div class="section-title">🚨 CHỈ SỐ AN TOÀN & CẢNH BÁO GẦN NHẤT</div>
    <div class="hw-grid">
      <div class="hw-box">
        <span class="hw-name">TG Bất Động</span>
        <span class="hw-val">${immobile_seconds:0}s</span>
      </div>
      <div class="hw-box">
        <span class="hw-name">Sự Kiện Gần Nhất</span>
        <span class="hw-val">${last_alert_event:NONE}</span>
      </div>
      <div class="hw-box">
        <span class="hw-name">Thời Điểm Báo</span>
        <span class="hw-val">${last_alert_time:--:--}</span>
      </div>
    </div>
  </div>

  <div class="footer-row">
    <div class="info-item">Chuỗi: <span>30 frames (17 khớp)</span></div>
    <div class="info-item">Tốc độ: <span>${fps:0} FPS</span></div>
    <div class="info-item">Model: <span>Transformer TFLite</span></div>
  </div>
</div>"""

    # Widget 5: Switch RPC bật/tắt giám sát bất động (id 35fa7634-b016-40c0-b681-a833ad7ad31b)
    w_switch = widgets["35fa7634-b016-40c0-b681-a833ad7ad31b"]
    w_switch["config"]["title"] = "Điều Khiển Giám Sát Bất Động (2 Chiều RPC)"
    w_switch["config"]["targetDeviceId"] = device_id_str
    w_switch["config"]["settings"]["title"] = "BẬT / TẮT Phát Hiện Nằm Bất Động Kéo Dài"
    w_switch["config"]["settings"]["getValueMethod"] = "getImmobilityDetection"
    w_switch["config"]["settings"]["setValueMethod"] = "setImmobilityDetection"
    w_switch["config"]["settings"]["valueKey"] = "enable_immobility_detection"
    w_switch["config"]["settings"]["parseValueFunction"] = "return data === true || data === 'true';"

    # Căn chỉnh lại bố cục 3 widget còn lại tràn đều 24 cột
    layout_widgets["30dde395-e4fc-4cc8-bf9b-e5f549e3db81"] = {
        "sizeX": 14, "sizeY": 6, "row": 0, "col": 0, "mobileOrder": 1
    }
    layout_widgets["35fa7634-b016-40c0-b681-a833ad7ad31b"] = {
        "sizeX": 10, "sizeY": 6, "row": 0, "col": 14, "mobileOrder": 2
    }
    layout_widgets["3c59e4be-03a5-44c8-ab5f-62b49183941d"] = {
        "sizeX": 24, "sizeY": 7, "row": 6, "col": 0, "mobileOrder": 3
    }

    base_db["configuration"]["states"]["default"]["name"] = DASHBOARD_TITLE

    # Kiểm tra xem Dashboard đã tồn tại chưa
    dashboards = tb.get("/api/tenant/dashboards?pageSize=50&page=0").get("data", [])
    existing = next((d for d in dashboards if d["title"] == DASHBOARD_TITLE), None)
    if existing:
        existing_full = tb.get(f"/api/dashboard/{existing['id']['id']}")
        base_db["id"] = existing_full["id"]
        base_db["createdTime"] = existing_full["createdTime"]
        base_db["tenantId"] = existing_full["tenantId"]
        base_db["version"] = existing_full.get("version", 1)
    else:
        base_db.pop("id", None)
        base_db.pop("createdTime", None)
        base_db.pop("tenantId", None)
        base_db.pop("version", None)
        base_db.pop("assignedCustomers", None)

    saved_db = tb.post("/api/dashboard", base_db)
    out_file = OUT_DIR / "smartfall_dashboard.json"
    out_file.write_text(json.dumps(saved_db, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Đã cấu hình Dashboard '{DASHBOARD_TITLE}' (ID: {saved_db['id']['id']}) và xuất ra: {out_file}")
    return saved_db


def main():
    print("=" * 65)
    print(f"ĐANG CẤU HÌNH THINGSBOARD TẠI: {TB_URL}")
    print("=" * 65)
    tb = TBClient(TB_URL, TB_USERNAME, TB_PASSWORD)
    rc = ensure_rule_chain(tb)
    prof = ensure_device_profile(tb, rc["id"])
    dev = ensure_device_and_token(tb, prof["id"])
    db = ensure_dashboard(tb, dev["id"]["id"])
    print("=" * 65)
    print("HOÀN TẤT CẤU HÌNH THINGSBOARD CHO FALL-DETECT-AIOT-SYSTEM!")
    print(f"  - ThingsBoard UI : {TB_URL}")
    print(f"  - Dashboard      : {DASHBOARD_TITLE} (ID: {db['id']['id']})")
    print(f"  - Device Name    : {DEVICE_NAME}")
    print(f"  - Access Token   : {DEVICE_TOKEN}")
    print(f"  - Rule Chain     : {RULE_CHAIN_NAME}")
    print("=" * 65)


if __name__ == "__main__":
    main()
