import os
import sqlite3
import time
import uuid
from datetime import datetime

import pandas as pd
import qrcode
import streamlit as st
from PIL import Image

APP_TITLE = "Q&A"

# --- Brand farver ---
BRAND_BG_DARK = "#1f2951"   # mørkeblå baggrund (dark mode)
BRAND_GOLD    = "#d6a550"   # detaljer/knapper
BRAND_ACCENT  = "#004899"   # ikke brugt meget, men handy

# --- Robust DB-path (Cloud-safe) ---
_default_cloud_dir = "/mount/data" if os.path.isdir("/mount/data") else os.getcwd()
DB_PATH = os.environ.get("QNA_DB_PATH", os.path.join(_default_cloud_dir, "qna_streamlit.db"))

# ---------- Styling ----------
def inject_theme():
    # Responsiv styling efter brugerens systemtema (dark/light)
    st.markdown(
        f"""
        <style>
        :root {{
            --brand-bg-dark: {BRAND_BG_DARK};
            --brand-gold: {BRAND_GOLD};
        }}

        /* Knapper (fælles) */
        .stButton>button, .stDownloadButton>button {{
            background-color: var(--brand-gold) !important;
            border: none !important;
            border-radius: 10px !important;
            padding: 0.6rem 1rem !important;
            font-weight: 600 !important;
        }}
        .stButton>button:hover, .stDownloadButton>button:hover {{
            filter: brightness(1.1);
        }}

        /* Dark mode */
        @media (prefers-color-scheme: dark) {{
            .stApp {{ background-color: var(--brand-bg-dark) !important; color: #ffffff !important; }}
            h1, h2, h3, h4, h5, h6,
            .stMarkdown, .stTextInput input, textarea {{ color: #ffffff !important; }}
            a {{ color: var(--brand-gold) !important; }}
            .stButton>button, .stDownloadButton>button {{ color: #ffffff !important; }}
            textarea, .stTextInput input {{
                background-color: rgba(255,255,255,0.1) !important;
                color: #ffffff !important;
                border: 1px solid var(--brand-gold) !important;
                border-radius: 8px !important;
            }}
            .stAlert>div {{
                background-color: rgba(255,255,255,0.1) !important;
                color: #ffffff !important;
                border-left: 6px solid var(--brand-gold) !important;
            }}
            code {{
                background-color: rgba(255,255,255,0.1) !important;
                color: #ffffff !important;
                padding: 2px 6px;
                border-radius: 4px;
            }}
        }}

        /* Light mode */
        @media (prefers-color-scheme: light) {{
            .stApp {{ background-color: #ffffff !important; color: #000000 !important; }}
            h1, h2, h3, h4, h5, h6,
            .stMarkdown, .stTextInput input, textarea {{ color: #000000 !important; }}
            a {{ color: {BRAND_BG_DARK} !important; }}
            .stButton>button, .stDownloadButton>button {{ color: #000000 !important; }}
            textarea, .stTextInput input {{
                background-color: rgba(0,0,0,0.03) !important;
                color: #000000 !important;
                border: 1px solid {BRAND_GOLD} !important;
                border-radius: 8px !important;
            }}
            .stAlert>div {{
                background-color: rgba(0,0,0,0.03) !important;
                color: #000000 !important;
                border-left: 6px solid var(--brand-gold) !important;
            }}
            code {{
                background-color: rgba(0,0,0,0.04) !important;
                color: #000000 !important;
                padding: 2px 6px;
                border-radius: 4px;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ---------- DB Helpers ----------
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_column(conn, table, column, coltype):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions(
        id TEXT PRIMARY KEY,
        title TEXT,
        admin_key TEXT,
        created_at INTEGER
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS questions(
        id TEXT PRIMARY KEY,
        session_id TEXT,
        text TEXT,
        created_at INTEGER,
        hidden INTEGER DEFAULT 0,
        answered INTEGER DEFAULT 0
    )""")
    conn.commit()
    # Sikr kolonne til anonym spørger (device-ID)
    ensure_column(conn, "questions", "asker_id", "TEXT")

