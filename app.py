"""Main Streamlit application â€” all views, navigation, streaming, and state management."""

import streamlit as st
import streamlit.components.v1 as components
import time
import json
import html
import concurrent.futures
import markdown as _md_lib
from datetime import datetime, date, timedelta, timezone

# â”€â”€ Timing utility â”€â”€
_t_start_run = time.perf_counter()
_t_log: list[tuple[str, float]] = []

def _t(label: str):
    """Record a timing checkpoint with the given label."""
    _t_log.append((label, time.perf_counter()))

def _t_report():
    """Print a per-rerun timing report to the terminal."""
    total = time.perf_counter() - _t_start_run
    print(f"\n{'='*65}")
    print(f"  PERF REPORT (all times ms)")
    print(f"{'='*65}")
    prev = _t_start_run
    for label, t in _t_log:
        elapsed = (t - prev) * 1000
        print(f"  {label:35s} {elapsed:8.1f} ms")
        prev = t
    print(f"  {'TOTAL':35s} {total*1000:8.1f} ms")
    print(f"{'='*65}\n")

_db_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

from memory import save_interview_report, build_interview_memory_context
from ai import ask_ai, analyze_resume
from resume import extract_resume_text
from interview import (
    generate_interview_questions,
    generate_interview_questions_with_memory,
    evaluate_answer,
    evaluate_answer_with_memory,
    generate_final_report,
    generate_structured_report,
)
from career import recommend_career, recommend_career_standalone, generate_learning_roadmap

import ui
import auth
import chat as chat_db
import database
import assessment


def _db_failed():
    """Reset cached DB and profile flags so they are re-checked on next rerun."""
    st.session_state.pop("_db_ok", None)
    st.session_state.pop("_db_missing", None)
    st.session_state.pop("_profile_ensured", None)


st.set_page_config(
    page_title="AI Placement Mentor",
    page_icon="ðŸ¤–",
    layout="wide",
    initial_sidebar_state="expanded",
)

_t("set_page_config")

# â”€â”€ CSS: injected every rerun (Streamlit rebuilds the DOM) â”€â”€
ui.load_css("styles.css")
_t("load_css")

# --- theme state ---
if "theme" not in st.session_state:
    params = st.query_params
    t = params.get("t", "dark")
    st.session_state.theme = t if t in ("light", "dark") else "dark"
_t("theme_state")

# =============================================================
# AUTH CHECK â€” unauthenticated users see login/signup only
# =============================================================
if not auth.is_authenticated():
    _t("auth_ui")
    ui.show_auth_ui()
    _t("auth_ui_done")
    st.stop()
_t("auth_check")

# =============================================================
# AUTHENTICATED â€” main application below
# =============================================================
user = auth.get_current_user()
user_id = user["id"]
_t("user_setup")

# â”€â”€ DB Health Check (cache after first success) â”€â”€
if "_db_ok" not in st.session_state:
    try:
        db_ok_result, db_missing_list = database.check_tables()
        st.session_state._db_ok = db_ok_result
        st.session_state._db_missing = db_missing_list
        st.session_state._db_error = None
    except Exception as e:
        st.session_state._db_ok = False
        st.session_state._db_missing = []
        st.session_state._db_error = str(e)
if not st.session_state._db_ok:
    ui.show_db_setup_message(
        missing=st.session_state.get("_db_missing"),
        error=st.session_state.get("_db_error"),
    )
    st.stop()
_t("db_health_check")

# â”€â”€ Ensure profile exists (cache after first success) â”€â”€
if "_profile_ensured" not in st.session_state:
        profile_ok = database.ensure_profile(user_id, user.get("email", ""))
        st.session_state._profile_ensured = profile_ok
_t("ensure_profile")

# --- Warm up AI provider on startup (not at import time) ---
import ai as ai_module
_t("import_ai")
if not ai_module.is_ready() and not st.session_state.get("_warmup_attempted"):
    st.session_state._warmup_attempted = True
    with st.status("Initializing AI...", expanded=True) as s:
        st.write("Connecting to AI provider...")
        ok = ai_module.warmup_ai()
        if ok:
            s.update(label="AI Ready", state="complete", expanded=False)
        else:
            err = ai_module.get_warmup_error()
            s.update(label=f"AI initialization failed: {err}", state="error")
    _t("ai_warmup")
    st.rerun()

# Show warmup error banner if initialization failed but we've already attempted
if not ai_module.is_ready() and st.session_state.get("_warmup_attempted"):
    err = ai_module.get_warmup_error()
    if err:
        st.warning(f"âš ï¸ **AI service unavailable:** {err}")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("ðŸ”„ Retry AI Initialization", use_container_width=True):
                st.session_state._warmup_attempted = False
                st.session_state.pop("ai_ready", None)
                st.rerun()
        with col2:
            if st.button("â© Continue Anyway", use_container_width=True):
                st.session_state._ai_continue = True
                st.rerun()
_t("warmup_check")

# --- Top bar (pure HTML buttons, JS injected via iframe) ---
cur_theme = st.session_state.theme
theme_icon = "\U0001f319" if cur_theme == "dark" else "\u2600\ufe0f"
st.markdown(f"""
<div id="top-bar-overlay">
<button id="hamburger-btn" aria-label="Toggle sidebar">\u2630</button>
<button id="theme-toggle-btn" aria-label="Toggle theme">{theme_icon}</button>
</div>
""", unsafe_allow_html=True)

# --- JS via same-origin iframe (injected every rerun â€” DOM is rebuilt) ---
components.html(f"""
<script>
(function() {{
  var w = window.parent;
  var doc = w.document;
  var el = doc.documentElement;
  if (!el.hasAttribute('data-theme')) el.setAttribute('data-theme', '{cur_theme}');
  if (!el.hasAttribute('data-sidebar-open')) el.setAttribute('data-sidebar-open', 'true');
  if (!w.__apmBooted) {{
    w.__apmBooted = true;
    try {{ var s = w.localStorage.getItem('apm_theme'); if (s && s !== '{cur_theme}' && w.location.search.indexOf('t=') < 0) {{ w.location.search = '?t=' + s; return; }} }} catch(e) {{}}
    try {{ var ss = w.localStorage.getItem('apm_sidebar'); if (ss) el.setAttribute('data-sidebar-open', ss); }} catch(e) {{}}
    try {{ var mq = w.matchMedia('(prefers-color-scheme:light)'); mq.addEventListener('change', function(e) {{ try {{ if (!w.localStorage.getItem('apm_theme')) el.setAttribute('data-theme', e.matches ? 'light' : 'dark'); }} catch(ex) {{}} }}); }} catch(ex) {{}}
  }}
  var b = doc.getElementById('theme-toggle-btn');
  if (b) {{ var t = el.getAttribute('data-theme') || 'dark'; b.textContent = t === 'dark' ? '\\u{{1F319}}' : '\\u{{2600}}\\u{{FE0F}}'; }}
  var h = doc.getElementById('hamburger-btn');
  if (h) {{ h.onclick = function() {{
    var e2 = doc.documentElement;
    var c2 = e2.getAttribute('data-sidebar-open');
    var n2 = c2 === 'true' ? 'false' : 'true';
    e2.setAttribute('data-sidebar-open', n2);
    try {{ w.localStorage.setItem('apm_sidebar', n2); }} catch(ex) {{}}
  }}; }}
  var t2 = doc.getElementById('theme-toggle-btn');
  if (t2) {{ t2.onclick = function() {{
    var e3 = doc.documentElement;
    var c3 = e3.getAttribute('data-theme');
    var n3 = c3 === 'dark' ? 'light' : 'dark';
    e3.setAttribute('data-theme', n3);
    this.textContent = n3 === 'dark' ? '\\u{{1F319}}' : '\\u{{2600}}\\u{{FE0F}}';
    try {{ w.localStorage.setItem('apm_theme', n3); }} catch(ex) {{}}
  }}; }}
  // Mobile: close sidebar when tapping outside
  if (!w.__apmMobileClose) {{
    w.__apmMobileClose = true;
    doc.addEventListener('click', function(e) {{
      if (w.innerWidth > 768) return;
      var s = doc.querySelector('[data-testid="stSidebar"]');
      var h = doc.getElementById('hamburger-btn');
      if (!s || !h) return;
      if (doc.documentElement.getAttribute('data-sidebar-open') !== 'true') return;
      if (s.contains(e.target) || h.contains(e.target)) return;
      doc.documentElement.setAttribute('data-sidebar-open', 'false');
      try {{ w.localStorage.setItem('apm_sidebar', 'false'); }} catch(ex) {{}}
    }});
  }}
  // Keyboard shortcuts (registered once)
  if (!w.__apmKS) {{
    w.__apmKS = true;
    doc.addEventListener('keydown', function(e) {{
      if (e.ctrlKey && e.key === 'n') {{
        e.preventDefault();
        var nb = doc.querySelector('.new-chat-btn button');
        if (nb) nb.click();
      }}
      if (e.ctrlKey && e.key === 'f') {{
        e.preventDefault();
        var si = doc.querySelector('[data-testid*=stTextInput] input');
        if (si) setTimeout(function() {{ si.focus(); si.select(); }}, 50);
      }}
    }});
  }}
  // No JS-managed footer â€” footer is now a native Streamlit element below the chat input
}})();
</script>
""", height=0)
_t("top_bar_and_js")

