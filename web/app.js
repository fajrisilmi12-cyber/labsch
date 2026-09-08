/* ═══════════════════════════════════════════
   LabSCH Manager — app.js
   Web UI for LabSCH Workers API
   ═══════════════════════════════════════════ */

const LabSCH = (() => {
  // ─── State ───
  let baseUrl = '';
  let token = '';
  let clients = [];
  let config = null;
  let profiles = [];
  let deviceFlags = { disable_camera: false, disable_audio: false };
  let events = [];
  let currentView = 'dashboard';

  // ─── API Client ───
  async function api(method, path, body) {
    const opts = {
      method,
      headers: { 'X-Agent-Token': token, 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(baseUrl + path, opts);
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = json?.detail || json?.error || `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return json;
  }

  // ─── Toast ───
  function toast(msg, type = 'info') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    document.getElementById('toast-container').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3500);
  }

  // ─── Modal ───
  function showModal(title, bodyHtml, footerHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-footer').innerHTML = footerHtml || '';
    document.getElementById('modal-overlay').classList.remove('hidden');
  }
  function closeModal() { document.getElementById('modal-overlay').classList.add('hidden'); }

  // ─── Time helpers ───
  function timeAgo(ts) {
    if (!ts) return '-';
    const now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 60) return `${Math.floor(diff)}d lalu`;
    if (diff < 3600) return `${Math.floor(diff/60)}m lalu`;
    if (diff < 86400) return `${Math.floor(diff/3600)}j lalu`;
    return `${Math.floor(diff/86400)}h lalu`;
  }
  function timeStr(ts) {
    if (!ts) return '-';
    return new Date(ts * 1000).toLocaleString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }

  // ═══════ VIEWS ═══════

  // ─── Dashboard ───
  async function loadDashboard() {
    try {
      clients = await api('GET', '/api/clients');
    } catch (e) {
      toast('Gagal load clients: ' + e.message, 'error');
      clients = [];
    }
    const total = clients.length;
    const online = clients.filter(c => c.status === 'online').length;
    const offline = total - online;
    const pending = clients.filter(c => c.pending_command).length;

    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-online').textContent = online;
    document.getElementById('stat-offline').textContent = offline;
    document.getElementById('stat-pending').textContent = pending;

    try {
      events = await api('GET', '/api/events?hours=1');
    } catch { events = []; }

    const evDiv = document.getElementById('dash-events');
    if (events.length === 0) {
      evDiv.innerHTML = '<p class="empty-state">Tidak ada events terbaru.</p>';
    } else {
      evDiv.innerHTML = events.slice(0, 8).map(renderEventCompact).join('');
    }

    // Update client selectors
    populateClientSelectors();
  }

  // ─── Clients ───
  async function refreshClients() {
    try {
      clients = await api('GET', '/api/clients');
    } catch (e) { toast('Error: ' + e.message, 'error'); return; }
    renderClients();
    populateClientSelectors();
    toast('Clients refreshed', 'success');
  }

  function renderClients() {
    const body = document.getElementById('clients-body');
    const empty = document.getElementById('clients-empty');
    if (clients.length === 0) {
      body.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    body.innerHTML = clients.map(c => `
      <tr>
        <td><span class="status-dot ${c.status === 'online' ? 'online' : 'offline'}"></span>${c.status || 'unknown'}</td>
        <td><span class="name-cell" onclick="LabSCH.showClientDetail('${c.client_id}')">${esc(c.display_name || c.client_id)}</span></td>
        <td class="mono">${esc(c.ip || '-')}</td>
        <td class="mono">${esc(c.version || '-')}</td>
        <td>${timeAgo(c.last_seen)}</td>
        <td>${c.pending_command ? `<span class="text-warning">${c.pending_command}</span>` : '<span class="text-muted">-</span>'}</td>
        <td>${c.is_test ? '<span class="text-warning">✓</span>' : ''}</td>
      </tr>
    `).join('');
  }

  async function showClientDetail(clientId) {
    const c = clients.find(x => x.client_id === clientId);
    if (!c) return;
    let overrideHtml = '<p class="text-muted">No override</p>';
    try {
      const ov = await api('GET', `/api/clients/${clientId}/override`);
      if (ov && (ov.blocked_websites?.length || ov.blocked_apps?.length || ov.allowed_websites?.length)) {
        overrideHtml = `
          ${ov.blocked_websites?.length ? `<p><strong>Blocked Sites:</strong> ${ov.blocked_websites.join(', ')}</p>` : ''}
          ${ov.blocked_apps?.length ? `<p><strong>Blocked Apps:</strong> ${ov.blocked_apps.join(', ')}</p>` : ''}
          ${ov.allowed_websites?.length ? `<p><strong>Allowed Sites:</strong> ${ov.allowed_websites.join(', ')}</p>` : ''}
        `;
      }
    } catch {}
    const html = `
      <div style="display:grid;gap:0.5rem;font-size:0.9rem">
        <p><strong>Status:</strong> <span class="status-dot ${c.status === 'online' ? 'online' : 'offline'}"></span>${c.status}</p>
        <p><strong>Device ID:</strong> <span class="mono">${esc(c.device_id || '-')}</span></p>
        <p><strong>Hostname:</strong> ${esc(c.hostname || '-')}</p>
        <p><strong>IP:</strong> <span class="mono">${esc(c.ip || '-')}</span></p>
        <p><strong>MAC:</strong> <span class="mono">${esc(c.mac || '-')}</span></p>
        <p><strong>Version:</strong> ${esc(c.version || '-')}</p>
        <p><strong>User:</strong> ${esc(c.user || '-')}</p>
        <p><strong>First Seen:</strong> ${c.first_seen ? new Date(c.first_seen*1000).toLocaleString('id-ID') : '-'}</p>
        <p><strong>Last Seen:</strong> ${c.last_seen ? new Date(c.last_seen*1000).toLocaleString('id-ID') : '-'}</p>
        <p><strong>Pending Cmd:</strong> ${c.pending_command || '<span class="text-muted">none</span>'}</p>
        <p><strong>Test PC:</strong> ${c.is_test ? '✅ Yes' : 'No'}</p>
        <hr style="border-color:var(--border)">
        <p><strong>Override:</strong></p>
        ${overrideHtml}
      </div>
    `;
    showModal(c.display_name || c.client_id, html, `
      <button class="btn btn-secondary" onclick="LabSCH.closeModal()">Tutup</button>
      <button class="btn btn-danger" onclick="LabSCH.renameClient('${c.client_id}')">✏️ Rename</button>
    `);
  }

  async function renameClient(clientId) {
    const name = prompt('Nama baru untuk client ini:');
    if (!name) return;
    try {
      await api('PUT', `/api/clients/${clientId}/display_name`, { display_name: name });
      toast('Client renamed!', 'success');
      closeModal();
      refreshClients();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  // ─── Config ───
  async function loadConfig() {
    try {
      config = await api('GET', '/api/admin/config');
    } catch (e) { toast('Error: ' + e.message, 'error'); return; }
    document.getElementById('config-version').textContent = `v${config.config_version || 0}`;
    renderList('blocked-websites-list', config.blocked_websites || [], 'blocked-site');
    renderList('blocked-apps-list', config.blocked_apps || [], 'blocked-app');
    renderList('allowed-websites-list', config.allowed_websites || [], 'allow-site');
  }

  function renderList(listId, items, removeAction) {
    const ul = document.getElementById(listId);
    if (!items.length) {
      ul.innerHTML = '<li class="text-muted" style="padding:0.5rem">Kosong</li>';
      return;
    }
    ul.innerHTML = items.map(item => `
      <li class="tag-item">
        <span>${esc(item)}</span>
        <span class="tag-remove" onclick="LabSCH.removeItem('${removeAction}','${esc(item)}')" title="Remove">✕</span>
      </li>
    `).join('');
  }

  async function addItem(action, inputId) {
    const input = document.getElementById(inputId);
    const val = input.value.trim();
    if (!val) return;
    try {
      await api('POST', `/api/admin/${action}`, { name: val });
      input.value = '';
      toast(`Added: ${val}`, 'success');
      loadConfig();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function removeItem(action, item) {
    try {
      if (action === 'allow-site') {
        const cfg = await api('GET', '/api/admin/config');
        await api('POST', '/api/admin/config', {
          blocked_apps: cfg.blocked_apps || [],
          blocked_websites: cfg.blocked_websites || [],
          allowed_websites: (cfg.allowed_websites || []).filter(x => x !== item),
        });
      } else {
        await api('POST', `/api/admin/un${action}`, { name: item });
      }
      toast(`Removed: ${item}`, 'success');
      loadConfig();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function clearList(listType) {
    if (!confirm(`Yakin mau clear semua ${listType}?`)) return;
    try {
      await api('POST', `/api/admin/clear-${listType}`);
      toast('Cleared!', 'success');
      loadConfig();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  // ─── Profiles ───
  async function loadProfiles() {
    try {
      profiles = await api('GET', '/api/admin/profiles');
    } catch (e) { profiles = []; }
    renderProfiles();
  }

  function renderProfiles() {
    const container = document.getElementById('profiles-list');
    const empty = document.getElementById('profiles-empty');
    if (!profiles.length) {
      container.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    container.innerHTML = profiles.map(p => `
      <div class="profile-card">
        <h4>📁 ${esc(p.name)}</h4>
        <div class="profile-meta">
          Sites: ${(p.blocked_websites||[]).length} · Apps: ${(p.blocked_apps||[]).length} · Allowed: ${(p.allowed_websites||[]).length}
          ${p.disable_camera ? ' · 📷 blocked' : ''}
          ${p.disable_audio ? ' · 🔊 blocked' : ''}
        </div>
        <div class="profile-actions">
          <button class="btn btn-success btn-sm" onclick="LabSCH.activateProfile('${esc(p.name)}')">⚡ Activate</button>
          <button class="btn btn-danger btn-sm" onclick="LabSCH.deleteProfile('${esc(p.name)}')">🗑️ Delete</button>
        </div>
      </div>
    `).join('');
  }

  async function saveProfile() {
    const name = document.getElementById('new-profile-name').value.trim();
    if (!name) { toast('Masukkan nama profile', 'error'); return; }
    try {
      // First get current config
      const cfg = await api('GET', '/api/admin/config');
      const flags = await api('GET', '/api/admin/device');
      await api('POST', '/api/admin/profiles', {
        name,
        blocked_apps: cfg.blocked_apps || [],
        blocked_websites: cfg.blocked_websites || [],
        allowed_websites: cfg.allowed_websites || [],
        disable_camera: flags.disable_camera === true,
        disable_audio: flags.disable_audio === true,
      });
      document.getElementById('new-profile-name').value = '';
      toast(`Profile "${name}" saved!`, 'success');
      loadProfiles();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function activateProfile(name) {
    if (!confirm(`Activate profile "${name}"?`)) return;
    try {
      await api('POST', `/api/admin/profiles/${encodeURIComponent(name)}/activate`);
      toast(`Profile "${name}" activated!`, 'success');
      loadConfig(); // refresh config view
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function deleteProfile(name) {
    if (!confirm(`Delete profile "${name}"?`)) return;
    try {
      await api('DELETE', `/api/admin/profiles/${encodeURIComponent(name)}`);
      toast(`Profile "${name}" deleted`, 'success');
      loadProfiles();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  // ─── Commands ───
  function populateClientSelectors() {
    const selects = ['cmd-client-select', 'device-client-select'];
    selects.forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const val = sel.value;
      sel.innerHTML = '<option value="">-- Pilih PC --</option>' +
        clients.map(c => `<option value="${c.client_id}">${esc(c.display_name || c.client_id)}${c.is_test ? ' [test]' : ''}</option>`).join('');
      sel.value = val;
    });
  }

  async function perCommand(cmd) {
    const clientId = document.getElementById('cmd-client-select').value;
    if (!clientId) { toast('Pilih PC dulu!', 'error'); return; }
    const c = clients.find(x => x.client_id === clientId);
    const name = c?.display_name || clientId;
    if (!confirm(`Kirim "${cmd}" ke ${name}?`)) return;
    try {
      await api('POST', `/api/admin/command/${clientId}?command=${cmd}`);
      toast(`${cmd} queued untuk ${name}`, 'success');
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function perNotify() {
    const clientId = document.getElementById('cmd-client-select').value;
    const msg = document.getElementById('per-notify-msg').value.trim();
    if (!clientId) { toast('Pilih PC dulu!', 'error'); return; }
    if (!msg) { toast('Masukkan pesan!', 'error'); return; }
    try {
      await api('POST', `/api/admin/command/${clientId}?command=notify&message=${encodeURIComponent(msg)}`);
      toast('Notify queued!', 'success');
      document.getElementById('per-notify-msg').value = '';
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function bulkCommand(cmd, onlineOnly = false) {
    const online = clients.filter(c => c.status === 'online');
    const targets = onlineOnly ? online : clients;
    if (!targets.length) { toast('Tidak ada target!', 'error'); return; }
    const label = onlineOnly ? 'online' : 'semua';
    if (!confirm(`Kirim "${cmd}" ke ${targets.length} PC (${label})?`)) return;
    let ok = 0, fail = 0;
    for (const c of targets) {
      try {
        await api('POST', `/api/admin/command/${c.client_id}?command=${cmd}`);
        ok++;
      } catch { fail++; }
    }
    toast(`${cmd}: ${ok} sukses, ${fail} gagal`, ok > 0 ? 'success' : 'error');
  }

  async function bulkNotify() {
    const msg = document.getElementById('bulk-notify-msg').value.trim();
    if (!msg) { toast('Masukkan pesan!', 'error'); return; }
    const online = clients.filter(c => c.status === 'online');
    if (!online.length) { toast('Tidak ada PC online!', 'error'); return; }
    if (!confirm(`Kirim notify ke ${online.length} PC online?`)) return;
    let ok = 0;
    for (const c of online) {
      try {
        await api('POST', `/api/admin/command/${c.client_id}?command=notify&message=${encodeURIComponent(msg)}`);
        ok++;
      } catch {}
    }
    toast(`Notify terkirim ke ${ok} PC`, 'success');
    document.getElementById('bulk-notify-msg').value = '';
  }

  // ─── Device ───
  async function loadDevice() {
    try {
      deviceFlags = await api('GET', '/api/admin/device');
    } catch { deviceFlags = { disable_camera: false, disable_audio: false }; }
    document.getElementById('global-camera').checked = deviceFlags.disable_camera;
    document.getElementById('global-audio').checked = deviceFlags.disable_audio;
    updateDeviceStatus();
  }

  function updateDeviceStatus() {
    document.getElementById('global-camera-status').textContent = deviceFlags.disable_camera ? '🔴 Blocked' : '🟢 Enabled';
    document.getElementById('global-audio-status').textContent = deviceFlags.disable_audio ? '🔴 Blocked' : '🟢 Enabled';
  }

  async function saveDeviceFlags() {
    const body = {
      disable_camera: document.getElementById('global-camera').checked,
      disable_audio: document.getElementById('global-audio').checked,
    };
    try {
      await api('POST', '/api/admin/device', body);
      deviceFlags = body;
      updateDeviceStatus();
      toast('Device flags updated!', 'success');
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function savePerDevice() {
    const clientId = document.getElementById('device-client-select').value;
    if (!clientId) { toast('Pilih PC dulu!', 'error'); return; }
    const body = {
      disable_camera: document.getElementById('per-camera').checked,
      disable_audio: document.getElementById('per-audio').checked,
    };
    try {
      await api('POST', `/api/admin/device/${clientId}`, body);
      toast('Per-PC override saved!', 'success');
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  async function clearPerDevice() {
    const clientId = document.getElementById('device-client-select').value;
    if (!clientId) { toast('Pilih PC dulu!', 'error'); return; }
    try {
      await api('DELETE', `/api/admin/device/${clientId}`);
      toast('Override cleared!', 'success');
    } catch (e) { toast('Error: ' + e.message, 'error'); }
  }

  // ─── Events ───
  async function refreshEvents() {
    const hours = document.getElementById('events-hours').value;
    try {
      events = await api('GET', `/api/events?hours=${hours}`);
    } catch (e) { toast('Error: ' + e.message, 'error'); return; }
    renderEvents();
    toast('Events refreshed', 'success');
  }

  function renderEvents() {
    const container = document.getElementById('events-list');
    const empty = document.getElementById('events-empty');
    if (!events.length) {
      container.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    container.innerHTML = events.map(renderEvent).join('');
  }

  function renderEvent(e) {
    const typeClass = getEventTypeClass(e.event_type);
    return `
      <div class="event-item">
        <span class="event-time">${timeStr(e.timestamp || e.ts)}</span>
        <span class="event-type ${typeClass}">${esc(e.event_type)}</span>
        <span class="event-client mono">${esc(e.client_id ? (clients.find(c=>c.client_id===e.client_id)?.display_name || e.client_id.slice(0,16)) : '-')}</span>
        <span class="event-detail">${esc(e.target || e.details || '')}</span>
      </div>
    `;
  }

  function renderEventCompact(e) {
    const typeClass = getEventTypeClass(e.event_type);
    return `
      <div class="event-item compact">
        <span class="event-type ${typeClass}">${esc(e.event_type)}</span>
        <span class="event-detail">${esc(e.target || e.details || '')}</span>
        <span class="event-time">${timeStr(e.timestamp || e.ts)}</span>
      </div>
    `;
  }

  function getEventTypeClass(type) {
    if (!type) return 'info';
    if (type.includes('error') || type.includes('failed') || type.includes('reject')) return 'error';
    if (type.includes('warn') || type.includes('block') || type.includes('command')) return 'warn';
    if (type.includes('success') || type.includes('applied') || type.includes('activated')) return 'success';
    return 'info';
  }

  // ═══════ ROUTING ═══════

  function switchView(view) {
    currentView = view;
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(`view-${view}`)?.classList.add('active');
    document.querySelectorAll('.nav-item').forEach(n => {
      n.classList.toggle('active', n.dataset.view === view);
    });
    // Load data for view
    switch (view) {
      case 'dashboard': loadDashboard(); break;
      case 'clients': refreshClients(); break;
      case 'config': loadConfig(); break;
      case 'profiles': loadProfiles(); break;
      case 'commands': if (!clients.length) loadDashboard(); break;
      case 'device': loadDevice(); if (!clients.length) loadDashboard(); break;
      case 'events': refreshEvents(); break;
    }
    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
  }

  // ═══════ INIT ═══════

  function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  function init() {
    // Check saved token
    token = localStorage.getItem('labsch_token') || '';
    baseUrl = localStorage.getItem('labsch_url') || 'https://labsch-api.fajrisilmi6.workers.dev';

    if (token) {
      document.getElementById('login-overlay').classList.add('hidden');
      document.getElementById('app').classList.remove('hidden');
      switchView('dashboard');
    }

    // Login form
    document.getElementById('login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const t = document.getElementById('login-token').value.trim();
      const u = document.getElementById('login-url').value.trim() || 'https://labsch-api.fajrisilmi6.workers.dev';
      if (!t) return;
      token = t;
      baseUrl = u;
      // Validate the token against an authenticated endpoint.
      try {
        await api('GET', '/api/clients');
        localStorage.setItem('labsch_token', token);
        localStorage.setItem('labsch_url', baseUrl);
        document.getElementById('login-overlay').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');
        switchView('dashboard');
      } catch (e) {
        document.getElementById('login-error').textContent = 'Koneksi gagal: ' + e.message;
        document.getElementById('login-error').classList.remove('hidden');
      }
    });

    // Logout
    document.getElementById('btn-logout').addEventListener('click', () => {
      if (!confirm('Logout?')) return;
      localStorage.removeItem('labsch_token');
      localStorage.removeItem('labsch_url');
      location.reload();
    });

    // Nav clicks
    document.querySelectorAll('.nav-item').forEach(n => {
      n.addEventListener('click', (e) => {
        e.preventDefault();
        switchView(n.dataset.view);
      });
    });

    // Hash routing
    window.addEventListener('hashchange', () => {
      const v = location.hash.slice(1);
      if (v && document.getElementById(`view-${v}`)) switchView(v);
    });
    if (location.hash) {
      const v = location.hash.slice(1);
      if (document.getElementById(`view-${v}`)) switchView(v);
    }

    // Mobile menu
    document.getElementById('mobile-menu-btn').addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('open');
    });
    document.getElementById('mobile-refresh').addEventListener('click', () => {
      switchView(currentView);
    });

    // Enter key on config inputs
    ['add-blocked-site', 'add-blocked-app', 'add-allowed-site'].forEach(id => {
      document.getElementById(id)?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          const action = id === 'add-allowed-site' ? 'allow-site' : id.replace('add-', '');
          LabSCH.addItem(action, id);
        }
      });
    });

    // Close modal on overlay click
    document.getElementById('modal-overlay').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) closeModal();
    });
  }

  document.addEventListener('DOMContentLoaded', init);

  // ─── Public API ───
  return {
    refreshClients, showClientDetail, renameClient,
    addItem, removeItem, clearList,
    saveProfile, activateProfile, deleteProfile, refreshProfiles: loadProfiles,
    perCommand, perNotify, bulkCommand, bulkNotify,
    saveDeviceFlags, savePerDevice, clearPerDevice,
    refreshEvents, closeModal,
  };
})();
