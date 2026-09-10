/* =============================================
   WA PLATFORM v5.0 — FRONTEND JS
   ============================================= */

'use strict';

// ==================== STATE ====================
let activeTab      = 'tab-dashboard';
let activeAccountForSend = null;
let qrPollInterval = null;
let dashInterval   = null;

// ==================== INIT ====================
document.addEventListener('DOMContentLoaded', () => {
    initTabNavigation();
    initModalListeners();
    initCampaignListeners();
    initProfileListeners();
    initSendMsgListeners();

    // Initial data load
    fetchDashboard();
    fetchAccounts();
    fetchCampaigns();
    fetchSendProfiles();

    // Live polling — only active tab
    dashInterval = setInterval(() => {
        if (activeTab === 'tab-dashboard') fetchDashboard();
        if (activeTab === 'tab-accounts')  fetchAccounts();
    }, 4000);
});

// ==================== TAB NAVIGATION ====================
function initTabNavigation() {
    const navBtns  = document.querySelectorAll('.nav-item');
    const tabPanes = document.querySelectorAll('.tab-pane');

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-tab');
            if (targetId === activeTab) return;

            // Remove active states
            navBtns.forEach(b => b.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            document.getElementById(targetId).classList.add('active');
            activeTab = targetId;

            // Trigger data load per tab
            if (targetId === 'tab-dashboard')    fetchDashboard();
            if (targetId === 'tab-accounts')     fetchAccounts();
            if (targetId === 'tab-campaigns')    fetchCampaigns();
            if (targetId === 'tab-send-profiles') fetchSendProfiles();
        });
    });
}

