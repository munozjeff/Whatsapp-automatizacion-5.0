import React, { useState, useEffect, useRef } from 'react';
import { useToast } from '../hooks/useToast';

/* ── Status helpers ─────────────────────────── */
const STATUS_META = {
  running:   { label: 'En ejecución', cls: 'badge-active',     icon: '🚀' },
  pending:   { label: 'Pendiente',    cls: 'badge-restricted',  icon: '⏳' },
  paused:    { label: 'Pausado',      cls: 'badge-restricted',  icon: '⏸️' },
  completed: { label: 'Completado',   cls: 'badge-available',   icon: '✅' },
  error:     { label: 'Error',        cls: 'badge-blocked',     icon: '❌' },
};

function statusMeta(s) {
  return STATUS_META[s] || { label: s, cls: 'badge-history', icon: '❓' };
}

/* ── Main Component ─────────────────────────── */
export default function Automation({ activeTab }) {
  const { addToast } = useToast();

  /* Data */
  const [profiles,  setProfiles]  = useState([]);
  const [accounts,  setAccounts]  = useState([]);
  const [jobs,      setJobs]      = useState([]);

  /* Form wizard */
  const [step, setStep]           = useState(1);   // 1=config, 2=contacts, 3=running
  const [selectedProfile, setSelectedProfile] = useState('');
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [contactsText, setContactsText] = useState('');
  const [contactsFile, setContactsFile] = useState(null);

  /* Derived */
  const [profileInfo, setProfileInfo] = useState(null);
  const [parsedCount, setParsedCount] = useState(0);
  const [launching, setLaunching] = useState(false);

  const pollRef = useRef(null);
  const fileInputRef = useRef(null);

  const [notifications, setNotifications] = useState([]);
  const [expandedNotifs, setExpandedNotifs] = useState(new Set());

  const toggleExpandNotif = (id, e) => {
    if (e) e.stopPropagation();
    setExpandedNotifs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  /* ── Fetch ───────────────────────────────── */
  const fetchAll = async () => {
    try {
      const [pRes, aRes, jRes, nRes] = await Promise.allSettled([
        fetch('/api/send_profiles').then((r) => r.json()),
        fetch('/api/accounts').then((r) => r.json()),
        fetch('/api/automation/jobs').then((r) => r.json()),
        fetch('/api/notifications?status=pending').then((r) => r.json()),
      ]);

      if (pRes.status === 'fulfilled' && pRes.value?.status === 'success') {
        setProfiles(pRes.value.profiles || []);
      }
      if (aRes.status === 'fulfilled' && aRes.value?.status === 'success') {
        setAccounts(aRes.value.accounts || []);
      }
      if (jRes.status === 'fulfilled' && jRes.value?.status === 'success') {
        setJobs(jRes.value.jobs || []);
      }
      if (nRes.status === 'fulfilled' && nRes.value?.status === 'success') {
        setNotifications(nRes.value.notifications || []);
      }
    } catch (err) {
      console.error('Error cargando datos de automatización:', err);
    }
  };

  const resolveNotification = async (id) => {
    try {
      const res = await fetch(`/api/notifications/${id}/resolve`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast('Notificación atendida.', 'success');
        fetchAll();
      }
    } catch (err) {
      addToast('Error al resolver notificación.', 'error');
    }
  };

  const resolveAllNotifications = async () => {
    try {
      const res = await fetch('/api/notifications/resolve_all', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        fetchAll();
      }
    } catch (err) {
      addToast('Error al resolver notificaciones.', 'error');
    }
  };

  const parseNotificationMessages = (text) => {
    if (!text) return [];
    return text
      .split('\n')
      .map((l) => l.replace(/^\[\d{1,2}:\d{2}.*?\]\s*/, '').trim())
      .filter((l) => l.length > 0);
  };

  useEffect(() => {
    if (activeTab === 'automation') {
      fetchAll();
      pollRef.current = setInterval(fetchAll, 5000);
      return () => clearInterval(pollRef.current);
    }
  }, [activeTab]);

  /* ── Auto-select default profile & accounts ────── */
  useEffect(() => {
    if (profiles.length > 0 && !selectedProfile) {
      setSelectedProfile(String(profiles[0].id));
    }
  }, [profiles]);

  useEffect(() => {
    if (accounts.length > 0 && selectedAccounts.length === 0) {
      const available = accounts
        .filter((a) => a.status_state !== 'bloqueado' && a.status_state !== 'restringido')
        .map((a) => a.account_id);
      setSelectedAccounts(available);
    }
  }, [accounts]);

  /* ── Profile selection info ───────────────────── */
  useEffect(() => {
    if (selectedProfile) {
      const p = profiles.find((p) => String(p.id) === String(selectedProfile));
      setProfileInfo(p || null);
    } else {
      setProfileInfo(null);
    }
  }, [selectedProfile, profiles]);

  /* ── Contact parsing preview ─────────────── */
  useEffect(() => {
    const lines = contactsText
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    setParsedCount(lines.length);
  }, [contactsText]);

  /* ── Account toggle ─────────────────────── */
  const toggleAccount = (id) => {
    setSelectedAccounts((prev) =>
      prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]
    );
  };

  const toggleAllAccounts = () => {
    const available = accounts
      .filter((a) => a.status_state !== 'bloqueado' && a.status_state !== 'restringido')
      .map((a) => a.account_id);
    if (selectedAccounts.length === available.length) {
      setSelectedAccounts([]);
    } else {
      setSelectedAccounts(available);
    }
  };

  const handleNextToContacts = () => {
    if (!selectedProfile) {
      addToast('Por favor selecciona un Perfil de Envío primero.', 'warning');
      return;
    }
    if (selectedAccounts.length === 0) {
      addToast('Por favor selecciona al menos una cuenta de WhatsApp.', 'warning');
      return;
    }
    setStep(2);
  };

  /* ── File upload ─────────────────────────── */
  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setContactsFile(file.name);
    const reader = new FileReader();
    reader.onload = (evt) => {
      setContactsText(evt.target.result);
    };
    reader.readAsText(file);
  };

  /* ── Launch ─────────────────────────────── */
  const handleLaunch = async () => {
    if (!selectedProfile) { addToast('Selecciona un perfil de envío.', 'error'); return; }
    if (selectedAccounts.length === 0) { addToast('Selecciona al menos una cuenta.', 'error'); return; }
    const isSoloHistory = profileInfo && profileInfo.accounts_for_sending === 0;
    if (!isSoloHistory && !contactsText.trim()) { addToast('La lista de contactos está vacía.', 'error'); return; }

    setLaunching(true);
    try {
      const res = await fetch('/api/automation/launch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile_id: selectedProfile,
          account_ids: selectedAccounts,
          contacts: contactsText,
        }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success', `Job #${data.job_id} creado`);
        setStep(3);
        fetchAll();
      } else {
        addToast(data.message, 'error');
      }
    } catch (err) {
      addToast('Error al lanzar la automatización.', 'error');
    } finally {
      setLaunching(false);
    }
  };

  /* ── Job control ─────────────────────────── */
  const updateJobStatus = async (jobId, status) => {
    try {
      const res = await fetch(`/api/automation/jobs/${jobId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        fetchAll();
      }
    } catch (err) {
      addToast('Error actualizando el job.', 'error');
    }
  };

  const [deletingJobId, setDeletingJobId] = useState(null);

  const confirmDeleteJob = (jobId) => {
    setDeletingJobId(jobId);
  };

  const executeDeleteJob = async () => {
    if (!deletingJobId) return;
    try {
      const res = await fetch(`/api/automation/jobs/${deletingJobId}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setDeletingJobId(null);
        fetchAll();
      }
    } catch (err) {
      addToast('Error eliminando el job.', 'error');
    }
  };

  /* ── Available accounts (not blocked/restricted) ── */
  /* ── Account Status Counts (Real-Time) ──────── */
  const availableCount = accounts.filter(
    (a) => a.status_state === 'disponible' || (!a.status_state && !a.is_blocked)
  ).length;

  const blockedCount = accounts.filter(
    (a) => a.status_state === 'bloqueado' || a.is_blocked
  ).length;

  const restrictedCount = accounts.filter(
    (a) => a.status_state === 'restringido'
  ).length;

  const activeCount = accounts.filter(
    (a) => a.is_active || a.status_state === 'enviando' || a.status_state === 'haciendo_historial'
  ).length;

  const availableAccounts = accounts.filter(
    (a) => a.status_state !== 'bloqueado' && a.status_state !== 'restringido'
  );

  /* ── UI ─────────────────────────────────── */
  return (
    <div className="tab-pane active" id="tab-automation">

      {/* Header */}
      <div className="page-header">
        <div>
          <h1>🚀 Centro de Automatización</h1>
          <p className="subtitle">
            Configura y lanza envíos masivos de WhatsApp con múltiples cuentas y perfiles de velocidad
          </p>
        </div>
        {step !== 1 && (
          <button className="btn btn-secondary" onClick={() => setStep(1)}>
            ← Nueva configuración
          </button>
        )}
      </div>

      {/* Barra de métricas de cuentas en tiempo real */}
      <div className="automation-realtime-bar">
        <div className="rt-bar-title">
          <span className="live-dot pulse">●</span>
          <span>Monitoreo de Cuentas en Tiempo Real:</span>
        </div>
        <div className="rt-metrics-grid">
          <div className="rt-metric-card metric-available">
            <span className="rt-metric-icon">🟢</span>
            <div className="rt-metric-info">
              <span className="rt-metric-val">{availableCount}</span>
              <span className="rt-metric-lbl">Disponibles</span>
            </div>
          </div>
          <div className="rt-metric-card metric-blocked">
            <span className="rt-metric-icon">🔴</span>
            <div className="rt-metric-info">
              <span className="rt-metric-val">{blockedCount}</span>
              <span className="rt-metric-lbl">Bloqueadas</span>
            </div>
          </div>
          <div className="rt-metric-card metric-restricted">
            <span className="rt-metric-icon">🟡</span>
            <div className="rt-metric-info">
              <span className="rt-metric-val">{restrictedCount}</span>
              <span className="rt-metric-lbl">Restringidas</span>
            </div>
          </div>
          <div className="rt-metric-card metric-active">
            <span className="rt-metric-icon">⚡</span>
            <div className="rt-metric-info">
              <span className="rt-metric-val">{activeCount}</span>
              <span className="rt-metric-lbl">En Ejecución</span>
            </div>
          </div>
          <div className="rt-metric-card metric-total">
            <span className="rt-metric-icon">📱</span>
            <div className="rt-metric-info">
              <span className="rt-metric-val">{accounts.length}</span>
              <span className="rt-metric-lbl">Total Registradas</span>
            </div>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════
          WIZARD — STEP 1: Configuración
      ═══════════════════════════════════════ */}
      {step === 1 && (
        <div className="automation-layout">

          {/* LEFT: Wizard */}
          <div className="automation-wizard">

            {/* Step indicator */}
            <div className="step-indicator">
              <div className="step-item active">
                <div className="step-num">1</div>
                <span>Perfil y Cuentas</span>
              </div>
              <div className="step-line"></div>
              <div className="step-item">
                <div className="step-num">2</div>
                <span>Lista de Contactos</span>
              </div>
              <div className="step-line"></div>
              <div className="step-item">
                <div className="step-num">3</div>
                <span>Lanzar</span>
              </div>
            </div>

            {/* Profile selector */}
            <div className="card wizard-card">
              <div className="card-header">
                <h3>⚙️ Seleccionar Perfil de Envío</h3>
              </div>
              <div className="card-body">
                {profiles.length === 0 ? (
                  <div className="alert alert-danger">
                    No tienes perfiles creados. Ve a "Perfiles de Envío" y crea uno primero.
                  </div>
                ) : (
                  <div className="profile-select-grid">
                    {profiles.map((p) => (
                      <div
                        key={p.id}
                        className={`profile-select-card ${String(selectedProfile) === String(p.id) ? 'selected' : ''}`}
                        onClick={() => setSelectedProfile(String(p.id))}
                      >
                        <div className="psc-header">
                          <span className="psc-icon">⚙️</span>
                          <div>
                            <div className="psc-name">{p.name}</div>
                            <div className="psc-campaign">
                              {p.campaign_name ? `📌 ${p.campaign_name}` : 'Sin campaña'}
                            </div>
                          </div>
                          {String(selectedProfile) === String(p.id) && (
                            <span className="psc-check">✓</span>
                          )}
                        </div>
                        <div className="psc-metrics">
                          <span>⏱ {p.delay_min_sec}–{p.delay_max_sec}s</span>
                          <span>📦 {p.messages_per_session} msgs</span>
                          {p.accounts_for_sending === 0 ? (
                            <span className="badge badge-restricted" style={{ fontSize: '0.7rem' }}>💬 Solo Historial</span>
                          ) : p.accounts_for_history === 0 ? (
                            <span className="badge badge-available" style={{ fontSize: '0.7rem' }}>📢 Solo Envío Real</span>
                          ) : (
                            <span className="badge badge-history" style={{ fontSize: '0.7rem' }}>🔄 Multi ({p.accounts_for_sending}E/{p.accounts_for_history}H)</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Accounts selector */}
            <div className="card wizard-card">
              <div className="card-header">
                <h3>📱 Seleccionar Cuentas de WhatsApp</h3>
                <button
                  className="btn btn-sm btn-secondary"
                  onClick={toggleAllAccounts}
                >
                  {selectedAccounts.length === availableAccounts.length
                    ? 'Deseleccionar todo'
                    : 'Seleccionar todo'}
                </button>
              </div>
              <div className="card-body">
                {accounts.length === 0 ? (
                  <div className="alert alert-danger">
                    No tienes cuentas registradas. Ve a "Gestor de Cuentas" primero.
                  </div>
                ) : (
                  <div className="accounts-check-grid">
                    {accounts.map((acc) => {
                      const disabled =
                        acc.status_state === 'bloqueado' ||
                        acc.status_state === 'restringido';
                      const checked = selectedAccounts.includes(acc.account_id);
                      return (
                        <div
                          key={acc.account_id}
                          className={`acc-check-card ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}`}
                          onClick={() => !disabled && toggleAccount(acc.account_id)}
                        >
                          <div className="acc-check-left">
                            <div className={`acc-checkbox ${checked ? 'chk-active' : ''}`}>
                              {checked && <span>✓</span>}
                            </div>
                            <div>
                              <div className="acc-check-name">{acc.account_id}</div>
                              <div className="acc-check-status">
                                <span className={`badge ${
                                  acc.status_state === 'bloqueado' ? 'badge-blocked' :
                                  acc.status_state === 'restringido' ? 'badge-restricted' :
                                  acc.status_state === 'enviando' ? 'badge-active' :
                                  'badge-available'
                                }`}>
                                  {acc.status_state || 'disponible'}
                                </span>
                              </div>
                            </div>
                          </div>
                          {acc.is_active && <span className="acc-live-dot pulse">●</span>}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {profileInfo?.accounts_for_sending === 0 ? (
              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  className="btn btn-primary"
                  style={{ flex: 1 }}
                  onClick={handleLaunch}
                  disabled={launching}
                >
                  {launching ? 'Lanzando...' : '💬 Lanzar Solo Historial Directamente'}
                </button>
                <button
                  className="btn btn-secondary"
                  style={{ flex: 1 }}
                  onClick={handleNextToContacts}
                >
                  Continuar → (Cargar Contactos Opcional)
                </button>
              </div>
            ) : (
              <button
                className="btn btn-primary btn-block"
                onClick={handleNextToContacts}
              >
                Continuar → Cargar Contactos
              </button>
            )}
          </div>

          {/* RIGHT: Jobs history sidebar & Client Notifications */}
          <div className="automation-sidebar">

            {/* Client Notifications Card */}
            <div className="client-notif-card">
              <div className="client-notif-header">
                <h3>🔔 Notificaciones de Clientes</h3>
                {notifications.length > 0 && <span className="client-notif-count">{notifications.length}</span>}
              </div>
              <div className="card-body no-pad">
                {notifications.length === 0 ? (
                  <div className="empty-state" style={{ padding: '20px 16px', fontSize: '0.88rem' }}>
                    <p>✅ No hay mensajes de clientes pendientes</p>
                  </div>
                ) : (
                  <div className="client-notif-list">
                    {notifications.map((n) => {
                      const isExpanded = expandedNotifs.has(n.id);
                      const accountName = [n.account_first_name, n.account_last_name].filter(Boolean).join(' ');
                      const receiverLabel = accountName 
                        ? (n.account_phone ? `${accountName} (${n.account_phone})` : accountName)
                        : (n.account_phone || (n.account_id && n.account_id !== '?' ? n.account_id : 'Sin identificar'));

                      const shortTime = n.received_at ? n.received_at.slice(11, 16) : '';
                      const parsedMsgs = parseNotificationMessages(n.message_text);

                      return (
                        <div 
                          key={n.id} 
                          className={`client-notif-item ${isExpanded ? 'expanded' : ''}`}
                          onClick={(e) => toggleExpandNotif(n.id, e)}
                        >
                          {/* Top Compact Header Bar */}
                          <div className="client-notif-header-compact">
                            <div className="client-notif-sender">
                              <div className="client-notif-avatar">👤</div>
                              <span title={n.client_phone || n.client_name}>
                                {n.client_phone || n.client_name || 'Cliente'}
                              </span>
                            </div>

                            <div className="client-notif-preview-msg">
                              {parsedMsgs.join(' • ') || n.message_text}
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              {shortTime && (
                                <span className="client-notif-time" style={{ fontSize: '0.72rem' }}>
                                  🕒 {shortTime}
                                </span>
                              )}
                              <span className="client-notif-chevron">▼</span>
                            </div>
                          </div>

                          {/* Expanded Details Body */}
                          {isExpanded && (
                            <div className="client-notif-body-expanded" onClick={(e) => e.stopPropagation()}>
                              <div className="client-notif-row">
                                <div className="client-notif-receiver-badge" title={`ID Cuenta: ${n.account_id}`}>
                                  <span>📥 Receptora:</span>
                                  <strong>{receiverLabel}</strong>
                                </div>
                                <span className="client-notif-time">
                                  🕒 {n.received_at?.slice(0, 16) || 'Reciente'}
                                </span>
                              </div>

                              <div className="client-notif-messages-container">
                                {parsedMsgs.length > 0 ? (
                                  parsedMsgs.map((msg, idx) => (
                                    <div key={idx} className="client-notif-sub-bubble">
                                      <span className="client-notif-msg-icon">💬</span>
                                      <span className="client-notif-msg-text">{msg}</span>
                                    </div>
                                  ))
                                ) : (
                                  <div className="client-notif-sub-bubble">
                                    <span className="client-notif-msg-icon">💬</span>
                                    <span className="client-notif-msg-text">{n.message_text}</span>
                                  </div>
                                )}
                              </div>

                              <div className="client-notif-footer" style={{ justifyContent: 'flex-end' }}>
                                <button
                                  className="client-notif-btn"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    resolveNotification(n.id);
                                  }}
                                >
                                  ✓ Marcar Atendido
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {notifications.length > 0 && (
                <div className="client-notif-card-footer">
                  <button
                    className="client-notif-all-btn"
                    onClick={resolveAllNotifications}
                  >
                    ✓ Marcar todo como atendido ({notifications.length})
                  </button>
                </div>
              )}
            </div>

            <div className="card">
              <div className="card-header">
                <h3>📋 Historial de Jobs</h3>
                <button className="btn btn-sm btn-secondary" onClick={fetchAll}>↻</button>
              </div>
              <div className="card-body no-pad">
                {jobs.length === 0 ? (
                  <div className="empty-state" style={{ padding: '30px 16px' }}>
                    <p>Sin trabajos aún</p>
                  </div>
                ) : (
                  <div className="jobs-list">
                    {jobs.map((job) => {
                      const sm = statusMeta(job.status);
                      const pct = job.total_contacts > 0
                        ? Math.round((job.sent_count / job.total_contacts) * 100)
                        : 0;
                      return (
                        <div key={job.id} className="job-item">
                          <div className="job-header">
                            <span className="job-id">Job #{job.id}</span>
                            <span className={`badge ${sm.cls}`}>{sm.icon} {sm.label}</span>
                          </div>
                          <div className="job-meta">
                            <span>⚙️ {job.profile_name || `Perfil #${job.profile_id}`}</span>
                            <span>📱 {JSON.parse(job.account_ids_json || '[]').length} ctas</span>
                            <span>👥 {job.total_contacts} contactos</span>
                          </div>
                          {/* Progress bar */}
                          <div className="job-progress-bar">
                            <div
                              className="job-progress-fill"
                              style={{ width: `${pct}%` }}
                            ></div>
                          </div>
                          <div className="job-stats">
                            <span className="stat-green">✅ {job.sent_count} enviados</span>
                            <span className="stat-red">❌ {job.error_count} errores</span>
                            <span className="stat-pct">{pct}%</span>
                          </div>
                          <div className="job-actions">
                            {job.status === 'running' && (
                              <button
                                className="btn btn-sm btn-warning"
                                onClick={() => updateJobStatus(job.id, 'paused')}
                              >
                                ⏸ Pausar
                              </button>
                            )}
                            {job.status === 'paused' && (
                              <button
                                className="btn btn-sm btn-success"
                                onClick={() => updateJobStatus(job.id, 'running')}
                              >
                                ▶ Reanudar
                              </button>
                            )}
                            {(job.status === 'completed' || job.status === 'paused' || job.status === 'error') && (
                              <button
                                className="btn btn-sm btn-danger"
                                onClick={() => confirmDeleteJob(job.id)}
                              >
                                🗑
                              </button>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════
          WIZARD — STEP 2: Contactos
      ═══════════════════════════════════════ */}
      {step === 2 && (
        <div className="automation-contacts-layout">

          <div className="card wizard-card-full">
            <div className="card-header">
              <h3>👥 Lista de Contactos</h3>
              <button className="btn btn-sm btn-secondary" onClick={() => setStep(1)}>
                ← Volver
              </button>
            </div>
            <div className="card-body">
              {profileInfo?.accounts_for_sending === 0 && (
                <div style={{
                  background: 'rgba(59, 130, 246, 0.15)',
                  border: '1px solid rgba(59, 130, 246, 0.4)',
                  color: '#60a5fa',
                  padding: '12px 16px',
                  borderRadius: '8px',
                  marginBottom: '16px',
                  fontSize: '0.9em',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  <span>💬</span>
                  <span><strong>Modo Solo Historial Activado:</strong> Cuentas para Envío Real está en 0. La automatización solo simulará historial entre cuentas amigas. La lista de contactos es opcional.</span>
                </div>
              )}

              {/* Format info */}
              <div className="contacts-format-box">
                <div className="format-title">📄 Formatos aceptados:</div>
                <div className="format-examples">
                  <div className="format-item">
                    <span className="format-label">Solo teléfono:</span>
                    <code>+5215512345678</code>
                  </div>
                  <div className="format-item">
                    <span className="format-label">CSV con variables:</span>
                    <code>+5215512345678,Juan,MiEmpresa</code>
                  </div>
                  <div className="format-item">
                    <span className="format-label">Las columnas extra se mapean a variables del mensaje en orden</span>
                  </div>
                </div>
              </div>

              {/* File upload */}
              <div className="file-drop-zone" onClick={() => fileInputRef.current.click()}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".txt,.csv"
                  style={{ display: 'none' }}
                  onChange={handleFileUpload}
                />
                <div className="file-drop-icon">📂</div>
                <div className="file-drop-text">
                  {contactsFile
                    ? `✅ ${contactsFile} cargado`
                    : 'Haz clic o arrastra un archivo .txt / .csv'}
                </div>
                <div className="file-drop-sub">O escribe / pega la lista directamente abajo</div>
              </div>

              {/* Manual input */}
              <div className="form-group">
                <label>Lista de contactos (un número por línea){profileInfo?.accounts_for_sending === 0 ? ' (Opcional)' : ''}:</label>
                <textarea
                  className="form-control contacts-textarea"
                  rows="12"
                  placeholder={`+5215512345678\n+5215598765432,María,Empresa ABC\n+5215511223344`}
                  value={contactsText}
                  onChange={(e) => setContactsText(e.target.value)}
                ></textarea>
              </div>

              {/* Count badge */}
              {parsedCount > 0 && (
                <div className="contacts-count-badge">
                  <span className="count-num">{parsedCount}</span>
                  <span className="count-lbl">contactos detectados y listos para enviar</span>
                </div>
              )}
            </div>
          </div>

          {/* Launch summary + button */}
          <div className="launch-summary-card card">
            <div className="card-header">
              <h3>📋 Resumen del Lanzamiento</h3>
            </div>
            <div className="card-body">
              <div className="launch-summary-items">
                <div className="ls-item">
                  <span className="ls-icon">⚙️</span>
                  <div>
                    <div className="ls-label">Perfil de Envío</div>
                    <div className="ls-val">{profileInfo?.name || `ID ${selectedProfile}`}</div>
                  </div>
                </div>

                {profileInfo && (
                  <>
                    <div className="ls-item">
                      <span className="ls-icon">📌</span>
                      <div>
                        <div className="ls-label">Campaña</div>
                        <div className="ls-val">
                          {profileInfo.campaign_name || 'Sin campaña asignada'}
                        </div>
                      </div>
                    </div>
                    <div className="ls-item">
                      <span className="ls-icon">⏱</span>
                      <div>
                        <div className="ls-label">Intervalo entre msgs</div>
                        <div className="ls-val">
                          {profileInfo.delay_min_sec}–{profileInfo.delay_max_sec} segundos
                        </div>
                      </div>
                    </div>
                    <div className="ls-item">
                      <span className="ls-icon">📦</span>
                      <div>
                        <div className="ls-label">Límite por sesión</div>
                        <div className="ls-val">{profileInfo.messages_per_session} mensajes</div>
                      </div>
                    </div>
                    <div className="ls-item">
                      <span className="ls-icon">😴</span>
                      <div>
                        <div className="ls-label">Reposo automático</div>
                        <div className="ls-val">{profileInfo.rest_time_minutes} minutos</div>
                      </div>
                    </div>
                  </>
                )}

                <div className="ls-item">
                  <span className="ls-icon">📱</span>
                  <div>
                    <div className="ls-label">Cuentas seleccionadas</div>
                    <div className="ls-val">
                      {selectedAccounts.length} cuenta(s): {selectedAccounts.join(', ')}
                    </div>
                  </div>
                </div>

                <div className="ls-item highlight">
                  <span className="ls-icon">👥</span>
                  <div>
                    <div className="ls-label">Total de contactos</div>
                    <div className="ls-val ls-big">{parsedCount}</div>
                  </div>
                </div>
              </div>

              <button
                className="btn btn-primary btn-block launch-btn"
                disabled={(profileInfo?.accounts_for_sending !== 0 && parsedCount === 0) || launching}
                onClick={handleLaunch}
              >
                {launching ? (
                  <>
                    <span className="spinner spinner-sm"></span>
                    Lanzando...
                  </>
                ) : (
                  <>🚀 Lanzar Automatización</>
                )}
              </button>

              <button
                className="btn btn-secondary btn-block"
                style={{ marginTop: '8px' }}
                onClick={() => setStep(1)}
              >
                ← Volver a configuración
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════
          STEP 3: Job lanzado — monitor
      ═══════════════════════════════════════ */}
      {step === 3 && (
        <div className="automation-monitor">
          <div className="monitor-banner">
            <div className="monitor-rocket">🚀</div>
            <h2>¡Automatización en marcha!</h2>
            <p>Los jobs están corriendo en segundo plano. Puedes monitorear el progreso aquí.</p>
            <button className="btn btn-secondary" onClick={() => setStep(1)}>
              + Lanzar otra automatización
            </button>
          </div>

          <div className="card">
            <div className="card-header">
              <h3>📊 Jobs Activos e Historial</h3>
              <button className="btn btn-sm btn-secondary" onClick={fetchAll}>↻ Actualizar</button>
            </div>
            <div className="card-body no-pad">
              {jobs.length === 0 ? (
                <div className="empty-state" style={{ padding: '40px' }}>
                  <p>No hay jobs registrados aún.</p>
                </div>
              ) : (
                <div className="jobs-table-wrapper">
                  <table className="custom-table">
                    <thead>
                      <tr>
                        <th>Job</th>
                        <th>Perfil</th>
                        <th>Cuentas</th>
                        <th>Progreso</th>
                        <th>Estado</th>
                        <th>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {jobs.map((job) => {
                        const sm = statusMeta(job.status);
                        const pct = job.total_contacts > 0
                          ? Math.round((job.sent_count / job.total_contacts) * 100)
                          : 0;
                        const accIds = (() => {
                          try { return JSON.parse(job.account_ids_json || '[]'); }
                          catch { return []; }
                        })();
                        return (
                          <tr key={job.id}>
                            <td>
                              <strong>#{job.id}</strong>
                              <div className="table-sub">{job.created_at?.slice(0, 16) || ''}</div>
                            </td>
                            <td>
                              <span>{job.profile_name || `#${job.profile_id}`}</span>
                              {job.campaign_name && (
                                <div className="table-sub">📌 {job.campaign_name}</div>
                              )}
                            </td>
                            <td>
                              <div className="acc-chips">
                                {accIds.map((a) => (
                                  <span key={a} className="acc-chip">{a}</span>
                                ))}
                              </div>
                            </td>
                            <td style={{ minWidth: '140px' }}>
                              <div className="inline-progress">
                                <div className="inline-bar">
                                  <div className="inline-fill" style={{ width: `${pct}%` }}></div>
                                </div>
                                <span className="inline-pct">{pct}%</span>
                              </div>
                              <div className="table-sub">
                                {job.sent_count}/{job.total_contacts} · {job.error_count} errores
                              </div>
                            </td>
                            <td>
                              <span className={`badge ${sm.cls}`}>{sm.icon} {sm.label}</span>
                            </td>
                            <td>
                              <div className="job-tbl-actions">
                                {job.status === 'running' && (
                                  <button className="btn btn-sm btn-warning"
                                    onClick={() => updateJobStatus(job.id, 'paused')}>
                                    ⏸
                                  </button>
                                )}
                                {job.status === 'paused' && (
                                  <button className="btn btn-sm btn-success"
                                    onClick={() => updateJobStatus(job.id, 'running')}>
                                    ▶
                                  </button>
                                )}
                                <button className="btn btn-sm btn-danger"
                                  onClick={() => confirmDeleteJob(job.id)}>
                                  🗑
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL: CONFIRMAR ELIMINACIÓN DE JOB ───────────── */}
      {deletingJobId && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header" style={{ borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
              <h2>⚠️ Confirmar Eliminación</h2>
              <button className="modal-close" onClick={() => setDeletingJobId(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🗑️</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Estás seguro de eliminar el registro de automatización?
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
                Job #{deletingJobId}
              </div>
              <p style={{ fontSize: '13px', color: 'var(--text-muted, #94a3b8)', marginBottom: '24px' }}>
                Esta acción eliminará el historial de este job de la base de datos.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  onClick={() => setDeletingJobId(null)}
                  style={{ flex: 1 }}
                >
                  Cancelar
                </button>
                <button 
                  type="button" 
                  className="btn btn-danger" 
                  onClick={executeDeleteJob}
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