# --- session state (fast: only runs for missing keys) ---
for key in [
    "messages", "interview_started", "interview_questions",
    "interview_finished", "current_question", "feedback",
    "answer_submitted", "interview_results", "career_report",
    "show_uploader", "resume_filename", "resume_analysis",
    "_awaiting_response", "chat_started",
]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in [
            "messages", "interview_questions", "interview_results"
        ] else (False if key in [
            "interview_started", "interview_finished", "answer_submitted", "show_uploader",
            "_awaiting_response", "chat_started",
        ] else (""))

if "resume_analysis" in st.session_state and st.session_state.resume_analysis is None:
    st.session_state.resume_analysis = ""

if "resume_filename" in st.session_state and st.session_state.resume_filename is None:
    st.session_state.resume_filename = ""

if "current_view" not in st.session_state:
    st.session_state.current_view = "chat"
_t("session_state_init")

# --- chat state (loaded from Supabase) ---
_t("chat_state_start")
if "chats" not in st.session_state:
    st.session_state.chats = chat_db.load_chats(user_id)
    _t("load_chats")

if "current_chat_id" not in st.session_state:
    if st.session_state.chats:
        sorted_chats = sorted(
            st.session_state.chats.items(),
            key=lambda x: x[1].get("updated_at", x[1]["created_at"]),
            reverse=True,
        )
        st.session_state.current_chat_id = sorted_chats[0][0]
        st.session_state.messages = chat_db.load_messages(sorted_chats[0][0])
        st.session_state.chat_started = bool(st.session_state.messages)
        st.session_state.chats[sorted_chats[0][0]]["messages"] = list(st.session_state.messages)
        _t("load_messages")
    else:
        _cid = chat_db.create_chat(user_id)
        _now = datetime.now().isoformat()
        st.session_state.chats[_cid] = {
            "id": _cid, "title": "New Chat",
            "created_at": _now, "updated_at": _now,
            "pinned": False, "messages": [],
        }
        st.session_state.current_chat_id = _cid
        st.session_state.messages = []
        _t("create_first_chat")

if "chat_search" not in st.session_state:
    st.session_state.chat_search = ""
if "rename_chat_id" not in st.session_state:
    st.session_state.rename_chat_id = None
if "delete_chat_id" not in st.session_state:
    st.session_state.delete_chat_id = None

# Ensure current_chat_id exists in chats dict
if st.session_state.current_chat_id is not None and st.session_state.current_chat_id not in st.session_state.chats:
    if st.session_state.chats:
        sorted_c = sorted(
            st.session_state.chats.items(),
            key=lambda x: x[1].get("updated_at", x[1]["created_at"]), reverse=True,
        )
        st.session_state.current_chat_id = sorted_c[0][0]
        st.session_state.messages = chat_db.load_messages(sorted_c[0][0])
    else:
        st.session_state.current_chat_id = None
        st.session_state.messages = []

# --- chat functions (Supabase-backed) ---
def _new_chat():
    """Create a new chat in Supabase and set it as the active conversation."""
    cid = chat_db.create_chat(user_id)
    now = datetime.now().isoformat()
    st.session_state.chats[cid] = {
        "id": cid, "title": "New Chat",
        "created_at": now, "updated_at": now,
        "pinned": False, "messages": [],
    }
    st.session_state.current_chat_id = cid
    st.session_state.messages = []
    st.session_state.chat_started = False

def _select_chat(cid):
    """Switch to an existing chat and load its messages from Supabase."""
    st.session_state.current_chat_id = cid
    st.session_state.messages = chat_db.load_messages(cid)
    st.session_state.chat_started = bool(st.session_state.messages)
    if cid in st.session_state.chats:
        st.session_state.chats[cid]["messages"] = list(st.session_state.messages)

def _delete_chat(cid):
    """Delete a chat from Supabase and remove it from session state; fall back to next chat or create new."""
    chat_db.delete_chat(cid, user_id)
    if cid in st.session_state.chats:
        del st.session_state.chats[cid]
    if st.session_state.current_chat_id == cid:
        if st.session_state.chats:
            sorted_c = sorted(
                st.session_state.chats.items(),
                key=lambda x: x[1].get("updated_at", x[1]["created_at"]), reverse=True,
            )
            _select_chat(sorted_c[0][0])
        else:
            _new_chat()

def _toggle_pin(cid):
    """Toggle the pinned status of a chat, syncing to Supabase."""
    if cid in st.session_state.chats:
        st.session_state.chats[cid]["pinned"] = not st.session_state.chats[cid]["pinned"]
        st.session_state.chats[cid]["updated_at"] = datetime.now().isoformat()
    if not chat_db.update_chat(cid, user_id, {"pinned": st.session_state.chats[cid]["pinned"]}):
        _db_failed()

def _rename_chat(cid, title):
    """Rename a chat in session state and sync to Supabase."""
    if cid in st.session_state.chats:
        st.session_state.chats[cid]["title"] = title
        st.session_state.chats[cid]["updated_at"] = datetime.now().isoformat()
    if not chat_db.update_chat(cid, user_id, {"title": title}):
        _db_failed()

def _duplicate_chat(cid):
    """Create a copy of a chat (title + messages) in Supabase and session state."""
    chat = st.session_state.chats[cid]
    new_id = chat_db.create_chat(user_id, chat["title"] + " (Copy)")
    now = datetime.now().isoformat()
    for msg in chat.get("messages", []):
        if not chat_db.save_message(new_id, user_id, msg["role"], msg["content"], msg.get("timestamp", ""), msg.get("metadata") or {}):
            _db_failed()
    st.session_state.chats[new_id] = {
        "id": new_id, "title": chat["title"] + " (Copy)",
        "created_at": now, "updated_at": now,
        "pinned": False, "messages": list(chat.get("messages", [])),
    }

def open_chat(chat_id=None, is_new=False):
    """Switch to Chat view and select or create a conversation."""
    _sync_current_chat()
    if is_new:
        _new_chat()
    elif chat_id:
        _select_chat(chat_id)
    st.session_state.current_view = "chat"
    st.session_state._awaiting_response = False

def _generate_chat_title(msg):
    """Truncate first user message to â‰¤40 chars for use as the chat title."""
    msg = msg.strip().replace("\n", " ")
    if len(msg) > 40:
        return msg[:40] + "..."
    return msg

def _sync_current_chat():
    """Sync the current chat's messages and updated_at timestamp to Supabase."""
    cid = st.session_state.current_chat_id
    if cid and cid in st.session_state.chats:
        st.session_state.chats[cid]["messages"] = list(st.session_state.messages)
        st.session_state.chats[cid]["updated_at"] = datetime.now().isoformat()
        if not chat_db.sync_chat(cid, user_id):
            _db_failed()

