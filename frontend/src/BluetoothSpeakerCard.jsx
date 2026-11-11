import React, { useEffect, useState, useRef } from 'react';
import { SpeakerHigh, ArrowsClockwise, MagnifyingGlass, X, LinkBreak, Bluetooth, Headphones } from '@phosphor-icons/react';
import { api } from './api';
import { useApp } from './context';
import { Button, Badge } from './ui';

function makeBtKey(prefix = 'bt') {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

const AUDIO_KEYWORDS = [
  'srs', 'xb', 'havit', 'hoco', 'tw', 'airpod', 'jbl', 'sony', 'marshall',
  'bose', 'edifier', 'speaker', 'loa', 'audio', 'headphone', 'earbud',
  'sound', 'music', 'anker', 'soundcore', 'xiaomi', 'baseus', 'ugreen',
  'harman', 'microlab', 'remake', 'buds', 'beats', 'sennheiser',
];

export function isAudioBluetoothDevice(name = '') {
  const low = String(name || '').toLowerCase();
  return AUDIO_KEYWORDS.some(kw => low.includes(kw));
}

export function BluetoothSpeakerCard({ cameraId, canControl = true, onCommandSent }) {
  const { notify, tick } = useApp();
  const [btData, setBtData] = useState({
    connected: false,
    deviceName: '',
    address: '',
    status: 'disconnected',
    devices: [],
    scanning: false,
    connecting_address: null,
  });
  const [isOpen, setIsOpen] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [connectingAddr, setConnectingAddr] = useState('');
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [searchText, setSearchText] = useState('');
  const [filterCategory, setFilterCategory] = useState('all');
  const pollTimerRef = useRef(null);

  async function fetchBluetoothState() {
    if (!cameraId) return null;
    try {
      const res = await api(`/cameras/${cameraId}/bluetooth`);
      if (res) {
        setBtData(res);
      }
      return res;
    } catch {
      return null;
    }
  }

  useEffect(() => {
    fetchBluetoothState();
  }, [cameraId, tick]);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  function startFastPolling(durationMs = 9000, onComplete) {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    const startedAt = Date.now();
    pollTimerRef.current = setInterval(async () => {
      const latest = await fetchBluetoothState();
      const elapsed = Date.now() - startedAt;
      if (elapsed >= durationMs || (latest && !latest.scanning && !latest.connecting_address && elapsed > 2200)) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
        if (onComplete) onComplete(latest);
      }
    }, 1100);
  }

  async function handleScan() {
    if (!cameraId || !canControl || isScanning) return;
    setIsScanning(true);
    try {
      await api(`/cameras/${cameraId}/commands`, {
        method: 'POST',
        body: {
          kind: 'bt_scan',
          ttl_seconds: 30,
          idempotency_key: makeBtKey('bt-scan'),
        },
      });
      onCommandSent?.();
      startFastPolling(8500, (latest) => {
        setIsScanning(false);
        const count = Array.isArray(latest?.devices) ? latest.devices.length : 0;
        notify(`Đã quét xong: tìm thấy ${count} thiết bị Bluetooth.`);
      });
    } catch (error) {
      setIsScanning(false);
      notify(error.message);
    }
  }

  async function handleConnect(dev) {
    if (!cameraId || !canControl || connectingAddr) return;
    setConnectingAddr(dev.address);
    try {
      const cmdRes = await api(`/cameras/${cameraId}/commands`, {
        method: 'POST',
        body: {
          kind: 'bt_connect',
          bt_address: dev.address,
          bt_name: dev.name,
          ttl_seconds: 35,
          idempotency_key: makeBtKey('bt-conn'),
        },
      });
      onCommandSent?.();
      startFastPolling(12000, (latest) => {
        setConnectingAddr('');
        const lastCmd = latest?.last_command;
        if (latest?.connected && (latest.address?.toUpperCase() === dev.address.toUpperCase() || latest.deviceName)) {
          notify(`Đã kết nối loa Bluetooth: ${latest.deviceName || dev.name}`);
        } else if (lastCmd && lastCmd.id === cmdRes?.id && lastCmd.status === 'failed') {
          notify(lastCmd.result || `Không thể kết nối tới ${dev.name}. Hãy bật nguồn loa và thử lại.`);
        } else {
          fetchBluetoothState();
        }
      });
    } catch (error) {
      setConnectingAddr('');
      notify(error.message);
    }
  }

  async function handleDisconnect(targetAddr = '') {
    if (!cameraId || !canControl || isDisconnecting) return;
    setIsDisconnecting(true);
    try {
      await api(`/cameras/${cameraId}/commands`, {
        method: 'POST',
        body: {
          kind: 'bt_disconnect',
          bt_address: targetAddr || btData.address || '',
          ttl_seconds: 25,
          idempotency_key: makeBtKey('bt-disc'),
        },
      });
      onCommandSent?.();
      startFastPolling(5500, () => {
        setIsDisconnecting(false);
        notify('Đã ngắt kết nối loa Bluetooth.');
      });
    } catch (error) {
      setIsDisconnecting(false);
      notify(error.message);
    }
  }

  function handleTogglePicker() {
    const nextOpen = !isOpen;
    setIsOpen(nextOpen);
    if (nextOpen && (!Array.isArray(btData.devices) || btData.devices.length === 0)) {
      handleScan();
    }
  }

  const devices = Array.isArray(btData.devices) ? btData.devices : [];
  const connected = Boolean(btData.connected && (btData.deviceName || btData.address));
  const scanningActive = isScanning || Boolean(btData.scanning);

  const filteredDevices = devices.filter(dev => {
    if (searchText.trim()) {
      const q = searchText.toLowerCase().trim();
      const matchName = String(dev.name || '').toLowerCase().includes(q);
      const matchAddr = String(dev.address || '').toLowerCase().includes(q);
      if (!matchName && !matchAddr) return false;
    }
    if (filterCategory === 'audio') {
      return isAudioBluetoothDevice(dev.name);
    }
    if (filterCategory === 'paired') {
      return Boolean(dev.paired);
    }
    return true;
  });

  return (
    <div className="bt-speaker-card">
      <div className="bt-speaker-header">
        <div className="bt-speaker-main">
          <div className={`bt-speaker-icon ${connected ? 'connected' : ''}`}>
            <Headphones size={20} weight="duotone" />
          </div>
          <div className="bt-speaker-meta">
            <div className="bt-speaker-title">
              <strong>{connected ? btData.deviceName : 'Chưa kết nối loa Bluetooth'}</strong>
              {connected && btData.address && <code className="bt-mac-inline">{btData.address}</code>}
            </div>
            <div className="bt-speaker-sub">
              {connected ? (
                <span className="bt-status-online">🟢 Đã kết nối • Sẵn sàng phát âm thanh</span>
              ) : (
                <span className="bt-status-offline">⚪ Chưa kết nối • Bấm &ldquo;Tìm loa&rdquo; để quét và ghép đôi</span>
              )}
            </div>
          </div>
        </div>

        <div className="bt-speaker-actions">
          {connected && canControl && (
            <Button
              kind="ghost danger bt-btn-sm"
              disabled={isDisconnecting}
              onClick={() => handleDisconnect(btData.address)}
              title="Ngắt kết nối loa Bluetooth hiện tại"
            >
              <LinkBreak size={15} />
              {isDisconnecting ? 'Đang ngắt…' : 'Ngắt kết nối'}
            </Button>
          )}
          {canControl && (
            <Button
              kind={isOpen ? 'bt-btn-sm' : 'secondary-btn bt-btn-sm'}
              onClick={handleTogglePicker}
            >
              <Bluetooth size={15} weight="bold" />
              {isOpen ? 'Đóng danh sách' : connected ? 'Đổi loa' : 'Tìm loa'}
            </Button>
          )}
        </div>
      </div>

      {isOpen && (
        <div className="bt-picker-drawer">
          <div className="bt-picker-toolbar">
            <span className="bt-picker-heading">
              DANH SÁCH THIẾT BỊ BLUETOOTH ({devices.length})
            </span>
            <button
              type="button"
              className="bt-rescan-link"
              disabled={scanningActive}
              onClick={handleScan}
            >
              <ArrowsClockwise size={14} className={scanningActive ? 'bt-spin' : ''} />
              <span>{scanningActive ? 'Đang quét quanh Pi…' : 'Quét lại'}</span>
            </button>
          </div>

          <div className="bt-picker-filters">
            <div className="bt-search-box">
              <MagnifyingGlass size={15} className="bt-search-icon" />
              <input
                type="search"
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                placeholder="Lọc theo tên thiết bị hoặc địa chỉ MAC…"
                aria-label="Lọc thiết bị Bluetooth"
              />
              {searchText && (
                <button type="button" className="bt-search-clear" onClick={() => setSearchText('')} aria-label="Xóa tìm kiếm">
                  <X size={13} />
                </button>
              )}
            </div>

            <div className="bt-category-pills">
              <button
                type="button"
                className={filterCategory === 'all' ? 'active' : ''}
                onClick={() => setFilterCategory('all')}
              >
                Tất cả ({devices.length})
              </button>
              <button
                type="button"
                className={filterCategory === 'audio' ? 'active' : ''}
                onClick={() => setFilterCategory('audio')}
              >
                Loa &amp; Tai nghe ({devices.filter(d => isAudioBluetoothDevice(d.name)).length})
              </button>
              <button
                type="button"
                className={filterCategory === 'paired' ? 'active' : ''}
                onClick={() => setFilterCategory('paired')}
              >
                Đã ghép đôi ({devices.filter(d => Boolean(d.paired)).length})
              </button>
            </div>
          </div>

          <div className="bt-device-list">
            {scanningActive && devices.length === 0 ? (
              <div className="bt-empty-state">
                <ArrowsClockwise size={18} className="bt-spin" />
                <span>Đang quét các thiết bị Bluetooth đang mở xung quanh Raspberry Pi…</span>
              </div>
            ) : filteredDevices.length === 0 ? (
              <div className="bt-empty-state">
                <span>Chưa tìm thấy thiết bị phù hợp. Hãy bật nguồn loa Bluetooth và bấm <strong>Quét lại</strong>.</span>
              </div>
            ) : (
              filteredDevices.map(dev => {
                const isCurrent = Boolean(
                  dev.connected ||
                  (connected && btData.address && btData.address.toUpperCase() === String(dev.address || '').toUpperCase())
                );
                const isConnectingThis =
                  connectingAddr === dev.address ||
                  btData.connecting_address === dev.address;
                const isAudio = isAudioBluetoothDevice(dev.name);

                return (
                  <div key={dev.address} className={`bt-device-item ${isCurrent ? 'current' : ''}`}>
                    <div className="bt-device-info">
                      <div className="bt-device-name-row">
                        {isAudio ? <SpeakerHigh size={16} weight="duotone" /> : <Bluetooth size={16} />}
                        <strong>{dev.name}</strong>
                        <Badge tone={isAudio ? 'teal' : 'amber'}>
                          {isAudio ? 'Loa/Tai nghe' : 'Thiết bị BT'}
                        </Badge>
                      </div>
                      <div className="bt-device-sub-row">
                        <code>{dev.address}</code>
                        {dev.paired && <span>• Đã lưu (Paired)</span>}
                      </div>
                    </div>

                    <div className="bt-device-cta">
                      {isCurrent ? (
                        <>
                          <Badge tone="teal">Đang dùng</Badge>
                          <Button
                            kind="ghost danger bt-btn-xs"
                            disabled={isDisconnecting}
                            onClick={() => handleDisconnect(dev.address)}
                          >
                            {isDisconnecting ? '…' : 'Ngắt'}
                          </Button>
                        </>
                      ) : (
                        <Button
                          kind="bt-btn-xs"
                          disabled={Boolean(connectingAddr) || isConnectingThis}
                          onClick={() => handleConnect(dev)}
                        >
                          {isConnectingThis ? 'Đang nối…' : 'Kết nối'}
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
