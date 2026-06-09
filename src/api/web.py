"""Built-in web UI for debugging only. Not for production use."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["debug"])

HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Healthy Agent</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
.header { background: #1e293b; padding: 16px 24px; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 20px; color: #38bdf8; }
.header .status { font-size: 13px; color: #94a3b8; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; display: grid; grid-template-columns: 300px 1fr; gap: 24px; }
.panel { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
.panel h2 { font-size: 14px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
.session-list { list-style: none; }
.session-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; font-size: 14px; transition: background 0.15s; }
.session-item:hover { background: #334155; }
.session-item.active { background: #0ea5e9; color: white; }
.session-item .meta { font-size: 11px; color: #64748b; margin-top: 2px; }
.session-item.active .meta { color: #bae6fd; }
button { background: #0ea5e9; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; transition: background 0.15s; }
button:hover { background: #0284c7; }
button.secondary { background: #334155; }
button.secondary:hover { background: #475569; }
.chat-area { display: flex; flex-direction: column; height: calc(100vh - 120px); }
.messages { flex: 1; overflow-y: auto; padding: 16px 0; }
.msg { margin-bottom: 16px; display: flex; gap: 12px; }
.msg .avatar { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 14px; flex-shrink: 0; }
.msg.user .avatar { background: #0ea5e9; }
.msg.assistant .avatar { background: #8b5cf6; }
.msg.system .avatar { background: #334155; }
.msg .content { background: #334155; padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; max-width: 80%; white-space: pre-wrap; word-break: break-word; }
.msg.user .content { background: #0c4a6e; }
.input-area { display: flex; gap: 8px; padding-top: 16px; border-top: 1px solid #334155; }
.input-area input { flex: 1; background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 12px 16px; border-radius: 8px; font-size: 14px; outline: none; }
.input-area input:focus { border-color: #0ea5e9; }
.input-area input::placeholder { color: #475569; }
.kernel-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 16px; }
.stat { background: #0f172a; padding: 12px; border-radius: 8px; text-align: center; }
.stat .num { font-size: 24px; font-weight: 700; color: #38bdf8; }
.stat .label { font-size: 11px; color: #64748b; margin-top: 4px; }
.empty { color: #475569; font-size: 14px; text-align: center; padding: 40px; }
.loading { display: inline-block; width: 16px; height: 16px; border: 2px solid #334155; border-top-color: #0ea5e9; border-radius: 50%; animation: spin 0.6s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <h1>Healthy Agent</h1>
  <div class="status" id="kernelStatus">connecting...</div>
</div>

<div class="container">
  <div>
    <div class="panel" style="margin-bottom: 16px;">
      <h2>Kernel</h2>
      <div class="kernel-stats" id="kernelStats">
        <div class="stat"><div class="num" id="statCores">-</div><div class="label">Cores</div></div>
        <div class="stat"><div class="num" id="statActive">-</div><div class="label">Active</div></div>
        <div class="stat"><div class="num" id="statProcs">-</div><div class="label">Total</div></div>
      </div>
    </div>
    <div class="panel">
      <h2>Sessions</h2>
      <button onclick="createSession()" style="width:100%; margin-bottom: 12px;">+ New Session</button>
      <ul class="session-list" id="sessionList"></ul>
    </div>
  </div>

  <div class="panel chat-area">
    <div class="messages" id="messages">
      <div class="empty">Type a message to start</div>
    </div>
    <div class="input-area">
      <input type="text" id="promptInput" placeholder="Type a message..." onkeydown="if(event.key==='Enter')sendMessage()">
      <button onclick="sendMessage()" id="sendBtn">Send</button>
    </div>
  </div>
</div>

<script>
const API = '';
let currentSession = null;
let polling = null;

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API + path, opts);
  return r.json();
}

async function refreshKernel() {
  try {
    const d = await api('GET', '/kernel/stats');
    document.getElementById('statCores').textContent = d.cores;
    document.getElementById('statActive').textContent = d.active;
    document.getElementById('statProcs').textContent = d.processes;
    document.getElementById('kernelStatus').textContent = `${d.cores} cores | ${d.active} active | ${d.processes} total`;
  } catch(e) {
    document.getElementById('kernelStatus').textContent = 'disconnected';
  }
}

async function refreshSessions() {
  const d = await api('GET', '/sessions');
  const list = document.getElementById('sessionList');
  list.innerHTML = '';
  for (const s of d.sessions) {
    const li = document.createElement('li');
    li.className = 'session-item' + (currentSession === s.session_id ? ' active' : '');
    li.innerHTML = `${s.metadata.user || s.session_id.slice(0,8)}<div class="meta">${s.messages} msgs | ${s.memory_backend}</div>`;
    li.onclick = () => selectSession(s.session_id);
    list.appendChild(li);
  }
}

async function createSession() {
  const name = prompt('User name (optional):', '');
  const d = await api('POST', '/sessions', { metadata: { user: name || 'user' } });
  currentSession = d.session_id;
  await refreshSessions();
  await loadMessages();
  document.getElementById('promptInput').disabled = false;
  document.getElementById('sendBtn').disabled = false;
}

async function selectSession(sid) {
  currentSession = sid;
  await refreshSessions();
  await loadMessages();
  document.getElementById('promptInput').disabled = false;
  document.getElementById('sendBtn').disabled = false;
}

async function loadMessages() {
  if (!currentSession) return;
  const d = await api('GET', `/sessions/${currentSession}/messages`);
  const el = document.getElementById('messages');
  if (!d.messages.length) {
    el.innerHTML = '<div class="empty">No messages yet. Type something!</div>';
    return;
  }
  el.innerHTML = d.messages.map(m => `
    <div class="msg ${m.role}">
      <div class="avatar">${m.role === 'user' ? 'U' : m.role === 'assistant' ? 'A' : 'S'}</div>
      <div class="content">${escHtml(m.content)}</div>
    </div>
  `).join('');
  el.scrollTop = el.scrollHeight;
}

async function ensureSession() {
  if (!currentSession) {
    const d = await api('POST', '/sessions', { metadata: { user: 'user' } });
    currentSession = d.session_id;
    await refreshSessions();
  }
}

async function sendMessage() {
  await ensureSession();
  const input = document.getElementById('promptInput');
  const prompt = input.value.trim();
  if (!prompt) return;
  input.value = '';
  input.focus();

  // Show user message immediately
  appendMsg('user', prompt);

  // Show loading
  const loadingId = appendMsg('assistant', '<div class="loading"></div> thinking...');

  // Submit task
  const task = await api('POST', `/sessions/${currentSession}/tasks`, {
    task_type: 'chat',
    payload: { prompt }
  });

  // Poll for result (input stays enabled, user can send more)
  const taskId = task.task_id;
  const poll = setInterval(async () => {
    try {
      const r = await api('GET', `/sessions/${currentSession}/tasks/${taskId}`);
      if (r.status !== 'running') {
        clearInterval(poll);
        removeMsg(loadingId);
        appendMsg('assistant', r.result || r.status);
        refreshKernel();
        refreshSessions();
      }
    } catch(e) {
      clearInterval(poll);
      removeMsg(loadingId);
      appendMsg('system', 'Request failed: ' + e.message);
    }
  }, 500);
}

function appendMsg(role, content) {
  const el = document.getElementById('messages');
  if (el.querySelector('.empty')) el.innerHTML = '';
  const id = 'msg-' + Date.now();
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.id = id;
  div.innerHTML = `
    <div class="avatar">${role === 'user' ? 'U' : role === 'assistant' ? 'A' : 'S'}</div>
    <div class="content">${content}</div>
  `;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return id;
}

function removeMsg(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Init
refreshKernel();
refreshSessions();
setInterval(refreshKernel, 5000);
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def web_ui():
    return HTML_PAGE
