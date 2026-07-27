"""Frontend for the scheduler pages.

Rendered server-side and delivered only after the auth gate has passed, so the
markup for the private pages never reaches an unauthenticated browser.

Written as plain strings rather than f-strings: the JavaScript is full of
braces, and f-string interpolation would fight it constantly.
"""

HEAD = (
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="robots" content="noindex, nofollow">'
)

CSS = """
:root {
  color-scheme: dark;
  --bg: #12151b; --panel: #1a1f28; --line: #262d39; --line-soft: #1f2530;
  --text: #e6e9ef; --muted: #8b95a7;
  --accent: #3d6ef5;
  --critical: #e5484d; --mid: #f5a524; --low: #46a758;
  --busy: #0b0d12;
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  padding-bottom: 5rem;
}
header {
  position: sticky; top: 0; z-index: 20;
  background: rgba(18,21,27,.95); backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line); padding: .7rem .9rem;
}
.bar { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.title { font-size: 1rem; font-weight: 650; margin-right: auto; }
button, select {
  background: var(--panel); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px;
  padding: .45rem .7rem; font-size: .85rem; cursor: pointer;
}
button:active { background: #232a35; }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.views { display: flex; gap: .25rem; }
.views button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.range { font-size: .9rem; color: var(--muted); padding: .5rem .9rem 0; }
main { padding: .6rem .9rem; }

/* month grid */
.dow { display: grid; grid-template-columns: repeat(7,1fr); gap: 3px; margin-bottom: 3px; }
.dow div { text-align: center; font-size: .68rem; color: var(--muted); padding: .25rem 0; }
.month { display: grid; grid-template-columns: repeat(7,1fr); gap: 3px; }
.cell {
  min-height: 4.6rem; background: var(--panel); border: 1px solid var(--line-soft);
  border-radius: 7px; padding: .3rem; overflow: hidden; cursor: pointer;
}
.cell.dim { opacity: .38; }
.cell.today { border-color: var(--accent); }
.cell.busy { background: var(--busy); border-color: #000; }
.cell .num { font-size: .72rem; color: var(--muted); margin-bottom: .2rem; }
.cell.today .num { color: var(--accent); font-weight: 700; }
.chip {
  font-size: .62rem; line-height: 1.25; border-radius: 4px;
  padding: .1rem .25rem; margin-bottom: .12rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #fff;
}
.busy-tag { font-size: .6rem; color: #7d8798; letter-spacing: .04em; }

/* week + day */
.week { display: grid; grid-template-columns: repeat(7,1fr); gap: 3px; }
.col { background: var(--panel); border: 1px solid var(--line-soft); border-radius: 7px; padding: .3rem; min-height: 8rem; }
.col h4 { margin: 0 0 .3rem; font-size: .68rem; color: var(--muted); font-weight: 600; text-align: center; }
.col.today h4 { color: var(--accent); }
.col.busy { background: var(--busy); }
.ev {
  border-radius: 6px; padding: .3rem .4rem; margin-bottom: .25rem;
  font-size: .68rem; color: #fff; cursor: pointer;
}
.ev .t { opacity: .85; font-size: .62rem; }
.daylist .ev { font-size: .85rem; padding: .6rem .7rem; }
.daylist .ev .t { font-size: .72rem; }
.empty { color: var(--muted); font-size: .85rem; padding: 1.5rem 0; text-align: center; }

/* legend */
.legend { display: flex; gap: .8rem; flex-wrap: wrap; padding: .7rem .9rem 0; font-size: .72rem; color: var(--muted); }
.legend i { display: inline-block; width: .65rem; height: .65rem; border-radius: 3px; margin-right: .3rem; vertical-align: -1px; }

/* dialogs */
dialog {
  background: var(--panel); color: var(--text);
  border: 1px solid var(--line); border-radius: 12px;
  width: min(94vw, 26rem); padding: 1.1rem;
}
dialog::backdrop { background: rgba(0,0,0,.65); }
dialog h3 { margin: 0 0 .8rem; font-size: 1rem; }
label { display: block; font-size: .75rem; color: var(--muted); margin: .55rem 0 .25rem; }
input, textarea, dialog select {
  width: 100%; padding: .6rem; background: var(--bg); color: var(--text);
  border: 1px solid var(--line); border-radius: 8px; font-size: .95rem; font-family: inherit;
}
textarea { min-height: 4rem; resize: vertical; }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
.actions { display: flex; gap: .5rem; margin-top: 1rem; }
.actions button { flex: 1; }
.danger { background: #3a1d22; border-color: #5d2b33; color: #ffb4bd; }

/* chat */
.fab {
  position: fixed; right: 1rem; bottom: 1rem; z-index: 30;
  border-radius: 999px; padding: .8rem 1.1rem; font-size: .9rem; font-weight: 600;
  background: var(--accent); border-color: var(--accent); color: #fff;
  box-shadow: 0 6px 20px rgba(0,0,0,.4);
}
.chat {
  position: fixed; inset: auto 0 0 0; z-index: 40;
  background: var(--panel); border-top: 1px solid var(--line);
  border-radius: 14px 14px 0 0; display: none; flex-direction: column;
  max-height: 80vh;
}
.chat.open { display: flex; }
.chat-head { display: flex; align-items: center; gap: .5rem; padding: .7rem .9rem; border-bottom: 1px solid var(--line); }
.chat-head strong { font-size: .9rem; margin-right: auto; }
.log { flex: 1; overflow-y: auto; padding: .8rem .9rem; display: flex; flex-direction: column; gap: .55rem; }
.msg { padding: .55rem .7rem; border-radius: 10px; font-size: .85rem; max-width: 85%; white-space: pre-wrap; word-wrap: break-word; }
.msg.me { background: var(--accent); color: #fff; align-self: flex-end; }
.msg.ai { background: #232a35; align-self: flex-start; }
.msg.sys { background: #3a1d22; color: #ffb4bd; align-self: center; font-size: .75rem; }
.chat-in { display: flex; gap: .5rem; padding: .7rem .9rem; border-top: 1px solid var(--line); }
.chat-in input { flex: 1; }
.finder { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: .8rem; margin-bottom: .8rem; }
.finder .row3 { display: grid; grid-template-columns: 1fr 1fr auto; gap: .5rem; }
.result { margin-top: .6rem; font-size: .85rem; color: var(--muted); }
.result b { color: var(--text); }
@media (max-width: 560px) {
  .cell { min-height: 3.9rem; }
  .week { grid-template-columns: 1fr; }
  .finder .row3 { grid-template-columns: 1fr; }
  .title { width: 100%; margin-bottom: .3rem; }
}
"""

