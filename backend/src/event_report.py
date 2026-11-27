"""Presentation of recorded event facts across Web, email and Telegram."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TITLES = {
    "fall": "Nghi ngờ té ngã", "immobility": "Bất động kéo dài",
    "environment": "Môi trường bất thường", "device": "Lỗi giám sát",
    "gas": "Tín hiệu gas bất thường", "temperature": "Nhiệt độ bất thường", "humidity": "Độ ẩm bất thường",
}
SEVERITIES = {"critical": "Nghiêm trọng", "warning": "Trung bình", "info": "Thông tin"}
STATUSES = {"OPEN": "Đang mở", "ACKNOWLEDGED": "Đã tiếp nhận", "RESOLVED": "Đã xử lý", "FALSE_ALARM": "Cảnh báo nhầm"}
GUIDANCE = {
    "fall": "Liên hệ hoặc kiểm tra tình trạng người thân. Gọi cấp cứu nếu có dấu hiệu chấn thương nghiêm trọng.",
    "immobility": "Liên hệ người thân và kiểm tra tại chỗ nếu cần.",
    "gas": "Nếu nghi rò rỉ khí, hãy rời khu vực, tránh lửa và công tắc điện. Gọi trợ giúp từ nơi an toàn.",
    "temperature": "Kiểm tra nhiệt độ, thông gió và thiết bị điều hòa trong phòng.",
    "humidity": "Kiểm tra thông gió và các nguồn ẩm trong phòng.",
    "device": "Kiểm tra nguồn điện, kết nối mạng và camera.",
}


def local_time(value, zone):
    if not value:
        return None
    try:
        target = ZoneInfo(zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        target = timezone.utc
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return stamp.astimezone(target).strftime("%d/%m/%Y %H:%M:%S %Z")


def number(value):
    return f"{value:.1f}".removesuffix(".0").replace(".", ",")


def event_report(event, zone=None):
    payload = event.get("payload") or {}
    metadata = (event.get("detection") if "detection" in event else payload.get("detection")) or {}
    kind = event.get("kind")
    category = (metadata.get("metric") or kind) if kind == "environment" else kind
    unit = {"C": "°C"}.get(metadata.get("unit"), metadata.get("unit", ""))
    facts = []

    def add(label, value, suffix="", percent=False):
        if value is None:
            return
        if isinstance(value, (int, float)):
            value = number(value * 100 if percent else value)
        facts.append([label, f"{value}{suffix}"])

    if kind == "fall":
        score = event.get("initial_confidence")
        if score is None:
            score = event.get("model_score")
        add("Điểm dự đoán AI", payload.get("confidence") if score is None else score, "%", True)
        add("Ngưỡng lúc phát hiện", metadata.get("fall_confidence_threshold"), "%", True)
        add("Model", metadata.get("model_name"))
    if kind == "immobility":
        duration = metadata.get("measured_value")
        if duration is None:
            duration = payload.get("duration_s", event.get("duration_s"))
        add("Thời lượng bất động", duration, " giây")
        add("Ngưỡng bất động", metadata.get("threshold_value"), " giây")
    if kind == "environment":
        measured, threshold = metadata.get("measured_value"), metadata.get("threshold_value")
        suffix = f" {unit}" if unit else ""
        add("Giá trị đo", measured, suffix)
        add("Ngưỡng lúc phát hiện", threshold, suffix)
        if measured is not None and threshold is not None:
            add("Chênh lệch so với ngưỡng", measured - threshold, suffix)
        add("Chất lượng phép đo", {"valid": "Hợp lệ", "error": "Lỗi", "warming_up": "Đang làm nóng"}.get(metadata.get("measurement_quality")))
        add("Cảm biến", metadata.get("sensor"))
        if metadata.get("local_alarm_confirmed") is True:
            add("Còi tại chỗ", "Đã kích hoạt")
    if kind == "device":
        add("Heartbeat cuối", local_time(metadata.get("last_heartbeat_at"), zone))
    add("Phiên bản Edge", metadata.get("edge_version"))
    detail = {
        "title": TITLES.get(category, "Cảnh báo"),
        "severity": SEVERITIES.get(event.get("severity")),
        "status": STATUSES.get(event.get("status")),
        "source": {"fall":"AI", "immobility":"Quan sát tư thế", "environment":"Cảm biến", "device":"Giám sát hệ thống"}.get(kind),
        "observed": local_time(event.get("first_observed_at") or event.get("observed_at"), zone),
        "received": local_time(event.get("first_received_at") or event.get("received_at"), zone),
        "reason": event.get("reason") or payload.get("reason"),
        "facts": facts,
        "guidance": GUIDANCE.get(category, "Kiểm tra tình trạng người thân và môi trường trong phòng."),
    }
    return detail
