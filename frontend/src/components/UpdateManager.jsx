import React, { useState, useEffect } from 'react';
import { useToast } from '../hooks/useToast';

export default function UpdateManager() {
  const { addToast } = useToast();
  const [updateInfo, setUpdateInfo] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [updating, setUpdating] = useState(false);

  const checkUpdates = async () => {
    try {
      const res = await fetch('/api/updates/check');
      const data = await res.json();
      if (data.status === 'success' && data.update_available) {
        setUpdateInfo(data);
      } else {
        setUpdateInfo(null);
      }
    } catch (err) {
      console.error('Error al verificar actualizaciones:', err);
    }
  };

  useEffect(() => {
    checkUpdates();
    const interval = setInterval(checkUpdates, 60000);
    return () => clearInterval(interval);
  }, []);

  const handleApplyUpdate = async () => {
    setUpdating(true);
    addToast('Descargando e instalando actualización...', 'info');
    try {
      const res = await fetch('/api/updates/apply', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast('¡Sistema actualizado con éxito!', 'success');
        setTimeout(() => {
          window.location.reload();
        }, 1500);
      } else {
        addToast(data.message || 'Error al aplicar la actualización.', 'error');
        setUpdating(false);
      }
    } catch (err) {
      addToast('Error al conectar con el servidor para actualizar.', 'error');
      setUpdating(false);
    }
  };

  if (!updateInfo || !updateInfo.update_available) {
    return null;
  }

  return (
    <>
      {/* Sidebar Banner */}
      <div className="update-sidebar-box">
        <div className="update-sidebar-title">
          <span>🚀 ¡Nueva Actualización!</span>
        </div>
        <div className="update-sidebar-desc">
          {updateInfo.behind_count} cambio(s) listo(s) en GitHub ({updateInfo.local_commit} → {updateInfo.remote_commit})
        </div>
        <button className="btn-update-now" onClick={() => setShowModal(true)}>
          ⚡ Actualizar (1-Click)
        </button>
      </div>

      {/* Modal de Actualización */}
      {showModal && (
        <div className="modal-backdrop" onClick={() => !updating && setShowModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '520px' }}>
            <div className="modal-header">
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px' }}>
                🚀 Actualización de Plataforma (1-Click)
              </h2>
              {!updating && (
                <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
              )}
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{
                background: 'rgba(0, 229, 255, 0.1)',
                border: '1px solid rgba(0, 229, 255, 0.3)',
                padding: '12px',
                borderRadius: '8px',
                fontSize: '0.88rem'
              }}>
                <div><strong>Commit Actual:</strong> <code>{updateInfo.local_commit}</code></div>
                <div><strong>Nueva Versión:</strong> <code style={{ color: '#00e5ff' }}>{updateInfo.remote_commit}</code></div>
                <div style={{ marginTop: '4px', color: 'var(--muted)' }}>
                  Hay {updateInfo.behind_count} actualización(es) disponible(s) en el repositorio remoto.
                </div>
              </div>

              {updateInfo.commit_messages && updateInfo.commit_messages.length > 0 && (
                <div>
                  <h4 style={{ fontSize: '0.85rem', marginBottom: '6px', color: 'var(--muted)' }}>
                    📝 Cambios incluidos:
                  </h4>
                  <div style={{
                    background: 'rgba(0, 0, 0, 0.3)',
                    border: '1px solid var(--border)',
                    padding: '10px 12px',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    fontFamily: 'monospace',
                    maxHeight: '140px',
                    overflowY: 'auto'
                  }}>
                    {updateInfo.commit_messages.map((msg, i) => (
                      <div key={i} style={{ color: '#e2e8f0', marginBottom: '4px' }}>
                        • {msg}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {updating && (
                <div style={{ textAlign: 'center', padding: '16px 0' }}>
                  <div className="spinner" style={{ margin: '0 auto 12px' }}></div>
                  <p style={{ fontWeight: 600, color: 'var(--cyan)' }}>
                    Descargando cambios e instalando automáticamente...
                  </p>
                  <p style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: '4px' }}>
                    Por favor no cierres la ventana. La aplicación se recargará al finalizar.
                  </p>
                </div>
              )}
            </div>

            <div className="modal-footer">
              {!updating ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setShowModal(false)}>
                    Cancelar
                  </button>
                  <button className="btn btn-primary" onClick={handleApplyUpdate} style={{
                    background: 'linear-gradient(135deg, #00e5ff 0%, #059669 100%)',
                    color: '#000',
                    fontWeight: 700
                  }}>
                    📥 Descargar e Instalar (1-Click)
                  </button>
                </>
              ) : (
                <button className="btn btn-secondary" disabled>
                  Actualizando...
                </button>
              )}
            </div>
          </div>
        </div>
      )}

    </>
  );
}