LEGEND = """
<div class="legend">
  <span><i style="background:var(--critical)"></i>critical</span>
  <span><i style="background:var(--mid)"></i>mid</span>
  <span><i style="background:var(--low)"></i>low</span>
  <span><i style="background:var(--busy);border:1px solid #333"></i>unavailable (1 critical or 3 mid)</span>
</div>
"""

# Shared calendar engine. MODE is injected per page:
#   full    -> /s        : event details + editing + Gemini
#   detail  -> /sprivate : event details, read-only
#   public  -> /spublic  : availability only, no titles
CALENDAR_JS = r"""
const MODE = "__MODE__";
const TZ = "Asia/Seoul";
const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
let view = "month";
let anchor = new Date();
let events = [];
let avail = {};

const pad = n => String(n).padStart(2, "0");
const iso = d => d.getFullYear() + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate());
const hhmm = s => { const d = new Date(s); return pad(d.getHours()) + ":" + pad(d.getMinutes()); };
const todayIso = () => iso(new Date());

function rangeFor() {
  const a = new Date(anchor);
  if (view === "month") {
    const first = new Date(a.getFullYear(), a.getMonth(), 1);
    const start = new Date(first);
    start.setDate(1 - ((first.getDay() + 6) % 7));       // grid starts Monday
    const end = new Date(start); end.setDate(start.getDate() + 41);
    return [start, end];
  }
  if (view === "week") {
    const start = new Date(a);
    start.setDate(a.getDate() - ((a.getDay() + 6) % 7));
    const end = new Date(start); end.setDate(start.getDate() + 6);
    return [start, end];
  }
  return [new Date(a), new Date(a)];
}

function label() {
  const [s, e] = rangeFor();
  const M = ["January","February","March","April","May","June","July",
             "August","September","October","November","December"];
  if (view === "month") return M[anchor.getMonth()] + " " + anchor.getFullYear();
  if (view === "week")  return iso(s) + "  to  " + iso(e);
  return anchor.toLocaleDateString("en-US",
    { weekday:"long", year:"numeric", month:"long", day:"numeric" });
}

async function load() {
  const [s, e] = rangeFor();
  const qs = "start=" + iso(s) + "&end=" + iso(e);
  const path = MODE === "public" ? "/api/availability?" : "/api/calendar?";
  const res = await fetch(path + qs, { credentials: "same-origin" });
  if (!res.ok) { document.getElementById("grid").innerHTML =
      '<p class="empty">Could not load (' + res.status + ').</p>'; return; }
  const data = await res.json();
  events = data.events || [];
  avail = data.availability || {};
  render();
}

function eventsOn(day) { return events.filter(x => x.day === day); }

function render() {
  document.getElementById("range").textContent = label();
  document.querySelectorAll(".views button").forEach(b =>
    b.classList.toggle("on", b.dataset.view === view));
  const grid = document.getElementById("grid");
  if (view === "month") grid.innerHTML = monthHtml();
  else if (view === "week") grid.innerHTML = weekHtml();
  else grid.innerHTML = dayHtml();
  bindCells();
}

function monthHtml() {
  const [start] = rangeFor();
  let html = '<div class="dow">' + DOW.map(d => "<div>" + d + "</div>").join("") + "</div>";
  html += '<div class="month">';
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const key = iso(d);
    const info = avail[key] || {};
    const cls = ["cell"];
    if (d.getMonth() !== anchor.getMonth()) cls.push("dim");
    if (key === todayIso()) cls.push("today");
    if (info.busy) cls.push("busy");
    html += '<div class="' + cls.join(" ") + '" data-day="' + key + '">';
    html += '<div class="num">' + d.getDate() + "</div>";
    if (MODE === "public") {
      // Availability only: never reveal what the events actually are.
      if (info.busy) html += '<div class="busy-tag">BUSY</div>';
      else if (info.total) html += '<div class="busy-tag">' + info.total + " held</div>";
    } else {
      const list = eventsOn(key);
      list.slice(0, 3).forEach(ev => {
        html += '<div class="chip" style="background:' + ev.color + '">' + esc(ev.title) + "</div>";
      });
      if (list.length > 3) html += '<div class="busy-tag">+' + (list.length - 3) + " more</div>";
    }
    html += "</div>";
  }
  return html + "</div>";
}

function weekHtml() {
  const [start] = rangeFor();
  let html = '<div class="week">';
  for (let i = 0; i < 7; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const key = iso(d);
    const info = avail[key] || {};
    const cls = ["col"];
    if (key === todayIso()) cls.push("today");
    if (info.busy) cls.push("busy");
    html += '<div class="' + cls.join(" ") + '" data-day="' + key + '">';
    html += "<h4>" + DOW[i] + " " + d.getDate() + "</h4>";
    if (MODE === "public") {
      html += info.busy
        ? '<div class="busy-tag">UNAVAILABLE</div>'
        : '<div class="busy-tag">open</div>';
    } else {
      const list = eventsOn(key);
      if (!list.length) html += '<div class="busy-tag">—</div>';
      list.forEach(ev => {
        html += '<div class="ev" data-id="' + ev.id + '" style="background:' + ev.color + '">' +
                '<div class="t">' + hhmm(ev.start) + "</div>" + esc(ev.title) + "</div>";
      });
    }
    html += "</div>";
  }
  return html + "</div>";
}

function dayHtml() {
  const key = iso(anchor);
  const info = avail[key] || {};
  if (MODE === "public") {
    return '<div class="empty">' + (info.busy ? "Unavailable this day."
      : (info.total ? info.total + " commitment(s), still open." : "Fully open.")) + "</div>";
  }
  const list = eventsOn(key);
  if (!list.length) return '<div class="empty">Nothing scheduled.</div>';
  let html = '<div class="daylist">';
  list.forEach(ev => {
    html += '<div class="ev" data-id="' + ev.id + '" style="background:' + ev.color + '">' +
            '<div class="t">' + hhmm(ev.start) + "–" + hhmm(ev.end) + " · " + ev.importance + "</div>" +
            esc(ev.title) + (ev.notes ? '<div class="t">' + esc(ev.notes) + "</div>" : "") + "</div>";
  });
  return html + "</div>";
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g,
    c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function bindCells() {
  document.querySelectorAll(".cell").forEach(c => c.onclick = () => {
    anchor = new Date(c.dataset.day + "T00:00:00");
    view = "day"; render();
  });
  if (MODE === "full") {
    document.querySelectorAll(".ev").forEach(el => el.onclick = ev => {
      ev.stopPropagation(); openEdit(Number(el.dataset.id));
    });
  }
}

function step(dir) {
  if (view === "month") anchor.setMonth(anchor.getMonth() + dir);
  else if (view === "week") anchor.setDate(anchor.getDate() + 7 * dir);
  else anchor.setDate(anchor.getDate() + dir);
  anchor = new Date(anchor); load();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".views button").forEach(b =>
    b.onclick = () => { view = b.dataset.view; load(); });
  document.getElementById("prev").onclick = () => step(-1);
  document.getElementById("next").onclick = () => step(1);
  document.getElementById("today").onclick = () => { anchor = new Date(); load(); };
  load();
});
"""

