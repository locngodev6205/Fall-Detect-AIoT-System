"""Provider-independent AnNhà email templates."""
from dataclasses import dataclass
from html import escape
import re
from urllib.parse import quote, urlencode, urlsplit


@dataclass(frozen=True)
class RenderedEmail:
    kind: str
    subject: str
    preheader: str
    html: str
    text: str


def _text(value, fallback=''):
    return str(value if value is not None else fallback)


def _base_url(public_url):
    value = _text(public_url).strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise ValueError('PUBLIC_URL phải là một địa chỉ HTTP(S) hợp lệ.')
    return value


def _token_link(public_url, page, token):
    return f"{_base_url(public_url)}/#/{page}?{urlencode({'token': _text(token)})}"


def _event_link(public_url, event_id):
    return f"{_base_url(public_url)}/#/event/{quote(_text(event_id), safe='')}"


def _layout(*, title, preheader, greeting, paragraphs, details, cta_label, link=None,
            verification_code=None, code_label='Mã xác minh', expiry=None, security_note=None):
    safe_link = escape(link, quote=True) if link else ''
    detail_rows = ''.join(
        '<tr><td style="padding:7px 12px 7px 0;color:#5f747b;vertical-align:top">'
        f'{escape(_text(label))}</td><td style="padding:7px 0;color:#1c3038;font-weight:600">'
        f'{escape(_text(value))}</td></tr>'
        for label, value in details if value not in (None, '')
    )
    paragraph_html = ''.join(
        f'<p style="margin:0 0 16px;line-height:1.65;color:#526970">{escape(_text(item))}</p>'
        for item in paragraphs
    )
    expiry_html = (
        f'<p style="margin:18px 0 0;line-height:1.55;color:#5f747b;font-size:14px">{escape(expiry)}</p>'
        if expiry else ''
    )
    security_html = (
        f'<p style="margin:14px 0 0;line-height:1.55;color:#5f747b;font-size:14px">{escape(security_note)}</p>'
        if security_note else ''
    )
    details_html = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;margin:4px 0 22px;border-top:1px solid #e1ebe8;border-bottom:1px solid #e1ebe8">'
        f'<tbody>{detail_rows}</tbody></table>' if detail_rows else ''
    )
    verification_code_html = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="width:100%;margin:22px 0 16px;background:#f1f8f6;border:1px solid #dcebe7;border-radius:12px">'
        '<tr><td align="center" style="padding:18px 12px">'
        f'<div style="margin-bottom:7px;color:#60767d;font-size:12px;font-weight:700;letter-spacing:1px">{escape(code_label.upper())}</div>'
        f'<div style="color:#137c76;font-family:Arial,Helvetica,sans-serif;font-size:32px;font-weight:700;letter-spacing:6px">{escape(_text(verification_code))}</div>'
        '</td></tr></table>' if verification_code else ''
    )
    cta_html = (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 18px"><tr><td bgcolor="#137c76" style="border-radius:9px">'
        f'<a class="email-cta" href="{safe_link}" style="display:inline-block;padding:14px 22px;border:1px solid #137c76;border-radius:9px;color:#fff;text-decoration:none;font-weight:700;line-height:1.3">{escape(cta_label)}</a>'
        '</td></tr></table>' if link else ''
    )
    link_fallback_html = (
        '<p style="margin:0 0 7px;color:#5f747b;font-size:14px;line-height:1.5">Nếu nút không mở được, hãy sao chép liên kết này vào trình duyệt:</p>'
        f'<p style="margin:0;overflow-wrap:anywhere;word-break:break-word;font-size:13px;line-height:1.55"><a href="{safe_link}" style="color:#137c76">{safe_link}</a></p>'
        if link else ''
    )
    html = f'''<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting"><title>{escape(title)}</title>
<style>
  @media screen and (max-width:600px) {{ .email-shell {{ width:100% !important; }} .email-card {{ padding:26px 20px !important; }} .email-cta {{ display:block !important; text-align:center !important; }} }}
</style></head>
<body style="margin:0;padding:0;background:#f3f7f6;font-family:Arial,Helvetica,sans-serif;color:#1c3038">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f3f7f6">
 <tr><td align="center" style="padding:28px 12px">
  <table role="presentation" class="email-shell" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px">
   <tr><td style="padding:0 8px 18px">
    <div style="font-size:27px;line-height:1.1;font-weight:700;letter-spacing:-.5px;color:#137c76">⌂ AnNhà</div>
    <div style="margin-top:6px;font-size:13px;color:#60767d">Nhà an tâm, mình an lòng</div>
   </td></tr>
   <tr><td class="email-card" style="padding:36px 40px;background:#fff;border:1px solid #dce8e5;border-radius:16px">
    <h1 style="margin:0 0 20px;font-size:25px;line-height:1.25;color:#1c3038">{escape(title)}</h1>
    <p style="margin:0 0 16px;line-height:1.65;color:#1c3038">Chào {escape(_text(greeting, 'bạn'))},</p>
    {paragraph_html}{details_html}
    {verification_code_html}{cta_html}{link_fallback_html}
    {expiry_html}{security_html}
   </td></tr>
   <tr><td style="padding:18px 8px 0;text-align:center;color:#71858a;font-size:12px;line-height:1.55">AnNhà · Thông báo tự động, vui lòng không trả lời email này.</td></tr>
  </table>
 </td></tr>
</table></body></html>'''

    text_lines = [title, '', f"Chào {_text(greeting, 'bạn')},", '', *map(_text, paragraphs)]
    if details:
        text_lines.extend(['', *(f'{_text(label)}: {_text(value)}' for label, value in details if value not in (None, ''))])
    if verification_code:
        text_lines.extend(['', f'{code_label}: {_text(verification_code)}', ''])
    elif link:
        text_lines.extend(['', f'{_text(cta_label)}: {link}', ''])
    if expiry:
        text_lines.extend([_text(expiry), ''])
    if security_note:
        text_lines.extend([_text(security_note), ''])
    text_lines.extend(['AnNhà · Nhà an tâm, mình an lòng', 'Thông báo tự động, vui lòng không trả lời email này.'])
    return html, '\n'.join(text_lines)


