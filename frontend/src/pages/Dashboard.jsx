import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useToast } from '../hooks/useToast';
import { fetchAccounts } from '../store/accountsSlice';

export default function Dashboard({ activeTab }) {
  const dispatch = useDispatch();
  const { accounts, diskMetrics, loading } = useSelector((state) => state.accounts);
  const { addToast } = useToast();

  const handleRefresh = () => {
    dispatch(fetchAccounts());
  };

  // Derive stats directly from Redux accounts
  const counters = {
    total_registered: accounts.length,
    disponibles: accounts.filter(a => a.status_state === 'disponible').length,
    en_ejecucion: accounts.filter(a => a.is_active).length,
    enviando: accounts.filter(a => a.status_state === 'enviando').length,
    haciendo_historial: accounts.filter(a => a.status_state === 'haciendo_historial').length,
    restringidos: accounts.filter(a => a.status_state === 'restringido').length,
    bloqueados: accounts.filter(a => a.status_state === 'bloqueado').length,
  };

  const activeServices = accounts.filter(a => a.is_active);


  return (
    <div className="tab-pane active" id="tab-dashboard">
      <div className="page-header">
        <div>
          <h1>Dashboard de Operaciones</h1>
          <p className="subtitle">Monitoreo en tiempo real de cuentas y servicios de WhatsApp</p>
        </div>
        <button className="btn btn-secondary" onClick={handleRefresh} disabled={loading}>
          <svg className="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M23 4v6h-6"></path>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
          Actualizar
        </button>
      </div>

      {/* Metrics Grid */}
      <div className="metrics-grid">
        <div className="metric-card cyan">
          <div className="metric-header">
            <span className="metric-title">Total Registradas</span>
            <div className="metric-icon">📱</div>
          </div>
          <div className="metric-value">{counters.total_registered}</div>
          <div className="metric-sub">Cuentas en el sistema</div>
        </div>

        <div className="metric-card green">
          <div className="metric-header">
            <span className="metric-title">Disponibles</span>
            <div className="metric-icon">✅</div>
          </div>
          <div className="metric-value">{counters.disponibles}</div>
          <div className="metric-[#00e676]">Listas para operar</div>
        </div>

        <div className="metric-card blue">
          <div className="metric-header">
            <span className="metric-title">En Ejecución</span>
            <div className="metric-icon">🚀</div>
          </div>
          <div className="metric-value">{counters.en_ejecucion}</div>
          <div className="metric-sub">Instancias de navegador abiertas</div>
        </div>

        <div className="metric-card purple">
          <div className="metric-header">
            <span className="metric-title">Enviando</span>
            <div className="metric-icon">📤</div>
          </div>
          <div className="metric-value">{counters.enviando}</div>
          <div className="metric-sub">Enviando mensajes ahora</div>
        </div>

        <div className="metric-card yellow">
          <div className="metric-header">
            <span className="metric-title">Haciendo Historial</span>
            <div className="metric-icon">📜</div>
          </div>
          <div className="metric-value">{counters.haciendo_historial}</div>
          <div className="metric-sub">Calentamiento automático</div>
        </div>

        <div className="metric-card orange">
          <div className="metric-header">
            <span className="metric-title">Restringidos</span>
            <div className="metric-icon">⚠️</div>
          </div>
          <div className="metric-value">{counters.restringidos}</div>
          <div className="metric-sub">Límite temporal / En reposo</div>
        </div>

        <div className="metric-card red">
          <div className="metric-header">
            <span className="metric-title">Bloqueados</span>
            <div className="metric-icon">🚫</div>
          </div>
          <div className="metric-value">{counters.bloqueados}</div>
          <div className="metric-sub">Revisión o baneo</div>
        </div>
      </div>

      {/* Main Grid: Services Table + Storage Card */}
      <div className="dashboard-main-grid">
        <div className="card dashboard-card">
          <div className="card-header">
            <h3>⚡ Servicios WhatsApp en Ejecución</h3>
            <span className="badge badge-pulse">
              <span className="dot pulse"></span> {activeServices.length} Instancias Activas
            </span>
          </div>
          <div className="card-body">
            {activeServices.length === 0 ? (
              <div className="empty-state">
                <p>No hay instancias de WhatsApp en ejecución actualmente.</p>
              </div>
            ) : (
              <div className="table-responsive">
                <table className="custom-table">
                  <thead>
                    <tr>
                      <th>Cuenta / ID</th>
                      <th>Estado Actual</th>
                      <th>Tamaño Sesión</th>
                      <th>Última Actividad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeServices.map((srv) => {
                      let badgeClass = 'badge-available';
                      let statusText = srv.status_state;
                      if (srv.status_state === 'enviando') {
                        badgeClass = 'badge-active';
                        statusText = 'Enviando Mensajes';
                      } else if (srv.status_state === 'haciendo_historial') {
                        badgeClass = 'badge-history';
                        statusText = 'Haciendo Historial';
                      } else if (srv.status_state === 'disponible') {
                        badgeClass = 'badge-available';
                        statusText = 'Instancia Abierta';
                      }

                      return (
                        <tr key={srv.account_id}>
                          <td>
                            <strong>{srv.account_id}</strong>
                          </td>
                          <td>
                            <span className={`badge ${badgeClass}`}>{statusText}</span>
                          </td>
                          <td>{srv.size_mb ? `${srv.size_mb} MB` : 'N/A'}</td>
                          <td>{srv.last_modified || 'Hace un momento'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Disk & Metrics Widget */}
        <div className="card storage-card">
          <div className="card-header">
            <h3>💾 Almacenamiento de Sesiones</h3>
          </div>
          <div className="card-body">
            <div className="storage-info">
              <span className="storage-amount">{diskMetrics.formatted}</span>
              <span className="storage-label">Espacio total ocupado por perfiles Playwright</span>
            </div>
            <div className="storage-progress-bar">
              <div
                className="storage-fill"
                style={{ width: `${Math.min(100, (diskMetrics.total_mb / 500) * 100)}%` }}
              ></div>
            </div>
            <div className="storage-meta">
              <span>{counters.total_registered} perfiles guardados</span>
              <span>Límite aprox: 500 MB</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