FINDER_HTML = """
<div class="finder">
  <div class="row3">
    <select id="f-day">
      <option value="any">Any day</option>
      <option value="weekday">Weekday</option>
      <option value="weekend">Weekend</option>
    </select>
    <select id="f-band">
      <option value="morning">Morning</option>
      <option value="afternoon">Afternoon</option>
      <option value="evening">Evening</option>
    </select>
    <button class="primary" id="f-go">Find</button>
  </div>
  <div class="result" id="f-result">Find the closest opening.</div>
</div>
"""

FINDER_JS = r"""
document.addEventListener("DOMContentLoaded", () => {
  const out = document.getElementById("f-result");
  document.getElementById("f-go").onclick = async () => {
    out.textContent = "Searching...";
    const q = "day_type=" + document.getElementById("f-day").value +
              "&band=" + document.getElementById("f-band").value;
    const r = await fetch("/api/availability/find?" + q, { credentials: "same-origin" });
    const d = await r.json();
    if (!r.ok) { out.textContent = d.detail || "Search failed."; return; }
    out.innerHTML = d.found
      ? "Closest opening: <b>" + d.date + " (" + d.weekday + ")</b> — " + d.band +
        ", from <b>" + d.start.slice(11,16) + "</b> to <b>" + d.end.slice(11,16) + "</b>"
      : "No opening found in the next 90 days.";
  };
});
"""