def _render_chat_list():
    """Render the sidebar chat list with search, pinned items first, then recent."""
    chats = st.session_state.chats
    search = st.session_state.chat_search.strip().lower()
    current_id = st.session_state.current_chat_id

    if not chats:
        st.markdown('<div class="chat-empty">No conversations yet.</div>', unsafe_allow_html=True)
        return

    filtered = {}
    for cid, chat in chats.items():
        if not search or search in chat["title"].lower():
            filtered[cid] = chat

    today_d = date.today()
    yesterday_d = today_d - timedelta(days=1)
    week_ago_d = today_d - timedelta(days=7)

    groups = {"pinned": [], "today": [], "yesterday": [], "week": [], "older": []}
    for cid, chat in filtered.items():
        try:
            created = datetime.fromisoformat(chat.get("updated_at", chat["created_at"])).date()
        except (ValueError, TypeError):
            created = today_d
        if chat.get("pinned"):
            groups["pinned"].append(cid)
        elif created == today_d:
            groups["today"].append(cid)
        elif created == yesterday_d:
            groups["yesterday"].append(cid)
        elif created >= week_ago_d:
            groups["week"].append(cid)
        else:
            groups["older"].append(cid)

    for key in groups:
        groups[key].sort(key=lambda cid: chats[cid].get("updated_at", chats[cid]["created_at"]), reverse=True)

    group_labels = {"pinned": "\U0001f4cc Pinned", "today": "Today", "yesterday": "Yesterday", "week": "Last 7 Days", "older": "Older"}

    for key, label in group_labels.items():
        ids = groups[key]
        if not ids:
            continue
        st.markdown(f'<div class="chat-group-label">{label}</div>', unsafe_allow_html=True)
        for cid in ids:
            chat = chats[cid]
            active = cid == current_id
            title = chat["title"]

            if st.session_state.rename_chat_id == cid:
                new_title = st.text_input("", value=title, key=f"rin_{cid}", label_visibility="collapsed", placeholder="Chat title...")
                rc1, rc2 = st.columns(2)
                with rc1:
                    if st.button("\u2705 Save", key=f"rns_{cid}", use_container_width=True):
                        _rename_chat(cid, new_title)
                        st.session_state.rename_chat_id = None
                        st.rerun()
                with rc2:
                    if st.button("\u274c", key=f"rnc_{cid}", use_container_width=True):
                        st.session_state.rename_chat_id = None
                        st.rerun()
                continue

            if st.session_state.delete_chat_id == cid:
                st.warning(f"Delete \u201c{title}\u201d?")
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("\U0001f5d1\ufe0f Delete", key=f"cfd_{cid}", use_container_width=True):
                        _delete_chat(cid)
                        st.session_state.delete_chat_id = None
                        st.rerun()
                with dc2:
                    if st.button("Cancel", key=f"ccl_{cid}", use_container_width=True):
                        st.session_state.delete_chat_id = None
                        st.rerun()
                continue

            cols = st.columns([5, 1, 1])
            with cols[0]:
                sel = "\u25c0 " if active else ""
                btn_label = f"{sel}{title}"
                if st.button(btn_label, key=f"cht_{cid}", use_container_width=True):
                    open_chat(chat_id=cid)
                    st.rerun()
            with cols[1]:
                star = "\u2b50" if chat.get("pinned") else "\u2606"
                if st.button(star, key=f"stt_{cid}", help="Toggle pin"):
                    _toggle_pin(cid)
                    st.rerun()
            with cols[2]:
                with st.popover("\u22ee", key=f"m_{cid}"):
                    if st.button("\u270f\ufe0f Rename", key=f"ren_{cid}", use_container_width=True):
                        st.session_state.rename_chat_id = cid
                        st.rerun()
                    if st.button("\U0001f4cb Duplicate", key=f"dup_{cid}", use_container_width=True):
                        _duplicate_chat(cid)
                        st.rerun()
                    chat_json = json.dumps(chat, indent=2, ensure_ascii=False)
                    st.download_button("\U0001f4e5 Export", data=chat_json, file_name=f"{title}.json", mime="application/json", key=f"exp_{cid}", use_container_width=True)
                    st.markdown('<div class="chat-menu-sep"></div>', unsafe_allow_html=True)
                    if st.button("\U0001f5d1\ufe0f Delete", key=f"del_{cid}", use_container_width=True):
                        st.session_state.delete_chat_id = cid
                        st.rerun()

