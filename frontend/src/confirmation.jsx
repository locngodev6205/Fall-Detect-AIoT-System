import React, { useCallback, useEffect, useRef, useState } from 'react';
import { PaperPlaneTilt, ShieldCheck, WarningCircle } from '@phosphor-icons/react';
import { Button, Modal } from './ui';

export function useConfirmation() {
  const [request, setRequest] = useState(null);
  const pending = useRef(null), cancelButton = useRef(null);
  const confirm = useCallback(options => new Promise(resolve => {
    pending.current?.(false);
    pending.current = resolve;
    setRequest(typeof options === 'string' ? { message: options } : options);
  }), []);
  const close = useCallback(accepted => {
    const resolve = pending.current;pending.current = null;
    setRequest(null);resolve?.(accepted);
  }, []);
  useEffect(() => () => { pending.current?.(false);pending.current = null; }, []);
  const Icon = request?.tone === 'danger' ? WarningCircle : request?.tone === 'privacy' ? ShieldCheck : PaperPlaneTilt;
  const dialog = request && <Modal title={request.title || 'Xác nhận thao tác'} onClose={() => close(false)}
    className="confirmation-modal" initialFocusRef={cancelButton}>
    <div className={'confirmation-icon ' + (request.tone || '')}><Icon weight="duotone" aria-hidden="true"/></div>
    <p className="confirmation-message">{request.message}</p>
    {request.preview && <div className="confirmation-preview"><span>{request.previewLabel || 'Nội dung'}</span><pre>{request.preview}</pre></div>}
    <div className="confirmation-actions">
      <Button ref={cancelButton} kind="secondary-btn" onClick={() => close(false)}>{request.cancelLabel || 'Hủy'}</Button>
      <Button kind={request.tone === 'danger' ? 'danger-confirm' : ''} onClick={() => close(true)}>{request.confirmLabel || 'Xác nhận'}</Button>
    </div>
  </Modal>;
  return { confirm, dialog };
}