EDIT_DIALOG = """
<dialog id="edit">
  <h3 id="edit-title">Event</h3>
  <input type="hidden" id="e-id">
  <label for="e-title">Title</label>
  <input id="e-title" required>
  <div class="row2">
    <div><label for="e-start">Start</label><input id="e-start" type="datetime-local"></div>
    <div><label for="e-end">End</label><input id="e-end" type="datetime-local"></div>
  </div>
  <label for="e-imp">Importance</label>
  <select id="e-imp">
    <option value="critical">Critical</option>
    <option value="mid">Mid</option>
    <option value="low">Low</option>
  </select>
  <label for="e-notes">Notes</label>
  <textarea id="e-notes"></textarea>
  <div class="actions">
    <button id="e-save" class="primary">Save</button>
    <button id="e-del" class="danger">Delete</button>
    <button id="e-cancel">Close</button>
  </div>
</dialog>
"""

EDIT_JS = r"""
const dlg = document.getElementById("edit");
function localValue(d) {
  return d.getFullYear() + "-" + pad(d.getMonth()+1) + "-" + pad(d.getDate()) +
         "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
}
function openNew() {
  const s = new Date(anchor); s.setHours(9,0,0,0);
  const e = new Date(s); e.setHours(10,0,0,0);
  document.getElementById("edit-title").textContent = "New event";
  document.getElementById("e-id").value = "";
  document.getElementById("e-title").value = "";
  document.getElementById("e-start").value = localValue(s);
  document.getElementById("e-end").value = localValue(e);
  document.getElementById("e-imp").value = "mid";
  document.getElementById("e-notes").value = "";
  document.getElementById("e-del").style.display = "none";
  dlg.showModal();
}
function openEdit(id) {
  const ev = events.find(x => x.id === id);
  if (!ev) return;
  document.getElementById("edit-title").textContent = "Edit event";
  document.getElementById("e-id").value = ev.id;
  document.getElementById("e-title").value = ev.title;
  document.getElementById("e-start").value = ev.start.slice(0,16);
  document.getElementById("e-end").value = ev.end.slice(0,16);
  document.getElementById("e-imp").value = ev.importance;
  document.getElementById("e-notes").value = ev.notes || "";
  document.getElementById("e-del").style.display = "";
  dlg.showModal();
}
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("add").onclick = openNew;
  document.getElementById("e-cancel").onclick = () => dlg.close();
  document.getElementById("e-save").onclick = async () => {
    const id = document.getElementById("e-id").value;
    const body = {
      title: document.getElementById("e-title").value.trim(),
      start: document.getElementById("e-start").value,
      end: document.getElementById("e-end").value,
      importance: document.getElementById("e-imp").value,
      notes: document.getElementById("e-notes").value
    };
    if (!body.title) { alert("Title required."); return; }
    const r = await fetch(id ? "/api/events/" + id : "/api/events", {
      method: id ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body)
    });
    if (!r.ok) { const e = await r.json().catch(()=>({})); alert(e.detail || "Save failed."); return; }
    dlg.close(); load();
  };
  document.getElementById("e-del").onclick = async () => {
    const id = document.getElementById("e-id").value;
    if (!id || !confirm("Delete this event?")) return;
    const r = await fetch("/api/events/" + id, { method: "DELETE", credentials: "same-origin" });
    if (!r.ok) { alert("Delete failed."); return; }
    dlg.close(); load();
  };
});
"""