# --- sidebar ---
with st.sidebar:
    _t("sidebar_start")
    ui.sidebar_header()

    # + New Chat
    st.markdown('<div class="new-chat-btn">', unsafe_allow_html=True)
    if st.button("+ New Chat", use_container_width=True, type="primary", key="new_chat_btn"):
        open_chat(is_new=True)
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    # Search
    st.text_input("\U0001f50d Search chats\u2026", key="chat_search", placeholder="Search chats\u2026", label_visibility="collapsed")

    # Scrollable chat list
    st.markdown('<div class="chat-list-scroll">', unsafe_allow_html=True)
    _render_chat_list()
    _t("sidebar_chat_list")
    st.markdown("</div>", unsafe_allow_html=True)

    interview_st = "Running" if st.session_state.interview_started else "Not Started"
    if st.session_state.interview_finished:
        interview_st = "Completed"
    _t("sidebar_dashboard_start")
    ui.dashboard(
        total_chats=len(st.session_state.messages),
        resume_status="Uploaded" if "resume_text" in st.session_state else "Not Uploaded",
        interview_status=interview_st,
        memory_status="Enabled",
    )
    _t("sidebar_dashboard_done")

    _t("sidebar_nav_start")
    st.markdown('<div class="sidebar-heading">Views</div>', unsafe_allow_html=True)

    cur = st.session_state.current_view
    for vid, vicon, vlabel in [
        ("dashboard", "\U0001f4ca", "Dashboard"),
        ("chat", "\U0001f4ac", "Chat"),
        ("resume", "\U0001f4c4", "Resume Analyzer"),
        ("interview", "\U0001f3a4", "Mock Interview"),
        ("career", "\U0001f3af", "Career"),
        ("history", "\U0001f4ca", "History"),
        ("weaknesses", "\U0001f6a9", "Weaknesses"),
        ("roadmap", "\U0001f9ed", "Roadmap"),
    ]:
        cls = "nav-btn-active" if cur == vid else ""
        st.markdown(f'<div class="{cls}">', unsafe_allow_html=True)
        if st.button(f"{vicon} {vlabel}", key=f"nv_{vid}", use_container_width=True):
            _sync_current_chat()
            st.session_state.current_view = vid
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    _t("sidebar_nav_done")

    st.divider()

    # Logout button
    st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
    if st.button("\U0001f6aa Sign Out", use_container_width=True):
        _sync_current_chat()
        auth.sign_out()
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.current_view == "chat":
        st.markdown('<div class="clear-btn">', unsafe_allow_html=True)
        if st.button("\U0001f5d1\ufe0f Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.session_state.chat_started = False
            st.session_state._awaiting_response = False
            if st.session_state.current_chat_id and st.session_state.current_chat_id in st.session_state.chats:
                st.session_state.chats[st.session_state.current_chat_id]["messages"] = []
                st.session_state.chats[st.session_state.current_chat_id]["updated_at"] = datetime.now().isoformat()
                if not chat_db.sync_chat(st.session_state.current_chat_id, user_id):
                    _db_failed()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    _t("sidebar_end")

# --- markdown renderer ---
def _md(text: str) -> str:
    """Render Markdown to HTML with fenced code, tables, and line-break extensions."""
    return _md_lib.markdown(text, extensions=["fenced_code", "tables", "nl2br"])


# --- weakness category mapping ---
WEAKNESS_CATEGORY_KEYWORDS = [
    ("DSA", ["dsa", "algorithm", "data structure", "tree", "graph", "sorting", "searching", "array", "linked list", "stack", "queue", "dp", "dynamic programming", "recursion", "binary", "complexity"]),
    ("OOP", ["oop", "object-oriented", "object oriented", "inheritance", "polymorphism", "encapsulation", "abstraction", "class", "object design"]),
    ("DBMS", ["dbms", "database", "sql", "query", "normalization", "indexing", "transaction", "acid", "join", "schema", "erd"]),
    ("Operating Systems", ["operating system", "os ", "process", "thread", "memory management", "scheduling", "file system", "deadlock", "semaphore", "mutex", "paging", "segmentation"]),
    ("Computer Networks", ["network", "computer network", "tcp", "ip ", "http", "dns", "routing", "protocol", "socket", "osi", "nat"]),
    ("Aptitude", ["aptitude", "logical", "quantitative", "verbal", "numerical", "reasoning"]),
    ("Projects", ["project", "portfolio", "github", "resume project"]),
    ("Communication", ["communication", "presentation", "speaking", "articulate", "explain", "soft skill"]),
    ("Problem Solving", ["problem solving", "problem-solving", "critical thinking", "analytical", "logic", "approach"]),
]


def _map_weakness_category(text: str) -> str:
    """Map a weakness text to a predefined category based on keyword matching."""
    tl = text.lower()
    for cat, kws in WEAKNESS_CATEGORY_KEYWORDS:
        if any(kw in tl for kw in kws):
            print(f"[WEAKNESS MAP] '{text[:40]}' -> {cat}")
            return cat
    print(f"[WEAKNESS MAP] '{text[:40]}' -> General (unmapped)")
    return "General"


# --- metadata bar helper ---
def _meta_bar(info: dict) -> str:
    """Build a runtime card HTML snippet for assistant response metadata."""
    provider = info.get("provider") or "Groq"
    model = info.get("model", "")
    latency = info.get("latency", 0)
    cost = info.get("cost", 0)

    items = []
    items.append(
        '<span class="rt-item rt-exec">'
        '<span class="rt-icon">\u26a1</span>'
        '<span class="rt-val">CascadeFlow</span>'
        '</span>'
    )
    items.append(
        '<span class="rt-item rt-provider">'
        '<span class="rt-icon">\u2601\ufe0f</span>'
        f'<span class="rt-val">{html.escape(str(provider))}</span>'
        '</span>'
    )
    if model:
        items.append(
            '<span class="rt-item rt-model">'
            '<span class="rt-icon">\U0001f916</span>'
            f'<span class="rt-val">{html.escape(str(model))}</span>'
            '</span>'
        )
    if latency:
        items.append(
            '<span class="rt-item rt-latency">'
            '<span class="rt-icon">\u23f1</span>'
            f'<span class="rt-val">{latency/1000:.2f}s</span>'
            '</span>'
        )
    if cost and cost > 0:
        cost_str = f"${cost:.6f}" if cost < 0.001 else f"${cost:.5f}"
        items.append(
            '<span class="rt-item rt-cost">'
            '<span class="rt-icon">\U0001f4b2</span>'
            f'<span class="rt-val">{cost_str}</span>'
            '</span>'
        )

    primary = '<span class="rt-pri">' + ''.join(items) + '</span>'

    route = str(info.get("_route_display") or "")
    reason = str(info.get("_reason_display") or "")
    if not route or not reason:
        clean_route, clean_reason = _classify_request(model, info.get("prompt", ""))
        if not route:
            route = clean_route
        if not reason:
            reason = clean_reason
    second_items = []
    second_items.append(
        '<span class="rt-item rt-route">'
        '<span class="rt-icon">\U0001f9ed</span>'
        '<span class="rt-lbl">Route:</span>'
        f'<span class="rt-val">{html.escape(route)}</span>'
        '</span>'
    )
    if reason:
        second_items.append(
            '<span class="rt-item rt-reason">'
            '<span class="rt-icon">\U0001f4dd</span>'
            '<span class="rt-lbl">Reason:</span>'
            f'<span class="rt-val">{html.escape(reason)}</span>'
            '</span>'
        )

    secondary = '<span class="rt-sec">' + ''.join(second_items) + '</span>'

    return (
        '<div class="runtime-card">'
        f'{primary}{secondary}'
        '</div>'
    )


def _classify_request(model_name: str, prompt: str) -> tuple[str, str]:
    """Generate user-friendly Route and Reason labels from the request.
    Returns (route_label, reason_text).
    """
    if not prompt:
        return _model_fallback(model_name)
    prompt_lower = prompt.lower().strip()
    first_word = prompt_lower.split()[0] if prompt_lower.split() else ""

    # Greeting detection — short conversational openers
    greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening", "good day"}
    if first_word in greetings or prompt_lower in greetings:
        return "Fast Model", "Short conversational request."

    # Complex engineering / system design
    complex_kw = ["system design", "distributed system", "microservices", "kubernetes",
                  "system architecture", "cloud architecture", "compiler", "kernel",
                  "operating system", "cap theorem", "raft", "paxos",
                  "load balancer", "event sourcing", "cqrs"]
    if any(kw in prompt_lower for kw in complex_kw):
        return "Advanced Model", "Complex technical reasoning required."

    # Resume / document analysis
    resume_kw = ["resume", "cv", "cover letter", "ats score"]
    if any(kw in prompt_lower for kw in resume_kw):
        return "Advanced Model", "Document analysis and structured evaluation."

    # Interview
    interview_kw = ["interview", "behavioral question", "interview question",
                    "coding interview", "mock interview"]
    if any(kw in prompt_lower for kw in interview_kw):
        return "Advanced Model", "Multi-step interview evaluation."

    # Programming / technical questions
    programming_kw = ["code", "python", "javascript", "java", "typescript", "c++", "c#",
                     "golang", "rust", "react", "angular", "vue", "sql", "mongodb",
                     "postgresql", "mysql", "algorithm", "data structure", "api",
                     "rest", "graphql", "debug", "testing", "function", "class",
                     "html", "css", "oop", "solid"]
    if any(kw in prompt_lower for kw in programming_kw):
        return "Balanced Model", "Programming question requiring moderate reasoning."

    # Career / learning / advice
    career_kw = ["career", "learning", "skill", "study", "roadmap", "job",
                 "recommend", "suggest", "path", "goal"]
    if any(kw in prompt_lower for kw in career_kw):
        return "Balanced Model", "Career guidance and skill development."

    return _model_fallback(model_name)


def _model_fallback(model_name: str) -> tuple[str, str]:
    """Default route/reason based on the selected model tier."""
    model_lower = model_name.lower()
    if "8b" in model_lower:
        return "Fast Model", "Short request processed efficiently."
    if "32b" in model_lower or "qwen" in model_lower:
        return "Advanced Model", "Complex query requiring advanced reasoning."
    return "Balanced Model", "General query requiring balanced reasoning."


# --- custom message renderer (no st.chat_message) ---
def _render_message_html(msg: dict) -> str:
    """Build the HTML for a single chat message (user or assistant bubble with avatar, timestamp, actions)."""
    role = msg["role"]
    avatar = "\U0001f642" if role == "user" else "\U0001f916"
    raw = msg.get("content", "")
    # Strip any embedded metadata comment that may have survived (defense in depth)
    if raw.startswith("<!--META:"):
        end_idx = raw.find("-->")
        if end_idx > 0:
            raw = raw[end_idx + 3:].lstrip("\n")
    content = _md(raw)
    ts = msg.get("timestamp", "")
    ts_html = f'<span class="msg-time">{ts}</span>' if ts else ""

    user_actions = (
        '<span class="msg-actions">'
        '<button class="msg-action-btn" title="Edit">\u270f\ufe0f</button>'
        '<button class="msg-action-btn" title="Delete">\U0001f5d1\ufe0f</button>'
        "</span>"
    )
    assistant_actions = (
        '<span class="msg-actions">'
        '<button class="msg-action-btn" title="Copy">\U0001f4cb</button>'
        '<button class="msg-action-btn" title="Regenerate">\U0001f504</button>'
        '<button class="msg-action-btn" title="Like">\U0001f44d</button>'
        '<button class="msg-action-btn" title="Dislike">\U0001f44e</button>'
        "</span>"
    )
    actions = user_actions if role == "user" else assistant_actions

    meta = ""
    if role == "assistant":
        m = msg.get("metadata")
        if m:
            meta = _meta_bar(m)

    return (
        f'<div class="message {role}">'
        f'{meta}'
        f'<div class="msg-row">'
        f'<div class="bubble">{content}</div>'
        f'<div class="avatar">{avatar}</div>'
        f"</div>"
        f'<div class="footer-row">'
        f"{ts_html}{actions}"
        f"</div>"
        f"</div>"
    )


# --- timestamp helper ---
def _make_timestamp() -> str:
    """Return a formatted local timestamp (e.g. 'Jun 28, 02:30 PM')."""
    dt = datetime.now(timezone.utc).astimezone()
    return dt.strftime("%b %d, %I:%M %p")


def _generate_pdf_report(data: dict) -> bytes:
    """Generate a PDF byte-string from an interview report data dict using fpdf2."""
    try:
        from fpdf import FPDF
        import io
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 14, "Interview Report", ln=True, align="C")
        pdf.ln(8)

        pdf.set_font("Helvetica", "", 11)
        def row(label, val):
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(50, 8, label, ln=False)
            pdf.set_font("Helvetica", "", 11)
            pdf.cell(0, 8, str(val), ln=True)

        row("Overall Score", f"{data.get('overall_score', 'N/A')}/10")
        row("Technical Score", f"{data.get('technical_score', 'N/A')}/10")
        row("Communication Score", f"{data.get('communication_score', 'N/A')}/10")
        row("Confidence Score", f"{data.get('confidence_score', 'N/A')}/10")
        row("Hiring Recommendation", data.get("hiring_recommendation", "N/A"))
        pdf.ln(6)

        for label, key in [
            ("Strengths", "strengths"),
            ("Weaknesses", "weaknesses"),
            ("Improvement Suggestions", "improvement_suggestions"),
            ("Recommended Topics", "recommended_topics"),
        ]:
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 10, label, ln=True)
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 6, data.get(key, ""))
            pdf.ln(3)

        buf = io.BytesIO()
        pdf.output(buf)
        return buf.getvalue()
    except Exception:
        return b""


