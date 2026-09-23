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

// ── LocalStorage helpers ─────────────────────────────────────────────
const LS_DEVICES_KEY = 'wa_devices_v2';
const LS_ACC_MAP_KEY = 'wa_account_device_map_v2';

function loadDevices() {
  try {
    return JSON.parse(localStorage.getItem(LS_DEVICES_KEY) || '[]');
  } catch { return []; }
}

function saveDevices(devices) {
  localStorage.setItem(LS_DEVICES_KEY, JSON.stringify(devices));
}

function loadAccountDeviceMap() {
  try {
    return JSON.parse(localStorage.getItem(LS_ACC_MAP_KEY) || '{}');
  } catch { return {}; }
}

function saveAccountDeviceMap(map) {
  localStorage.setItem(LS_ACC_MAP_KEY, JSON.stringify(map));
}

export default function Accounts() {
  const dispatch = useDispatch();
  const { accounts, loading } = useSelector((state) => state.accounts);

  // ── Device management ──────────────────────────────────────────────
  const [devices, setDevices] = useState(loadDevices);
  // accountDeviceMap: { account_id: device_id }
  const [accountDeviceMap, setAccountDeviceMap] = useState(loadAccountDeviceMap);

  // Persist to localStorage whenever they change
  useEffect(() => { saveDevices(devices); }, [devices]);
  useEffect(() => { saveAccountDeviceMap(accountDeviceMap); }, [accountDeviceMap]);

  // ── Add Device modal ───────────────────────────────────────────────
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false);
  const [newDeviceName, setNewDeviceName] = useState('');

  // ── Delete Device ──────────────────────────────────────────────────
  const [deletingDeviceId, setDeletingDeviceId] = useState(null);

  // ── Add account modal ──────────────────────────────────────────────
  const [showAddModal, setShowAddModal] = useState(false);
  const [addModalDeviceId, setAddModalDeviceId] = useState(null); // which device this account belongs to
  const [newAccName, setNewAccName] = useState('');
  const [qrStatus, setQrStatus] = useState(null);
  const [currentAccId, setCurrentAccId] = useState(null);

  // ── Send message modal ─────────────────────────────────────────────
  const [showSendModal, setShowSendModal] = useState(false);
  const [sendAccId, setSendAccId] = useState('');
  const [sendPhone, setSendPhone] = useState('');
  const [sendMessageText, setSendMessageText] = useState('');

  // ── Edit status modal ──────────────────────────────────────────────
  const [showEditModal, setShowEditModal] = useState(false);
  const [editAccId, setEditAccId] = useState('');
  const [editStatus, setEditStatus] = useState('disponible');
  const [editPhone, setEditPhone] = useState('');
  const [editNotes, setEditNotes] = useState('');

  // ── Rescan modal ───────────────────────────────────────────────────
  const [showRescanModal, setShowRescanModal] = useState(false);
  const [rescanAccId, setRescanAccId] = useState(null);
  const [rescanQrStatus, setRescanQrStatus] = useState(null);

  // ── Delete account modal ───────────────────────────────────────────
  const [deletingAccId, setDeletingAccId] = useState(null);

  // ── View mode & search ─────────────────────────────────────────────
  const [viewMode, setViewMode] = useState('devices');
  const [searchPhone, setSearchPhone] = useState('');

  const { addToast } = useToast();
  const pollTimerRef = useRef(null);

  // ── Escape key / cleanup ───────────────────────────────────────────
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowAddModal(false);
        setShowAddDeviceModal(false);
        setShowSendModal(false);
        setShowEditModal(false);
        setShowRescanModal(false);
        setDeletingAccId(null);
        setDeletingDeviceId(null);
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

  // ── Helpers & search filter for accounts ───────────────────────────
  const filteredAccounts = accounts.filter((acc) => {
    if (!searchPhone.trim()) return true;
    const query = searchPhone.trim().toLowerCase();
    const phone = (acc.phone || '').toLowerCase();
    const accId = (acc.account_id || '').toLowerCase();
    return phone.includes(query) || accId.includes(query);
  });

  const getAccountsForDevice = (deviceId) => {
    return filteredAccounts.filter((acc) => accountDeviceMap[acc.account_id] === deviceId);
  };

  const getUnassignedAccounts = () => {
    return filteredAccounts.filter((acc) => !accountDeviceMap[acc.account_id]);
  };

  // ── QR polling ────────────────────────────────────────────────────
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
    setAddModalDeviceId(null);
    setCurrentAccId(null);
    setQrStatus(null);
    setNewAccName('');
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  };

  const closeRescanModal = () => {
    setShowRescanModal(false);
    setRescanAccId(null);
    setRescanQrStatus(null);
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
  };

  // ── Create Device ──────────────────────────────────────────────────
  const handleCreateDevice = (e) => {
    e.preventDefault();
    const name = newDeviceName.trim() || `Dispositivo ${devices.length + 1}`;
    const newDevice = {
      id: `device_${Date.now()}`,
      name,
      createdAt: new Date().toISOString(),
    };
    setDevices((prev) => [...prev, newDevice]);
    setNewDeviceName('');
    setShowAddDeviceModal(false);
    addToast(`Dispositivo '${name}' creado correctamente.`, 'success');
  };

  const handleDeleteDevice = (deviceId) => {
    const dev = devices.find((d) => d.id === deviceId);
    const devAccounts = getAccountsForDevice(deviceId);
    if (devAccounts.length > 0) {
      addToast('No puedes eliminar un dispositivo con cuentas activas.', 'error');
      setDeletingDeviceId(null);
      return;
    }
    setDevices((prev) => prev.filter((d) => d.id !== deviceId));
    setDeletingDeviceId(null);
    addToast(`Dispositivo '${dev?.name}' eliminado.`, 'success');
  };

  // ── Open slot → Add Account ────────────────────────────────────────
  const openAddAccountInDevice = (deviceId) => {
    setAddModalDeviceId(deviceId);
    setNewAccName('');
    setQrStatus(null);
    setCurrentAccId(null);
    setShowAddModal(true);
  };

  // ── Add account (QR login) ─────────────────────────────────────────
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

        // Associate account to the device immediately
        if (addModalDeviceId) {
          setAccountDeviceMap((prev) => {
            const updated = { ...prev, [accId]: addModalDeviceId };
            saveAccountDeviceMap(updated);
            return updated;
          });
        }

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
  const confirmDeleteAccount = (accId) => setDeletingAccId(accId);

  const executeDeleteAccount = async () => {
    if (!deletingAccId) return;
    const result = await dispatch(deleteAccount(deletingAccId));
    if (deleteAccount.fulfilled.match(result)) {
      addToast(`Cuenta '${deletingAccId}' eliminada.`, 'success');
      // Remove from device map
      setAccountDeviceMap((prev) => {
        const updated = { ...prev };
        delete updated[deletingAccId];
        return updated;
      });
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
          addToast(`✅ '${accId}' verificado/re-escaneado.`, 'success');
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
    addToast(`Generando CSV para ${availablePhonesCount} contacto(s)...`, 'info');
    window.location.href = '/api/accounts/export_contacts';
  };

  // ── Mini Account Card ─────────────────────────────────────────────
  const renderMiniCard = (acc) => {
    const isInstActive = acc.is_active;
    let badgeClass = 'badge-available';
    let badgeText = acc.status_state || 'Disponible';
    if (acc.status_state === 'restringido') { badgeClass = 'badge-restricted'; badgeText = 'Restringido'; }
    else if (acc.status_state === 'bloqueado') { badgeClass = 'badge-blocked'; badgeText = 'Bloqueado'; }
    else if (acc.status_state === 'enviando') { badgeClass = 'badge-active'; badgeText = 'Enviando'; }
    else if (acc.status_state === 'haciendo_historial') { badgeClass = 'badge-history'; badgeText = 'Historial'; }

    return (
      <div key={acc.account_id} className={`mini-account-card ${isInstActive ? 'active-instance' : ''}`}>
        {/* Header: nombre + estado */}
        <div className="mini-account-header">
          <div className="mini-account-title">
            <span className="mini-account-name" title={acc.account_id}>{acc.account_id}</span>
          </div>
          <span className={`badge ${badgeClass}`} style={{ fontSize: '10px', padding: '2px 7px', flexShrink: 0 }}>
            {badgeText}
          </span>
        </div>

        {/* Teléfono */}
        <div className="mini-account-phone">
          <span style={{ fontSize: '11px', color: 'var(--muted)' }}>📱</span>
          <span className={`phone-val ${acc.phone ? 'has-phone' : 'no-phone'}`}>
            {acc.phone ? acc.phone : 'Sin extraer'}
          </span>
        </div>

        {/* Detalles */}
        <div className="mini-account-details">
          <span>💾 {acc.size_mb} MB</span>
          {isInstActive
            ? <span style={{ color: '#00e5ff', fontWeight: '600' }}>● Activa</span>
            : <span>Cerrada</span>
          }
        </div>

        {/* Acciones */}
        <div className="mini-actions">
          {!isInstActive ? (
            <button className="btn btn-sm btn-success" onClick={() => handleOpenInstance(acc.account_id)} title="Abrir Instancia">
              ▶ Abrir
            </button>
          ) : (
            <button className="btn btn-sm btn-warning" onClick={() => handleCloseInstance(acc.account_id)} title="Cerrar Instancia">
              ⏹ Cerrar
            </button>
          )}
          <button
            className="btn btn-sm btn-secondary"
            style={{ background: 'rgba(251,191,36,0.15)', borderColor: '#fbbf24', color: '#fbbf24' }}
            onClick={() => handleRescanAccount(acc.account_id)}
            title="Re-escanear QR"
          >
            🔄
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
            title="Editar Estado"
          >
            ✏️
          </button>
          <button
            className="btn btn-sm btn-danger"
            onClick={() => confirmDeleteAccount(acc.account_id)}
            title="Eliminar Cuenta"
          >
            🗑️
          </button>
        </div>
      </div>
    );
  };

  // ── Unassigned accounts auto-assign on load ───────────────────────
  // (existing accounts with no device stay visible in list view)
  const unassigned = getUnassignedAccounts();

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className="tab-pane active" id="tab-accounts">
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1>Gestor de Cuentas de WhatsApp</h1>
          <p className="subtitle">Organiza tus dispositivos y sesiones de WhatsApp</p>
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
            Exportar CSV 📥
          </button>
          <button
            className="btn btn-primary"
            onClick={() => {
              setNewDeviceName('');
              setShowAddDeviceModal(true);
            }}
          >
            <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            Nuevo Dispositivo
          </button>
        </div>
      </div>

      {/* Selector de Vista + Buscador por teléfono + contador */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            className={`btn btn-sm ${viewMode === 'devices' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('devices')}
            style={{ borderRadius: '20px', padding: '6px 16px' }}
          >
            📱 Vista Dispositivos (2×2)
          </button>
          <button
            className={`btn btn-sm ${viewMode === 'list' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setViewMode('list')}
            style={{ borderRadius: '20px', padding: '6px 16px' }}
          >
            📑 Vista Lista
          </button>
        </div>

        {/* Buscador de cuentas por celular o ID */}
        <div style={{ position: 'relative', minWidth: '240px', flex: 1, maxWidth: '380px' }}>
          <input
            type="text"
            className="form-control"
            placeholder="🔍 Buscar cuenta por número cel o ID..."
            value={searchPhone}
            onChange={(e) => setSearchPhone(e.target.value)}
            style={{
              paddingLeft: '34px',
              paddingRight: searchPhone ? '32px' : '12px',
              borderRadius: '20px',
              height: '36px',
              fontSize: '0.85rem',
              background: 'rgba(15, 23, 42, 0.7)',
              borderColor: searchPhone ? 'var(--cyan)' : 'rgba(255, 255, 255, 0.15)',
              boxShadow: searchPhone ? '0 0 8px rgba(0, 229, 255, 0.25)' : 'none'
            }}
          />
          <span style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', opacity: 0.6, fontSize: '0.85rem' }}>
            📱
          </span>
          {searchPhone && (
            <button
              type="button"
              onClick={() => setSearchPhone('')}
              style={{
                position: 'absolute',
                right: '10px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: 'transparent',
                border: 'none',
                color: 'var(--muted)',
                cursor: 'pointer',
                fontSize: '14px',
                lineHeight: 1
              }}
              title="Limpiar búsqueda"
            >
              ✕
            </button>
          )}
        </div>

        <div style={{ fontSize: '13px', color: 'var(--muted)', display: 'flex', gap: '16px', alignItems: 'center' }}>
          <span>Dispositivos: <strong style={{ color: 'var(--cyan)' }}>{devices.length}</strong></span>
          <span>
            Cuentas: <strong style={{ color: 'var(--cyan)' }}>
              {searchPhone.trim() ? `${filteredAccounts.length}/${accounts.length}` : accounts.length}
            </strong>
          </span>
        </div>
      </div>

      {/* ── VISTA DISPOSITIVOS ─────────────────────────────────────── */}
      {viewMode === 'devices' && (
        <>
          {loading && accounts.length === 0 ? (
            <div className="card empty-card">
              <div className="empty-state">
                <div className="spinner"></div>
                <p style={{ marginTop: '12px', color: 'var(--muted)' }}>Cargando cuentas de WhatsApp...</p>
              </div>
            </div>
          ) : devices.length === 0 ? (
            <div className="card empty-card">
              <div className="empty-state">
                <div className="empty-icon">📱</div>
                <h3>Sin Dispositivos</h3>
                <p>Crea tu primer Dispositivo para comenzar a gestionar cuentas de WhatsApp.</p>
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => { setNewDeviceName(''); setShowAddDeviceModal(true); }}
                >
                  ➕ Crear Primer Dispositivo
                </button>
              </div>
            </div>
          ) : searchPhone.trim() && filteredAccounts.length === 0 ? (
            <div className="card empty-card" style={{ marginTop: '16px' }}>
              <div className="empty-state">
                <div className="empty-icon">🔍</div>
                <h3>Sin coincidencias</h3>
                <p>No se encontraron cuentas asociadas al número de celular o búsqueda "<strong>{searchPhone}</strong>".</p>
                <button className="btn btn-secondary btn-sm" onClick={() => setSearchPhone('')}>
                  Limpiar Búsqueda
                </button>
              </div>
            </div>
          ) : (
            <div className="device-grid">
              {devices.map((device) => {
                const devAccounts = getAccountsForDevice(device.id);
                const activeCount = devAccounts.filter((a) => a.is_active).length;
                const emptySlots = Math.max(0, 4 - devAccounts.length);

                return (
                  <div key={device.id} className="device-card">
                    {/* Device Card Header */}
                    <div className="device-card-header">
                      <div className="device-info-box">
                        <div className="device-icon-box">📱</div>
                        <div>
                          <div className="device-title">{device.name}</div>
                          <div className="device-subtitle">
                            {devAccounts.length}/4 Cuentas · {activeCount} Activas
                          </div>
                        </div>
                      </div>
                      <div className="device-header-stats">
                        {/* Indicador visual de slots */}
                        <div style={{ display: 'flex', gap: '4px' }}>
                          {[0,1,2,3].map((i) => (
                            <div key={i} style={{
                              width: '8px', height: '8px', borderRadius: '50%',
                              background: i < devAccounts.length
                                ? (devAccounts[i]?.is_active ? '#00e5ff' : '#00e676')
                                : 'rgba(255,255,255,0.12)',
                              border: `1px solid ${i < devAccounts.length ? 'transparent' : 'rgba(255,255,255,0.2)'}`,
                            }} />
                          ))}
                        </div>
                        <button
                          className="btn btn-sm btn-danger"
                          onClick={() => setDeletingDeviceId(device.id)}
                          title="Eliminar Dispositivo"
                          style={{ padding: '4px 8px', fontSize: '11px' }}
                        >
                          🗑️
                        </button>
                      </div>
                    </div>

                    {/* Mini-cards grid 2x2 */}
                    <div className="device-accounts-grid">
                      {/* Cuentas existentes */}
                      {devAccounts.map((acc) => renderMiniCard(acc))}

                      {/* Slots vacíos (solo cuando no hay búsqueda activa) */}
                      {!searchPhone.trim() && Array.from({ length: emptySlots }).map((_, slotIdx) => (
                        <div
                          key={`slot-${slotIdx}`}
                          className="empty-slot-card"
                          onClick={() => openAddAccountInDevice(device.id)}
                        >
                          <span className="empty-slot-icon">➕</span>
                          <span className="empty-slot-text">Agregar Cuenta</span>
                          <span style={{ fontSize: '10px', color: 'var(--muted)', opacity: 0.6 }}>
                            Slot {devAccounts.length + slotIdx + 1} de 4
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Cuentas no asignadas (existentes antes de esta versión) */}
          {unassigned.length > 0 && (
            <div style={{ marginTop: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                <span style={{ fontSize: '13px', color: 'var(--muted)' }}>
                  ⚠️ {unassigned.length} cuenta(s) sin dispositivo asignado — aparecen en Vista Lista.
                </span>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── VISTA LISTA ───────────────────────────────────────────── */}
      {viewMode === 'list' && (
        <div className="accounts-grid">
          {loading && accounts.length === 0 ? (
            <div className="card empty-card">
              <div className="empty-state">
                <div className="spinner"></div>
                <p style={{ marginTop: '12px', color: 'var(--muted)' }}>Cargando...</p>
              </div>
            </div>
          ) : accounts.length === 0 ? (
            <div className="card empty-card">
              <div className="empty-state">
                <p>No hay cuentas registradas. Crea un Dispositivo y agrega cuentas desde sus slots.</p>
              </div>
            </div>
          ) : filteredAccounts.length === 0 ? (
            <div className="card empty-card" style={{ gridColumn: '1 / -1' }}>
              <div className="empty-state">
                <div className="empty-icon">🔍</div>
                <h3>Sin coincidencias</h3>
                <p>No se encontraron cuentas con el número o búsqueda "<strong>{searchPhone}</strong>".</p>
                <button className="btn btn-secondary btn-sm" onClick={() => setSearchPhone('')}>
                  Limpiar Búsqueda
                </button>
              </div>
            </div>
          ) : (
            filteredAccounts.map((acc) => {
              const isInstActive = acc.is_active;
              let badgeClass = 'badge-available';
              let badgeText = acc.status_state || 'Disponible';
              if (acc.status_state === 'restringido') { badgeClass = 'badge-restricted'; badgeText = 'Restringido'; }
              else if (acc.status_state === 'bloqueado') { badgeClass = 'badge-blocked'; badgeText = 'Bloqueado'; }
              else if (acc.status_state === 'enviando') { badgeClass = 'badge-active'; badgeText = 'Enviando'; }
              else if (acc.status_state === 'haciendo_historial') { badgeClass = 'badge-history'; badgeText = 'Haciendo Historial'; }

              const deviceOfAcc = devices.find((d) => d.id === accountDeviceMap[acc.account_id]);

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
                        {isInstActive && <span className="badge badge-active">Activa</span>}
                        {deviceOfAcc && (
                          <span className="badge" style={{ background: 'rgba(206,147,216,0.12)', border: '1px solid rgba(206,147,216,0.25)', color: 'var(--purple)', fontSize: '10px' }}>
                            📱 {deviceOfAcc.name}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="account-details">
                    <div className="detail-item full-width" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '6px', marginBottom: '4px' }}>
                      <span className="label">📱 Número Vinculado:</span>
                      <span className="val" style={{ fontWeight: '700', color: acc.phone ? '#10b981' : '#f59e0b' }}>
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
                      onClick={() => { setSendAccId(acc.account_id); setSendPhone(''); setSendMessageText(''); setShowSendModal(true); }}
                    >
                      📤 Enviar
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => { setEditAccId(acc.account_id); setEditStatus(acc.status_state || 'disponible'); setEditPhone(acc.phone || ''); setEditNotes(acc.notes || ''); setShowEditModal(true); }}
                    >
                      ✏️ Estado
                    </button>
                    <button
                      className="btn btn-sm btn-secondary"
                      style={{ background: 'rgba(251,191,36,0.15)', borderColor: '#fbbf24', color: '#fbbf24' }}
                      onClick={() => handleRescanAccount(acc.account_id)}
                    >
                      🔄 Re-escanear
                    </button>
                    <button className="btn btn-sm btn-danger" onClick={() => confirmDeleteAccount(acc.account_id)}>
                      🗑️ Eliminar
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* ── MODAL: NUEVO DISPOSITIVO ─────────────────────────────────── */}
      {showAddDeviceModal && (
        <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) setShowAddDeviceModal(false); }}>
          <div className="modal" style={{ maxWidth: '460px' }}>
            <div className="modal-header">
              <h2>📱 Crear Nuevo Dispositivo</h2>
              <button className="modal-close" onClick={() => setShowAddDeviceModal(false)}>✕</button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleCreateDevice}>
                <div className="form-group">
                  <label>Nombre del Dispositivo:</label>
                  <input
                    type="text"
                    className="form-control"
                    placeholder={`Ej: Celular Ventas, Dispositivo ${devices.length + 1}`}
                    value={newDeviceName}
                    onChange={(e) => setNewDeviceName(e.target.value)}
                    autoFocus
                  />
                  <small className="form-text">
                    Deja vacío para nombre automático (<em>Dispositivo {devices.length + 1}</em>).
                    Este dispositivo puede contener hasta 4 cuentas de WhatsApp.
                  </small>
                </div>
                <div className="modal-footer" style={{ padding: '16px 0 0 0' }}>
                  <button type="button" className="btn btn-secondary" onClick={() => setShowAddDeviceModal(false)}>
                    Cancelar
                  </button>
                  <button type="submit" className="btn btn-primary">
                    ➕ Crear Dispositivo
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: AGREGAR CUENTA EN DISPOSITIVO (QR) ─────────────────── */}
      {showAddModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>
                📲 Vincular Cuenta en {devices.find((d) => d.id === addModalDeviceId)?.name || 'Dispositivo'}
              </h2>
              <button className="modal-close" onClick={closeAddModal}>✕</button>
            </div>
            <div className="modal-body">
              {!currentAccId ? (
                <form onSubmit={handleStartQRLogin}>
                  <div className="form-group">
                    <label>Nombre de la Cuenta:</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="Ej: Ventas Norte, Soporte 01"
                      value={newAccName}
                      onChange={(e) => setNewAccName(e.target.value)}
                      required
                      autoFocus
                    />
                    <small className="form-text">
                      Asigna un nombre descriptivo. Esta cuenta quedará asociada al dispositivo seleccionado.
                    </small>
                  </div>
                  <div className="modal-footer" style={{ padding: '16px 0 0 0' }}>
                    <button type="button" className="btn btn-secondary" onClick={closeAddModal}>Cancelar</button>
                    <button type="submit" className="btn btn-primary">Generar Código QR 📲</button>
                  </div>
                </form>
              ) : (
                <div className="qr-container">
                  <p className="qr-instructions">
                    Escanea el código QR desde tu WhatsApp:<br />
                    <strong>Dispositivos vinculados → Vincular un dispositivo</strong>
                  </p>

                  {qrStatus && qrStatus.qr ? (
                    <div className="qr-code-box">
                      <img src={qrStatus.qr} alt="Código QR de WhatsApp" />
                      <p className="qr-timer">⌛ Actualizando automáticamente... {qrStatus.timeout ? `(${qrStatus.timeout}s)` : ''}</p>
                    </div>
                  ) : null}

                  {(!qrStatus || qrStatus.status === 'waiting_qr' || qrStatus.status === 'unknown') && (
                    <div className="qr-loading">
                      <div className="spinner"></div>
                      <p>Iniciando WhatsApp y generando código QR...</p>
                    </div>
                  )}

                  {qrStatus && qrStatus.status === 'success' && (
                    <div className="alert alert-success">✅ ¡Cuenta vinculada exitosamente!</div>
                  )}
                  {qrStatus && qrStatus.status === 'error' && (
                    <div className="alert alert-danger">❌ {qrStatus.message || 'Error al vincular la cuenta.'}</div>
                  )}

                  <div className="modal-footer" style={{ padding: '16px 0 0 0', marginTop: '16px' }}>
                    <button type="button" className="btn btn-secondary" onClick={closeAddModal}>Cerrar</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: ENVIAR MENSAJE DE PRUEBA ────────────────────────── */}
      {showSendModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>💬 Enviar Mensaje desde '{sendAccId}'</h2>
              <button className="modal-close" onClick={() => setShowSendModal(false)}>✕</button>
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
                  <button type="button" className="btn btn-secondary" onClick={() => setShowSendModal(false)}>Cancelar</button>
                  <button type="submit" className="btn btn-primary">Enviar Mensaje 🚀</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: EDITAR ESTADO ────────────────────────────────────── */}
      {showEditModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-header">
              <h2>⚙️ Configurar Cuenta '{editAccId}'</h2>
              <button className="modal-close" onClick={() => setShowEditModal(false)}>✕</button>
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
                  <small className="form-text">Extraído automáticamente al escanear QR, o edita manualmente.</small>
                </div>
                <div className="form-group">
                  <label>Estado Operativo:</label>
                  <select className="form-control" value={editStatus} onChange={(e) => setEditStatus(e.target.value)}>
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
                  <button type="button" className="btn btn-secondary" onClick={() => setShowEditModal(false)}>Cancelar</button>
                  <button type="submit" className="btn btn-primary">💾 Guardar Cambios</button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: RE-ESCANEAR QR ─────────────────────────────────── */}
      {showRescanModal && (
        <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) closeRescanModal(); }}>
          <div className="modal">
            <div className="modal-header">
              <h2>🔄 Re-escanear Cuenta '{rescanAccId}'</h2>
              <button className="modal-close" onClick={closeRescanModal}>✕</button>
            </div>
            <div className="modal-body">
              <div className="qr-container">
                <p className="qr-instructions">
                  Escanea el nuevo QR para actualizar la sesión:<br />
                  <strong>Dispositivos vinculados → Vincular un dispositivo</strong>
                </p>
                {rescanQrStatus && rescanQrStatus.qr ? (
                  <div className="qr-code-box">
                    <img src={rescanQrStatus.qr} alt="Código QR" />
                    <p className="qr-timer">⌛ Actualizando... {rescanQrStatus.timeout ? `(${rescanQrStatus.timeout}s)` : ''}</p>
                  </div>
                ) : null}
                {(!rescanQrStatus || rescanQrStatus.status === 'waiting_qr' || rescanQrStatus.status === 'unknown') && (
                  <div className="qr-loading">
                    <div className="spinner"></div>
                    <p>Reiniciando sesión y generando nuevo QR...</p>
                  </div>
                )}
                {rescanQrStatus && rescanQrStatus.status === 'success' && (
                  <div className="alert alert-success">✅ ¡Re-escaneo exitoso! Número actualizado.</div>
                )}
                {rescanQrStatus && rescanQrStatus.status === 'error' && (
                  <div className="alert alert-danger">❌ {rescanQrStatus.message || 'Error al re-escanear.'}</div>
                )}
                <div className="modal-footer" style={{ padding: '16px 0 0 0', marginTop: '16px' }}>
                  <button type="button" className="btn btn-secondary" onClick={closeRescanModal}>Cerrar</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: CONFIRMAR ELIMINACIÓN CUENTA ──────────────────── */}
      {deletingAccId && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header" style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
              <h2>⚠️ Confirmar Eliminación</h2>
              <button className="modal-close" onClick={() => setDeletingAccId(null)}>✕</button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🗑️</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Estás seguro de eliminar la cuenta?
              </p>
              <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444', padding: '10px 14px', borderRadius: '8px', fontWeight: '600', marginBottom: '20px' }}>
                "{deletingAccId}"
              </div>
              <p style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '24px' }}>
                Se eliminarán permanentemente las cookies y la sesión asociada.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setDeletingAccId(null)} style={{ flex: 1 }}>
                  Cancelar
                </button>
                <button type="button" className="btn btn-danger" onClick={executeDeleteAccount} style={{ flex: 1, backgroundColor: '#ef4444', borderColor: '#ef4444' }}>
                  🗑️ Eliminar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: CONFIRMAR ELIMINACIÓN DISPOSITIVO ──────────────── */}
      {deletingDeviceId && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header">
              <h2>⚠️ Eliminar Dispositivo</h2>
              <button className="modal-close" onClick={() => setDeletingDeviceId(null)}>✕</button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>📱</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Eliminar el dispositivo?
              </p>
              <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444', padding: '10px 14px', borderRadius: '8px', fontWeight: '600', marginBottom: '12px' }}>
                "{devices.find((d) => d.id === deletingDeviceId)?.name}"
              </div>
              <p style={{ fontSize: '13px', color: '#f59e0b', marginBottom: '20px' }}>
                ⚠️ Solo puedes eliminar dispositivos sin cuentas activas.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button type="button" className="btn btn-secondary" onClick={() => setDeletingDeviceId(null)} style={{ flex: 1 }}>
                  Cancelar
                </button>
                <button type="button" className="btn btn-danger" onClick={() => handleDeleteDevice(deletingDeviceId)} style={{ flex: 1, backgroundColor: '#ef4444', borderColor: '#ef4444' }}>
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