CHAT_HTML = """
<button class="fab" id="fab">Ask Gemini</button>
<section class="chat" id="chat">
  <div class="chat-head">
    <strong>Gemini</strong>
    <button id="key-btn">API key</button>
    <button id="chat-close">Close</button>
  </div>
  <div class="log" id="log"></div>
  <div class="chat-in">
    <input id="chat-input" placeholder="e.g. dentist Friday 3pm, critical" autocomplete="off">
    <button class="primary" id="send">Send</button>
  </div>
</section>

<dialog id="keydlg">
  <h3>Gemini API key</h3>
  <p style="font-size:.8rem;color:var(--muted);margin:0 0 .3rem">
    Stored server-side and never sent back to the browser. Get a free key at
    aistudio.google.com/apikey
  </p>
  <label for="k-val">Key</label>
  <input id="k-val" type="password" placeholder="AIza...">
  <div class="actions">
    <button class="primary" id="k-save">Save</button>
    <button id="k-cancel">Cancel</button>
  </div>
</dialog>
"""

CHAT_JS = r"""
let history = [];
const chat = document.getElementById("chat");
const logEl = document.getElementById("log");

function say(text, cls) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.textContent = text;
  logEl.appendChild(d);
  logEl.scrollTop = logEl.scrollHeight;
  return d;
}

async function send() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  say(text, "me");
  history.push({ role: "user", text: text });
  const pending = say("...", "ai");
  try {
    const r = await fetch("/api/gemini/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ message: text, history: history.slice(0, -1) })
    });
    const d = await r.json();
    if (!r.ok) {
      pending.remove();
      say(d.detail || "Gemini error.", "sys");
      if (r.status === 428) document.getElementById("keydlg").showModal();
      return;
    }
    pending.textContent = d.reply;
    history.push({ role: "model", text: d.reply });
    // A tool call means the calendar changed underneath us.
    if (d.actions && d.actions.length) load();
  } catch (err) {
    pending.remove();
    say("Network error.", "sys");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("fab").onclick = () => {
    chat.classList.add("open");
    document.getElementById("chat-input").focus();
  };
  document.getElementById("chat-close").onclick = () => chat.classList.remove("open");
  document.getElementById("send").onclick = send;
  document.getElementById("chat-input").addEventListener("keydown", e => {
    if (e.key === "Enter") send();
  });

  const kd = document.getElementById("keydlg");
  document.getElementById("key-btn").onclick = () => kd.showModal();
  document.getElementById("k-cancel").onclick = () => kd.close();
  document.getElementById("k-save").onclick = async () => {
    const v = document.getElementById("k-val").value.trim();
    if (!v) return;
    const r = await fetch("/api/settings/gemini-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ key: v })
    });
    if (r.ok) { document.getElementById("k-val").value = ""; kd.close(); say("API key saved.", "sys"); }
    else alert("Could not save key.");
  };

  fetch("/api/settings", { credentials: "same-origin" })
    .then(r => r.json())
    .then(d => { if (!d.gemini_key_set) say("Set your Gemini API key to start.", "sys"); });
});
"""


