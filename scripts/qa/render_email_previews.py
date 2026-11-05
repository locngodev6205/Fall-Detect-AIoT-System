#!/usr/bin/env python3
"""Create offline HTML previews from the provider-independent draft templates."""
from html import escape
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.src.email_templates import render_email


OUTPUT = ROOT / 'docs/reports/assets/phase5-email-preview.html'
BASE = 'https://annha.example'


def samples():
    return [
        ('verification', 'Mã xác minh · tên ngắn', {'recipient_name': 'Minh', 'code': '48271635'}),
        ('verification', 'Mã xác minh · nội dung dài', {'recipient_name': 'Nguyễn Thị Minh Châu', 'code': '07391584'}),
        ('password_reset', 'Đặt lại mật khẩu · tên ngắn', {'recipient_name': 'An', 'code': '83012745'}),
        ('password_reset', 'Đặt lại mật khẩu · nội dung dài', {'recipient_name': 'Nguyễn Thị Minh Châu', 'code': '01593628'}),
        ('invitation', 'Lời mời · tên ngắn', {'recipient_name': 'Minh', 'inviter_name': 'Chủ nhà', 'home_name': 'Nhà AnNhà',
             'role_label': 'Người chăm sóc', 'scope_text': 'Phòng khách', 'token': 'preview-invite-short'}),
        ('invitation', 'Lời mời · nội dung dài', {'recipient_name': 'Nguyễn Thị Minh Châu', 'inviter_name': 'Nguyễn Văn Bình',
             'home_name': 'Ngôi nhà nhiều thế hệ của gia đình Nguyễn tại Thành phố Hồ Chí Minh',
             'role_label': 'Người chăm sóc',
             'scope_text': 'Phòng khách, phòng ngủ của bà, hành lang tầng hai và camera cửa chính',
             'token': 'preview-invite-long'}),
        ('safety_alert', 'Cảnh báo · nội dung ngắn', {'recipient_name': 'Minh', 'home_name': 'Nhà AnNhà',
             'room_name': 'Phòng khách', 'camera_name': 'Camera 1', 'severity_label': 'Cần lưu ý',
             'event_label': 'Nghi ngờ té ngã', 'occurred_at': '08:30 05/11/2026', 'event_id': 'preview-short'}),
        ('safety_alert', 'Cảnh báo · nội dung dài', {'recipient_name': 'Nguyễn Thị Minh Châu',
             'home_name': 'Ngôi nhà nhiều thế hệ của gia đình Nguyễn tại Thành phố Hồ Chí Minh',
             'room_name': 'Phòng sinh hoạt chung cạnh khu vườn phía sau',
             'camera_name': 'Camera tự động theo dõi khu vực cửa ra vào phía đông',
             'severity_label': 'Khẩn cấp', 'event_label': 'Môi trường bất thường',
             'occurred_at': '08:30:15 ngày 05/11/2026 (múi giờ Asia/Ho_Chi_Minh)', 'event_id': 'preview-long'}),
    ]


def frame(content, width, label):
    return (f'<figure class="device"><figcaption>{escape(label)} · {width}px</figcaption>'
            f'<iframe title="{escape(label)}" width="{width}" height="660" '
            f'srcdoc="{escape(content, quote=True)}"></iframe></figure>')


def main():
    sections = []
    for kind, label, values in samples():
        rendered = render_email(kind, public_url=BASE, **values)
        sections.append(f'''<section class="sample"><header><div><small>BẢN NHÁP · CHỜ DUYỆT</small><h2>{escape(label)}</h2></div>
          <div><strong>{escape(rendered.subject)}</strong><p>{escape(rendered.preheader)}</p></div></header>
          <div class="devices">{frame(rendered.html, 600, 'Desktop')}{frame(rendered.html, 375, 'Điện thoại')}</div>
          <details><summary>Xem bản text thuần</summary><pre>{escape(rendered.text)}</pre></details></section>''')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text('''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AnNhà · Bản xem trước email</title>
<style>body{margin:0;background:#f3f7f6;color:#1c3038;font:16px/1.5 Arial,sans-serif}.page{max-width:1440px;margin:auto;padding:32px 24px}h1{margin:0 0 8px}.intro{color:#5f747b;margin:0 0 28px}.draft{padding:14px 16px;border:1px solid #e1bf72;background:#fff8e7;border-radius:10px;margin-bottom:20px}.sample{background:white;border:1px solid #dce8e5;border-radius:16px;padding:22px;margin:18px 0}.sample header{display:flex;gap:24px;justify-content:space-between;align-items:flex-start;margin-bottom:14px}.sample header small{color:#137c76;font-weight:700;letter-spacing:.06em}.sample h2{margin:3px 0 0}.sample header p{margin:5px 0;color:#5f747b}.devices{display:flex;flex-wrap:wrap;align-items:flex-start;gap:18px;overflow:auto}.device{margin:0;flex:0 0 auto}.device figcaption{font-weight:700;margin:0 0 8px}.device iframe{display:block;border:1px solid #dce8e5;border-radius:10px;background:#f3f7f6;max-width:100%}details{margin-top:16px}pre{white-space:pre-wrap;background:#f5f8f7;padding:16px;border-radius:8px}@media(max-width:700px){.page{padding:18px 12px}.sample{padding:16px}.sample header{display:block}.device iframe{height:620px}}</style></head><body><main class="page"><h1>AnNhà · Xem trước email</h1><p class="intro">Bốn mẫu email · bản HTML và text thuần · dữ liệu hoàn toàn tổng hợp.</p><div class="draft"><strong>Đây là bản nháp chờ bạn duyệt.</strong> Nội dung và phong cách chưa được chốt, chưa dùng để gửi email thật.</div>''' + ''.join(sections) + '</main></body></html>', encoding='utf-8')
    print(f'Wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size} bytes; {len(samples())} preview cases).')


if __name__ == '__main__':
    main()