def ensure_session(session_id, title="", admin_key=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    if row:
        return dict(row)
    if not admin_key:
        admin_key = uuid.uuid4().hex[:8]
    cur.execute(
        "INSERT INTO sessions(id,title,admin_key,created_at) VALUES(?,?,?,?)",
        (session_id, title, admin_key, int(time.time()))
    )
    conn.commit()
    return {"id": session_id, "title": title, "admin_key": admin_key, "created_at": int(time.time())}

def get_session(session_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def add_question(session_id, text, asker_id=None):
    qid = uuid.uuid4().hex
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO questions(id,session_id,text,created_at,hidden,answered,asker_id) VALUES(?,?,?,?,0,0,?)",
        (qid, session_id, text[:1000], int(time.time()), asker_id)
    )
    conn.commit()
    return qid

def list_questions(session_id, include_hidden=True):
    conn = get_db()
    cur = conn.cursor()
    if include_hidden:
        cur.execute(
            """SELECT * FROM questions WHERE session_id=?
               ORDER BY answered ASC, hidden ASC, created_at ASC""",
            (session_id,)
        )
    else:
        cur.execute(
            """SELECT * FROM questions WHERE session_id=? AND hidden=0
               ORDER BY answered ASC, created_at ASC""",
            (session_id,)
        )
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def list_user_questions_last24(session_id, asker_id):
    if not asker_id:
        return []
    conn = get_db()
    cur = conn.cursor()
    cutoff = int(time.time()) - 24*3600
    cur.execute(
        """SELECT * FROM questions
           WHERE session_id=? AND asker_id=? AND created_at>=?
           ORDER BY created_at DESC""",
        (session_id, asker_id, cutoff)
    )
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def list_sessions_with_stats(only_used=False, limit=20):
    """Sessions med antal spørgsmål og seneste aktivitet."""
    conn = get_db()
    cur = conn.cursor()
    base_sql = """
        SELECT s.id, s.title, s.admin_key, s.created_at,
               COUNT(q.id) AS q_count,
               COALESCE(MAX(q.created_at), s.created_at) AS last_activity
        FROM sessions s
        LEFT JOIN questions q ON q.session_id = s.id
    """
    if only_used:
        base_sql += " GROUP BY s.id HAVING COUNT(q.id) > 0"
    else:
        base_sql += " GROUP BY s.id"
    base_sql += " ORDER BY last_activity DESC LIMIT ?"
    cur.execute(base_sql, (limit,))
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def toggle_field(qid, field):
    assert field in ("hidden", "answered")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE questions SET {field} = CASE {field} WHEN 1 THEN 0 ELSE 1 END WHERE id=?",
        (qid,)
    )
    conn.commit()

def delete_question(qid):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM questions WHERE id=?", (qid,))
    conn.commit()

def export_csv(session_id):
    rows = list_questions(session_id, include_hidden=True)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"], unit="s")
    return df

# ---------- QR Helpers ----------
def make_qr_png(data: str) -> Image.Image:
    qr = qrcode.QRCode(version=1, box_size=8, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    if hasattr(img, "get_image"):
        img = img.get_image()
    return img.convert("RGB")

# ---------- UI Helpers ----------
def header():
    st.set_page_config(page_title=APP_TITLE, page_icon="❓", layout="wide")
    inject_theme()
    st.title(APP_TITLE)
    st.caption("Stil et spørgsmål til scenen.")

def nav():
    qp = dict(st.query_params)
    return qp.get("view", "home")

def set_qp(**kwargs):
    qp = dict(st.query_params)
    qp.update({k: v for k, v in kwargs.items() if v is not None})
    st.query_params.clear()
    for k, v in qp.items():
        st.query_params[k] = v

def link_for(base_url, params: dict):
    base = base_url.rstrip("/")
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}/?{query}"

