// ─── LabSCH Full Agent view ───
// Uses separate server (labsch-agent on VPS2) with its own token.

let agentUrl = '';
let agentToken = '';

function agentInit() {
  agentUrl = localStorage.getItem('labsch_agent_url') || '';
  agentToken = localStorage.getItem('labsch_agent_token') || '';
  document.getElementById('agent-url').value = agentUrl;
  document.getElementById('agent-tok').value = agentToken;
  if (agentUrl && agentToken) agentLoadAll();
}

async function agentApi(method, path, body) {
  const opts = {
    method,
    headers: { 'Authorization': 'Bearer ' + agentToken, 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(agentUrl + path, opts);
  const json = await res.json().catch(() => null);
  if (!res.ok) throw new Error(json?.detail || json?.error || `HTTP ${res.status}`);
  return json;
}

async function agentSaveConn() {
  agentUrl = document.getElementById('agent-url').value.replace(/\/+$/, '');
  agentToken = document.getElementById('agent-tok').value;
  localStorage.setItem('labsch_agent_url', agentUrl);
  localStorage.setItem('labsch_agent_token', agentToken);
  agentLoadAll();
}

async function agentLoadAll() {
  try {
    const j = await agentApi('GET', '/api/dashboard/jobs');
    document.getElementById('agent-kill-state').innerHTML = j.killswitch
      ? '<b class="bad">🔴 KILL-SWITCH AKTIF</b>' : '<b class="ok">🟢 agent aktif</b>';
    document.getElementById('agent-allowlist').value = JSON.stringify(j.allowlist || []);
    const tb = document.querySelector('#agent-jobs tbody');
    tb.innerHTML = '';
    for (const [id, x] of Object.entries(j.jobs || {})) {
      const r = (j.results || {})[id] || {};
      tb.innerHTML += `<tr><td>${id}</td><td>${x.tool}</td><td>${JSON.stringify(x.argv)}</td>` +
        `<td>${x.client_id || '(any)'}</td>` +
        `<td class="${x.status === 'done' ? 'text-success' : x.status === 'failed' ? 'bad' : 'text-warning'}">${x.status}</td></tr>`;
    }
    const a = await agentApi('GET', '/api/dashboard/audit?limit=100');
    document.getElementById('agent-audit').textContent =
      (a.entries || []).map(e => JSON.stringify(e)).join('\n');
  } catch (e) {
    toast('Agent error: ' + e.message, 'error');
  }
}

async function agentCall() {
  const tool = document.getElementById('agent-tool').value;
  const target = document.getElementById('agent-target').value;
  try {
    const r = await agentApi('POST', '/api/agent/call', { tool, target });
    toast(`Queued ${r.job_id}`, 'success');
    agentLoadAll();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function agentKill(state) {
  await agentApi('POST', `/api/dashboard/killswitch?state=${state}`);
  toast(`Kill-switch ${state}`, state === 'on' ? 'error' : 'success');
  agentLoadAll();
}

async function agentSaveAllow() {
  try {
    const targets = JSON.parse(document.getElementById('agent-allowlist').value);
    await agentApi('POST', '/api/dashboard/allowlist', targets);
    toast('Allowlist saved', 'success');
    agentLoadAll();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}