def _shell(title: str, header_extra: str, body: str, scripts: str, mode: str) -> str:
    return (
        "<!doctype html><html lang=\"en\"><head>"
        + HEAD
        + f"<title>{title}</title><style>{CSS}</style></head><body>"
        + '<header><div class="bar">'
        + f'<span class="title">{title}</span>'
        + '<div class="views">'
        '<button data-view="month">Month</button>'
        '<button data-view="week">Week</button>'
        '<button data-view="day">Day</button>'
        "</div>"
        '<button id="prev">&lsaquo;</button>'
        '<button id="today">Today</button>'
        '<button id="next">&rsaquo;</button>'
        + header_extra
        + '</div><div class="range" id="range"></div>'
        + LEGEND
        + "</header><main>"
        + body
        + '<div id="grid"></div></main>'
        + "<script>"
        + CALENDAR_JS.replace("__MODE__", mode)
        + scripts
        + "</script></body></html>"
    )


def scheduler_page() -> str:
    """/s — full manager: calendar, manual editing, and Gemini CRUD."""
    return _shell(
        "Schedule",
        '<button class="primary" id="add">+ Add</button>',
        EDIT_DIALOG + CHAT_HTML,
        EDIT_JS + CHAT_JS,
        "full",
    )


def private_page() -> str:
    """/sprivate — event specifics, read-only, with the availability finder."""
    return _shell("Schedule detail", "", FINDER_HTML, FINDER_JS, "detail")


def public_page() -> str:
    """/spublic — availability only. No titles or notes are ever sent here."""
    return _shell("Availability", "", FINDER_HTML, FINDER_JS, "public")
