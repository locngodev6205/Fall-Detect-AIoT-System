import React, { useEffect, useState } from 'react';
import { TelegramLogo, Copy, LinkSimple, ArrowClockwise, CheckCircle } from '@phosphor-icons/react';
import { api, eventNames, roleNames } from './api';
import { Badge, Button, Empty, Field, Heading } from './ui';
import { ResourceState, useApp, useResource } from './context';

const kinds = ['fall', 'immobility', 'environment', 'device'];
const severityNames = { warning: 'Trung bình trở lên', critical: 'Nghiêm trọng' };

function makeDraft(data) {
  return {
    reminder_interval_minutes: data.reminder_interval_minutes,
    max_reminders: data.max_reminders,
    recipients: (data.recipients || []).map(person => ({
      ...person,
      telegram: normalizeChannel(person.telegram, person.camera_ids),
      emailPreference: normalizeChannel(person.email_channel, person.camera_ids),
    })),
  };
}

function normalizeChannel(channel, allowedCameraIds) {
  const cameraIds = channel.camera_scope_all ? [] : channel.camera_ids.filter(id => allowedCameraIds.includes(id));
  return { ...channel, camera_scope_all: channel.camera_scope_all || cameraIds.length === 0,
    camera_ids: cameraIds, chat_id: '', clear_destination: false };
}

function channelPayload({ enabled, event_kinds, minimum_severity, camera_scope_all, camera_ids,
  allow_media, chat_id = '', clear_destination = false }) {
  return { enabled, event_kinds, minimum_severity, camera_scope_all, camera_ids,
    allow_media, chat_id, clear_destination };
}

function testMessage(home, recipient) {
  return `AnNhà · Kiểm tra kết nối\nNhà: ${home.name}\nNgười nhận: ${recipient.name}\nĐây là tin nhắn thử do chủ nhà yêu cầu. Không phải cảnh báo thật.`;
}