# ---------- Views ----------
def view_home():
    st.subheader("Opret eller åbn en session")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### Opret ny session")
        title = st.text_input("Titel (valgfri)", "")
        custom_id = st.text_input("Custom ID (a-z, 0-9, -) – ellers genereres", "")
        if st.button("Opret session"):
            sid = custom_id.strip().lower()
            if sid == "":
                sid = uuid.uuid4().hex[:6]
            sid = "".join(ch for ch in sid if ch.isalnum() or ch == "-")[:40]
            session = ensure_session(sid, title=title)
            st.success(f"Session oprettet: {session['id']}")
            st.session_state["last_session"] = session

    with col2:
        st.markdown("#### Åbn eksisterende session")
        sid2 = st.text_input("Session ID", key="open_sid")
        if st.button("Åbn"):
            s = get_session(sid2.strip())
            if s:
                st.session_state["last_session"] = s
                st.success(f"Åbnede session: {s['id']}")
            else:
                st.error("Session findes ikke.")

        # NYT: Liste over BRUGTE sessions (med aktivitet)
        st.markdown("#### Brugte sessions (seneste)")
        used = list_sessions_with_stats(only_used=True, limit=20)
        if not used:
            st.caption("Ingen brugte sessions endnu.")
        else:
            for r in used:
                title = r["title"] or r["id"]
                ts = datetime.fromtimestamp(r["last_activity"]).strftime("%Y-%m-%d %H:%M")
                with st.container(border=True):
                    st.markdown(f"**{title}**  \n`{r['id']}` • {r['q_count']} spørgsmål • senest {ts}")
                    cA, cB = st.columns(2)
                    with cA:
                        if st.button("Åbn", key=f"open_used_{r['id']}"):
                            s = get_session(r["id"])
                            st.session_state["last_session"] = s
                            st.rerun()
                    with cB:
                        # lille “kopiér id” convenience
                        st.code(r["id"], language="text")

    if "last_session" in st.session_state:
        s = st.session_state["last_session"]
        st.divider()
        st.markdown(f"### Session: `{s['id']}` {('– ' + s['title']) if s.get('title') else ''}")

        # Brug PUBLIC_BASE_URL hvis sat, ellers default til din offentlige URL
        default_public_url = "https://sporgogsvar-appv2-4jb4dnsmshrhypicrqfjd2.streamlit.app"
        env_base = os.environ.get("PUBLIC_BASE_URL")
        if env_base:
            base_url = env_base.rstrip("/")
            st.markdown("**Offentligt base-URL (låst fra miljøvariabel):**")
            st.code(base_url, language="text")
        else:
            base_url = st.text_input(
                "Offentligt base-URL (brug det, publikum kan nå)",
                value=default_public_url
            ).rstrip("/")
            if base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1"):
                st.warning("🟠 Base-URL er localhost. QR virker ikke for publikum. Brug din offentlige URL.")

        join_url  = link_for(base_url, {"view": "ask",   "room": s["id"]})
        admin_url = link_for(base_url, {"view": "admin", "room": s["id"], "key": s["admin_key"]})

        c1, c2 = st.columns([2, 3])
        with c1:
            st.markdown("**Publikum-link**")
            st.code(join_url, language="text")
            st.markdown("**Moderator-link**")
            st.code(admin_url, language="text")

            # Vis kun QR hvis base ikke er localhost
            if base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1"):
                st.info("QR skjult, fordi Base-URL er localhost.")
            else:
                img = make_qr_png(join_url)
                st.markdown("**QR-kode til publikum**")
                st.image(img, caption="Scan for at stille spørgsmål", use_column_width=False)

        with c2:
            st.info("Tip: Brug den offentlige URL fra din Streamlit Cloud-app, så alle – også på 5G – kan deltage.")
            st.markdown("- Publikum: kan kun indsende spørgsmål.\n- Moderator: kan skjule/markere som besvaret og slette.")

