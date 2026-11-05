import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { spawnSync } from 'node:child_process';

const base = process.env.UI_BASE_URL || 'http://127.0.0.1:5188';
const homeId = '11111111-1111-4111-8111-111111111111';
const ownerId = '22222222-2222-4222-8222-222222222222';
const caregiverId = '33333333-3333-4333-8333-333333333333';
const cameraId = '44444444-4444-4444-8444-444444444444';
const allKinds = ['fall', 'immobility', 'environment', 'device'];
const channel = (id, configured = false) => ({
  id, enabled: false, event_kinds: allKinds, minimum_severity: 'warning',
  camera_scope_all: true, camera_ids: [], allow_media: false,
  destination_configured: configured, destination_hint: configured ? '••••1234' : '',
});
const policyBody = { reminder_interval_minutes: 15, max_reminders: 3 };
let savedPolicy, savedRecipient, testSendCount = 0, pairingCreateCount = 0, pairingStatusCount = 0;
let disconnectCount = 0, nativeDialogCount = 0;

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  page.on('dialog', async dialog => { nativeDialogCount++;await dialog.dismiss(); });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  // The disconnect failure fixture below intentionally returns one HTTP 503.
  page.on('console', message => { if (message.type() === 'error' && !message.text().includes('status of 503')) pageErrors.push(message.text()); });
  await page.addInitScript(() => {
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = function (url, ...args) {
      if (String(url).includes('/ws/alerts?')) return { readyState: 1, onmessage: null, onclose: null, close() { this.readyState = 3;this.onclose?.({ code: 1000 }); } };
      return new NativeWebSocket(url, ...args);
    };
    for (const key of ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED']) window.WebSocket[key] = NativeWebSocket[key];
  });
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, '');
    let status = 200, data = {};
    if (path === '/auth/me') data = { user: { id: ownerId, name: 'Chủ nhà', email: 'owner@example.test' }, csrf: 'ui-smoke-csrf' };
    else if (path === '/homes') data = [{ id: homeId, name: 'Nhà AnNhà', timezone: 'Asia/Ho_Chi_Minh', role: 'owner' }];
    else if (path === `/homes/${homeId}/cameras`) data = [{ id: cameraId, name: 'Camera phòng khách', room_id: 'room-1', room_name: 'Phòng khách', online: false, snapshot_available: false }];
    else if (path === `/homes/${homeId}/rooms` || path === `/homes/${homeId}/events` || path === `/homes/${homeId}/reminders`) data = [];
    else if (path === `/homes/${homeId}/active-events`) data = { count: 0, items: [], as_of: new Date().toISOString() };
    else if (path === `/homes/${homeId}/settings`) data = {
      temperature_low: 18, temperature_high: 32, humidity_high: 75, gas_high: 250,
      gas_unit: 'ADC', environment_hold_seconds: 30, hysteresis: 3, retention_days: 30,
    };
    else if (path === `/homes/${homeId}/storage`) data = {
      used_bytes: 0, reserved_bytes: 0, available_bytes: 1073741824, quota_bytes: 1073741824,
      used_percent: 0, warning_level: 'normal', retention_days: 30, reconciliation: null,
    };
    else if (path === `/homes/${homeId}/notification-settings`) data = {
      home: { name: 'Nhà AnNhà', timezone: 'Asia/Ho_Chi_Minh' },
      reminder_interval_minutes: 15, max_reminders: 3,
      telegram_bot_configured: true, telegram_pairing_ready: true, telegram_bot_url: 'https://t.me/AnNhaSafetyAlertBot', email_provider_configured: false,
      telegram_event_url_base: `${base}/#/event/`, cameras: [{ id: cameraId, name: 'Camera phòng khách', room_name: 'Phòng khách' }],
      default_event_kinds: allKinds, default_minimum_severity: 'warning',
      recipients: [
        { user_id: ownerId, name: 'Chủ nhà', email: 'owner@example.test', role: 'owner', email_verified: true,
          camera_ids: [cameraId], telegram: channel('telegram-owner', true), email_channel: channel('email-owner') },
        { user_id: caregiverId, name: 'Người chăm sóc', email: 'caregiver@example.test', role: 'caregiver', email_verified: true,
          camera_ids: [cameraId], telegram: channel('telegram-caregiver'), email_channel: channel('email-caregiver') },
      ],
    };
    else if (path === `/homes/${homeId}/notification-policy` && request.method() === 'PUT') {
      savedPolicy = request.postDataJSON(); data = { ...savedPolicy, persistent_environment_after_ack: 'stop_until_new_episode' };
    } else if (path === `/homes/${homeId}/notification-recipients/${ownerId}` && request.method() === 'PUT') {
      savedRecipient = request.postDataJSON(); data = { message: 'Đã lưu người nhận và bộ lọc cảnh báo.' };
      const validation = spawnSync('python3', ['-c',
        'import sys; from backend.src.models import NotificationRecipientUpdate; NotificationRecipientUpdate.model_validate_json(sys.stdin.read())'],
        { input: JSON.stringify(savedRecipient), encoding: 'utf8' });
      assert.equal(validation.status, 0, `Frontend payload must pass the actual backend model: ${validation.stderr}`);
      if (savedRecipient.telegram.clear_destination) {
        disconnectCount++;
        if (disconnectCount === 1) { status = 503;data = { detail: 'Chưa thể ngắt kết nối. Hãy thử lại.' }; }
      }
    } else if (path.endsWith('/telegram-pairing') && request.method() === 'POST') {
      pairingCreateCount++;data = { pairing_id: 'pairing-1', expires_at: new Date(Date.now()+600000).toISOString(), url: 'https://t.me/AnNhaSafetyAlertBot?start=mockPairingToken_1234567890' };
    } else if (path.endsWith('/telegram-pairing/pairing-1') && request.method() === 'GET') {
      pairingStatusCount++;data = { status: 'pending', expires_at: new Date(Date.now()+600000).toISOString() };
    } else if (path.endsWith('/telegram-test')) { testSendCount++;data = { status: 'accepted', message: 'Đã gửi' }; }
    else { status = 404;data = { detail: `Unexpected API request: ${request.method()} ${path}` }; }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });

  await page.goto(`${base}/#/settings`);
  await page.getByRole('heading', { name: 'Thông báo an toàn' }).waitFor();
  const telegramGuide = page.getByRole('region', { name: 'Nhận cảnh báo qua Telegram' });
  await telegramGuide.getByRole('link', { name: 'Mở bot AnNhà' }).waitFor();
  const guideDetails = telegramGuide.locator('.telegram-guide-details');
  assert.equal(await guideDetails.locator('.telegram-guide-steps > li').count(), 3);
  const guideClosed = await telegramGuide.boundingBox();
  assert.ok(guideClosed && guideClosed.height < 180, 'The setup guide should stay compact until opened.');
  await guideDetails.locator('summary').click();
  assert.match(await guideDetails.innerText(), /Trong mục người nhận/);
  assert.match(await guideDetails.innerText(), /Kiểm tra đã kết nối/);
  assert.doesNotMatch(await telegramGuide.innerText(), /Chat ID|python3|scripts\/telegram/);
  const guideDesktop = await telegramGuide.boundingBox();
  const guidePadding = await telegramGuide.evaluate(element => getComputedStyle(element).paddingLeft);
  assert.ok(guideDesktop && parseFloat(guidePadding) >= 20, 'Telegram guide should have comfortable desktop padding.');
  await page.setViewportSize({ width: 390, height: 844 });
  const guideMobile = await telegramGuide.boundingBox();
  assert.ok(guideMobile && guideMobile.x >= 0 && guideMobile.x + guideMobile.width <= 390,
    'Telegram guide should fit the mobile viewport without horizontal overflow.');
  assert.ok(parseFloat(await telegramGuide.evaluate(element => getComputedStyle(element).paddingLeft)) >= 14,
    'The guide should retain readable padding on mobile.');
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: '/tmp/annha-notification-settings.png', fullPage: true });
  assert.equal(await page.locator('.notification-recipient[open]').count(), 0,
    'Recipient settings should start collapsed to keep long lists scannable.');
  const caregiverCard = page.locator('.notification-recipient').nth(1);
  const caregiverSummary = caregiverCard.locator(':scope > summary');
  const summaryPadding = await caregiverSummary.evaluate(element => getComputedStyle(element).paddingLeft);
  assert.ok(parseFloat(summaryPadding) >= 15, 'Recipient rows should keep comfortable text padding.');
  await caregiverSummary.click();
  await caregiverCard.locator('.notification-channel').first().locator(':scope > summary').click();
  await page.screenshot({ path: '/tmp/annha-notification-settings-expanded.png', fullPage: true });
  assert.match(await caregiverCard.innerText(), /Chưa liên kết Telegram/);
  assert.equal(await page.getByLabel('Khoảng cách giữa các lần nhắc (phút)').inputValue(), '15');
  assert.equal(await page.getByLabel('Số lần nhắc tối đa').inputValue(), '3');
  assert.equal(await page.getByRole('checkbox', { name: 'Cho phép gửi kèm ảnh bằng chứng khi có ảnh hợp lệ' }).count(), 1,
    'Only the expanded recipient should expose its detailed Telegram options.');
  const settingsText = await page.locator('.notification-settings-section').innerText();
  assert.doesNotMatch(settingsText, /Chat ID|python3|HTTPS công khai|Mức lọc hiện tại/);
  assert.equal(await page.locator('.notification-kind-list:visible').first().evaluate(element => getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/).length), 2,
    'Event filters should use two compact columns on desktop.');
  assert.equal(await page.locator('.notification-kind-list .checkbox').first().evaluate(element => getComputedStyle(element).marginTop), '3px',
    'Event filters should not inherit large form spacing.');

  await caregiverCard.getByRole('button', { name: 'Tạo liên kết Telegram' }).click();
  await caregiverCard.getByRole('link', { name: 'Mở liên kết' }).waitFor();
  await caregiverCard.getByText('Liên kết đã sẵn sàng', { exact: true }).waitFor();
  await caregiverCard.getByRole('button', { name: 'Tạo lại liên kết', exact: true }).waitFor();
  await caregiverCard.getByRole('button', { name: 'Kiểm tra kết nối' }).click();
  assert.equal(pairingCreateCount, 1);
  assert.equal(pairingStatusCount, 1);

  await page.getByRole('button', { name: 'Lưu lịch nhắc' }).click();
  await page.getByText('Đã lưu lịch nhắc cảnh báo.').waitFor();
  assert.deepEqual(savedPolicy, policyBody);

  const ownerCard = page.locator('.notification-recipient').first();
  await ownerCard.locator(':scope > summary').click();
  await ownerCard.locator('.notification-channel').first().locator(':scope > summary').click();
  await page.getByRole('button', { name: 'Lưu thay đổi' }).first().click();
  await page.getByText('Đã lưu kênh nhận cảnh báo cho Chủ nhà.').waitFor();
  assert.ok(savedRecipient.telegram && savedRecipient.email);
  assert.deepEqual(savedRecipient.telegram.event_kinds, allKinds);
  assert.equal(savedRecipient.telegram.minimum_severity, 'warning');

  await page.getByRole('button', { name: 'Gửi tin nhắn thử' }).first().click();
  const sendDialog = page.getByRole('dialog', { name: 'Gửi tin nhắn thử?' });
  await sendDialog.waitFor();
  assert.match(await sendDialog.innerText(), /••••1234/);
  assert.match(await sendDialog.innerText(), /gửi thật qua Telegram/);
  assert.match(await sendDialog.innerText(), /Không phải cảnh báo thật/);
  assert.equal(await sendDialog.getByRole('button', { name: 'Hủy', exact: true }).evaluate(node => node === document.activeElement), true);
  await page.setViewportSize({ width: 390, height: 844 });
  const dialogBox = await sendDialog.boundingBox();
  assert.ok(dialogBox.x >= 0 && dialogBox.x + dialogBox.width <= 390);
  await page.screenshot({ path: '/tmp/annha-confirmation-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: '/tmp/annha-confirmation-desktop.png', fullPage: true });
  await sendDialog.getByRole('button', { name: 'Hủy', exact: true }).click();
  assert.equal(testSendCount, 0, 'Dismissing the explicit confirmation must not call the live-send endpoint.');
  await ownerCard.getByRole('button', { name: 'Ngắt kết nối', exact: true }).click();
  await page.getByRole('dialog', { name: 'Ngắt kết nối Telegram?' }).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(disconnectCount, 0, 'Cancelling disconnect must not write changes.');
  await ownerCard.getByRole('button', { name: 'Ngắt kết nối', exact: true }).click();
  await page.getByRole('dialog', { name: 'Ngắt kết nối Telegram?' }).getByRole('button', { name: 'Ngắt kết nối', exact: true }).click();
  await page.getByText('Chưa thể ngắt kết nối. Hãy thử lại.', { exact: true }).waitFor();
  await ownerCard.getByRole('button', { name: 'Ngắt kết nối', exact: true }).waitFor();
  assert.match(await ownerCard.locator(':scope > summary').innerText(), /Telegram · Đã kết nối/);
  await ownerCard.getByRole('button', { name: 'Ngắt kết nối', exact: true }).click();
  await page.getByRole('dialog', { name: 'Ngắt kết nối Telegram?' }).getByRole('button', { name: 'Ngắt kết nối', exact: true }).click();
  await page.getByText('Đã ngắt kết nối Telegram của Chủ nhà.', { exact: true }).waitFor();
  assert.equal(disconnectCount, 2);
  assert.equal(savedRecipient.telegram.enabled, false);
  assert.equal(savedRecipient.telegram.clear_destination, true);
  assert.equal(savedRecipient.email.enabled, false);
  await ownerCard.getByRole('button', { name: 'Tạo liên kết Telegram' }).waitFor();
  assert.match(await ownerCard.locator(':scope > summary').innerText(), /Telegram · Chưa liên kết/);
  assert.equal(testSendCount, 0);
  assert.equal(nativeDialogCount, 0, 'Notification actions must use app dialogs instead of browser defaults.');
  assert.deepEqual(pageErrors, []);
  console.log('PASS Notification settings load approved defaults, save independent recipient channels and require explicit confirmation before a Telegram test send.');
} finally {
  await browser.close();
}