export function NotificationSettings({onRecipients}) {
  const { home, notify, confirm } = useApp();
  const resource = useResource(home.role === 'owner' ? `/homes/${home.id}/notification-settings` : null);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState('');
  const [pairingLinks, setPairingLinks] = useState({});
  const [pairingBusy, setPairingBusy] = useState('');
  const [pairingStatuses, setPairingStatuses] = useState({});
  useEffect(() => { if (resource.data) {setDraft(makeDraft(resource.data));onRecipients?.(resource.data.recipients.map(person=>[person.user_id,person.name]));} }, [resource.data,onRecipients]);

  function updateRecipient(userId, channel, patch) {
    setDraft(previous => ({
      ...previous,
      recipients: previous.recipients.map(person => person.user_id === userId
        ? { ...person, [channel]: { ...person[channel], ...patch } }
        : person),
    }));
  }

  function updateCameraScope(person, channel, checked) {
    const current = person[channel];
    updateRecipient(person.user_id, channel, {
      camera_scope_all: checked,
      camera_ids: checked ? [] : (current.camera_ids.length ? current.camera_ids : [...person.camera_ids]),
    });
  }

  function updateCamera(person, channel, cameraId, checked) {
    const current = person[channel].camera_ids;
    const next = checked ? [...new Set([...current,cameraId])] : current.filter(id => id !== cameraId);
    if (!next.length) { notify('Chọn ít nhất một camera hoặc bật phạm vi tất cả camera.');return; }
    updateRecipient(person.user_id,channel,{ camera_ids: next });
  }

  function updateKinds(person, channel, kind, checked) {
    const current = person[channel].event_kinds || kinds;
    const next = checked ? [...new Set([...current, kind])] : current.filter(item => item !== kind);
    if (!next.length) { notify('Chọn ít nhất một loại sự kiện.');return; }
    updateRecipient(person.user_id, channel, { event_kinds: next });
  }

  async function savePolicy(event) {
    event.preventDefault();setBusy('policy');
    try {
      await api(`/homes/${home.id}/notification-policy`, { method: 'PUT', body: {
        reminder_interval_minutes: Number(draft.reminder_interval_minutes),
        max_reminders: Number(draft.max_reminders),
      } });
      notify('Đã lưu lịch nhắc cảnh báo.');resource.reload();
    } catch (error) { notify(error.message); } finally { setBusy(''); }
  }

  async function saveRecipient(person) {
    setBusy(person.user_id);
    try {
      await api(`/homes/${home.id}/notification-recipients/${person.user_id}`, { method: 'PUT', body: {
        telegram: channelPayload(person.telegram),
        email: channelPayload(person.emailPreference),
      } });
      notify(`Đã lưu kênh nhận cảnh báo cho ${person.name}.`);resource.reload();
    } catch (error) { notify(error.message); } finally { setBusy(''); }
  }

  async function testTelegram(person) {
    const destination = person.telegram.destination_hint || 'tài khoản Telegram đã liên kết';
    const message = testMessage(resource.data.home, person);
    const approved = await confirm({ title: 'Gửi tin nhắn thử?',
      message: `Tin nhắn sẽ được gửi thật qua Telegram đến ${person.name} (${destination}).`,
      preview: message, previewLabel: 'Nội dung sẽ gửi', confirmLabel: 'Gửi tin nhắn' });
    if (!approved) return;
    setBusy(`test:${person.user_id}`);
    try {
      const result = await api(`/homes/${home.id}/notification-recipients/${person.user_id}/telegram-test`, { method: 'POST', body: {} });
      notify(result.message);
    } catch (error) { notify(error.message); } finally { setBusy(''); }
  }

  async function disconnectTelegram(person) {
    if (!await confirm({ title: 'Ngắt kết nối Telegram?', message: `${person.name} sẽ ngừng nhận cảnh báo qua Telegram. Bạn có thể kết nối lại bất cứ lúc nào.`,
      confirmLabel: 'Ngắt kết nối', tone: 'danger' })) return;
    setBusy(`disconnect:${person.user_id}`);
    try {
      const saved = makeDraft(resource.data).recipients.find(item => item.user_id === person.user_id);
      await api(`/homes/${home.id}/notification-recipients/${person.user_id}`, { method: 'PUT', body: {
        telegram: channelPayload({ ...saved.telegram, enabled: false, clear_destination: true, allow_media: false }),
        email: channelPayload(saved.emailPreference),
      } });
      updateRecipient(person.user_id, 'telegram', {
        enabled: false, clear_destination: false, destination_configured: false,
        destination_hint: '', chat_id: '', allow_media: false,
      });
      setPairingLinks(previous => { const next = { ...previous };delete next[person.user_id];return next; });
      setPairingStatuses(previous => { const next = { ...previous };delete next[person.user_id];return next; });
      notify(`Đã ngắt kết nối Telegram của ${person.name}.`);
    } catch (error) { notify(error.message); } finally { setBusy(''); }
  }

  async function createPairing(person) {
    setPairingBusy(person.user_id);
    try {
      const result = await api(`/homes/${home.id}/notification-recipients/${person.user_id}/telegram-pairing`, { method: 'POST', body: {} });
      setPairingLinks(previous => ({ ...previous, [person.user_id]: result }));
      setPairingStatuses(previous => ({ ...previous, [person.user_id]: 'pending' }));
      notify(`Liên kết Telegram của ${person.name} đã sẵn sàng. Mở hoặc sao chép liên kết để kết nối.`);
    } catch (error) { notify(error.message); } finally { setPairingBusy(''); }
  }

  async function copyPairing(person) {
    const link = pairingLinks[person.user_id]?.url;
    if (!link) return;
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(link);
      else { await confirm({ title: 'Sao chép liên kết Telegram', message: 'Chọn và sao chép liên kết bên dưới, rồi gửi riêng cho đúng người nhận.', preview: link, confirmLabel: 'Đã xong' });return; }
      notify('Đã sao chép liên kết Telegram. Hãy gửi riêng cho đúng người nhận.');
    } catch { await confirm({ title: 'Sao chép liên kết Telegram', message: 'Chọn và sao chép liên kết bên dưới, rồi gửi riêng cho đúng người nhận.', preview: link, confirmLabel: 'Đã xong' }); }
  }

  async function checkPairing(person) {
    const pairing = pairingLinks[person.user_id];
    if (!pairing) return;
    setPairingBusy(person.user_id);
    try {
      const result = await api(`/homes/${home.id}/notification-recipients/${person.user_id}/telegram-pairing/${pairing.pairing_id}`);
      setPairingStatuses(previous => ({ ...previous, [person.user_id]: result.status }));
      if (result.status === 'connected') {
        setPairingLinks(previous => { const next = { ...previous };delete next[person.user_id];return next; });
        notify(`Telegram của ${person.name} đã được liên kết.`);resource.reload();
      } else if (result.status === 'expired' || result.status === 'cancelled') {
        notify(result.status === 'expired' ? 'Liên kết đã hết hạn. Hãy tạo liên kết mới.' : 'Liên kết này không còn hiệu lực.');
      } else notify('Chưa thấy người nhận nhấn Bắt đầu. Hãy kiểm tra lại sau khi họ mở liên kết.');
    } catch (error) { notify(error.message); } finally { setPairingBusy(''); }
  }

  if (!draft) return <ResourceState resource={resource}>{null}</ResourceState>;

  const data = resource.data;
  return <section className="notification-settings-section">
    <Heading title="Thông báo an toàn" text="Chọn người nhận, loại cảnh báo và phòng cần nhận thông báo." level={2}/>
    <section className="panel telegram-setup-guide" aria-labelledby="telegram-guide-title">
      <header className="telegram-guide-header">
        <span className="telegram-guide-icon" aria-hidden="true"><TelegramLogo weight="fill"/></span>
        <div>
          <h3 id="telegram-guide-title">Nhận cảnh báo qua Telegram</h3>
          <p>Gửi cảnh báo đến người thân bằng Telegram.</p>
        </div>
        <a className="button secondary-btn telegram-open-bot" href={data.telegram_bot_url || 'https://t.me/AnNhaSafetyAlertBot'} target="_blank" rel="noreferrer">
          Mở bot AnNhà
        </a>
      </header>
      <details className="telegram-guide-details">
        <summary>Cách kết nối trong 3 bước</summary>
        <ol className="telegram-guide-steps">
          <li><span className="telegram-guide-number">1</span><p>Trong mục người nhận, tạo liên kết cho thành viên và gửi riêng cho họ.</p></li>
          <li><span className="telegram-guide-number">2</span><p>Người nhận mở liên kết bằng Telegram rồi nhấn <b>Bắt đầu</b>.</p></li>
          <li><span className="telegram-guide-number">3</span><p>Kiểm tra đã kết nối, chọn cảnh báo muốn nhận, rồi bật Telegram và lưu.</p></li>
        </ol>
        <p className="telegram-guide-security">Mỗi liên kết chỉ dùng một lần và hết hạn sau 10 phút.</p>
      </details>
    </section>
    <form className="panel notification-policy" onSubmit={savePolicy}>
      <div><h3>Nhắc lại cảnh báo chưa được xử lý</h3><p>Nhắc lại mỗi khoảng thời gian đã chọn, tối đa theo số lần cài đặt. Dừng khi có người tiếp nhận hoặc sự kiện được đóng.</p></div>
      <div className="notification-policy-fields">
        <Field label="Khoảng cách giữa các lần nhắc (phút)" type="number" min="5" max="1440" value={draft.reminder_interval_minutes}
          onChange={event => setDraft({ ...draft, reminder_interval_minutes: event.target.value })}/>
        <Field label="Số lần nhắc tối đa" type="number" min="0" max="5" value={draft.max_reminders}
          onChange={event => setDraft({ ...draft, max_reminders: event.target.value })}/>
        <Button type="submit" disabled={busy === 'policy'}>Lưu lịch nhắc</Button>
      </div>
      <small>Sự kiện môi trường đã được tiếp nhận sẽ không nhắc lại trong cùng đợt bất thường.</small>
    </form>

      {!draft.recipients.length ? <section className="panel spaced"><Empty title="Chưa có người nhận phù hợp" text="Chủ nhà và người chăm sóc cần có quyền xem ít nhất một camera trong nhà."/></section> : <>
      <header className="notification-recipients-heading"><h3>Người nhận cảnh báo</h3><p>Mở từng thành viên để chọn cách nhận và loại cảnh báo.</p></header>
      <div className="notification-recipient-list">{draft.recipients.map(person => {
        const telegramTestBusy = busy === `test:${person.user_id}`;
        const disconnecting = busy === `disconnect:${person.user_id}`;
        const telegramBusy = busy === person.user_id || disconnecting;
        const canTest = data.telegram_bot_configured && person.telegram.destination_configured && !person.telegram.clear_destination && !telegramBusy && !telegramTestBusy;
        return <details className="panel notification-recipient" key={person.user_id}>
          <summary className="notification-recipient-summary">
            <span className="notification-recipient-identity"><strong>{person.name}</strong><small>{roleNames[person.role]} · {person.email}</small></span>
            <span className="notification-recipient-statuses">
              <span className={person.telegram.destination_configured ? 'is-ready' : ''}>Telegram · {person.telegram.destination_configured ? 'Đã kết nối' : 'Chưa liên kết'}</span>
              <span className={person.email_verified ? 'is-ready' : 'is-pending'}>Email · {person.email_verified ? 'Đã xác minh' : 'Chưa xác minh'}</span>
            </span>
            <span className="notification-recipient-chevron" aria-hidden="true">⌄</span>
          </summary>
          <div className="notification-recipient-content">
          <ChannelEditor title="Telegram" channel="telegram" person={person} data={data} busy={telegramBusy}
            pairing={pairingLinks[person.user_id]} pairingStatus={pairingStatuses[person.user_id]}
            pairingBusy={pairingBusy === person.user_id} onCreatePairing={() => createPairing(person)}
            disconnecting={disconnecting} onDisconnect={() => disconnectTelegram(person)}
            onCopyPairing={() => copyPairing(person)} onCheckPairing={() => checkPairing(person)}
            onUpdate={patch => updateRecipient(person.user_id, 'telegram', patch)}
            onCameraScope={checked => updateCameraScope(person, 'telegram', checked)}
            onKind={(kind,checked) => updateKinds(person,'telegram',kind,checked)}
            onCamera={(cameraId,checked) => updateCamera(person,'telegram',cameraId,checked)}
            onConsent={async checked => {
              if (!checked || await confirm({ title: 'Cho phép gửi kèm ảnh?', message: `Ảnh sự kiện có thể hiển thị người thân và không gian riêng tư. Chỉ gửi tới Telegram của ${person.name} khi người này còn quyền xem camera.`, confirmLabel: 'Cho phép gửi ảnh', tone: 'privacy' }))
                updateRecipient(person.user_id,'telegram',{allow_media:checked});
            }}
            testButton={person.telegram.destination_configured && <Button kind="secondary-btn" disabled={!canTest} onClick={() => testTelegram(person)}>
              {telegramTestBusy ? 'Đang kiểm tra…' : 'Gửi tin nhắn thử'}
            </Button>}
          />
          <ChannelEditor title="Email" channel="emailPreference" person={person} data={data} busy={telegramBusy}
            onUpdate={patch => updateRecipient(person.user_id, 'emailPreference', patch)}
            onCameraScope={checked => updateCameraScope(person, 'emailPreference', checked)}
            onKind={(kind,checked) => updateKinds(person,'emailPreference',kind,checked)}
            onCamera={(cameraId,checked) => updateCamera(person,'emailPreference',cameraId,checked)}
          />
          <div className="notification-recipient-actions"><Button disabled={telegramBusy} onClick={() => saveRecipient(person)}>{telegramBusy ? 'Đang lưu…' : 'Lưu thay đổi'}</Button></div>
          </div>
        </details>;
      })}</div></>}
  </section>;
}