def view_ask():
    qp = dict(st.query_params)
    room = qp.get("room", "")
    if not room:
        st.error("Mangler ?room=ID i URL'en.")
        return
    s = get_session(room)
    if not s:
        st.error("Session findes ikke.")
        return

    st.header(f"Stil et spørgsmål · {room}")

    # Anonym device-ID pr. browser-session
    if "asker_id" not in st.session_state:
        st.session_state["asker_id"] = uuid.uuid4().hex
    asker_id = st.session_state["asker_id"]

    # Form: clearer input automatisk ved submit
    with st.form("ask_form", clear_on_submit=True):
        txt = st.text_area(
            "Skriv dit spørgsmål her:",
            height=140,
            placeholder="Hvad vil du gerne have uddybet?",
            key="question_text",
        )
        submitted = st.form_submit_button("Send spørgsmål")

    if submitted:
        t = (txt or "").strip()
        if len(t) == 0:
            st.warning("Skriv venligst et spørgsmål.")
        else:
            add_question(room, t, asker_id=asker_id)
            st.success("Tak – dit spørgsmål er sendt!")
            set_qp(view="ask", room=room)
            st.rerun()

    # Dine spørgsmål i dag (seneste 24 timer)
    mine = list_user_questions_last24(room, asker_id)
    st.subheader("Dine spørgsmål i dag")
    if not mine:
        st.caption("Du har ikke stillet nogen spørgsmål i dag.")
    else:
        for q in mine:
            ts = datetime.fromtimestamp(q["created_at"]).strftime("%H:%M")
            badge = []
            if q.get("answered"):
                badge.append("besvaret")
            if q.get("hidden"):
                badge.append("skjult")
            btxt = f" ({', '.join(badge)})" if badge else ""
            st.markdown(f"- {q['text']}  \n  <span style='opacity:.7;font-size:0.9em'>kl. {ts}{btxt}</span>", unsafe_allow_html=True)

def view_admin():
    qp = dict(st.query_params)
    room = qp.get("room", "")
    key = qp.get("key", "")
    if not room:
        st.error("Mangler ?room=ID")
        return
    s = get_session(room)
    if not s:
        st.error("Session findes ikke.")
        return
    if key != s["admin_key"]:
        st.error("Forkert eller manglende admin nøgle (?key=).")
        return

    st.header(f"Moderator · {room}")
    st.caption("Denne visning opdaterer automatisk.")
    set_qp(view="admin", room=room, key=key)

    # Sidebar base-url (samme logik som på forsiden)
    default_public_url = "https://sporgogsvar-appv2-4jb4dnsmshrhypicrqfjd2.streamlit.app"
    env_base = os.environ.get("PUBLIC_BASE_URL")
    if env_base:
        base_url = env_base.rstrip("/")
        st.sidebar.markdown("**Base URL (låst fra miljøvariabel):**")
        st.sidebar.code(base_url, language="text")
    else:
        base_url = st.sidebar.text_input("Base URL til QR", value=default_public_url).rstrip("/")

    ask_url = link_for(base_url, {"view": "ask", "room": room})
    st.sidebar.code(ask_url, language="text")
    if base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1"):
        st.sidebar.info("QR skjult, fordi Base-URL er localhost.")
    else:
        st.sidebar.image(make_qr_png(ask_url))

    colA, colB = st.columns([1, 3])
    with colA:
        if st.button("Opdater liste"):
            st.rerun()
    with colB:
        st.caption("Listen sorteres: ubesvarede først, derefter skjulte, ældst først.")

    rows = list_questions(room, include_hidden=True)
    if not rows:
        st.info("Ingen spørgsmål endnu.")
    else:
        for r in rows:
            with st.container(border=True):
                st.markdown(r["text"])
                meta = datetime.fromtimestamp(r["created_at"]).strftime("%H:%M:%S")
                st.caption(
                    f"id: {r['id'][:8]} • {meta} • "
                    f"{'SKJULT • ' if r['hidden'] else ''}"
                    f"{'BESVARET' if r['answered'] else ''}"
                )

                c1, c2, c3 = st.columns(3)

                with c1:
                    if st.button(("Vis" if r["hidden"] else "Skjul"), key=f"h{r['id']}"):
                        toggle_field(r["id"], "hidden")
                        st.rerun()

                with c2:
                    if st.button(("Markér ubesvaret" if r["answered"] else "Markér besvaret"), key=f"a{r['id']}"):
                        toggle_field(r["id"], "answered")
                        st.rerun()

                with c3:
                    if st.button("Slet", key=f"d{r['id']}"):
                        delete_question(r["id"])
                        st.rerun()

        st.divider()
        df = export_csv(room)
        if df is not None:
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", data=csv, file_name=f"{room}_questions.csv", mime="text/csv")

def main():
    init_db()
    header()
    view = nav()

    if view == "home":
        view_home()
    elif view == "ask":
        view_ask()
    elif view == "admin":
        view_admin()
    else:
        st.error("Ukendt view. Brug ?view=home|ask|admin")

if __name__ == "__main__":
    main()
