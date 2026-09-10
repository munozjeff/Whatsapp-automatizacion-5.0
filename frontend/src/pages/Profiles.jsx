import React, { useState, useEffect } from 'react';
import { useToast } from '../hooks/useToast';

export default function Profiles({ activeTab }) {
  const [profiles, setProfiles] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingProfileId, setEditingProfileId] = useState(null);
  const [deletingProfile, setDeletingProfile] = useState(null);

  // Form state
  const [form, setForm] = useState({
    name: '',
    campaign_id: '',
    delay_min_sec: 15,
    delay_max_sec: 45,
    messages_per_session: 50,
    messages_per_interval: 2,
    rest_time_minutes: 30,
    accounts_for_sending: 5,
    accounts_for_history: 5,
    history_msgs_per_turn: 2,
    auto_reply_enabled: 0,
    auto_reply_message: '',
  });

  const { addToast } = useToast();

  const fetchAll = async () => {
    try {
      const [pRes, cRes] = await Promise.all([
        fetch('/api/send_profiles'),
        fetch('/api/campaigns'),
      ]);
      const pData = await pRes.json();
      const cData = await cRes.json();

      if (pData.status === 'success') setProfiles(pData.profiles || []);
      if (cData.status === 'success') setCampaigns(cData.campaigns || []);
    } catch (err) {
      console.error('Error cargando perfiles:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'profiles') {
      fetchAll();
    }
  }, [activeTab]);

  const openModal = (profileToEdit = null) => {
    if (profileToEdit) {
      setEditingProfileId(profileToEdit.id);
      setForm({
        name: profileToEdit.name || '',
        campaign_id: profileToEdit.campaign_id || '',
        delay_min_sec: profileToEdit.delay_min_sec || 15,
        delay_max_sec: profileToEdit.delay_max_sec || 45,
        messages_per_session: profileToEdit.messages_per_session || 50,
        messages_per_interval: profileToEdit.messages_per_interval || 2,
        rest_time_minutes: profileToEdit.rest_time_minutes || 30,
        accounts_for_sending: profileToEdit.accounts_for_sending ?? 5,
        accounts_for_history: profileToEdit.accounts_for_history ?? 5,
        history_msgs_per_turn: profileToEdit.history_msgs_per_turn || 2,
        auto_reply_enabled: profileToEdit.auto_reply_enabled ? 1 : 0,
        auto_reply_message: profileToEdit.auto_reply_message || '',
      });
    } else {
      setEditingProfileId(null);
      setForm({
        name: '',
        campaign_id: '',
        delay_min_sec: 15,
        delay_max_sec: 45,
        messages_per_session: 50,
        messages_per_interval: 2,
        rest_time_minutes: 30,
        accounts_for_sending: 5,
        accounts_for_history: 5,
        history_msgs_per_turn: 2,
        auto_reply_enabled: 0,
        auto_reply_message: '',
      });
    }
    setShowModal(true);
  };

  const handleFormChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? (checked ? 1 : 0) : type === 'number' ? Number(value) : value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) {
      addToast('El nombre del perfil es obligatorio.', 'error');
      return;
    }
    if (form.delay_min_sec >= form.delay_max_sec) {
      addToast('El tiempo mínimo debe ser menor que el máximo.', 'error');
      return;
    }
    if (form.accounts_for_sending === 0 && form.accounts_for_history === 0) {
      addToast('Cuentas por tanda para Envío Real y para Historial no pueden ser 0 al mismo tiempo.', 'error');
      return;
    }
    if (form.accounts_for_sending < 0 || form.accounts_for_history < 0) {
      addToast('La cantidad de cuentas no puede ser negativa.', 'error');
      return;
    }
    if (form.auto_reply_enabled && !form.auto_reply_message.trim()) {
      addToast('Si activas la autorespuesta, debes escribir un mensaje de respuesta.', 'error');
      return;
    }

    try {
      const url = editingProfileId ? `/api/send_profiles/${editingProfileId}` : '/api/send_profiles';
      const method = editingProfileId ? 'PUT' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setShowModal(false);
        fetchAll();
      } else {
        addToast(data.message, 'error');
      }
    } catch (err) {
      addToast('Error al guardar el perfil de envío.', 'error');
    }
  };

  const confirmDelete = (prof) => {
    setDeletingProfile(prof);
  };

  const executeDelete = async () => {
    if (!deletingProfile) return;
    try {
      const res = await fetch(`/api/send_profiles/${deletingProfile.id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setDeletingProfile(null);
        fetchAll();
      } else {
        addToast(data.message || 'Error al eliminar el perfil.', 'error');
      }
    } catch (err) {
      addToast('Error al eliminar el perfil.', 'error');
    }
  };

  const getCampaignName = (id) => {
    if (!id) return 'Sin campaña asignada';
    const found = campaigns.find((c) => c.id === parseInt(id));
    return found ? found.name : `Campaña #${id}`;
  };

  return (
    <div className="tab-pane active" id="tab-profiles">
      <div className="page-header">
        <div>
          <h1>Perfiles de Envío</h1>
          <p className="subtitle">
            Configura la velocidad, cantidad de mensajes y el comportamiento de cada instancia de envío
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => openModal()}>
          <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          Nuevo Perfil
        </button>
      </div>

      {profiles.length === 0 ? (
        <div className="card empty-card">
          <div className="empty-state">
            <span className="empty-icon">⚙️</span>
            <h3>Sin perfiles de envío</h3>
            <p>Define cómo se comportará cada instancia al enviar mensajes.</p>
            <button className="btn btn-primary btn-sm" onClick={() => openModal()}>
              Crear primer perfil
            </button>
          </div>
        </div>
      ) : (
        <div className="profiles-grid">
          {profiles.map((prof) => (
            <div key={prof.id} className="profile-card">
              <div className="profile-card-header">
                <div className="profile-icon">⚙️</div>
                <div>
                  <h3 className="profile-name">{prof.name}</h3>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: '4px', flexWrap: 'wrap' }}>
                    <span className="profile-campaign">📌 {getCampaignName(prof.campaign_id)}</span>
                    {prof.accounts_for_sending === 0 ? (
                      <span className="badge badge-restricted" style={{ fontSize: '0.75rem' }}>💬 Solo Historial</span>
                    ) : prof.accounts_for_history === 0 ? (
                      <span className="badge badge-available" style={{ fontSize: '0.75rem' }}>📢 Solo Envío Real</span>
                    ) : (
                      <span className="badge badge-history" style={{ fontSize: '0.75rem' }}>🔄 Multi ({prof.accounts_for_sending}E / {prof.accounts_for_history}H)</span>
                    )}
                    {Boolean(prof.auto_reply_enabled) && (
                      <span className="badge badge-available" style={{ fontSize: '0.75rem', backgroundColor: 'rgba(16, 185, 129, 0.2)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.4)' }}>
                        🤖 Autorespuesta Activa
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="profile-metrics">
                <div className="profile-metric">
                  <div className="metric-ico">⏱️</div>
                  <div className="metric-data">
                    <span className="metric-num">
                      {prof.delay_min_sec}–{prof.delay_max_sec}s
                    </span>
                    <span className="metric-lbl">Intervalo entre mensajes</span>
                  </div>
                </div>

                <div className="profile-metric">
                  <div className="metric-ico">📦</div>
                  <div className="metric-data">
                    <span className="metric-num">{prof.messages_per_session}</span>
                    <span className="metric-lbl">Mensajes por sesión</span>
                  </div>
                </div>

                <div className="profile-metric">
                  <div className="metric-ico">🔁</div>
                  <div className="metric-data">
                    <span className="metric-num">{prof.messages_per_interval}</span>
                    <span className="metric-lbl">Mensajes por ráfaga</span>
                  </div>
                </div>

                <div className="profile-metric">
                  <div className="metric-ico">😴</div>
                  <div className="metric-data">
                    <span className="metric-num">{prof.rest_time_minutes} min</span>
                    <span className="metric-lbl">Tiempo de reposo</span>
                  </div>
                </div>
              </div>

              {Boolean(prof.auto_reply_enabled) && (
                <div style={{ marginTop: '12px', padding: '10px', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px dashed rgba(255,255,255,0.1)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted, #94a3b8)', fontWeight: '600', marginBottom: '4px' }}>
                    💬 Autorespuesta a Clientes:
                  </div>
                  <div style={{ fontSize: '0.85rem', fontStyle: 'italic', color: '#e2e8f0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    "{prof.auto_reply_message}"
                  </div>
                </div>
              )}

              <div className="profile-footer">
                <span className="meta-text">ID #{prof.id}</span>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => openModal(prof)}
                  >
                    ✏️ Editar
                  </button>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => confirmDelete(prof)}
                  >
                    🗑️ Eliminar
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ===== MODAL CREAR / EDITAR PERFIL ===== */}
      {showModal && (
        <div className="modal-backdrop">
          <div className="modal modal-lg">
            <div className="modal-header">
              <h2>⚙️ {editingProfileId ? 'Editar Perfil de Envío' : 'Crear Perfil de Envío'}</h2>
              <button className="modal-close" onClick={() => setShowModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleSubmit}>
                {/* Nombre y campaña */}
                <div className="form-row-2">
                  <div className="form-group">
                    <label>Nombre del Perfil:</label>
                    <input
                      type="text"
                      name="name"
                      className="form-control"
                      placeholder="Ej: Envío lento con reposo"
                      value={form.name}
                      onChange={handleFormChange}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>Campaña Asociada:</label>
                    <select
                      name="campaign_id"
                      className="form-control"
                      value={form.campaign_id}
                      onChange={handleFormChange}
                    >
                      <option value="">-- Sin campaña asignada --</option>
                      {campaigns.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} ({c.type === 'dinamica' ? '⚡ Dinámica' : '📌 Estática'})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Tiempo entre mensajes */}
                <div className="form-section">
                  <h4 className="form-section-title">⏱️ Tiempo Entre Mensajes</h4>
                  <div className="form-row-2">
                    <div className="form-group">
                      <label>Mínimo (segundos):</label>
                      <input
                        type="number"
                        name="delay_min_sec"
                        className="form-control"
                        min="5"
                        max="300"
                        value={form.delay_min_sec}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Mínimo 5 seg para evitar ban</small>
                    </div>
                    <div className="form-group">
                      <label>Máximo (segundos):</label>
                      <input
                        type="number"
                        name="delay_max_sec"
                        className="form-control"
                        min="10"
                        max="600"
                        value={form.delay_max_sec}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Variación aleatoria para parecer humano</small>
                    </div>
                  </div>
                </div>

                {/* Límites de mensajes */}
                <div className="form-section">
                  <h4 className="form-section-title">📦 Cantidad de Mensajes</h4>
                  <div className="form-row-2">
                    <div className="form-group">
                      <label>Límite por sesión:</label>
                      <input
                        type="number"
                        name="messages_per_session"
                        className="form-control"
                        min="1"
                        max="500"
                        value={form.messages_per_session}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Total de mensajes que enviará esta instancia antes de detenerse</small>
                    </div>
                    <div className="form-group">
                      <label>Mensajes por ráfaga:</label>
                      <input
                        type="number"
                        name="messages_per_interval"
                        className="form-control"
                        min="1"
                        max="20"
                        value={form.messages_per_interval}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Cuántos envía cada vez que le toca (sin contar respuestas)</small>
                    </div>
                  </div>
                </div>

                {/* Tandas de Envío Real y Hacer Historial */}
                <div className="form-section">
                  <h4 className="form-section-title">🔄 Tandas Multitarea (Envío Real vs. Hacer Historial)</h4>
                  <div className="form-row-2">
                    <div className="form-group">
                      <label>Cuentas por tanda para Envío Real:</label>
                      <input
                        type="number"
                        name="accounts_for_sending"
                        className="form-control"
                        min="0"
                        max="100"
                        value={form.accounts_for_sending ?? 0}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Si se coloca 0, NO se enviará a lista real (Solo Historial)</small>
                    </div>
                    <div className="form-group">
                      <label>Cuentas por tanda para Hacer Historial:</label>
                      <input
                        type="number"
                        name="accounts_for_history"
                        className="form-control"
                        min="0"
                        max="100"
                        value={form.accounts_for_history ?? 0}
                        onChange={handleFormChange}
                      />
                      <small className="form-text">Si se coloca 0, NO se simulará historial (Solo Envío Real)</small>
                    </div>
                  </div>
                  <div className="form-group" style={{ marginTop: '12px', maxWidth: '300px' }}>
                    <label>Mensajes de historial por turno:</label>
                    <input
                      type="number"
                      name="history_msgs_per_turn"
                      className="form-control"
                      min="1"
                      max="10"
                      value={form.history_msgs_per_turn || 2}
                      onChange={handleFormChange}
                    />
                    <small className="form-text">Interacciones cruzadas enviadas entre cuentas amigas</small>
                  </div>
                </div>

                {/* Reposo */}
                <div className="form-section">
                  <h4 className="form-section-title">😴 Reposo Mínimo Entre Turnos</h4>
                  <div className="form-group">
                    <label>Tiempo de reposo mínimo (minutos):</label>
                    <input
                      type="number"
                      name="rest_time_minutes"
                      className="form-control"
                      min="1"
                      max="1440"
                      value={form.rest_time_minutes}
                      onChange={handleFormChange}
                      style={{ maxWidth: '300px' }}
                    />
                    <small className="form-text">
                      ⏱️ Tiempo mínimo que descansa cada cuenta de WhatsApp antes de repetir turno. La cuenta esperará a que hayan pasado todas las demás cuentas disponibles Y a que transcurra este descanso mínimo.
                    </small>
                  </div>
                </div>

                {/* Autorespuesta */}
                <div className="form-section">
                  <h4 className="form-section-title">🤖 Autorespuesta Automática (Clientes Exclusivos)</h4>
                  <div className="form-group" style={{ marginBottom: '12px' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontWeight: '600' }}>
                      <input
                        type="checkbox"
                        name="auto_reply_enabled"
                        checked={Boolean(form.auto_reply_enabled)}
                        onChange={handleFormChange}
                        style={{ width: '18px', height: '18px', accentColor: 'var(--primary-color, #6366f1)' }}
                      />
                      Habilitar Autorespuesta para mensajes de nuevos clientes
                    </label>
                    <small className="form-text" style={{ marginTop: '4px' }}>
                      💡 Si está activo, cuando una cuenta detecte un mensaje de un cliente nuevo se enviará la autorespuesta. Se omite para cuentas del sistema e historial.
                    </small>
                  </div>

                  {Boolean(form.auto_reply_enabled) && (
                    <div className="form-group">
                      <label>Mensaje de Autorespuesta:</label>
                      <textarea
                        name="auto_reply_message"
                        className="form-control"
                        rows="3"
                        placeholder="Ej: ¡Hola! Gracias por escribirnos. Un asesor responderá a la brevedad..."
                        value={form.auto_reply_message}
                        onChange={handleFormChange}
                        required={Boolean(form.auto_reply_enabled)}
                      />
                    </div>
                  )}
                </div>

                {/* Summary box */}
                <div className="profile-summary-box">
                  <h4>📋 Resumen del Perfil</h4>
                  <div className="summary-grid">
                    <div className="summary-item">
                      <span className="s-label">Intervalo:</span>
                      <span className="s-val">
                        {form.delay_min_sec}–{form.delay_max_sec} seg
                      </span>
                    </div>
                    <div className="summary-item">
                      <span className="s-label">Límite sesión:</span>
                      <span className="s-val">{form.messages_per_session} msgs</span>
                    </div>
                    <div className="summary-item">
                      <span className="s-label">Por ráfaga:</span>
                      <span className="s-val">{form.messages_per_interval} msgs</span>
                    </div>
                    <div className="summary-item">
                      <span className="s-label">Reposo:</span>
                      <span className="s-val">{form.rest_time_minutes} min</span>
                    </div>
                    <div className="summary-item">
                      <span className="s-label">Tanda Envío:</span>
                      <span className="s-val">{form.accounts_for_sending ?? 0} ctas</span>
                    </div>
                    <div className="summary-item">
                      <span className="s-label">Tanda Historial:</span>
                      <span className="s-val">{form.accounts_for_history ?? 0} ctas</span>
                    </div>
                  </div>
                </div>

                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowModal(false)}
                  >
                    Cancelar
                  </button>
                  <button type="submit" className="btn btn-primary">
                    💾 Guardar Perfil
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ===== MODAL CONFIRMAR ELIMINACIÓN DE PERFIL ===== */}
      {deletingProfile && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header" style={{ borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
              <h2>⚠️ Confirmar Eliminación</h2>
              <button className="modal-close" onClick={() => setDeletingProfile(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🗑️</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Estás seguro de eliminar el perfil de envío?
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
                "{deletingProfile.name}"
              </div>
              <p style={{ fontSize: '13px', color: 'var(--text-muted, #94a3b8)', marginBottom: '24px' }}>
                Esta acción eliminará la configuración del perfil permanentemente.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  onClick={() => setDeletingProfile(null)}
                  style={{ flex: 1 }}
                >
                  Cancelar
                </button>
                <button 
                  type="button" 
                  className="btn btn-danger" 
                  onClick={executeDelete}
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