function ChannelEditor({ title, channel, person, data, busy, onUpdate, onCameraScope, onCamera, onKind, onConsent, testButton,
  pairing, pairingStatus, pairingBusy, onCreatePairing, onCopyPairing, onCheckPairing, disconnecting, onDisconnect }) {
  const preference = person[channel];
  const isTelegram = channel === 'telegram';
  const available = isTelegram ? data.telegram_bot_configured && preference.destination_configured : data.email_provider_configured && person.email_verified;
  const sampleCamera = data.cameras.find(item => person.camera_ids.includes(item.id));
  const sampleKind = kinds.find(kind => preference.event_kinds.includes(kind)) || 'fall';
  const sampleSeverity = preference.minimum_severity === 'critical' ? 'Nghiêm trọng' : 'Trung bình';
  return <details className="notification-channel">
    <summary><h4>{title}</h4><span className="notification-channel-status">{isTelegram
      ? data.telegram_bot_configured ? 'Sẵn sàng' : 'Tạm thời chưa sẵn sàng'
      : !person.email_verified ? 'Cần xác minh email' : data.email_provider_configured ? 'Sẵn sàng gửi' : 'Chưa sẵn sàng'}</span><span className="notification-channel-chevron" aria-hidden="true">⌄</span></summary>
    <div className="notification-channel-content">
    <label className="checkbox notification-toggle"><input type="checkbox" checked={preference.enabled} disabled={!available}
      onChange={event => onUpdate({ enabled: event.target.checked })}/><span>{isTelegram ? 'Nhận cảnh báo qua Telegram' : 'Nhận cảnh báo qua email'}</span></label>
    {!isTelegram&&!data.email_provider_configured&&<p className="notification-explanation" role="status">Kênh cảnh báo email chưa được bật. Hãy liên hệ người quản trị để kích hoạt. Email xác minh và đổi mật khẩu vẫn hoạt động.</p>}
    {!isTelegram&&data.email_provider_configured&&!person.email_verified&&<p className="notification-explanation" role="status">Người nhận cần xác minh địa chỉ email trước khi bật cảnh báo.</p>}
    {isTelegram && <div className="notification-destination">
      <div className="telegram-pairing-panel">
        <div className="telegram-pairing-summary">{preference.destination_configured
          ? <><Badge><CheckCircle weight="fill"/>Đã kết nối</Badge><p>Telegram đã liên kết với {person.name}.</p></>
          : <><strong>Chưa liên kết Telegram</strong><p>{data.telegram_pairing_ready
            ? 'Tạo liên kết để người thân kết nối tài khoản của họ.'
            : 'Tính năng liên kết đang tạm thời chưa sẵn sàng. Hãy thử lại sau.'}</p></>}</div>
        {preference.destination_configured ? <Button kind="secondary-btn" disabled={busy}
          onClick={onDisconnect}>
          {disconnecting ? 'Đang ngắt kết nối…' : 'Ngắt kết nối'}
        </Button> : <Button kind="secondary-btn" disabled={!data.telegram_pairing_ready || pairingBusy || busy} onClick={onCreatePairing}>
          {pairingBusy ? 'Đang tạo liên kết…' : pairing ? 'Tạo lại liên kết' : 'Tạo liên kết Telegram'}
        </Button>}
      </div>
      {pairing && !preference.destination_configured && <div className="telegram-pairing-link">
        <div><strong>{pairingStatus === 'expired' ? 'Liên kết đã hết hạn' : pairingStatus === 'cancelled' ? 'Liên kết không còn hiệu lực' : 'Liên kết đã sẵn sàng'}</strong>
          <small>Hết hạn lúc {new Date(pairing.expires_at).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'})}. Gửi riêng cho {person.name}.</small></div>
        <div className="telegram-pairing-actions">
          <a className="button secondary-btn" href={pairing.url} target="_blank" rel="noreferrer"><LinkSimple/>Mở liên kết</a>
          <Button kind="secondary-btn" onClick={onCopyPairing}><Copy/>Sao chép</Button>
          <Button kind="secondary-btn" disabled={pairingBusy} onClick={onCheckPairing}><ArrowClockwise/>{pairingBusy ? 'Đang kiểm tra…' : 'Kiểm tra kết nối'}</Button>
        </div>
      </div>}
      {testButton}
    </div>}
    <div className="notification-options">
      <div><strong>Phòng và camera</strong><label className="checkbox"><input type="checkbox" checked={preference.camera_scope_all}
        onChange={event => onCameraScope(event.target.checked)}/><span>Tất cả camera mà người này được xem</span></label></div>
      {!preference.camera_scope_all && <div className="notification-camera-list">{person.camera_ids.map(cameraId => {
        const camera = data.cameras.find(item => item.id === cameraId);
        return <label className="checkbox" key={cameraId}><input type="checkbox" checked={preference.camera_ids.includes(cameraId)}
          onChange={event => onCamera(cameraId,event.target.checked)}/>
          <span>{camera?.room_name ? `${camera.room_name} · ` : ''}{camera?.name || 'Camera'}</span></label>;
      })}</div>}
      <div><strong>Loại cảnh báo</strong><div className="notification-kind-list">{kinds.map(kind => <label className="checkbox" key={kind}>
        <input type="checkbox" checked={preference.event_kinds.includes(kind)} onChange={event => onKind(kind,event.target.checked)}/><span>{eventNames[kind]}</span>
      </label>)}</div></div>
      <Field label="Mức độ cảnh báo"><select value={preference.minimum_severity} onChange={event => onUpdate({ minimum_severity: event.target.value })}>
        {Object.entries(severityNames).map(([value,label]) => <option key={value} value={value}>{label}</option>)}
      </select></Field>
    </div>
    {isTelegram && <label className="checkbox notification-consent"><input type="checkbox" checked={preference.allow_media}
      onChange={event => onConsent(event.target.checked)}/><span>Cho phép gửi kèm ảnh bằng chứng khi có ảnh hợp lệ</span></label>}
    {isTelegram && preference.allow_media && <small className="notification-note">Ảnh chỉ được gửi nếu bạn cho phép và người nhận còn quyền xem camera. Nếu không có ảnh, cảnh báo vẫn được gửi bằng chữ.</small>}
    {isTelegram && <details className="notification-template"><summary>Xem mẫu cảnh báo</summary><pre>{[
      '🚨 AnNhà · Cảnh báo trong gia đình',
      `Nhà: ${data.home.name}`,
      `Vị trí: ${sampleCamera?.room_name || 'Phòng'} · ${sampleCamera?.name || 'Camera'}`,
      `Sự kiện: ${eventNames[sampleKind]} · ${sampleSeverity}`,
      'Thời điểm: [thời gian ghi nhận]',
      'Chi tiết: Phát hiện dấu hiệu cần kiểm tra.',
      `Mở sự kiện: ${data.telegram_event_url_base}event-id`,
      'Yêu cầu gửi đã được tiếp nhận; đây không xác nhận người nhận đã đọc.',
    ].join('\n')}</pre></details>}
    </div>
  </details>;
}