def render_email(kind, *, public_url='http://localhost:8188', **values):
    """Render one approved template to HTML and plain text."""
    name = _text(values.get('recipient_name'), 'bạn').strip() or 'bạn'
    verification_code = None
    if kind == 'verification':
        title = 'Xác minh địa chỉ email'
        preheader = 'Nhập mã xác minh để hoàn tất tạo tài khoản AnNhà.'
        link = None
        verification_code = _text(values.get('code', ''))
        if not re.fullmatch(r'\d{8}', verification_code):
            raise ValueError('Mã xác minh phải gồm 8 chữ số.')
        paragraphs = ['Hãy xác nhận đây là địa chỉ email của bạn để hoàn tất việc tạo tài khoản AnNhà.']
        details = []
        cta = 'Xác minh email'
        expiry = 'Mã có hiệu lực trong 24 giờ kể từ khi yêu cầu được tạo. Nếu mã hết hạn, bạn có thể yêu cầu gửi lại email xác minh.'
        note = 'Nếu bạn không tạo tài khoản AnNhà, hãy bỏ qua email này. Tài khoản sẽ không được xác minh nếu bạn không nhập mã.'
        subject = 'Mã xác minh email AnNhà'
    elif kind == 'password_reset':
        title = 'Đặt lại mật khẩu AnNhà'
        preheader = 'Mã đặt lại mật khẩu của bạn có hiệu lực trong 15 phút.'
        link = None
        verification_code = _text(values.get('code', ''))
        if not re.fullmatch(r'\d{8}', verification_code):
            raise ValueError('Mã đặt lại mật khẩu phải gồm 8 chữ số.')
        paragraphs = ['Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản AnNhà của bạn.',
                      'Nhập mã bên dưới trên website AnNhà để tạo mật khẩu mới.']
        details = []
        cta = 'Tạo mật khẩu mới'
        expiry = 'Mã có hiệu lực trong 15 phút và chỉ sử dụng một lần. Nếu mã hết hạn, bạn có thể yêu cầu gửi lại.'
        note = 'Nếu bạn không yêu cầu đặt lại mật khẩu, hãy bỏ qua email này. Mật khẩu hiện tại sẽ không thay đổi.'
        subject = 'Mã đặt lại mật khẩu AnNhà'
    elif kind == 'invitation':
        title = 'Bạn được mời tham gia một ngôi nhà trên AnNhà'
        preheader = f"{_text(values.get('inviter_name'), 'Người thân')} đã gửi lời mời đến bạn."
        link = _token_link(public_url, 'invitation', values.get('token', 'preview-token'))
        paragraphs = [f"{_text(values.get('inviter_name'), 'Người thân')} mời bạn tham gia không gian gia đình trên AnNhà."]
        details = [('Ngôi nhà', values.get('home_name')), ('Vai trò', values.get('role_label')),
                   ('Phòng/camera được chia sẻ', values.get('scope_text'))]
        cta = 'Xem lời mời'
        expiry = 'Lời mời có hiệu lực trong 7 ngày kể từ khi được tạo.'
        note = 'Đăng nhập hoặc tạo tài khoản bằng đúng địa chỉ email nhận lời mời. Chỉ tài khoản này mới có thể chấp nhận.'
        subject = 'Lời mời tham gia AnNhà'
    elif kind == 'safety_alert':
        title = 'AnNhà ghi nhận sự kiện cần bạn kiểm tra'
        preheader = f"{_text(values.get('home_name'), 'Ngôi nhà')} có thông tin mới cần lưu ý."
        link = _event_link(public_url, values.get('event_id', 'preview-event'))
        paragraphs = ['Vui lòng mở AnNhà để xem thông tin và chủ động kiểm tra tình hình. Email này không xác nhận người thân đang an toàn hay cần trợ giúp y tế.']
        details = [('Mức độ', values.get('severity_label')), ('Sự kiện', values.get('event_label')),
                   ('Ngôi nhà', values.get('home_name')), ('Phòng', values.get('room_name')),
                   ('Camera', values.get('camera_name')), ('Thời điểm ghi nhận', values.get('occurred_at'))]
        cta = 'Mở sự kiện trong AnNhà'
        expiry = None
        note = 'Để bảo vệ riêng tư, email không đính kèm ảnh hoặc video gia đình.'
        subject = 'AnNhà · Thông tin an toàn cần lưu ý'
    else:
        raise ValueError(f'Unknown email template: {kind}')
    html, text = _layout(title=title, preheader=preheader, greeting=name, paragraphs=paragraphs,
                         details=details, cta_label=cta, link=link,
                         verification_code=verification_code, code_label='Mã đặt lại mật khẩu' if kind=='password_reset' else 'Mã xác minh', expiry=expiry, security_note=note)
    return RenderedEmail(kind, subject, preheader, html, text)