# =============================================================
# DASHBOARD VIEW
# =============================================================
if st.session_state.current_view == "dashboard":
    _t("dashboard_view")

    ui.view_header(
        "\U0001f4ca", "Your Progress Dashboard",
        "Overview of your interview performance, weaknesses, and learning activity."
    )

    reports = database.get_interview_reports(user_id)
    weaknesses = database.get_user_weaknesses(user_id)
    careers = database.get_career_recommendations(user_id)
    roadmaps = database.get_learning_roadmaps(user_id)
    chat_history = chat_db.load_chats(user_id)

    total_interviews = len(reports)
    total_weaknesses = len(weaknesses)
    resolved_weaknesses = sum(1 for w in weaknesses if w["status"] == "resolved")
    total_careers = len(careers)
    total_roadmaps = len(roadmaps)
    total_chats = len(chat_history)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Interviews", total_interviews)
    with col2:
        st.metric("Weaknesses Tracked", total_weaknesses)
    with col3:
        st.metric("Resolved", resolved_weaknesses)
    with col4:
        st.metric("Roadmaps Created", total_roadmaps)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Career Recommendations", total_careers)
    with col2:
        st.metric("Chat Sessions", total_chats)
    with col3:
        if reports:
            avg_score = sum(float(r.get("overall_score", 0) or 0) for r in reports) / total_interviews
            st.metric("Avg Overall Score", f"{avg_score:.1f}/10")
        else:
            st.metric("Avg Overall Score", "N/A")

    # â”€â”€ Assessment Section â”€â”€
    parsed = assessment.parse_resume_analysis(st.session_state.get("resume_analysis", ""))
    assess = assessment.get_assessment(parsed, reports, weaknesses)

    with st.expander("\U0001f9d0 Assessment & Insights", expanded=True):
        st.caption(assess["source_label"])
        if assess["notice"]:
            st.info(assess["notice"])

        if not assess["has_resume"] and not reports:
            st.markdown("Upload a resume and complete a mock interview to see your assessment here.")
        else:
            cols = st.columns(3)
            with cols[0]:
                st.metric("Estimated Readiness", assess.get("readiness", "Unknown"))
            with cols[1]:
                if reports:
                    st.metric("Avg Overall", f'{assess.get("average_score", "N/A")}/10')
                else:
                    st.metric("ATS Score", f'{parsed.get("ats_score", "N/A")}/100')
            with cols[2]:
                st.metric("Weaknesses Identified", len(assess.get("weak_areas", [])))

            if assess.get("strengths"):
                with st.expander("\U0001f4aa Strengths", expanded=False):
                    for s in assess["strengths"]:
                        count = s.get("count", 1)
                        src = s.get("source", "")
                        label = f"- {s['text']}" if count == 1 else f"- {s['text']} (identified {count}x in {src})"
                        st.markdown(label)

            if assess.get("weak_areas"):
                with st.expander("\u26a0\ufe0f Areas to Improve", expanded=False):
                    for w in assess["weak_areas"]:
                        count = w.get("count", 1)
                        src = w.get("source", "")
                        conf = w.get("confidence", "")
                        st.markdown(f"- {w['text']}  `[{conf} confidence â€” from {src}]`")

            if assess.get("missing_skills"):
                with st.expander("\U0001f9d7 Missing Skills", expanded=False):
                    for s in assess["missing_skills"]:
                        st.markdown(f"- {s}")

            if reports and len(reports) >= 2 and assess.get("trends"):
                with st.expander("\U0001f4c8 Performance Trends", expanded=False):
                    t = assess["trends"]
                    st.markdown(f"- **Overall:** {t.get('overall', 'N/A')} pt")
                    st.markdown(f"- **Technical:** {t.get('technical', 'N/A')} pt")
                    st.markdown(f"- **Communication:** {t.get('communication', 'N/A')} pt")
                    st.markdown(f"- **Confidence:** {t.get('confidence', 'N/A')} pt")

    if reports:
        st.markdown("### \U0001f4c8 Score Trends")
        scores = []
        for r in reversed(reports):
            scores.append({
                "session": r.get("session_id", "")[:8],
                "overall": float(r.get("overall_score", 0) or 0),
                "technical": float(r.get("technical_score", 0) or 0),
                "communication": float(r.get("communication_score", 0) or 0),
                "confidence": float(r.get("confidence_score", 0) or 0),
            })
        if len(scores) > 1:
            chart_data = {"Session": [], "Overall": [], "Technical": [], "Communication": [], "Confidence": []}
            for s in scores:
                chart_data["Session"].append(s["session"])
                chart_data["Overall"].append(s["overall"])
                chart_data["Technical"].append(s["technical"])
                chart_data["Communication"].append(s["communication"])
                chart_data["Confidence"].append(s["confidence"])
            st.line_chart(chart_data, x="Session", y=["Overall", "Technical", "Communication", "Confidence"])
        else:
            st.caption("Complete at least 2 interviews to see score trends.")

    st.markdown("### \U0001f680 Quick Actions")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("\U0001f3a4 New Interview", use_container_width=True):
            _sync_current_chat()
            st.session_state.current_view = "interview"
            st.rerun()
    with col2:
        if st.button("\U0001f6a9 View Weaknesses", use_container_width=True):
            _sync_current_chat()
            st.session_state.current_view = "weaknesses"
            st.rerun()
    with col3:
        if st.button("\U0001f9ed Learning Roadmap", use_container_width=True):
            _sync_current_chat()
            st.session_state.current_view = "roadmap"
            st.rerun()
    with col4:
        if st.button("\U0001f4ca History", use_container_width=True):
            _sync_current_chat()
            st.session_state.current_view = "history"
            st.rerun()

