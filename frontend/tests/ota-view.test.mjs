import test from 'node:test';
import assert from 'node:assert/strict';
import { compareVersions, compatibleReleases, otaPollDelay, otaResult } from '../src/ota-view.mjs';

const state = { current_version: '0.1.0', last_seen: 30, model_sha256: 'a', runtime_sha256: 'b', target: 'linux-arm64' };
const job = { version: '0.10.0', from_version: '0.1.0', created_at: 20, updated_at: 25 };

test('orders compatible versions numerically and rejects unknown device versions', () => {
  const releases = [
    { ...state, version: '0.2.0' }, { ...state, version: '0.10.0' },
    { ...state, version: '1.0.0', runtime_sha256: 'c' },
  ];
  assert.deepEqual(compatibleReleases(releases, state).map(release => release.version), ['0.10.0', '0.2.0']);
  assert.deepEqual(compatibleReleases(releases, null), []);
  assert.equal(compareVersions('0.10.0', 'unmanaged'), null);
});

test('reload during installation uses job state even when the updater is offline', () => {
  for (const [status, phase] of [['ready', 2], ['deferred', 2], ['installing', 2], ['health_check', 3], ['rolling_back', -1]]) {
    const active = { ...job, status };
    const view = otaResult(active, null, false);
    assert.equal(view.phase, phase);
    assert.equal(view.confirmed, false);
    assert.equal(otaPollDelay(active, view), 2500);
  }
});

test('successful install and manual rollback wait for matching heartbeat', () => {
  for (const rollback of [false, true]) {
    const done = { ...job, rollback, status: 'succeeded' };
    assert.equal(otaResult(done, state, true).waiting, true);
    const matching = { ...state, current_version: job.version };
    assert.equal(otaResult(done, matching, false).confirmed, false);
    assert.equal(otaResult(done, { ...matching, last_seen: 19 }, true).confirmed, false);
    const view = otaResult(done, matching, true);
    assert.equal(view.confirmed, true);
    assert.equal(view.title, rollback ? 'Khôi phục thành công' : 'Cập nhật thành công');
    assert.equal(otaPollDelay(done, view), null);
  }
});

test('automatic rollback needs a matching heartbeat after the rollback result', () => {
  const rolledBack = { ...job, status: 'rolled_back' };
  assert.equal(otaResult(rolledBack, { ...state, last_seen: 24 }, true).waiting, true);
  assert.equal(otaResult(rolledBack, state, true).confirmed, true);
  assert.equal(otaResult({ ...rolledBack, from_version: undefined }, state, true).confirmed, false);
});

test('failed jobs stay failed even when the requested version matches', () => {
  const failed = { ...job, status: 'failed' };
  const view = otaResult(failed, { ...state, current_version: job.version }, true);
  assert.equal(view.title, 'Thất bại');
  assert.equal(otaPollDelay(failed, view), null);
});
