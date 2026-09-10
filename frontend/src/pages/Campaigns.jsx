import React, { useState, useEffect } from 'react';
import { useToast } from '../hooks/useToast';

function detectVars(text) {
  if (!text) return [];
  const matches = text.match(/\{(\w+)\}/g) || [];
  return [...new Set(matches)];
}

export default function Campaigns({ activeTab }) {
  const [campaigns, setCampaigns] = useState([]);
  const [loading, setLoading] = useState(true);

  // Form state
  const [showModal, setShowModal] = useState(false);
  const [deletingCampaign, setDeletingCampaign] = useState(null);
  const [name, setName] = useState('');
  const [type, setType] = useState('estatica');
  const [templateMessage, setTemplateMessage] = useState('');
  const [detectedVars, setDetectedVars] = useState([]);

  const { addToast } = useToast();

  const fetchCampaigns = async () => {
    try {
      const res = await fetch('/api/campaigns');
      const data = await res.json();
      if (data.status === 'success') {
        setCampaigns(data.campaigns || []);
      }
    } catch (err) {
      console.error('Error cargando campañas:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'campaigns') {
      fetchCampaigns();
    }
  }, [activeTab]);

  const handleMessageChange = (val) => {
    setTemplateMessage(val);
    const vars = detectVars(val);
    setDetectedVars(vars);
    if (vars.length > 0 && type === 'estatica') {
      setType('dinamica');
    }
  };

  const openModal = () => {
    setName('');
    setType('estatica');
    setTemplateMessage('');
    setDetectedVars([]);
    setShowModal(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim() || !templateMessage.trim()) {
      addToast('Nombre y mensaje son obligatorios.', 'error');
      return;
    }

    try {
      const res = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, type, template_message: templateMessage }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setShowModal(false);
        fetchCampaigns();
      } else {
        addToast(data.message, 'error');
      }
    } catch (err) {
      addToast('Error al crear la campaña.', 'error');
    }
  };

  const confirmDelete = (camp) => {
    setDeletingCampaign(camp);
  };

  const executeDelete = async () => {
    if (!deletingCampaign) return;
    try {
      const res = await fetch(`/api/campaigns/${deletingCampaign.id}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.status === 'success') {
        addToast(data.message, 'success');
        setDeletingCampaign(null);
        fetchCampaigns();
      } else {
        addToast(data.message || 'Error al eliminar la campaña.', 'error');
      }
    } catch (err) {
      addToast('Error al eliminar la campaña.', 'error');
    }
  };

  // Render message with highlighted variables
  const renderHighlighted = (text) => {
    if (!text) return '';
    const parts = text.split(/(\{\w+\})/g);
    return parts.map((part, i) => {
      if (/^\{\w+\}$/.test(part)) {
        return (
          <span key={i} className="var-highlight">
            {part}
          </span>
        );
      }
      return <span key={i}>{part}</span>;
    });
  };

  return (
    <div className="tab-pane active" id="tab-campaigns">
      <div className="page-header">
        <div>
          <h1>Gestión de Campañas de WhatsApp</h1>
          <p className="subtitle">
            Crea mensajes estáticos o dinámicos con variables como{' '}
            <code className="var-badge">{'{nombre}'}</code>
          </p>
        </div>
        <button className="btn btn-primary" onClick={openModal}>
          <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          Nueva Campaña
        </button>
      </div>

      {campaigns.length === 0 ? (
        <div className="card empty-card">
          <div className="empty-state">
            <span className="empty-icon">💬</span>
            <h3>Sin campañas creadas</h3>
            <p>Crea tu primera campaña para empezar a enviar mensajes masivos.</p>
            <button className="btn btn-primary btn-sm" onClick={openModal}>
              Crear primera campaña
            </button>
          </div>
        </div>
      ) : (
        <div className="campaigns-grid">
          {campaigns.map((camp) => {
            const vars = camp.variables ? (typeof camp.variables === 'string' ? JSON.parse(camp.variables) : camp.variables) : [];
            return (
              <div key={camp.id} className="campaign-card">
                <div className="campaign-card-header">
                  <div className="campaign-title-row">
                    <h3>{camp.name}</h3>
                    <div className="campaign-badges">
                      <span className={`badge ${camp.type === 'dinamica' ? 'badge-dynamic' : 'badge-static'}`}>
                        {camp.type === 'dinamica' ? '⚡ Dinámica' : '📌 Estática'}
                      </span>
                    </div>
                  </div>
                  {vars.length > 0 && (
                    <div className="vars-row">
                      {vars.map((v) => (
                        <span key={v} className="var-badge">{`{${v}}`}</span>
                      ))}
                    </div>
                  )}
                </div>

                {/* WhatsApp bubble preview */}
                <div className="wa-preview">
                  <div className="wa-bubble">
                    <div className="wa-text">{renderHighlighted(camp.template_message)}</div>
                    <div className="wa-meta">
                      <span>Ahora</span>
                      <svg className="wa-check" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M20.285 2l-11.285 11.567-5.286-5.011-3.714 3.716 9 8.728 15-15.285z" />
                      </svg>
                    </div>
                  </div>
                </div>

                <div className="campaign-footer">
                  <span className="meta-text">ID #{camp.id}</span>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => confirmDelete(camp)}
                  >
                    🗑️ Eliminar
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ===== MODAL CREAR CAMPAÑA ===== */}
      {showModal && (
        <div className="modal-backdrop">
          <div className="modal modal-lg">
            <div className="modal-header">
              <h2>💬 Crear Nueva Campaña</h2>
              <button className="modal-close" onClick={() => setShowModal(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <form onSubmit={handleSubmit} className="campaign-form">
                <div className="form-row-2">
                  <div className="form-group">
                    <label>Nombre de la Campaña:</label>
                    <input
                      type="text"
                      className="form-control"
                      placeholder="Ej: Promo Diciembre 2024"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>Tipo:</label>
                    <select
                      className="form-control"
                      value={type}
                      onChange={(e) => setType(e.target.value)}
                    >
                      <option value="estatica">📌 Estática (texto fijo)</option>
                      <option value="dinamica">⚡ Dinámica (con variables)</option>
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <label>
                    Mensaje Plantilla:
                    {type === 'dinamica' && (
                      <small className="form-hint">
                        {' '}Usa{' '}
                        <code>{'{nombre}'}</code>
                        {', '}
                        <code>{'{empresa}'}</code> etc. para variables dinámicas
                      </small>
                    )}
                  </label>
                  <textarea
                    className="form-control"
                    rows="5"
                    placeholder={
                      type === 'dinamica'
                        ? 'Hola {nombre}, te ofrecemos una promoción especial de {empresa}...'
                        : 'Escribe tu mensaje de campaña aquí...'
                    }
                    value={templateMessage}
                    onChange={(e) => handleMessageChange(e.target.value)}
                    required
                  ></textarea>
                </div>

                {/* Live variable detection */}
                {detectedVars.length > 0 && (
                  <div className="vars-detected">
                    <span className="vars-label">Variables detectadas:</span>
                    {detectedVars.map((v) => (
                      <span key={v} className="var-badge">
                        {`{${v}}`}
                      </span>
                    ))}
                  </div>
                )}

                {/* Preview */}
                {templateMessage && (
                  <div className="form-group">
                    <label>Vista Previa (burbuja WhatsApp):</label>
                    <div className="wa-preview-form">
                      <div className="wa-bubble-form">
                        <div className="wa-text">{renderHighlighted(templateMessage)}</div>
                        <div className="wa-meta">
                          <span>Ahora</span>
                          <svg className="wa-check" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M20.285 2l-11.285 11.567-5.286-5.011-3.714 3.716 9 8.728 15-15.285z" />
                          </svg>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <div className="modal-footer">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setShowModal(false)}
                  >
                    Cancelar
                  </button>
                  <button type="submit" className="btn btn-primary">
                    💾 Crear Campaña
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ===== MODAL CONFIRMAR ELIMINACIÓN DE CAMPAÑA ===== */}
      {deletingCampaign && (
        <div className="modal-backdrop" style={{ animation: 'fadeIn 0.2s ease-out' }}>
          <div className="modal" style={{ maxWidth: '420px', borderRadius: '12px' }}>
            <div className="modal-header" style={{ borderBottom: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
              <h2>⚠️ Confirmar Eliminación</h2>
              <button className="modal-close" onClick={() => setDeletingCampaign(null)}>
                ✕
              </button>
            </div>
            <div className="modal-body" style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '16px' }}>🗑️</div>
              <p style={{ fontSize: '16px', marginBottom: '12px', fontWeight: '500' }}>
                ¿Estás seguro de eliminar la campaña?
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
                "{deletingCampaign.name}"
              </div>
              <p style={{ fontSize: '13px', color: 'var(--text-muted, #94a3b8)', marginBottom: '24px' }}>
                Esta acción eliminará la plantilla de mensaje de esta campaña.
              </p>
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'center' }}>
                <button 
                  type="button" 
                  className="btn btn-secondary" 
                  onClick={() => setDeletingCampaign(null)}
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
