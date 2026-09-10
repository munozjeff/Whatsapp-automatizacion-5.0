import React, { useState, useEffect, useRef } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useToast } from '../hooks/useToast';
import {
  fetchAccounts,
  updateAccountStatus,
  openInstance,
  closeInstance,
  deleteAccount,
} from '../store/accountsSlice';

export default function Accounts() {
  const dispatch = useDispatch();
  const { accounts, diskMetrics, loading } = useSelector((state) => state.accounts);

  // Add account modal
  const [showAddModal, setShowAddModal] = useState(false);
  const [newAccName, setNewAccName] = useState('');
  const [qrStatus, setQrStatus] = useState(null);
  const [currentAccId, setCurrentAccId] = useState(null);

  // Send message modal
  const [showSendModal, setShowSendModal] = useState(false);
  const [sendAccId, setSendAccId] = useState('');
  const [sendPhone, setSendPhone] = useState('');
  const [sendMessageText, setSendMessageText] = useState('');

  // Edit status modal
  const [showEditModal, setShowEditModal] = useState(false);
  const [editAccId, setEditAccId] = useState('');
  const [editStatus, setEditStatus] = useState('disponible');
  const [editPhone, setEditPhone] = useState('');
  const [editNotes, setEditNotes] = useState('');

  // Rescan modal
  const [showRescanModal, setShowRescanModal] = useState(false);
  const [rescanAccId, setRescanAccId] = useState(null);
  const [rescanQrStatus, setRescanQrStatus] = useState(null);

  // Delete modal
  const [deletingAccId, setDeletingAccId] = useState(null);

  const { addToast } = useToast();
  const pollTimerRef = useRef(null);

  // Clean timer on unmount and Escape key listener
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowAddModal(false);
        setShowSendModal(false);
        setShowEditModal(false);
        setShowRescanModal(false);
        setDeletingAccId(null);
        setCurrentAccId(null);
        setRescanAccId(null);
        if (pollTimerRef.current) clearInterval(pollTimerRef.current);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  // ── QR polling helper ─────────────────────────────────────────────
  const startQrPolling = (accId, onSuccess, onStatusUpdate) => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      try {
        const qres = await fetch(`/api/qr_status/${accId}`);
        const qdata = await qres.json();
        onStatusUpdate(qdata);
        if (qdata.status === 'success' || qdata.status === 'error') {
          clearInterval(pollTimerRef.current);
          dispatch(fetchAccounts());
          if (qdata.status === 'success' && onSuccess) onSuccess();
        }
      } catch (err) {
        console.error('Error polling QR:', err);
      }
    }, 2000);
  };

  const closeAddModal = () => {
    setShowAddModal(false);
    setCurrentAccId(null);
    setQrStatus(null);
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  };

  const closeRescanModal = () => {
    setShowRescanModal(false);
    setRescanAccId(null);
    setRescanQrStatus(null);
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  };

  // ── Add account (QR login) ────────────────────────────────────────
  const handleStartQRLogin = async (e) => {
    e.preventDefault();
    if (!newAccName.trim()) return;
    try {
      const res = await fetch('/api/accounts/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_name: newAccName }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'info');
        const accId = data.account_id;
        setCurrentAccId(accId);
        startQrPolling(
          accId,
          () => {
            addToast('¡Cuenta vinculada con éxito!', 'success');
            dispatch(fetchAccounts());
            setTimeout(() => closeAddModal(), 2000);
          },
          setQrStatus
        );
      } else {
        addToast(data.message, 'error');
      }
    } catch (err) {
      addToast('Error al iniciar vinculación QR.', 'error');
    }
  };

  const handleCreateAccountSubmit = handleStartQRLogin;

  // ── Open/Close instance ───────────────────────────────────────────
  const handleOpenInstance = async (accId) => {
    addToast(`Abriendo instancia para '${accId}'...`, 'info');
    const result = await dispatch(openInstance(accId));
    if (openInstance.fulfilled.match(result)) {
      addToast(`Instancia para '${accId}' abierta correctamente.`, 'success');
    } else {
      addToast(result.payload || 'Error al abrir instancia.', 'error');
    }
  };

  const handleCloseInstance = async (accId) => {
    addToast(`Cerrando instancia para '${accId}'...`, 'info');
    const result = await dispatch(closeInstance(accId));
    if (closeInstance.fulfilled.match(result)) {
      addToast(`Instancia para '${accId}' cerrada.`, 'success');
    } else {
      addToast(result.payload || 'Error al cerrar instancia.', 'error');
    }
  };

  // ── Delete account ────────────────────────────────────────────────
  const confirmDeleteAccount = (accId) => {
    setDeletingAccId(accId);
  };

  const executeDeleteAccount = async () => {
    if (!deletingAccId) return;
    const result = await dispatch(deleteAccount(deletingAccId));
    if (deleteAccount.fulfilled.match(result)) {
      addToast(`Cuenta '${deletingAccId}' eliminada.`, 'success');
      setDeletingAccId(null);
    } else {
      addToast(result.payload || 'Error al eliminar la cuenta.', 'error');
    }
  };

  // ── Send test message ─────────────────────────────────────────────
  const handleSendMessageSubmit = async (e) => {
    e.preventDefault();
    if (!sendPhone.trim() || !sendMessageText.trim()) return;
    addToast(`Enviando mensaje desde '${sendAccId}'...`, 'info');
    try {
      const res = await fetch(`/api/accounts/${sendAccId}/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone: sendPhone, message: sendMessageText }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setShowSendModal(false);
        setSendMessageText('');
      } else {
        addToast(data.message, 'error');
      }
      dispatch(fetchAccounts());
    } catch (err) {
      addToast('Error al enviar el mensaje.', 'error');
    }
  };

  // ── Edit status ───────────────────────────────────────────────────
  const handleEditStatusSubmit = async (e) => {
    e.preventDefault();
    const result = await dispatch(
      updateAccountStatus({
        account_id: editAccId,
        status_state: editStatus,
        phone: editPhone,
        notes: editNotes,
      })
    );
    if (updateAccountStatus.fulfilled.match(result)) {
      addToast('Estado actualizado correctamente.', 'success');
      setShowEditModal(false);
    } else {
      addToast(result.payload || 'Error al actualizar el estado.', 'error');
    }
  };

  // ── Rescan account ────────────────────────────────────────────────
  const handleRescanAccount = async (accId) => {
    setRescanAccId(accId);
    setRescanQrStatus({ status: 'waiting_qr', message: 'Verificando sesión y extraiendo número...' });
    setShowRescanModal(true);
    try {
      const res = await fetch(`/api/accounts/${accId}/rescan`, { method: 'POST' });
      const data = await res.json();
      if (data.status !== 'success') {
        setRescanQrStatus({ status: 'error', message: data.message });
        return;
      }
      addToast(`Proceso de re-escaneo iniciado para '${accId}'.`, 'info');
      startQrPolling(
        accId,
        () => {
          addToast(`✅ '${accId}' verificado/re-escaneado. Número de teléfono actualizado.`, 'success');
          dispatch(fetchAccounts());
          setTimeout(() => closeRescanModal(), 1000);
        },
        setRescanQrStatus
      );
    } catch (err) {
      setRescanQrStatus({ status: 'error', message: 'Error al conectar con el servidor.' });
    }
  };

  const handleExportContactsCSV = () => {
    const availablePhonesCount = accounts.filter(acc => acc.phone && acc.phone.trim()).length;
    if (availablePhonesCount === 0) {
      addToast('No hay cuentas con teléfono extraído para exportar.', 'warning');
      return;
    }
    addToast(`Generando y descargando plantilla CSV para ${availablePhonesCount} contacto(s)...`, 'info');
    window.location.href = '/api/accounts/export_contacts';
  };

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className="tab-pane active" id="tab-accounts">
      <div className="page-header">
        <div>
          <h1>Gestor de Cuentas de WhatsApp</h1>
          <p className="subtitle">Administra tus sesiones, añade perfiles y controla instancias</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            className="btn btn-secondary"
            onClick={handleExportContactsCSV}
            title="Exportar plantilla CSV con formato de contactos de Google"
          >
            <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            Exportar Contactos CSV 📥
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              setNewAccName('');
              setQrStatus(null);
              setCurrentAccId(null);
              setShowAddModal(true);
            }}
          >
            <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            Nueva Cuenta WhatsApp
          </button>
        </div>
      </div>

      {/* Grid of Accounts */}
      <div className="accounts-grid">
        {loading && accounts.length === 0 ? (
          <div className="card empty-card">
            <div className="empty-state">
              <div className="spinner"></div>
              <p style={{ marginTop: '12px', color: 'var(--text-muted, #94a3b8)' }}>Cargando cuentas de WhatsApp...</p>
            </div>
          </div>
        ) : accounts.length === 0 ? (
          <div className="card empty-card">
            <div className="empty-state">
              <p>No tienes ninguna cuenta registrada aún.</p>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => {
                  setNewAccName('');
                  setQrStatus(null);
                  setShowAddModal(true);
                }}
              >
                Vincular primera cuenta QR
              </button>
            </div>
          </div>
        ) : (
          accounts.map((acc) => {
            const isInstActive = acc.is_active;
            let badgeClass = 'badge-available';
            let badgeText = acc.status_state || 'Disponible';
            if (acc.status_state === 'restringido') { badgeClass = 'badge-restricted'; badgeText = 'Restringido'; }
            else if (acc.status_state === 'bloqueado') { badgeClass = 'badge-blocked'; badgeText = 'Bloqueado'; }
            else if (acc.status_state === 'enviando') { badgeClass = 'badge-active'; badgeText = 'Enviando'; }
            else if (acc.status_state === 'haciendo_historial') { badgeClass = 'badge-history'; badgeText = 'Haciendo Historial'; }

            return (
              <div key={acc.account_id} className={`account-card ${isInstActive ? 'active-instance' : ''}`}>
                <div className="account-card-header">
                  <div className="account-avatar">💬</div>
                  <div className="account-title-box">
                    <h3 className="account-name">
                      {acc.account_id}
                      {acc.phone && <span style={{ fontSize: '0.85em', color: '#10b981', marginLeft: '6px' }}>📱 {acc.phone}</span>}
                    </h3>
                    <div className="badges-group">
                      <span className={`badge ${badgeClass}`}>{badgeText}</span>
                      {isInstActive && <span className="badge badge-active">Instancia Abierta</span>}
                    </div>
                  </div>
                </div>

                <div className="account-details">
                  <div className="detail-item full-width" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '6px', marginBottom: '4px' }}>
                    <span className="label">📱 Número Vinculado:</span>
                    <span className="val" style={{ 
                      fontWeight: '700', 
                      color: acc.phone ? '#10b981' : '#f59e0b',
                      fontSize: '1em'
                    }}>
                      {acc.phone ? acc.phone : '⚠️ Sin extraer (Re-escanear para extraer)'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <span className="label">Tamaño Sesión:</span>
                    <span className="val">{acc.size_mb} MB</span>
                  </div>
                  <div className="detail-item">
                    <span className="label">Modificado:</span>
                    <span className="val">{acc.last_modified}</span>
                  </div>
                  {acc.notes && (
                    <div className="detail-item full-width">
                      <span className="label">Notas:</span>
                      <span className="val notes">{acc.notes}</span>
                    </div>
                  )}
                </div>

                <div className="account-actions">
                  {!isInstActive ? (
                    <button className="btn btn-sm btn-success" onClick={() => handleOpenInstance(acc.account_id)}>
                      <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <polygon points="5 3 19 12 5 21 5 3"></polygon>
                      </svg>
                      Abrir
                    </button>
                  ) : (
                    <button className="btn btn-sm btn-warning" onClick={() => handleCloseInstance(acc.account_id)}>
                      <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="6" y="6" width="12" height="12"></rect>
                      </svg>
                      Cerrar
                    </button>
                  )}

                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => {
                      setSendAccId(acc.account_id);
                      setSendPhone('');
                      setSendMessageText('');
                      setShowSendModal(true);
                    }}
                  >
                    📤 Enviar
                  </button>

                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => {
                      setEditAccId(acc.account_id);
                      setEditStatus(acc.status_state || 'disponible');
                      setEditPhone(acc.phone || '');
                      setEditNotes(acc.notes || '');
                      setShowEditModal(true);
                    }}
                  >
                    ✏️ Estado
                  </button>

                  <button
                    className="btn btn-sm btn-secondary"
                    style={{ background: 'rgba(251,191,36,0.15)', borderColor: '#fbbf24', color: '#fbbf24' }}
                    onClick={() => handleRescanAccount(acc.account_id)}
                    title="Re-escanear QR y actualizar número"
                  >
                    🔄 Re-escanear
                  </button>

                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => confirmDeleteAccount(acc.account_id)}
                    title="Eliminar Cuenta"
                  >
                    🗑️ Eliminar
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* ── MODAL: NUEVA CUENTA QR ─────────────────────────────── */}
      {showAddModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>➕ Conectar Nueva Cuenta de WhatsApp</h2>
              <button className="modal-close" onClick={closeAddModal}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              {!currentAccId ? (
                <form onSubmit={handleCreateAccountSubmit}>
                  <div className="form-group">
                    <label>Nombre de la Cuenta / Identificador:</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="Ej: Cuenta 1 (Ventas), Marketing 02"
                      value={newAccName}
                      onChange={(e) => setNewAccName(e.target.value)}
                      required
                    />
                    <small className="form-text">
                      Asigna un nombre descriptivo para identificar esta sesión.
                    </small>
                  </div>
                  <div className="modal-footer" style={{ padding: '16px 0 0 0' }}>
                    <button type="button" className="btn btn-secondary" onClick={closeAddModal}>
                      Cancelar
                    </button>
                    <button type="submit" className="btn btn-primary">
                      Generar Código QR 📲
                    </button>
                  </div>
                </form>
              ) : (
                <div className="qr-container">
                  <p className="qr-instructions">
                    Escanea el siguiente código QR desde tu WhatsApp: <br />
                    <strong>Dispositivos vinculados &gt; Vincular un dispositivo</strong>
                  </p>

                  {qrStatus && qrStatus.qr ? (
                    <div className="qr-code-box">
                      <img src={qrStatus.qr} alt="Código QR de WhatsApp" />
                      <p className="qr-timer">
                        ⌛ Actualizando automáticamente... {qrStatus.timeout ? `(${qrStatus.timeout}s)` : ''}
                      </p>
                    </div>
                  ) : null}

                  {(!qrStatus || qrStatus.status === 'waiting_qr' || qrStatus.status === 'unknown') && (
                    <div className="qr-loading">
                      <div className="spinner"></div>
                      <p>Iniciando servicio de WhatsApp y generando código QR...</p>
                    </div>
                  )}

                  {qrStatus && qrStatus.status === 'success' && (
                    <div className="alert alert-success">
                      ✅ ¡Cuenta vinculada exitosamente! Guardando sesión y extrayendo número...
                    </div>
                  )}

                  {qrStatus && qrStatus.status === 'error' && (
                    <div className="alert alert-danger">
                      ❌ {qrStatus.message || 'Error al vincular la cuenta. Por favor reintenta.'}
                    </div>
                  )}

                  <div className="modal-footer" style={{ padding: '16px 0 0 0', marginTop: '16px' }}>
                    <button type="button" className="btn btn-secondary" onClick={closeAddModal}>
                      Cerrar
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: ENVIAR MENSAJE DE PRUEBA ───────────────────── */}
      {showSendModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>💬 Enviar Mensaje desde '{sendAccId}'</h2>
              <button className="modal-close" onClick={() => setShowSendModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleSendMessageSubmit}>
                <div className="form-group">
                  <label>Número de Destino (con código de país):</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="Ej: 573001234567"
                    value={sendPhone}
                    onChange={(e) => setSendPhone(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Mensaje:</label>
                  <textarea
                    className="form-control"
                    rows="4"
                    placeholder="Escribe tu mensaje..."
                    value={sendMessageText}
                    onChange={(e) => setSendMessageText(e.target.value)}
                    required
                  ></textarea>
                </div>
                <div className="modal-footer" style={{ padding: '16px 0 0 0' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowSendModal(false)}
                  >
                    Cancelar
                  </button>
                  <button type="submit" className="btn btn-primary">
                    Enviar Mensaje 🚀
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: EDITAR ESTADO / NOTAS ─────────────────────── */}
      {showEditModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>⚙️ Configurar Cuenta '{editAccId}'</h2>
              <button className="modal-close" onClick={() => setShowEditModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleEditStatusSubmit}>
                <div className="form-group">
                  <label>Número de Teléfono:</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder="Ej: +57 300 1234567"
                    value={editPhone}
                    onChange={(e) => setEditPhone(e.target.value)}
                  />
                  <small className="form-text">
                    Extraído automáticamente al escanear QR, o puedes editarlo manualmente.
                  </small>
                </div>

                <div className="form-group">
                  <label>Estado Operativo:</label>
                  <select
                    className="form-control"
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value)}
                  >
                    <option value="disponible">🟢 Disponible (Listo para envíos e historial)</option>
                    <option value="enviando">📤 Enviando (En ráfaga activa)</option>
                    <option value="haciendo_historial">💬 Haciendo Historial (En interacción cruzada)</option>
                    <option value="restringido">⚠️ Restringido (Límite temporal)</option>
                    <option value="bloqueado">🚫 Bloqueado (Inactivo / Desconectado)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label>Notas / Etiqueta:</label>
                  <textarea
                    className="form-control"
                    rows="3"
                    placeholder="Ej: Chip principal ventas zona norte..."
                    value={editNotes}
                    onChange={(e) => setEditNotes(e.target.value)}
                  ></textarea>
                </div>

                <div className="modal-footer" style={{ padding: '16px 0 0 0' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowEditModal(false)}
                  >
                    Cancelar
                  </button>
                  <button type="submit" className="btn btn-primary">
                    💾 Guardar Cambios
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: RE-ESCANEAR QR ────────────────────────────── */}
      {showRescanModal && (
        <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) closeRescanModal(); }}>
          <div className="modal">
            <div className="modal-header">
              <h2>🔄 Re-escanear Cuenta '{rescanAccId}'</h2>
              <button className="modal-close" onClick={closeRescanModal}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="qr-container">
                <p className="qr-instructions">
                  Escanea el nuevo código QR para actualizar la sesión y re-extraer el número de teléfono: <br />
                  <strong>Dispositivos vinculados &gt; Vincular un dispositivo</strong>
                </p>

                {rescanQrStatus && rescanQrStatus.qr ? (
                  <div className="qr-code-box">
                    <img src={rescanQrStatus.qr} alt="Código QR de WhatsApp" />
                    <p className="qr-timer">
                      ⌛ Actualizando automáticamente... {rescanQrStatus.timeout ? `(${rescanQrStatus.timeout}s)` : ''}
                    </p>
                  </div>
                ) : null}

                {(!rescanQrStatus || rescanQrStatus.status === 'waiting_qr' || rescanQrStatus.status === 'unknown') && (
                  <div className="qr-loading">
                    <div className="spinner"></div>
                    <p>Reiniciando sesión y generando nuevo código QR...</p>
                  </div>
                )}

                {rescanQrStatus && rescanQrStatus.status === 'success' && (
                  <div className="alert alert-success">
                    ✅ ¡Re-escaneo exitoso! Número de teléfono actualizado.
                  </div>
                )}

                {rescanQrStatus && rescanQrStatus.status === 'error' && (
                  <div className="alert alert-danger">
                    ❌ {rescanQrStatus.message || 'Error al re-escanear la cuenta.'}
                  </div>
                )}

                <div className="modal-footer" style={{ padding: '16px 0 0 0', marginTop: '16px' }}>
                  <button type="button" className="btn btn-secondary" onClick={closeRescanModal}>
                    Cerrar
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: CONFIRMAR ELIMINACIÓN DE CUENTA ───────────── */}
      {deletingAccId && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header" style={{ borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
              <h2>⚠️ Confirmar Eliminación</h2>
              <button className="modal-close" onClick={() => setDeletingAccId(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🗑️</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Estás seguro de eliminar la cuenta de WhatsApp?
              </p>
              <div style={{ 
                background: 'rgba(239, 68, 68, 0.1)', 
                border: '1px solid rgba(239, 68, 68, 0.3)', 
                color: '#ef4444', 
                padding: '10px 14px', 
                borderRadius: '8px',
                fontWeight: '600',
                marginBottom: '20px'
              }}>
                "{deletingAccId}"
              </div>
              <p style={{ fontSize: '13px', color: 'var(--text-muted, #94a3b8)', marginBottom: '24px' }}>
                Se eliminarán permanentemente las cookies y la sesión asociada a este dispositivo.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  onClick={() => setDeletingAccId(null)}
                  style={{ flex: 1 }}
                >
                  Cancelar
                </button>
                <button 
                  type="button" 
                  className="btn btn-danger" 
                  onClick={executeDeleteAccount}
                  style={{ flex: 1, backgroundColor: '#ef4444', borderColor: '#ef4444' }}
                >
                  🗑️ Eliminar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
