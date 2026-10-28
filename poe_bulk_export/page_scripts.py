"""JavaScript evaluated inside the Poe page.

The helpers locate the page's Relay environment through the React fiber tree
and return only the records that belong to the target chat (owner record,
its ``messagesConnection`` connections, edges, message nodes and the records
those reference). Python does the actual parsing in ``extract.py``.
"""

from __future__ import annotations

_PRELUDE = r"""
const CONN_RE = /messagesconnection/i;
const HANDLE_RE = /^__.*_connection$/;

const refsOf = (v) => {
  if (!v || typeof v !== 'object') return [];
  if (typeof v.__ref === 'string') return [v.__ref];
  if (Array.isArray(v.__refs)) return v.__refs.filter((x) => typeof x === 'string');
  return [];
};

const isEnv = (e) => !!(e && typeof e.getStore === 'function' && typeof e.execute === 'function');

const findEnv = () => {
  if (isEnv(window.__poeExportEnv)) return window.__poeExportEnv;
  let start = null;
  const containers = [document.getElementById('__next'), document.body, document.documentElement];
  for (const el of containers) {
    if (!el) continue;
    const key = Object.keys(el).find((k) => k.startsWith('__reactContainer$'));
    if (key && el[key]) { start = el[key]; break; }
  }
  if (!start) {
    const el = document.querySelector('#__next *') || document.querySelector('body *');
    const key = el && Object.keys(el).find((k) => k.startsWith('__reactFiber$'));
    if (key) {
      let f = el[key];
      while (f && f.return) f = f.return;
      start = f;
    }
  }
  if (!start) return null;
  const stack = [start];
  let visited = 0;
  while (stack.length && visited < 400000) {
    const f = stack.pop();
    visited++;
    if (!f) continue;
    for (const props of [f.memoizedProps, f.pendingProps]) {
      if (!props || typeof props !== 'object') continue;
      const candidates = [props.environment, props.relayEnvironment, props.value && props.value.environment, props.value];
      for (const c of candidates) {
        if (isEnv(c)) { window.__poeExportEnv = c; return c; }
      }
    }
    if (f.sibling) stack.push(f.sibling);
    if (f.child) stack.push(f.child);
  }
  return null;
};

const recordSource = (env) => {
  const src = env.getStore().getSource();
  if (typeof src.getRecordIDs === 'function' && typeof src.get === 'function') {
    return { ids: src.getRecordIDs(), get: (id) => src.get(id) };
  }
  const all = src.toJSON();
  return { ids: Object.keys(all), get: (id) => all[id] };
};

const matchTarget = (rec, t) => {
  const results = [];
  const cmp = (field, want) => {
    if (want === null || want === undefined || want === '') return;
    const have = rec[field];
    if (have === null || have === undefined || have === '' || typeof have === 'object') return;
    results.push(String(have) === String(want));
  };
  cmp('chatCode', t.chatCode);
  cmp('chatId', t.chatId);
  cmp('id', t.nodeId);
  cmp('shareCode', t.shareCode);
  return results.length ? results.some(Boolean) : null;
};

const findOwners = (rs, t) => {
  const owners = [];
  for (const id of rs.ids) {
    const rec = rs.get(id);
    if (!rec || typeof rec !== 'object') continue;
    const conns = [];
    for (const k of Object.keys(rec)) {
      if (!CONN_RE.test(k)) continue;
      for (const cid of refsOf(rec[k])) {
        const c = rs.get(cid);
        if (c && c.edges !== undefined) conns.push([k, cid]);
      }
    }
    if (conns.length) owners.push({ id, rec, conns, match: matchTarget(rec, t) });
  }
  let chosen = owners.filter((o) => o.match === true);
  if (!chosen.length) {
    const unknown = owners.filter((o) => o.match === null);
    if (unknown.length === 1 && !owners.some((o) => o.match === false)) chosen = unknown;
  }
  return { owners, chosen };
};

const connectionStatus = (rs, chosen) => {
  const nodes = new Set();
  let handleInfo = null;
  let plainInfo = null;
  for (const o of chosen) {
    for (const [k, cid] of o.conns) {
      const c = rs.get(cid);
      if (!c) continue;
      for (const eid of refsOf(c.edges)) {
        const e = rs.get(eid);
        for (const nid of refsOf(e && e.node)) nodes.add(nid);
      }
      const pid = refsOf(c.pageInfo)[0];
      const pi = pid ? rs.get(pid) : null;
      if (!pi) continue;
      const info = {
        hasPreviousPage: pi.hasPreviousPage, startCursor: pi.startCursor,
        hasNextPage: pi.hasNextPage, endCursor: pi.endCursor,
      };
      if (HANDLE_RE.test(k)) handleInfo = handleInfo || info; else plainInfo = plainInfo || info;
    }
  }
  return { messageCount: nodes.size, pageInfo: handleInfo || plainInfo };
};

const ownerSummary = (o) => ({
  dataID: o.id,
  typename: o.rec.__typename || null,
  chatCode: o.rec.chatCode || null,
  chatId: o.rec.chatId === undefined ? null : o.rec.chatId,
  shareCode: o.rec.shareCode || null,
  title: typeof o.rec.title === 'string' ? o.rec.title : null,
  match: o.match,
  connections: o.conns.map(([k]) => k),
});

const nextData = () => {
  if (window.__NEXT_DATA__) return window.__NEXT_DATA__;
  const el = document.getElementById('__NEXT_DATA__');
  if (el) { try { return JSON.parse(el.textContent); } catch (e) { return null; } }
  return null;
};
"""