// ==================== TOAST NOTIFICATIONS ====================
function showToast(message, type = 'info', duration = 3500) {
    const icons = {
        success: 'fa-circle-check',
        error:   'fa-circle-xmark',
        info:    'fa-circle-info',
        warning: 'fa-triangle-exclamation',
    };

    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i><span>${message}</span>`;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 350);
    }, duration);
}

// ==================== API HELPERS ====================
async function apiGet(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function apiPost(url, body = {}) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return res.json();
}

async function apiDelete(url) {
    const res = await fetch(url, { method: 'DELETE' });
    return res.json();
}

// ==================== DASHBOARD ====================
async function fetchDashboard() {
    try {
        const data = await apiGet('/api/dashboard/stats');
        if (data.status !== 'success') return;

        const c = data.counters;
        setVal('dash-total',       c.total_registered  || 0);
        setVal('dash-disponibles', c.disponibles       || 0);
        setVal('dash-ejecucion',   c.en_ejecucion      || 0);
        setVal('dash-enviando',    c.enviando          || 0);
        setVal('dash-historial',   c.haciendo_historial|| 0);
        setVal('dash-restringidas',c.restringidos      || 0);
        setVal('dash-bloqueadas',  c.bloqueados        || 0);

        // Disk info
        const dm = data.disk_metrics;
        if (dm) {
            const diskEl = document.getElementById('dash-disk-info');
            if (diskEl) {
                diskEl.innerHTML = `<i class="fa-solid fa-hard-drive"></i> ${dm.total_mb || '0'} MB en ${dm.count || 0} perfiles`;
            }
        }

        renderActiveServicesTable(data.active_services || []);
    } catch (err) {
        console.warn('Dashboard fetch error:', err);
    }
}

function setVal(id, val) {
    const el = document.getElementById(id);
    if (el && el.textContent !== String(val)) el.textContent = val;
}

function renderActiveServicesTable(services) {
    const tbody = document.getElementById('tbl-active-body');
    if (!tbody) return;

    if (!services.length) {
        tbody.innerHTML = `
            <tr><td colspan="5" class="empty-cell">
                <i class="fa-solid fa-moon"></i>
                No hay instancias en ejecución en este momento
            </td></tr>
        `;
        return;
    }

    tbody.innerHTML = services.map(s => {
        const badgeClass = stateToClass(s.status_state);
        const stateLabel = stateToLabel(s.status_state);
        return `
            <tr>
                <td><strong>${escHtml(s.account_id)}</strong></td>
                <td><span class="badge ${badgeClass}">${stateLabel}</span></td>
                <td>${s.size_mb || '—'} MB</td>
                <td style="font-size:12px;color:var(--text-muted);">${s.last_modified || '—'}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="closeAccount('${escHtml(s.account_id)}')">
                        <i class="fa-solid fa-stop"></i> Detener
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function stateToClass(state) {
    const map = {
        enviando:          'badge-green',
        haciendo_historial:'badge-purple',
        disponible:        'badge-blue',
        restringido:       'badge-yellow',
        bloqueado:         'badge-red',
    };
    return map[state] || 'badge-gray';
}

function stateToLabel(state) {
    const map = {
        enviando:          '📤 Enviando',
        haciendo_historial:'💬 Historial',
        disponible:        '✅ Disponible',
        restringido:       '⚠️ Restringida',
        bloqueado:         '🚫 Bloqueada',
    };
    return map[state] || state;
}

// ==================== ACCOUNTS ====================
async function fetchAccounts() {
    try {
        const data = await apiGet('/api/accounts');
        if (data.status === 'success') renderAccounts(data.accounts || []);
    } catch (err) {
        console.warn('Accounts fetch error:', err);
    }
}

function renderAccounts(accounts) {
    const container = document.getElementById('accounts-container');
    if (!container) return;

    if (!accounts.length) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-folder-open"></i>
                <p>No tienes cuentas registradas aún.<br>Presiona <strong>Agregar Cuenta</strong> para comenzar.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = accounts.map(acc => buildAccountCard(acc)).join('');
}

function buildAccountCard(acc) {
    const isActive = acc.is_active;
    const state    = acc.status_state || 'disponible';
    const sizeDisplay = acc.size_mb >= 1 ? `${acc.size_mb} MB` : (acc.size_kb ? `${acc.size_kb} KB` : '—');

    let statusBadge = '';
    if (isActive) {
        statusBadge = `<span class="badge badge-green"><i class="fa-solid fa-circle" style="font-size:7px;"></i> Activa en pantalla</span>`;
    } else if (acc.pending_qr && acc.pending_qr.status === 'waiting_qr') {
        statusBadge = `<span class="badge badge-yellow"><i class="fa-solid fa-qrcode"></i> Esperando QR...</span>`;
    } else {
        statusBadge = `<span class="badge badge-blue"><i class="fa-solid fa-cloud"></i> En disco</span>`;
    }

    const actionBtns = isActive ? `
        <button class="btn btn-secondary btn-sm" onclick="closeAccount('${acc.account_id}')">
            <i class="fa-solid fa-stop"></i> Cerrar Instancia
        </button>
        <button class="btn btn-primary btn-sm" onclick="showSendModal('${acc.account_id}')">
            <i class="fa-solid fa-paper-plane"></i> Probar Envío
        </button>
    ` : `
        <button class="btn btn-primary btn-sm" onclick="openAccount('${acc.account_id}')">
            <i class="fa-solid fa-play"></i> Abrir Sesión
        </button>
    `;

    return `
        <div class="account-card ${isActive ? 'is-active' : ''}">
            <div class="acc-header">
                <div class="acc-title">
                    <div class="acc-avatar">
                        <i class="fa-brands fa-whatsapp"></i>
                    </div>
                    <div>
                        <div class="acc-name">${escHtml(acc.account_id)}</div>
                        <div class="acc-sub">Estado DB: ${stateToLabel(state)}</div>
                    </div>
                </div>
                <span class="acc-size"><i class="fa-solid fa-hard-drive"></i> ${sizeDisplay}</span>
            </div>

            <div>${statusBadge}</div>

            <div class="acc-actions">
                ${actionBtns}
                <button class="btn btn-danger btn-sm" onclick="deleteAccount('${acc.account_id}')" title="Eliminar sesión de disco">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>
        </div>
    `;
}

async function openAccount(accountId) {
    showToast(`Abriendo sesión de '${accountId}'...`, 'info');
    try {
        const data = await apiPost(`/api/accounts/${accountId}/open`);
        if (data.status === 'success') {
            showToast(data.message, 'success');
            setTimeout(fetchAccounts, 2500);
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        showToast('Error al abrir sesión: ' + err, 'error');
    }
}

async function closeAccount(accountId) {
    showToast(`Cerrando instancia de '${accountId}'...`, 'info');
    try {
        const data = await apiPost(`/api/accounts/${accountId}/close`);
        if (data.status === 'success') {
            showToast(data.message, 'success');
        } else {
            showToast(data.message || 'Error al cerrar', 'error');
        }
    } catch (err) {
        showToast('Error de red: ' + err, 'error');
    }
    setTimeout(() => { fetchAccounts(); fetchDashboard(); }, 1000);
}

async function deleteAccount(accountId) {
    if (!confirm(`¿Eliminar permanentemente la sesión de '${accountId}'?\nEsta acción no se puede deshacer.`)) return;
    try {
        const data = await apiDelete(`/api/accounts/${accountId}/delete`);
        if (data.status === 'success') {
            showToast(data.message, 'success');
            fetchAccounts();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        showToast('Error al eliminar: ' + err, 'error');
    }
}

// ==================== MODAL: ADD ACCOUNT ====================
function initModalListeners() {
    const modalAdd    = document.getElementById('modal-add');
    const btnAdd      = document.getElementById('btn-add-account');
    const closeBtnAdd = document.getElementById('close-modal-add');
    const cancelAdd   = document.getElementById('cancel-add-btn');
    const confirmAdd  = document.getElementById('confirm-add-btn');

    const openAddModal = () => {
        document.getElementById('input-account-name').value = '';
        document.getElementById('qr-status-box').classList.add('hidden');
        document.getElementById('qr-status-text').textContent = 'Iniciando navegador...';
        modalAdd.classList.add('active');
    };

    const closeAddModal = () => {
        modalAdd.classList.remove('active');
        if (qrPollInterval) { clearInterval(qrPollInterval); qrPollInterval = null; }
    };

    btnAdd?.addEventListener('click', openAddModal);
    closeBtnAdd?.addEventListener('click', closeAddModal);
    cancelAdd?.addEventListener('click', closeAddModal);

    // Click outside to close
    modalAdd?.addEventListener('click', e => { if (e.target === modalAdd) closeAddModal(); });

    confirmAdd?.addEventListener('click', async () => {
        const name = document.getElementById('input-account-name').value.trim();
        if (!name) { showToast('Ingresa un nombre para la cuenta', 'warning'); return; }

        const qrBox  = document.getElementById('qr-status-box');
        const qrText = document.getElementById('qr-status-text');
        qrBox.classList.remove('hidden');
        qrText.textContent = 'Iniciando Chromium en modo visible...';
        confirmAdd.disabled = true;

        try {
            const data = await apiPost('/api/accounts/add', { account_name: name });

            if (data.status === 'success') {
                const accId = data.account_id;
                qrText.textContent = '✅ Navegador listo. Escanea el QR que aparece en pantalla.';
                showToast('Navegador abierto — escanea el QR', 'info', 5000);

                // Poll QR status
                qrPollInterval = setInterval(async () => {
                    try {
                        const st = await apiGet(`/api/qr_status/${accId}`);
                        if (st.status === 'success') {
                            clearInterval(qrPollInterval);
                            qrPollInterval = null;
                            qrText.textContent = '🎉 ' + st.message;
                            showToast('¡Sesión guardada exitosamente!', 'success', 5000);
                            setTimeout(() => { closeAddModal(); fetchAccounts(); }, 2500);
                        } else if (st.status === 'error') {
                            clearInterval(qrPollInterval);
                            qrPollInterval = null;
                            qrText.textContent = '❌ ' + st.message;
                            showToast(st.message, 'error', 6000);
                            confirmAdd.disabled = false;
                        }
                    } catch (_) {}
                }, 2500);

            } else {
                qrText.textContent = '❌ ' + data.message;
                showToast(data.message, 'error');
                confirmAdd.disabled = false;
            }
        } catch (err) {
            qrText.textContent = '❌ Error de servidor';
            showToast('Error de servidor: ' + err, 'error');
            confirmAdd.disabled = false;
        }
    });
}

// ==================== MODAL: SEND TEST MESSAGE ====================
function initSendMsgListeners() {
    const modal      = document.getElementById('modal-send');
    const closeBtn   = document.getElementById('close-modal-send');
    const cancelBtn  = document.getElementById('cancel-send-btn');
    const confirmBtn = document.getElementById('confirm-send-btn');

    const closeModal = () => {
        modal.classList.remove('active');
        document.getElementById('send-status-box').classList.add('hidden');
    };

    closeBtn?.addEventListener('click', closeModal);
    cancelBtn?.addEventListener('click', closeModal);
    modal?.addEventListener('click', e => { if (e.target === modal) closeModal(); });

    confirmBtn?.addEventListener('click', async () => {
        const phone   = document.getElementById('input-target-phone').value.trim();
        const message = document.getElementById('input-target-message').value.trim();
        const statusBox = document.getElementById('send-status-box');

        if (!phone || !message) {
            showToast('Completa teléfono y mensaje', 'warning');
            return;
        }

        statusBox.className = 'alert-box info';
        statusBox.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Enviando mensaje...';
        statusBox.classList.remove('hidden');
        confirmBtn.disabled = true;

        try {
            const data = await apiPost(`/api/accounts/${activeAccountForSend}/send`, { phone, message });

            if (data.status === 'success') {
                statusBox.className = 'alert-box success';
                statusBox.innerHTML = `<i class="fa-solid fa-circle-check"></i> ${data.message}`;
                showToast('Mensaje enviado con éxito', 'success');
                setTimeout(closeModal, 2500);
            } else {
                statusBox.className = 'alert-box error';
                statusBox.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> ${data.message}`;
                showToast(data.message, 'error');
            }
        } catch (err) {
            statusBox.className = 'alert-box error';
            statusBox.innerHTML = `<i class="fa-solid fa-circle-xmark"></i> Error: ${err}`;
        }

        confirmBtn.disabled = false;
    });
}

function showSendModal(accountId) {
    activeAccountForSend = accountId;
    document.getElementById('send-modal-account-name').textContent = accountId;
    document.getElementById('input-target-phone').value = '';
    document.getElementById('input-target-message').value = '';
    document.getElementById('send-status-box').classList.add('hidden');
    document.getElementById('modal-send').classList.add('active');
}

// ==================== CAMPAIGNS ====================
function initCampaignListeners() {
    const modal      = document.getElementById('modal-campaign');
    const btnOpen    = document.getElementById('btn-open-create-campaign');
    const btnClose   = document.getElementById('close-modal-campaign');
    const btnCancel  = document.getElementById('cancel-campaign-btn');
    const btnSave    = document.getElementById('save-campaign-btn');
    const templateEl = document.getElementById('input-campaign-template');
    const previewEl  = document.getElementById('campaign-preview-bubble');
    const varsBox    = document.getElementById('vars-detected-box');
    const varsTags   = document.getElementById('vars-tags-list');

    const openModal = () => {
        document.getElementById('input-campaign-name').value = '';
        document.getElementById('select-campaign-type').value = 'estatica';
        templateEl.value = '';
        previewEl.textContent = 'Tu mensaje aparecerá aquí...';
        varsBox.classList.add('hidden');
        modal.classList.add('active');
    };

    const closeModal = () => modal.classList.remove('active');

    btnOpen?.addEventListener('click', openModal);
    btnClose?.addEventListener('click', closeModal);
    btnCancel?.addEventListener('click', closeModal);
    modal?.addEventListener('click', e => { if (e.target === modal) closeModal(); });

    // Live variable detection
    templateEl?.addEventListener('input', () => {
        const text = templateEl.value;
        const matches = text.match(/\{(\w+)\}/g) || [];
        const unique = [...new Set(matches.map(m => m.replace(/[{}]/g, '')))];

        if (unique.length) {
            varsBox.classList.remove('hidden');
            varsTags.innerHTML = unique.map(v => `<span class="var-tag">{${v}}</span>`).join('');
        } else {
            varsBox.classList.add('hidden');
        }

        // Preview
        let preview = text;
        unique.forEach(v => {
            preview = preview.replaceAll(`{${v}}`, `[${v.toUpperCase()}]`);
        });
        previewEl.textContent = preview || 'Tu mensaje aparecerá aquí...';
    });

    btnSave?.addEventListener('click', async () => {
        const name     = document.getElementById('input-campaign-name').value.trim();
        const type     = document.getElementById('select-campaign-type').value;
        const template = templateEl.value.trim();

        if (!name || !template) {
            showToast('Nombre y mensaje son obligatorios', 'warning');
            return;
        }

        btnSave.disabled = true;
        try {
            const data = await apiPost('/api/campaigns', {
                name,
                type,
                template_message: template,
            });

            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal();
                fetchCampaigns();
            } else {
                showToast(data.message, 'error');
            }
        } catch (err) {
            showToast('Error al guardar campaña: ' + err, 'error');
        }
        btnSave.disabled = false;
    });
}

async function fetchCampaigns() {
    try {
        const data = await apiGet('/api/campaigns');
        if (data.status === 'success') {
            renderCampaigns(data.campaigns || []);
            const pill = document.getElementById('campaigns-count');
            if (pill) pill.textContent = data.campaigns?.length || 0;
        }
    } catch (err) {
        console.warn('Campaigns fetch error:', err);
    }
}

function renderCampaigns(campaigns) {
    const container = document.getElementById('campaigns-container');
    if (!container) return;

    if (!campaigns.length) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-bullhorn"></i>
                <p>No tienes campañas creadas aún.<br>Presiona <strong>Nueva Campaña</strong> para comenzar.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = campaigns.map(c => {
        const vars = Array.isArray(c.variables) ? c.variables : [];
        const varsHtml = vars.length ? `
            <div class="vars-row" style="margin-top:10px;">
                <span style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.4px;">Variables:</span>
                ${vars.map(v => `<span class="var-tag">{${v}}</span>`).join('')}
            </div>
        ` : '';

        return `
            <div class="campaign-card">
                <div class="camp-header">
                    <div>
                        <div class="camp-name">${escHtml(c.name)}</div>
                        <div class="camp-meta">
                            <i class="fa-solid fa-clock"></i>
                            ${c.created_at ? new Date(c.created_at).toLocaleDateString('es-ES') : 'Creada'}
                        </div>
                    </div>
                    <span class="type-badge ${c.type}">${c.type}</span>
                </div>

                <div>
                    <div class="whatsapp-bubble">${escHtml(c.template_message)}</div>
                    ${varsHtml}
                </div>

                <div class="card-actions">
                    <button class="btn btn-danger btn-sm" onclick="deleteCampaign(${c.id})">
                        <i class="fa-solid fa-trash"></i> Eliminar
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

async function deleteCampaign(id) {
    if (!confirm('¿Eliminar esta campaña?')) return;
    try {
        const data = await apiDelete(`/api/campaigns/${id}`);
        showToast(data.message, data.status === 'success' ? 'success' : 'error');
        fetchCampaigns();
    } catch (err) {
        showToast('Error: ' + err, 'error');
    }
}

// ==================== SEND PROFILES ====================
function initProfileListeners() {
    const modal     = document.getElementById('modal-send-profile');
    const btnOpen   = document.getElementById('btn-open-create-profile');
    const btnClose  = document.getElementById('close-modal-send-profile');
    const btnCancel = document.getElementById('cancel-send-profile-btn');
    const btnSave   = document.getElementById('save-send-profile-btn');

    const openModal = async () => {
        document.getElementById('input-profile-name').value = '';
        document.getElementById('input-delay-min').value    = '15';
        document.getElementById('input-delay-max').value    = '45';
        document.getElementById('input-msgs-session').value = '10';
        document.getElementById('input-msgs-interval').value = '2';
        document.getElementById('input-rest-mins').value   = '30';
        await populateCampaignSelect();
        modal.classList.add('active');
    };

    const closeModal = () => modal.classList.remove('active');

    btnOpen?.addEventListener('click', openModal);
    btnClose?.addEventListener('click', closeModal);
    btnCancel?.addEventListener('click', closeModal);
    modal?.addEventListener('click', e => { if (e.target === modal) closeModal(); });

    btnSave?.addEventListener('click', async () => {
        const name       = document.getElementById('input-profile-name').value.trim();
        const campaignId = document.getElementById('select-profile-campaign').value;
        const delayMin   = parseInt(document.getElementById('input-delay-min').value) || 15;
        const delayMax   = parseInt(document.getElementById('input-delay-max').value) || 45;
        const msgsSession   = parseInt(document.getElementById('input-msgs-session').value) || 10;
        const msgsInterval  = parseInt(document.getElementById('input-msgs-interval').value) || 2;
        const restMins   = parseInt(document.getElementById('input-rest-mins').value) || 30;

        if (!name) {
            showToast('Ingresa un nombre para el perfil', 'warning');
            return;
        }

        if (delayMin >= delayMax) {
            showToast('El tiempo mínimo debe ser menor al máximo', 'warning');
            return;
        }

        btnSave.disabled = true;
        try {
            const data = await apiPost('/api/send_profiles', {
                name,
                campaign_id: campaignId ? parseInt(campaignId) : null,
                delay_min_sec: delayMin,
                delay_max_sec: delayMax,
                messages_per_session: msgsSession,
                messages_per_interval: msgsInterval,
                rest_time_minutes: restMins,
            });

            if (data.status === 'success') {
                showToast(data.message, 'success');
                closeModal();
                fetchSendProfiles();
            } else {
                showToast(data.message, 'error');
            }
        } catch (err) {
            showToast('Error al guardar perfil: ' + err, 'error');
        }
        btnSave.disabled = false;
    });
}

async function populateCampaignSelect() {
    const select = document.getElementById('select-profile-campaign');
    if (!select) return;
    select.innerHTML = '<option value="">— Sin campaña vinculada —</option>';

    try {
        const data = await apiGet('/api/campaigns');
        if (data.status === 'success' && data.campaigns.length) {
            data.campaigns.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = `${c.name} (${c.type})`;
                select.appendChild(opt);
            });
        }
    } catch (_) { /* silent */ }
}

async function fetchSendProfiles() {
    try {
        const data = await apiGet('/api/send_profiles');
        if (data.status === 'success') {
            renderSendProfiles(data.profiles || []);
            const pill = document.getElementById('profiles-count');
            if (pill) pill.textContent = data.profiles?.length || 0;
        }
    } catch (err) {
        console.warn('Profiles fetch error:', err);
    }
}

function renderSendProfiles(profiles) {
    const container = document.getElementById('profiles-container');
    if (!container) return;

    if (!profiles.length) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="fa-solid fa-sliders"></i>
                <p>No tienes perfiles de envío creados aún.<br>Presiona <strong>Nuevo Perfil</strong> para comenzar.</p>
            </div>
        `;
        return;
    }

    container.innerHTML = profiles.map(p => `
        <div class="profile-card">
            <div class="prof-header">
                <div>
                    <div class="prof-name">${escHtml(p.name)}</div>
                    <div class="prof-campaign">
                        <i class="fa-solid fa-bullhorn" style="font-size:11px;"></i>
                        ${p.campaign_name ? escHtml(p.campaign_name) : 'Sin campaña vinculada'}
                    </div>
                </div>
                <span class="badge badge-blue" style="align-self:flex-start;">Activo</span>
            </div>

            <div class="prof-stats">
                <div class="prof-stat">
                    <span class="prof-stat-label">⏱ Intervalo</span>
                    <span class="prof-stat-val">${p.delay_min_sec}<span class="prof-stat-unit">s</span> – ${p.delay_max_sec}<span class="prof-stat-unit">s</span></span>
                </div>
                <div class="prof-stat">
                    <span class="prof-stat-label">📦 Límite sesión</span>
                    <span class="prof-stat-val">${p.messages_per_session}<span class="prof-stat-unit"> msgs</span></span>
                </div>
                <div class="prof-stat">
                    <span class="prof-stat-label">⚡ Ráfaga</span>
                    <span class="prof-stat-val">${p.messages_per_interval}<span class="prof-stat-unit"> msgs</span></span>
                </div>
                <div class="prof-stat">
                    <span class="prof-stat-label">💤 Reposo</span>
                    <span class="prof-stat-val">${p.rest_time_minutes}<span class="prof-stat-unit"> min</span></span>
                </div>
            </div>

            <div class="card-actions">
                <button class="btn btn-danger btn-sm" onclick="deleteSendProfile(${p.id})">
                    <i class="fa-solid fa-trash"></i> Eliminar
                </button>
            </div>
        </div>
    `).join('');
}

async function deleteSendProfile(id) {
    if (!confirm('¿Eliminar este perfil de envío?')) return;
    try {
        const data = await apiDelete(`/api/send_profiles/${id}`);
        showToast(data.message, data.status === 'success' ? 'success' : 'error');
        fetchSendProfiles();
    } catch (err) {
        showToast('Error: ' + err, 'error');
    }
}

// ==================== UTILS ====================
function escHtml(str) {
    if (typeof str !== 'string') return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
