let selectedRunId = null;
let selectedEvent = null;

const runsEl = document.getElementById('runs');
const treeEl = document.getElementById('tree');
const rawEl = document.getElementById('raw');
const titleEl = document.getElementById('detail-title');
const autoRefreshEl = document.getElementById('auto-refresh');

document.getElementById('refresh').addEventListener('click', () => loadRuns());
setInterval(() => {
  if (autoRefreshEl.checked) {
    loadRuns(false);
    if (selectedRunId) loadRun(selectedRunId, false);
  }
}, 2000);

function duration(ms) {
  if (ms === null || ms === undefined) return 'running';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

async function loadRuns(selectLatest = true) {
  const res = await fetch('/api/runs');
  const data = await res.json();
  runsEl.innerHTML = '';
  if (!data.runs.length) {
    runsEl.innerHTML = '<p class="muted">No traces found. Run `ouro --task "..." --trace` first.</p>';
    return;
  }
  for (const run of data.runs) {
    const row = document.createElement('div');
    row.className = `run-row ${run.run_id === selectedRunId ? 'active' : ''}`;
    row.innerHTML = `
      <div class="run-id">${run.run_id}</div>
      <div class="meta"><span class="status-${run.status}">${run.status}</span> · ${duration(run.duration_ms)}</div>
      <div class="meta">LLM ${run.llm_calls} · Tools ${run.tool_calls} · Events ${run.event_count}</div>
      <div class="meta">${run.started_at}</div>
    `;
    row.addEventListener('click', () => loadRun(run.run_id));
    runsEl.appendChild(row);
  }
  if (selectLatest && !selectedRunId) loadRun(data.runs[0].run_id);
}

async function loadRun(runId, updateRaw = true) {
  selectedRunId = runId;
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) return;
  const data = await res.json();
  titleEl.textContent = `Trace ${runId}`;
  renderTree(data.events);
  if (updateRaw) rawEl.textContent = selectedEvent ? JSON.stringify(selectedEvent, null, 2) : 'Click a trace node to inspect raw event metadata.';
  loadRuns(false);
}

function renderTree(events) {
  treeEl.innerHTML = '';
  const terminal = events.filter(e => ['completed', 'failed'].includes(e.status));
  const bySpan = new Map(terminal.map(e => [e.span_id, e]));
  const children = new Map();
  for (const event of terminal) {
    const parent = event.parent_span_id || '__root__';
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(event);
  }
  const roots = children.get('__root__') || terminal.filter(e => !bySpan.has(e.parent_span_id));
  if (!roots.length) {
    treeEl.innerHTML = '<p class="muted">No completed spans yet.</p>';
    return;
  }
  for (const root of roots) renderNode(root, children, 0);
}

function renderNode(event, children, depth) {
  const node = document.createElement('div');
  node.className = `node ${event.status}`;
  node.style.setProperty('--depth', `${depth * 18}px`);
  node.innerHTML = `
    <span class="node-title">${event.event_type} ${event.name}</span>
    <span class="badge">${event.status} · ${duration(event.duration_ms)}</span>
  `;
  node.addEventListener('click', (e) => {
    e.stopPropagation();
    selectedEvent = event;
    rawEl.textContent = JSON.stringify(event, null, 2);
  });
  treeEl.appendChild(node);
  for (const child of children.get(event.span_id) || []) renderNode(child, children, depth + 1);
}

loadRuns();