# Cheap readiness / progress probe (no record contents).
PROBE_JS = (
    "(t) => {"
    + _PRELUDE
    + r"""
  const env = findEnv();
  let store = null;
  if (env) {
    const rs = recordSource(env);
    const { owners, chosen } = findOwners(rs, t);
    store = Object.assign(connectionStatus(rs, chosen), {
      records: rs.ids.length, owners: owners.length, chosen: chosen.length,
    });
  }
  const nd = nextData();
  return {
    url: location.href,
    title: document.title,
    envFound: !!env,
    hasNextData: !!nd,
    nextDataBytes: nd ? JSON.stringify(nd).length : 0,
    store,
    domMessages: document.querySelectorAll('[class*="Markdown_markdownContainer"]').length,
  };
}"""
)

# Chat-scoped store records plus diagnostics.
SNAPSHOT_JS = (
    "(t) => {"
    + _PRELUDE
    + r"""
  const env = findEnv();
  if (!env) return { envFound: false, records: {}, owners: [], chosen: [], storeRecords: 0, typenames: {} };
  const rs = recordSource(env);
  const { owners, chosen } = findOwners(rs, t);
  const out = {};
  const add = (id) => {
    if (!id || out[id] !== undefined) return false;
    const rec = rs.get(id);
    if (!rec) return false;
    out[id] = rec;
    return true;
  };
  const addRefsOf = (rec, depth) => {
    if (!rec || depth <= 0) return;
    for (const v of Object.values(rec)) {
      for (const rid of refsOf(v)) {
        if (add(rid)) addRefsOf(rs.get(rid), depth - 1);
      }
    }
  };
  for (const o of chosen) {
    add(o.id);
    for (const [k, v] of Object.entries(o.rec)) {
      if (CONN_RE.test(k)) {
        for (const cid of refsOf(v)) {
          add(cid);
          const c = rs.get(cid);
          if (!c) continue;
          for (const pid of refsOf(c.pageInfo)) add(pid);
          for (const eid of refsOf(c.edges)) {
            add(eid);
            const e = rs.get(eid);
            for (const nid of refsOf(e && e.node)) {
              add(nid);
              addRefsOf(rs.get(nid), 2);
            }
          }
        }
      } else if (/bot/i.test(k)) {
        for (const rid of refsOf(v)) add(rid);
      }
    }
  }
  const typenames = {};
  for (const id of rs.ids) {
    const rec = rs.get(id);
    const tn = (rec && rec.__typename) || '?';
    typenames[tn] = (typenames[tn] || 0) + 1;
  }
  return {
    envFound: true,
    records: out,
    owners: owners.map(ownerSummary),
    chosen: chosen.map((o) => o.id),
    status: connectionStatus(rs, chosen),
    storeRecords: rs.ids.length,
    typenames,
  };
}"""
)

