import React from 'react';
import { useToast } from '../hooks/useToast';

export default function ToastContainer() {
  const { toasts, removeToast } = useToast();

  if (!toasts.length) return null;

  return (
    <div className="toast-container" id="toastContainer">
      {toasts.map((t) => {
        let icon = 'ℹ️';
        if (t.type === 'success') icon = '✅';
        if (t.type === 'error') icon = '❌';
        if (t.type === 'warning') icon = '⚠️';

        return (
          <div key={t.id} className={`toast ${t.type}`}>
            <span className="toast-icon">{icon}</span>
            <div className="toast-body">
              {t.title && <div className="toast-title">{t.title}</div>}
              <div className="toast-msg">{t.message}</div>
            </div>
            <button className="toast-close" onClick={() => removeToast(t.id)}>
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