# =============================================================
# CHAT VIEW â€” three containers: messages â†’ typing â†’ input
# =============================================================
elif st.session_state.current_view == "chat":

    _t("chat_view_start")

    # â”€â”€ Container 1: Chat input (processed FIRST; Streamlit fixes to bottom) â”€â”€
    prompt = st.chat_input(
        "Message\u2026",
        key="chat_input",
        disabled=st.session_state.get("_awaiting_response", False),
    )
    _t("chat_input")

    # â”€â”€ Footer: rendered natively inside the same bottom block as the input â”€â”€
    st.markdown(
        '<div class="footer-powered">Powered by Groq, Hindsight, CascadeFlow</div>',
        unsafe_allow_html=True,
    )

    if prompt and not st.session_state.get("_awaiting_response"):
        if st.session_state.current_chat_id is None:
            _new_chat()

        now = _make_timestamp()
        user_msg = {"role": "user", "content": prompt, "timestamp": now}
        st.session_state.messages.append(user_msg)
        st.session_state.chat_started = True

        # Defer DB writes â€” batch with assistant response after AI completes
        st.session_state._pending_user_msg = user_msg

        chat = st.session_state.chats.get(st.session_state.current_chat_id)
        if chat and chat["title"] == "New Chat" and len([m for m in st.session_state.messages if m["role"] == "user"]) == 1:
            chat["title"] = _generate_chat_title(prompt)
            st.session_state._pending_title = chat["title"]

        st.session_state._awaiting_response = True
        _t("handle_prompt")

    # â”€â”€ Container 2: Messages (conversation history) â”€â”€
    messages_container = st.container()
    with messages_container:
        if st.session_state.messages:
            for m in st.session_state.messages:
                st.markdown(_render_message_html(m), unsafe_allow_html=True)
        else:
            st.markdown('<div class="home-center">', unsafe_allow_html=True)
            ui.hero()
            st.markdown('</div>', unsafe_allow_html=True)
    _t("render_messages")

    # â”€â”€ Container 3: Typing placeholder (always exists between messages and input) â”€â”€
    typing_ph = st.empty()

    if st.session_state.get("_awaiting_response"):
        last_user = st.session_state.messages[-1]["content"]

        typing_ph.markdown(
            '<div class="message assistant">'
            '<div class="msg-row">'
            '<div class="avatar">\U0001f916</div>'
            '<div class="bubble">'
            '<div class="typing-indicator">AI is typing'
            '<span class="typing-dots"><span>.</span><span>.</span><span>.</span></span></div>'
            "</div>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        _t("ask_ai_start")
        answer, info = ask_ai(last_user, user_id)
        _t("ask_ai_done")
        # Build metadata with CascadeFlow routing information
        metadata = {
            "provider": info.get("provider", "Groq"),
            "model": info.get("model", ""),
            "latency": info.get("latency", 0),
            "cost": info.get("cost", 0),
            "complexity": info.get("complexity", ""),
            "routing_strategy": info.get("routing_strategy", ""),
            "cascaded": info.get("cascaded", False),
            "draft_accepted": info.get("draft_accepted", False),
            "reason": info.get("reason", ""),
            # Quality diagnostics
            "quality_score": info.get("quality_score"),
            "quality_check_passed": info.get("quality_check_passed"),
            # Model details
            "draft_model": info.get("draft_model", ""),
            "verifier_model": info.get("verifier_model", ""),
            # Cost breakdown
            "draft_cost": info.get("draft_cost"),
            "verifier_cost": info.get("verifier_cost"),
            "cost_saved": info.get("cost_saved"),
            "prompt": last_user,
        }
        route_label, clean_reason = _classify_request(metadata.get("model", ""), last_user)
        metadata["_route_display"] = route_label
        metadata["_reason_display"] = clean_reason
        meta_line = _meta_bar(metadata)
        now = _make_timestamp()

        _t("streaming_start")
        words = answer.split()
        accumulated = ""
        for j, w in enumerate(words):
            accumulated += w + " "
            cursor = '<span class="typing-cursor">\u258c</span>' if j < len(words) - 1 else ""
            typing_ph.markdown(
                '<div class="message assistant">'
                f'{meta_line}'
                '<div class="msg-row">'
                '<div class="avatar">\U0001f916</div>'
                f'<div class="bubble">{accumulated}{cursor}</div>'
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )
            time.sleep(0.018)
        _t("streaming_done")

        # â”€â”€ Final render: replace streaming text with properly rendered markdown â”€â”€
        final_html = _md(answer)
        typing_ph.markdown(
            '<div class="message assistant">'
            f'{meta_line}'
            '<div class="msg-row">'
            '<div class="avatar">\U0001f916</div>'
            f'<div class="bubble">{final_html}</div>'
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )

        st.session_state.messages.append({
            "role": "assistant", "content": answer, "timestamp": now, "metadata": metadata,
        })
        _t("save_batch_start")
        pending_user = st.session_state.pop("_pending_user_msg", None)
        pending_title = st.session_state.pop("_pending_title", None)
        if pending_user:
            cid = st.session_state.current_chat_id
            asst_msg = {"role": "assistant", "content": answer, "timestamp": now, "metadata": metadata}
            f1 = _db_pool.submit(chat_db.save_messages_batch, cid, user_id, [pending_user, asst_msg])
            if pending_title:
                f2 = _db_pool.submit(chat_db.update_chat, cid, user_id, {"title": pending_title})
            else:
                f2 = _db_pool.submit(chat_db.sync_chat, cid, user_id)
            concurrent.futures.wait([f1, f2])
            ok = True
            for f in [f1, f2]:
                try:
                    f.result()
                except Exception:
                    ok = False
            if not ok:
                _db_failed()
        _t("save_batch_done")
        print("MESSAGE SAVED")
        st.session_state._awaiting_response = False
        _t("save_streamed_response")

        # Don't clear typing_ph â€” it holds the final answer until the next rerun
        # renders it from st.session_state.messages in Container 2

    _t("chat_footer")

    # â”€â”€ Footer is now rendered natively via st.markdown() above â”€â”€

    # â”€â”€ Auto-scroll to bottom â”€â”€
    st.markdown(
        """
        <div id="scroll-anchor"></div>
        <script>
        (function() {
            var a = document.getElementById('scroll-anchor');
            if (a) a.scrollIntoView({ behavior: 'auto', block: 'end' });
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

# =============================================================
# RESUME VIEW
# =============================================================
elif st.session_state.current_view == "resume":
    _t("resume_view")

    ui.view_header(
        "ðŸ“„", "Resume Analyzer",
        "Upload and analyze your resume for ATS scores, missing skills, and improvement suggestions."
    )

    # â”€â”€ State: analysis complete â”€â”€
    if st.session_state.get("resume_analysis_complete"):
        st.success("âœ… Resume uploaded successfully! âœ… Resume analysis completed successfully!")
        ui.resume_card(st.session_state.resume_filename or "Resume")
        with st.expander("ðŸ“Š AI Resume Analysis", expanded=True):
            st.markdown(st.session_state.resume_analysis)
        if st.button("ðŸ”„ Analyze Another Resume", use_container_width=True, type="primary"):
            for k in ["resume_text", "resume_filename", "resume_analysis", "resume_analysis_complete"]:
                st.session_state.pop(k, None)
            st.session_state.resume_upload_counter = st.session_state.get("resume_upload_counter", 0) + 1
            st.rerun()

    # â”€â”€ State: analyzing â”€â”€
    elif st.session_state.get("resume_analyzing"):
        st.success("âœ… Resume uploaded successfully!")
        with st.status("ðŸ” Analyzing resume...", expanded=True) as status:
            st.write("ðŸ“„ Extracting text from file...")
            text = st.session_state.get("resume_text")
            if text:
                st.write("âœ… Text extracted")
                st.write("ðŸ§  Running AI analysis...")
                analysis = analyze_resume(text, user_id)
                if analysis:
                    st.session_state.resume_analysis = analysis
                    st.write("âœ… Analysis complete!")
                    status.update(label="Analysis complete!", state="complete", expanded=False)
                else:
                    st.error("Analysis failed. Please try again.")
                    status.update(label="Analysis failed", state="error")
            else:
                st.error("No resume text found. Please upload a valid file.")
                status.update(label="Upload required", state="error")
            st.session_state.resume_analysis_complete = True
            del st.session_state.resume_analyzing
        st.rerun()

    # â”€â”€ State: upload / file selected â”€â”€
    else:
        upload_counter = st.session_state.get("resume_upload_counter", 0)
        uploaded = st.file_uploader(
            "Resume file", type=["pdf", "docx", "txt"],
            key=f"resume_uploader_{upload_counter}",
            label_visibility="collapsed",
        )

        if uploaded:
            st.session_state.resume_filename = uploaded.name
            try:
                text = extract_resume_text(uploaded)
                if text:
                    st.session_state.resume_text = text
                    st.success("âœ… Resume uploaded successfully!")
                    time.sleep(1)
                else:
                    st.error("âŒ Resume upload failed.")
                    st.error("Could not extract text. Please upload a valid PDF, DOCX, or TXT file.")
            except Exception as e:
                st.error("âŒ Resume upload failed.")
                st.error(f"Error: {e}")

        has_text = "resume_text" in st.session_state

        if st.button(
            "ðŸ” Analyze Resume",
            disabled=not has_text,
            type="primary",
            use_container_width=True,
        ):
            if has_text:
                st.session_state.resume_analyzing = True
                st.rerun()

        if not has_text:
            st.markdown(
                '<p style="text-align:center;font-size:12px;color:var(--text-muted);margin-top:-4px;">'
                "Supported formats: PDF, DOCX, TXT</p>",
                unsafe_allow_html=True,
            )

# =============================================================
# INTERVIEW VIEW
# =============================================================
elif st.session_state.current_view == "interview":
    _t("interview_view")

    ui.view_header(
        "ðŸŽ¤", "Mock Interview",
        "Practice with AI-generated interview questions based on your resume."
    )

    if "resume_text" not in st.session_state:
        ui.glass_card()
        st.warning("âš ï¸ Please upload your resume first.")
        st.markdown(
            '<p style="text-align:center;color:var(--text-muted);font-size:13px;">'
            "Go to <strong>Resume Analyzer</strong> in the sidebar to upload.</p>",
            unsafe_allow_html=True,
        )
        ui.glass_card_close()
    else:
        if not st.session_state.interview_started:
            ui.glass_card("Get Started", "ðŸŽ¤")
            st.markdown(
                '<p style="color:var(--text-secondary);font-size:14px;margin-bottom:12px;">'
                "Ready to practice? Start a 5-question mock interview tailored to your resume.</p>",
                unsafe_allow_html=True,
            )

            use_memory = st.checkbox(
                "ðŸ“ Use Previous Interview Memory",
                value=st.session_state.get("_use_interview_memory", False),
                key="_use_interview_memory_toggle",
                help="Include past interview performance and weaknesses to tailor questions.",
            )
            st.session_state._use_interview_memory = use_memory

            if use_memory:
                mem = build_interview_memory_context(user_id)
                if mem:
                    st.session_state._interview_memory_context = mem
                else:
                    st.session_state._interview_memory_context = ""

            if st.button("ðŸŽ¤ Start Mock Interview", use_container_width=True, type="primary"):
                with st.spinner("Preparing interview questions..."):
                    mem = st.session_state.get("_interview_memory_context", "")
                    if mem:
                        raw = generate_interview_questions_with_memory(st.session_state["resume_text"], mem)
                    else:
                        raw = generate_interview_questions(st.session_state["resume_text"])
                    st.session_state.interview_questions = [
                        q.strip() for q in raw.split("\n")
                        if q.strip() and q.strip()[0].isdigit()
                    ]
                st.session_state.interview_started = True
                st.session_state.current_question = 0
                st.session_state.feedback = ""
                st.session_state.answer_submitted = False
                st.session_state.interview_finished = False
                st.session_state.interview_results = []
                if "final_report" in st.session_state:
                    del st.session_state.final_report
                st.rerun()
            ui.glass_card_close()

        if st.session_state.interview_started:
            qs = [q for q in st.session_state.interview_questions if q.strip()]
            tq = len(qs)

            if st.session_state.current_question < tq:
                prog_pct = st.session_state.current_question / max(tq, 1) * 100
                q_num = st.session_state.current_question + 1

                st.markdown(
                    f'''
                    <div class="interview-question-card">
                        <div class="interview-q-header">
                            <span class="interview-q-badge">Question {q_num} of {tq}</span>
                            <span class="interview-q-difficulty">Difficulty: Medium</span>
                        </div>
                        <div class="interview-q-progress-track">
                            <div class="interview-q-progress-bar" style="width:{prog_pct}%"></div>
                        </div>
                        <div class="interview-q-text">{qs[st.session_state.current_question]}</div>
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )

                submitted = st.session_state.get("answer_submitted", False)

                if submitted:
                    last = st.session_state.interview_results[-1] if st.session_state.interview_results else {}
                    answer_text = last.get("answer", "")

                    st.markdown(
                        f'''
                        <div class="interview-answer-card">
                            <div class="interview-answer-title">âœï¸ Your Answer</div>
                            <div class="interview-submitted-answer">{answer_text}</div>
                        </div>
                        ''',
                        unsafe_allow_html=True,
                    )

                    ui.feedback_card(st.session_state.get("feedback", ""))

                    is_last = q_num >= tq
                    btn_label = "\U0001f389 Finish Interview" if is_last else "\u27a1\ufe0f Next Question"
                    if st.button(btn_label, use_container_width=True, type="primary"):
                        if is_last:
                            st.session_state.current_question += 1
                        else:
                            st.session_state.current_question += 1
                            st.session_state.answer_submitted = False
                            st.session_state.feedback = ""
                        st.rerun()
                else:
                    st.markdown('<div class="interview-answer-card">', unsafe_allow_html=True)
                    st.markdown('<div class="interview-answer-title">\u270d\ufe0f Your Answer</div>', unsafe_allow_html=True)
                    ans = st.text_area(
                        "", key=f"ans_{st.session_state.current_question}",
                        height=150, placeholder="Write your answer here...",
                        label_visibility="collapsed",
                    )
                    if st.button("\u2705 Submit Answer", type="primary", use_container_width=True):
                        if ans.strip():
                            with st.spinner("\U0001f916 Evaluating your answer..."):
                                mem = st.session_state.get("_interview_memory_context", "")
                                if mem:
                                    fb = evaluate_answer_with_memory(
                                        qs[st.session_state.current_question], ans, mem
                                    )
                                else:
                                    fb = evaluate_answer(
                                        qs[st.session_state.current_question], ans
                                    )
                                save_interview_report(user_id, fb)
                                st.session_state.feedback = fb
                                st.session_state.answer_submitted = True
                            st.session_state.interview_results.append({
                                "question": qs[st.session_state.current_question],
                                "answer": ans,
                                "feedback": fb,
                            })
                            st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.session_state.interview_finished = True
                st.balloons()
                ui.success_box("Interview Completed!", "Great job! Here's your performance summary.")

                if "final_report" not in st.session_state:
                    with st.spinner("ðŸ“Š Generating final report..."):
                        st.session_state.final_report = generate_final_report(
                            st.session_state.interview_results
                        )

                with st.expander("ðŸ† Final Interview Report", expanded=True):
                    st.markdown(st.session_state.final_report)

                if "_interview_report_saved" not in st.session_state:
                    with st.spinner("ðŸ“Š Extracting scores..."):
                        struct = generate_structured_report(st.session_state.interview_results)
                    if struct:
                        struct["report_text"] = st.session_state.final_report
                        struct["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")
                        if database.save_interview_report_record(user_id, struct):
                            st.session_state._interview_report_data = struct
                            st.session_state._interview_report_saved = True

                        # â”€â”€ Extract & persist weaknesses from structured report â”€â”€
                        if struct.get("weaknesses"):
                            raw = struct["weaknesses"]
                            print(f"[WEAKNESS FLOW] Raw weaknesses from report: {raw}")
                            items = [i.strip() for i in raw.replace(",", "\n").split("\n") if i.strip()]
                            for item in items:
                                clean = item.lstrip("- *â€¢0123456789.)").strip()
                                if not clean or len(clean) < 3:
                                    continue
                                cat = _map_weakness_category(clean)
                                print(f"[WEAKNESS FLOW] Extracted: '{clean}' -> category '{cat}'")
                                ok = database.upsert_weakness(user_id, clean, cat)
                                print(f"[WEAKNESS FLOW] DB upsert result: {ok}")
                        else:
                            print("[WEAKNESS FLOW] No weaknesses field in structured report")

                if st.session_state.get("_interview_report_saved"):
                    report_data = st.session_state._interview_report_data
                    pdf_bytes = _generate_pdf_report(report_data)
                    if pdf_bytes:
                        st.download_button(
                            "ðŸ“„ Download PDF Report",
                            pdf_bytes,
                            "interview_report.pdf",
                            "application/pdf",
                            use_container_width=True,
                        )

                if st.session_state.career_report == "":
                    with st.spinner("ðŸŽ¯ Finding best career path..."):
                        st.session_state.career_report = recommend_career(
                            st.session_state["resume_text"],
                            st.session_state.final_report,
                        )

                with st.expander("ðŸŽ¯ Career Recommendation", expanded=True):
                    st.markdown(st.session_state.career_report)

                if st.button("ðŸ”„ Start New Interview", use_container_width=True, type="primary"):
                    st.session_state.interview_started = False
                    st.session_state.current_question = 0
                    st.session_state.feedback = ""
                    st.session_state.answer_submitted = False
                    st.session_state.interview_questions = []
                    st.session_state.interview_results = []
                    st.session_state.career_report = ""
                    st.session_state.pop("_interview_report_saved", None)
                    st.session_state.pop("_interview_report_data", None)
                    if "final_report" in st.session_state:
                        del st.session_state.final_report
                    st.rerun()

# =============================================================
# CAREER VIEW
# =============================================================
elif st.session_state.current_view == "career":
    _t("career_view")

    ui.view_header(
        "ðŸŽ¯", "Career Recommendation",
        "Personalized career path based on your resume, skills, and interests."
    )

    # â”€â”€ Show interview-triggered report if it exists â”€â”€
    if st.session_state.career_report and "_standalone_career_result" not in st.session_state:
        ui.glass_card()
        st.markdown(st.session_state.career_report)
        ui.glass_card_close()
        st.markdown("---")

    # â”€â”€ Standalone form â”€â”€
    with st.expander("âœï¸ Get a New Career Recommendation", expanded="_standalone_career_result" not in st.session_state):
        with st.form("career_form", clear_on_submit=False):
            skills = st.text_area(
                "Your Skills",
                st.session_state.get("_career_skills", ""),
                placeholder="e.g. Python, JavaScript, SQL, communication, project management",
                height=80,
            )
            exp_level = st.selectbox(
                "Experience Level",
                ["Entry Level / Fresher", "Mid Level (1-3 years)", "Senior (3+ years)"],
                index=0,
            )
            interests = st.text_area(
                "Your Interests",
                st.session_state.get("_career_interests", ""),
                placeholder="e.g. AI/ML, web development, data science, product management",
                height=80,
            )
            submitted = st.form_submit_button("ðŸŽ¯ Generate Career Recommendation", type="primary", use_container_width=True)

    if submitted:
        if skills.strip() and interests.strip():
            st.session_state._career_skills = skills
            st.session_state._career_interests = interests
            with st.spinner("ðŸŽ¯ Finding best career path..."):
                result_md = recommend_career_standalone(skills, exp_level, interests)
            st.session_state._standalone_career_result = result_md
            st.session_state._standalone_career_data = {
                "skills": skills, "experience_level": exp_level,
                "interests": interests, "recommendation_markdown": result_md,
            }
            st.session_state.pop("_standalone_career_saved", None)
            st.rerun()

    if st.session_state.get("_standalone_career_result"):
        report_md = st.session_state._standalone_career_result
        ui.glass_card()
        st.markdown(report_md)
        ui.glass_card_close()

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if not st.session_state.get("_standalone_career_saved"):
                if st.button("ðŸ’¾ Save Recommendation", use_container_width=True):
                    if database.save_career_recommendation(user_id, st.session_state._standalone_career_data):
                        st.session_state._standalone_career_saved = True
                        st.rerun()
            else:
                st.success("âœ… Saved to history")

        with col1:
            if st.button("ðŸ”„ New Recommendation", use_container_width=True):
                st.session_state.pop("_standalone_career_result", None)
                st.session_state.pop("_standalone_career_data", None)
                st.session_state.pop("_standalone_career_saved", None)
                st.rerun()

    # â”€â”€ History â”€â”€
    st.markdown("---")
    with st.expander("ðŸ“œ Past Recommendations", expanded=False):
        history = database.get_career_recommendations(user_id)
        if history:
            for entry in history:
                with st.container():
                    st.markdown(f"**{entry.get('created_at', '')}**")
                    st.markdown(
                        f"Skills: {entry.get('skills', '')[:80]}...  |  "
                        f"Level: {entry.get('experience_level', '')}  |  "
                        f"Interests: {entry.get('interests', '')[:80]}..."
                    )
                    if st.button("ðŸ“„ View", key=f"view_career_{entry['id']}"):
                        st.session_state._standalone_career_result = entry.get("recommendation_markdown", "")
                        st.session_state._standalone_career_data = entry
                        st.session_state.pop("_standalone_career_saved", None)
                        st.rerun()
                    st.markdown("---")
        else:
            st.caption("No past recommendations yet.")

# =============================================================
# HISTORY VIEW (Interview Reports)
# =============================================================
elif st.session_state.current_view == "history":
    _t("history_view")

    ui.view_header(
        "ðŸ“Š", "Interview History",
        "Your past interview performance reports and scores."
    )

    reports = database.get_interview_reports(user_id)
    if not reports:
        ui.glass_card()
        st.info("No interview reports yet. Complete a mock interview to see your history here.")
        ui.glass_card_close()
    else:
        for r in reports:
            label = f"ðŸ† Session {r.get('session_id', '')[:12]} â€” {r.get('overall_score', '?')}/10"
            with st.expander(label, expanded=False):
                cols = st.columns(4)
                metrics = [
                    ("Overall", r.get("overall_score", "N/A"), "10"),
                    ("Technical", r.get("technical_score", "N/A"), "10"),
                    ("Communication", r.get("communication_score", "N/A"), "10"),
                    ("Confidence", r.get("confidence_score", "N/A"), "10"),
                ]
                for col, (name, val, denom) in zip(cols, metrics):
                    with col:
                        st.metric(name, f"{val}/{denom}")

                for label, key in [
                    ("ðŸ’ª Strengths", "strengths"),
                    ("âš ï¸ Weaknesses", "weaknesses"),
                    ("ðŸ“ˆ Improvement Suggestions", "improvement_suggestions"),
                    ("ðŸ“š Recommended Topics", "recommended_topics"),
                    ("âœ… Hiring Recommendation", "hiring_recommendation"),
                ]:
                    val = r.get(key, "")
                    if val:
                        st.markdown(f"**{label}**")
                        st.markdown(val)
                        st.markdown("---")

                if r.get("report_text"):
                    with st.expander("ðŸ“„ Full Report"):
                        st.markdown(r["report_text"])

                st.caption(f"Completed: {r.get('created_at', '')}")

# =============================================================
# WEAKNESS TRACKING VIEW
# =============================================================
elif st.session_state.current_view == "weaknesses":
    _t("weaknesses_view")

    ui.view_header(
        "\U0001f6a9", "Weakness Tracking",
        "Track weaknesses identified in your interviews and monitor improvement."
    )

    # â”€â”€ Manual scan button (top-right of header area) â”€â”€
    header_cols = st.columns([4, 1])
    with header_cols[1]:
        if st.button("ðŸ” Scan Latest Interview", use_container_width=True, key="scan_weaknesses_btn"):
            reports = database.get_interview_reports(user_id)
            if not reports:
                st.info("â„¹ï¸ No new interview reports found.")
            else:
                latest = reports[0]  # sorted by created_at desc
                raw_weaknesses = (latest.get("weaknesses") or "").strip()
                if not raw_weaknesses:
                    st.info("â„¹ï¸ No new weaknesses detected.")
                else:
                    items = [i.strip() for i in raw_weaknesses.replace(",", "\n").split("\n") if i.strip()]
                    imported = 0
                    for item in items:
                        clean = item.lstrip("- *â€¢0123456789.)").strip()
                        if not clean or len(clean) < 3:
                            continue
                        cat = _map_weakness_category(clean)
                        database.upsert_weakness(user_id, clean, cat)
                        imported += 1
                    if imported:
                        st.success(f"âœ… Weaknesses updated successfully. ({imported} imported)")
                    else:
                        st.info("â„¹ï¸ No new weaknesses detected.")
            st.rerun()

    weaknesses = database.get_user_weaknesses(user_id)
    reports = database.get_interview_reports(user_id)
    parsed = assessment.parse_resume_analysis(st.session_state.get("resume_analysis", ""))
    assess = assessment.get_assessment(parsed, reports, weaknesses)

    st.caption(assess["source_label"])
    if assess["notice"]:
        st.info(assess["notice"])

    if not weaknesses and not assess["has_resume"]:
        ui.glass_card()
        st.info("No weaknesses tracked yet. Complete a mock interview and generate a report to see your weaknesses here.")
        ui.glass_card_close()
    elif not weaknesses and assess["has_resume"]:
        st.markdown("### \U0001f4c4 Resume-Derived Insights")
        st.markdown("No interview data yet. Below are insights from your resume analysis.")
        if parsed.get("weaknesses"):
            st.markdown("**Resume Weaknesses:**")
            for w in parsed["weaknesses"]:
                st.markdown(f"- {w}")
        if parsed.get("missing_skills"):
            st.markdown("**Missing Skills:**")
            for s in parsed["missing_skills"]:
                st.markdown(f"- {s}")
        if parsed.get("strengths"):
            st.markdown("**Resume Strengths:**")
            for s in parsed["strengths"]:
                st.markdown(f"- {s}")
        st.markdown("---")

    if weaknesses:
        active = [w for w in weaknesses if w["status"] == "active"]
        improving = [w for w in weaknesses if w["status"] == "improving"]
        resolved = [w for w in weaknesses if w["status"] == "resolved"]

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Active", len(active))
        with col2:
            st.metric("Improving", len(improving))
        with col3:
            st.metric("Resolved", len(resolved))

        for group_label, group_list, status_color in [
            ("\u26a0\ufe0f Active Weaknesses", active, "#ff4b4b"),
            ("\U0001f4aa Improving", improving, "#ffa726"),
            ("\u2705 Resolved", resolved, "#66bb6a"),
        ]:
            if group_list:
                st.markdown(f"### {group_label}")
                for w in group_list:
                    category = w.get("category", "General")
                    with st.container():
                        cols = st.columns([3, 1, 1, 1])
                        with cols[0]:
                            st.markdown(f"**{w.get('weakness_text', '')}**")
                            st.caption(f"Category: {category}  |  Detected {w.get('detected_count', 1)}x")
                        with cols[1]:
                            if w["status"] == "active":
                                if st.button("Improving", key=f"imp_{w['id']}", use_container_width=True):
                                    database.update_weakness_status(w["id"], "improving")
                                    st.rerun()
                        with cols[2]:
                            if w["status"] != "resolved":
                                if st.button("Resolved", key=f"res_{w['id']}", use_container_width=True):
                                    database.update_weakness_status(w["id"], "resolved")
                                    st.rerun()
                        with cols[3]:
                            if st.button("Delete", key=f"del_{w['id']}", use_container_width=True):
                                try:
                                    supabase = auth.get_supabase()
                                    supabase.table("user_weaknesses").delete().eq("id", w["id"]).execute()
                                except Exception:
                                    pass
                                st.rerun()
                        st.markdown("---")

# =============================================================
# LEARNING ROADMAP VIEW
# =============================================================
elif st.session_state.current_view == "roadmap":
    _t("roadmap_view")

    ui.view_header(
        "\U0001f9ed", "Learning Roadmap",
        "Personalized learning plan based on your weaknesses and skill gaps."
    )

    weaknesses = database.get_user_weaknesses(user_id)
    active_weaknesses = [w for w in weaknesses if w["status"] in ("active", "improving")]
    weaknesses_text = "\n".join(f"- {w['weakness_text']}" for w in active_weaknesses) if active_weaknesses else ""

    with st.form("roadmap_form"):
        st.text_area(
            "Areas to Improve",
            key="_roadmap_weaknesses",
            value=weaknesses_text,
            height=100,
            placeholder="e.g. Data structures, System design, Communication skills",
        )
        st.text_area(
            "Current Skills (optional)",
            key="_roadmap_skills",
            height=80,
            placeholder="e.g. Python, JavaScript, SQL, React",
        )
        submitted = st.form_submit_button("\U0001f9ed Generate Learning Roadmap", type="primary", use_container_width=True)

    if submitted:
        w_text = st.session_state._roadmap_weaknesses
        s_text = st.session_state.get("_roadmap_skills", "")
        if w_text.strip():
            with st.spinner("\U0001f9ed Creating your personalized roadmap..."):
                roadmap = generate_learning_roadmap(w_text, s_text)
            st.session_state._roadmap_result = roadmap
            st.session_state._roadmap_input = {"weaknesses_input": w_text, "roadmap_markdown": roadmap}
            st.session_state.pop("_roadmap_saved", None)
            st.rerun()

    if st.session_state.get("_roadmap_result"):
        ui.glass_card()
        st.markdown(st.session_state._roadmap_result)
        ui.glass_card_close()

        col1, col2 = st.columns([1, 1])
        with col1:
            if not st.session_state.get("_roadmap_saved"):
                if st.button("\U0001f4be Save Roadmap", use_container_width=True):
                    if database.save_learning_roadmap(user_id, st.session_state._roadmap_input):
                        st.session_state._roadmap_saved = True
                        st.rerun()
            else:
                st.success("\u2705 Saved")
        with col2:
            if st.button("\U0001f504 New Roadmap", use_container_width=True):
                st.session_state.pop("_roadmap_result", None)
                st.session_state.pop("_roadmap_input", None)
                st.session_state.pop("_roadmap_saved", None)
                st.rerun()

    st.markdown("---")
    with st.expander("\U0001f4da Past Roadmaps", expanded=False):
        past = database.get_learning_roadmaps(user_id)
        if past:
            for entry in past:
                with st.container():
                    st.markdown(f"**{entry.get('created_at', '')}**")
                    if st.button("\U0001f4dd View", key=f"view_roadmap_{entry['id']}", use_container_width=True):
                        st.session_state._roadmap_result = entry.get("roadmap_markdown", "")
                        st.session_state._roadmap_input = entry
                        st.session_state.pop("_roadmap_saved", None)
                        st.rerun()
                    st.markdown("---")
        else:
            st.caption("No past roadmaps yet.")

# â”€â”€ Timing report printed to terminal every rerun (commented out for production) â”€â”€
# print("RERUN")
# _t_report()