NEXT_DATA_JS = "() => {" + _PRELUDE + "\n  return nextData();\n}"

# Scroll the message list to its oldest end so the page requests older messages
# itself. Setting scrollTop to -scrollHeight reaches the top of both normal and
# column-reverse scrollers. Returns a point inside the scroller for wheel events.
SCROLL_TO_OLDEST_JS = r"""() => {
  const rows = document.querySelectorAll('[class*="Message_row"], [class*="ChatMessage_"], [class*="Markdown_markdownContainer"]');
  const first = rows.length ? rows[0] : null;
  let scroller = null;
  for (let el = first; el && el !== document.documentElement; el = el.parentElement) {
    const s = getComputedStyle(el);
    if (/(auto|scroll|overlay)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 4) { scroller = el; break; }
  }
  scroller = scroller || document.scrollingElement || document.documentElement;
  scroller.scrollTop = -scroller.scrollHeight;
  scroller.dispatchEvent(new Event('scroll', { bubbles: true }));
  if (first && first.scrollIntoView) first.scrollIntoView({ block: 'start' });
  const r = scroller.getBoundingClientRect();
  return {
    rows: rows.length,
    x: Math.round(r.left + r.width / 2),
    y: Math.round(r.top + Math.max(10, Math.min(r.height / 3, 240))),
    scrollTop: scroller.scrollTop,
    scrollHeight: scroller.scrollHeight,
  };
}"""

# Rendered message HTML, used only when the page exposes no raw messages.
DOM_MESSAGES_JS = r"""() => {
  const out = [];
  const containers = Array.from(document.querySelectorAll('[class*="Markdown_markdownContainer"]'));
  for (const c of containers) {
    if (c.parentElement && c.parentElement.closest('[class*="Markdown_markdownContainer"]')) continue;
    let role = 'unknown';
    for (let el = c; el && el !== document.body; el = el.parentElement) {
      const cls = String(el.className || '');
      if (/rightSide|humanMessage/i.test(cls)) { role = 'human'; break; }
      if (/leftSide|botMessage/i.test(cls)) { role = 'bot'; break; }
    }
    const clone = c.cloneNode(true);
    for (const pre of Array.from(clone.querySelectorAll('pre'))) {
      const code = pre.querySelector('code');
      let lang = '';
      const m = code && String(code.className || '').match(/language-([\w+#.-]+)/);
      if (m) lang = m[1];
      const block = pre.parentElement && pre.parentElement.closest('[class*="odeBlock"], [class*="odeblock"]');
      const scope = block && clone.contains(block) ? block : pre;
      if (!lang) {
        const label = scope.querySelector('[class*="anguage"]');
        if (label) lang = label.textContent.trim();
      }
      const clean = document.createElement('pre');
      const cleanCode = document.createElement('code');
      if (lang) cleanCode.className = 'language-' + lang;
      cleanCode.textContent = (code || pre).textContent;
      clean.appendChild(cleanCode);
      scope.replaceWith(clean);
    }
    clone.querySelectorAll('button, svg, [role="button"]').forEach((n) => n.remove());
    out.push({ role, html: clone.innerHTML });
  }
  return out;
}"""

# Chat column HTML for `dump` (falls back to <body>).
DOM_SNAPSHOT_JS = r"""() => {
  const row = document.querySelector('[class*="Message_row"], [class*="Markdown_markdownContainer"]');
  let el = row;
  for (let i = 0; el && i < 8 && el.parentElement && el.parentElement !== document.body; i++) el = el.parentElement;
  return (el || document.body).outerHTML;
}"""
