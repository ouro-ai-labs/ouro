let selectedRunId = null;
let selectedSpanId = null;
let selectedEvent = null;
let currentSpans = new Map();

const runsEl = document.getElementById('runs');
const treeEl = document.getElementById('tree');
const rawEl = document.getElementById('raw');
const titleEl = document.getElementById('detail-title');
const autoRefreshEl = document.getElementById('auto-refresh');
const runStatsEl = document.getElementById('run-stats');

document.getElementById('refresh').addEventListener('click', () => loadRuns());
setInterval(() => {
  if (autoRefreshEl.checked) {
    loadRuns(false);
    if (selectedRunId) loadRun(selectedRunId, false);
  }
}, 2000);

function shortId(value) {
  if (!value) return '—';
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function isScrolledNearBottom(element) {
  const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
  return distanceFromBottom < 80;
}

function scrollTreeToLatest() {
  treeEl.scrollTop = treeEl.scrollHeight;
}

function duration(ms) {
  if (ms === null || ms === undefined) return 'running';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatValue(value) {
  if (value === null || value === undefined) return '<span class="muted">None</span>';
  if (typeof value === 'object') return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
  return `<code>${escapeHtml(value)}</code>`;
}

async function loadRuns(selectLatest = true) {
  const res = await fetch('/api/runs');
  const data = await res.json();
  updateRunStats(data.runs);
  runsEl.innerHTML = '';
  if (!data.runs.length) {
    runsEl.innerHTML = '<p class="muted">No traces found. Run `ouro --task "..." --trace` first.</p>';
    return;
  }
  for (const run of data.runs) {
    const row = document.createElement('div');
    row.className = `run-row status-${escapeHtml(run.status)} ${run.run_id === selectedRunId ? 'active' : ''}`;
    row.innerHTML = `
      <div class="run-head">
        <div class="run-id" title="${escapeHtml(run.run_id)}">${escapeHtml(run.run_id)}</div>
        <span class="pill status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
      </div>
      <div class="meta">${escapeHtml(run.started_at)} · ${duration(run.duration_ms)}</div>
      <div class="metric-strip">
        <span>LLM ${run.llm_calls}</span>
        <span>Tools ${run.tool_calls}</span>
        <span>Events ${run.event_count}</span>
      </div>
    `;
    row.addEventListener('click', () => {
      selectedSpanId = null;
      selectedEvent = null;
      loadRun(run.run_id);
    });
    runsEl.appendChild(row);
  }
  if (selectLatest && !selectedRunId) loadRun(data.runs[0].run_id);
}

function updateRunStats(runs) {
  const totalEvents = runs.reduce((sum, run) => sum + run.event_count, 0);
  const latest = runs[0];
  runStatsEl.innerHTML = `
    <div class="stat-card"><span>Total runs</span><strong>${runs.length}</strong></div>
    <div class="stat-card"><span>Latest</span><strong title="${latest ? escapeHtml(latest.run_id) : '—'}">${latest ? escapeHtml(latest.status) : '—'}</strong></div>
    <div class="stat-card"><span>Events</span><strong>${totalEvents}</strong></div>
  `;
}

async function loadRun(runId, resetDetail = true) {
  selectedRunId = runId;
  const res = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) return;
  const data = await res.json();
  titleEl.textContent = `Trace · ${shortId(runId)}`;
  const shouldFollowLatest = resetDetail || isScrolledNearBottom(treeEl);
  currentSpans = buildSpanModels(data.events);
  renderTree(currentSpans);
  if (shouldFollowLatest) scrollTreeToLatest();

  if (selectedSpanId && currentSpans.has(selectedSpanId)) {
    selectedEvent = currentSpans.get(selectedSpanId);
    renderEventDetail(selectedEvent);
  } else if (resetDetail) {
    selectedEvent = null;
    renderEventDetail(null);
  }
  loadRuns(false);
}

function buildSpanModels(events) {
  const grouped = new Map();
  for (const event of events) {
    if (!grouped.has(event.span_id)) grouped.set(event.span_id, []);
    grouped.get(event.span_id).push(event);
  }

  const spans = new Map();
  for (const [spanId, spanEvents] of grouped) {
    spanEvents.sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
    const started = spanEvents.find(e => e.status === 'started') || spanEvents[0];
    const failed = spanEvents.find(e => e.status === 'failed');
    const completed = spanEvents.find(e => e.status === 'completed');
    const terminal = failed || completed || null;
    const display = terminal || started;
    spans.set(spanId, {
      ...display,
      status: terminal ? terminal.status : 'running',
      duration_ms: terminal ? terminal.duration_ms : null,
      parent_span_id: started.parent_span_id || display.parent_span_id,
      timestamp: started.timestamp,
      sequence: started.sequence ?? display.sequence ?? 0,
      attributes: {
        ...(started.attributes || {}),
        ...(terminal?.attributes || {}),
      },
      lifecycle_events: spanEvents,
    });
  }
  return spans;
}

function renderTree(spans) {
  treeEl.innerHTML = '';
  const children = new Map();
  const roots = [];
  for (const span of spans.values()) {
    const parent = span.parent_span_id;
    if (parent && spans.has(parent)) {
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(span);
    } else {
      roots.push(span);
    }
  }
  for (const group of children.values()) group.sort(compareSpanOrder);
  roots.sort(compareSpanOrder);

  if (!roots.length) {
    treeEl.innerHTML = '<p class="muted">No trace spans yet.</p>';
    return;
  }
  for (const root of roots) renderNode(root, children, 0);
}

function compareSpanOrder(a, b) {
  return (a.sequence ?? 0) - (b.sequence ?? 0);
}

function renderNode(event, children, depth) {
  const node = document.createElement('div');
  node.className = `node ${event.status} ${event.span_id === selectedSpanId ? 'selected' : ''}`;
  node.style.setProperty('--depth', `${depth * 18}px`);
  node.innerHTML = `
    <span class="node-main">
      <span class="node-title"><span class="node-type">${escapeHtml(event.event_type)}</span> ${escapeHtml(event.name)}</span>
    </span>
    <span class="badge">${escapeHtml(event.status)} · ${duration(event.duration_ms)}</span>
  `;
  node.addEventListener('click', (e) => {
    e.stopPropagation();
    selectedSpanId = event.span_id;
    selectedEvent = event;
    renderEventDetail(event);
    renderTree(currentSpans);
  });
  treeEl.appendChild(node);
  for (const child of children.get(event.span_id) || []) renderNode(child, children, depth + 1);
}

function renderEventDetail(event) {
  if (!event) {
    rawEl.innerHTML = '<p class="muted">Click a trace node to inspect event details.</p>';
    return;
  }

  const rawJsonWasOpen = rawEl.querySelector('.raw-json')?.open ?? false;

  rawEl.innerHTML = `
    <div class="event-summary">
      ${summaryCard('Status', `<span class="status-${escapeHtml(event.status)}">${escapeHtml(event.status)}</span>`)}
      ${summaryCard('Type', escapeHtml(event.event_type))}
      ${summaryCard('Name', escapeHtml(event.name))}
      ${summaryCard('Duration', duration(event.duration_ms))}
    </div>

    <section class="detail-section">
      <h3>Span</h3>
      ${keyValueTable({
        'Run ID': event.run_id,
        'Event ID': event.event_id,
        'Span ID': event.span_id,
        'Parent Span': event.parent_span_id,
        'Timestamp': event.timestamp,
        'Sequence': event.sequence,
        'Agent ID': event.agent_id,
        'Task ID': event.task_id,
      })}
    </section>

    <section class="detail-section">
      <h3>Attributes</h3>
      ${keyValueTable(event.attributes || {}, 'No attributes recorded.')}
    </section>

    <section class="detail-section">
      <h3>Error</h3>
      ${renderError(event.error)}
    </section>

    <section class="detail-section">
      <h3>Links</h3>
      ${renderLinks(event.links)}
    </section>

    <details class="raw-json">
      <summary>Raw JSON</summary>
      <pre>${escapeHtml(JSON.stringify(event, null, 2))}</pre>
    </details>
  `;

  const rawJson = rawEl.querySelector('.raw-json');
  if (rawJson) rawJson.open = rawJsonWasOpen;
}

function summaryCard(label, value) {
  return `
    <div class="summary-card">
      <div class="summary-label">${escapeHtml(label)}</div>
      <div class="summary-value">${value}</div>
    </div>
  `;
}

function keyValueTable(values, emptyText = 'None') {
  const entries = Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!entries.length) return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  return `
    <table class="kv-table">
      <tbody>
        ${entries.map(([key, value]) => `
          <tr>
            <th>${escapeHtml(key)}</th>
            <td>${formatValue(value)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function renderError(error) {
  if (!error) return '<p class="muted">None</p>';
  return `
    <div class="error-block">
      <strong>${escapeHtml(error.type || 'Error')}</strong>
      <div>${escapeHtml(error.message || JSON.stringify(error))}</div>
    </div>
  `;
}

function renderLinks(links) {
  if (!links || !links.length) return '<p class="muted">None</p>';
  return `<ul class="links">${links.map(link => `<li><code>${escapeHtml(link)}</code></li>`).join('')}</ul>`;
}

loadRuns();
