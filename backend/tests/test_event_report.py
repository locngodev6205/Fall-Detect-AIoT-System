from unittest import TestCase
from unittest.mock import patch

from backend.src.event_report import event_report
from backend.src.pgservices import format_safety_email, format_telegram_caption, format_telegram_event


class EventReportTests(TestCase):
    def record(self, **fields):
        return {
            "id": "fixture-id", "kind": "fall", "severity": "critical", "status": "OPEN",
            "first_observed_at": "2026-11-27T07:32:18+00:00", "timezone": "Asia/Ho_Chi_Minh",
            "received_at": "2026-11-27T07:32:19+00:00", "room_name": "Phòng khách",
            "camera_name": "Camera <1>", "home_name": "Nhà", "model_score": 0.968, **fields,
        }

    def test_old_event_does_not_get_a_threshold_from_current_settings(self):
        report = event_report(self.record(fall_confidence_threshold=0.70), "Asia/Ho_Chi_Minh")
        self.assertEqual(report["facts"], [["Điểm dự đoán AI", "96,8%"]])
        self.assertIn("14:32:18", report["observed"])

    def test_snapshot_used_across_channels(self):
        event = self.record(detection={"fall_confidence_threshold": 0.85, "model_name": "Transformer TFLite"},
                            reason="<script>alert(1)</script>", payload={"detection": {"fall_confidence_threshold": 0.70}})
        with patch.dict("os.environ", {"PUBLIC_URL": "https://annha.example"}):
            rendered = format_safety_email(event, "Người nhận")
            self.assertEqual(rendered.subject, "[AnNhà][Khẩn cấp] Nghi ngờ té ngã — Phòng khách")
            self.assertIn("85%", rendered.text)
            self.assertIn("96,8%", rendered.html)
            self.assertNotIn("<script>", rendered.html)
            home = {"name": "🏠" * 120, "timezone": event["timezone"]}
            for format_message, limit in ((format_telegram_caption, 1024), (format_telegram_event, 4096)):
                text = format_message(home, {**event, "reason": "👤" * 2500})
                self.assertLessEqual(len(text.encode("utf-16-le")) // 2, limit)
                self.assertIn("85%", text)
                self.assertTrue(text.endswith("/#/event/fixture-id"))

    def test_event_specific_facts(self):
        for metric, unit in (("gas", "ADC"), ("temperature", "C"), ("humidity", "%")):
            with self.subTest(metric=metric):
                report = event_report(self.record(kind="environment", detection={
                    "metric": metric, "unit": unit, "measured_value": 55,
                    "threshold_value": 50, "measurement_quality": "valid",
                }))
                self.assertIn("Chênh lệch so với ngưỡng", dict(report["facts"]))
                self.assertNotIn("ppm", str(report))
        self.assertEqual(dict(event_report(self.record(kind="immobility", duration_s=42))["facts"])["Thời lượng bất động"], "42 giây")
        self.assertIn("Heartbeat cuối", dict(event_report(self.record(kind="device",
            detection={"last_heartbeat_at":"2026-11-27T07:30:00Z"}), "Asia/Ho_Chi_Minh")["facts"]))
