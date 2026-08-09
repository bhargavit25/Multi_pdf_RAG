import streamlit as st
import requests
import json
import time

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Multi-PDF RAG Chatbot", layout="wide", page_icon="📚")

if "chat_display" not in st.session_state:
    st.session_state.chat_display = []
if "session_id" not in st.session_state:
    st.session_state.session_id = "demo-session"


# ---------------- Visual identity ----------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {
    --paper: #F3F5F7;
    --paper-raised: #FFFFFF;
    --ink: #1F2A44;
    --ink-soft: #5B6478;
    --amber: #FFC857;
    --amber-deep: #E8AC2E;
    --sage: #6B9080;
    --coral: #E85D4E;
    --violet: #7C6FAD;
    --rule: #D8DEE6;
}

html, body, [data-testid="stAppViewContainer"] {
    background: var(--paper);
    color: var(--ink);
    font-family: 'Inter', sans-serif;
}

h1, h2, h3 { font-family: 'Fraunces', serif; color: var(--ink); letter-spacing: -0.01em; }

/* ---- Masthead ---- */
.masthead {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    border-bottom: 2px solid var(--ink);
    padding-bottom: 0.6rem;
    margin-bottom: 0.3rem;
}
.masthead .title {
    font-family: 'Fraunces', serif;
    font-weight: 700;
    font-size: 2.1rem;
    color: var(--ink);
}
.masthead .subtitle {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    color: var(--ink-soft);
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

/* ---- Sidebar: the binder ---- */
[data-testid="stSidebar"] {
    background: var(--paper-raised);
    border-right: 2px solid var(--ink);
}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    font-family: 'Fraunces', serif;
    font-size: 1.05rem;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.35rem;
}

/* Upload dropzone reads as a highlighter tab */
[data-testid="stFileUploader"] section {
    background: #FFF9E8;
    border: 1.5px dashed var(--amber-deep);
    border-radius: 4px;
}

/* Buttons: flat, inked, no default rounded-pill look */
.stButton > button {
    background: var(--ink);
    color: var(--paper);
    border: none;
    border-radius: 3px;
    font-family: 'Inter', sans-serif;
    font-weight: 500;
    padding: 0.5rem 1rem;
    transition: background 0.15s ease;
}
.stButton > button:hover { background: var(--violet); color: white; }
.stButton > button:active { background: var(--amber-deep); }

/* Primary "Index PDFs" button gets the highlighter treatment */
[data-testid="stSidebar"] .stButton > button {
    background: var(--amber);
    color: var(--ink);
    font-weight: 600;
}
[data-testid="stSidebar"] .stButton > button:hover { background: var(--amber-deep); }

/* ---- Status chips ---- */
.status-chip {
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    padding: 0.15rem 0.55rem;
    border-radius: 3px;
    margin: 0.15rem 0;
}
.status-done { background: #E3EDE8; color: var(--sage); border: 1px solid var(--sage); }
.status-error { background: #FBE7E4; color: var(--coral); border: 1px solid var(--coral); }
.status-pending { background: #FFF3D9; color: var(--amber-deep); border: 1px solid var(--amber-deep); }

/* ---- Chat area: margin notes on ruled paper ---- */
[data-testid="stChatMessage"] {
    border-radius: 4px;
    border: 1px solid var(--rule);
    background: var(--paper-raised);
}
[data-testid="stChatMessageAvatarUser"] ~ div [data-testid="stChatMessage"],
div[data-testid="stChatMessage"]:has(div[data-testid="stChatMessageAvatarUser"]) {
    background: var(--ink);
    color: var(--paper);
}

/* ---- Flashcards: index cards with a folded corner ---- */
[data-testid="stExpander"] {
    background: #FFFDF6;
    border: 1px solid var(--rule);
    border-left: 4px solid var(--violet);
    border-radius: 2px;
    box-shadow: 2px 3px 0px rgba(31,42,68,0.08);
    margin-bottom: 0.5rem;
}
[data-testid="stExpander"] summary {
    font-family: 'Fraunces', serif;
    font-weight: 600;
    color: var(--ink);
}

/* ---- Quiz: scantron-style bubbles instead of default radios ---- */
div[role="radiogroup"] label {
    background: var(--paper-raised);
    border: 1.5px solid var(--rule);
    border-radius: 20px;
    padding: 0.4rem 0.9rem !important;
    margin: 0.2rem 0.3rem 0.2rem 0;
    display: inline-block;
}
div[role="radiogroup"] label:hover { border-color: var(--violet); }

/* ---- Dividers as ruled lines ---- */
hr { border-top: 1px solid var(--rule); }

/* Captions (page/source refs) in mono, like a citation stamp */
.stCaption, [data-testid="stCaptionContainer"] {
    font-family: 'IBM Plex Mono', monospace !important;
    color: var(--ink-soft) !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="masthead">
    <span class="title">📚 Multi-PDF RAG Chatbot</span>
    <span class="subtitle">study desk</span>
</div>
""", unsafe_allow_html=True)


def safe_post(endpoint, payload=None, files=None, timeout=60):
    """Wrapper around requests.post that never crashes the app."""
    try:
        resp = requests.post(f"{API_URL}{endpoint}", json=payload, files=files, timeout=timeout)
        if resp.ok:
            try:
                return resp.json(), None
            except json.JSONDecodeError:
                return None, f"Backend returned invalid JSON (status {resp.status_code}). Check backend terminal for errors."
        else:
            return None, f"Backend error {resp.status_code}: {resp.text[:300]}"
    except requests.exceptions.ConnectionError:
        return None, "⚠️ Cannot connect to backend. Make sure uvicorn is running on port 8000."
    except requests.exceptions.Timeout:
        return None, "⚠️ Request timed out. The backend may be processing a large document."
    except requests.exceptions.RequestException as e:
        return None, f"⚠️ Request failed: {e}"


def safe_get(endpoint, timeout=10):
    try:
        resp = requests.get(f"{API_URL}{endpoint}", timeout=timeout)
        if resp.ok:
            try:
                return resp.json(), None
            except json.JSONDecodeError:
                return None, "Backend returned invalid JSON."
        else:
            return None, f"Backend error {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return None, "⚠️ Cannot connect to backend. Make sure uvicorn is running on port 8000."
    except requests.exceptions.RequestException as e:
        return None, f"⚠️ Request failed: {e}"


def upload_and_wait(f, poll_interval=2, max_wait=900):
    """
    Uploads a file (returns almost instantly), then polls /status/{filename}
    until the backend reports done or error - avoids timeouts on large PDFs.
    """
    files = {"file": (f.name, f.getvalue(), "application/pdf")}
    data, error = safe_post("/upload", files=files, timeout=30)
    if error:
        return None, error
    if data and "error" in data:
        return None, data["error"]

    filename = data["filename"]
    waited = 0
    while waited < max_wait:
        status_data, status_error = safe_get(f"/status/{filename}")
        if status_error:
            return None, status_error
        status = status_data.get("status", "unknown")

        if status.startswith("done"):
            chunk_count = status.split(":", 1)[1] if ":" in status else "?"
            return {"filename": filename, "chunks_indexed": chunk_count}, None
        if status.startswith("error"):
            return None, status
        if status == "unknown":
            return None, "Backend lost track of this file's status."

        time.sleep(poll_interval)
        waited += poll_interval

    return None, f"Still processing after {max_wait}s - check back later or re-check /status/{filename}."


# ---------------- Sidebar: Upload + Tools ----------------
with st.sidebar:
    st.markdown("### 📎 Upload PDFs")
    uploaded_files = st.file_uploader("Choose PDF(s)", type="pdf", accept_multiple_files=True, label_visibility="collapsed")

    if uploaded_files and st.button("Index PDFs", use_container_width=True):
        for f in uploaded_files:
            with st.spinner(f"Indexing {f.name}... large PDFs can take a few minutes"):
                data, error = upload_and_wait(f)
            if error:
                st.markdown(f'<span class="status-chip status-error">{f.name}: {error}</span>', unsafe_allow_html=True)
            elif data:
                st.markdown(f'<span class="status-chip status-done">{f.name}: {data["chunks_indexed"]} chunks indexed</span>', unsafe_allow_html=True)
            else:
                st.warning(f"{f.name}: Unexpected response")

    st.markdown("### 🗂️ Tools")

    files_data, files_error = safe_get("/files")
    available_files = files_data.get("files", []) if files_data else []

    if files_error:
        st.error(files_error)
    elif not available_files:
        st.info("No documents indexed yet. Upload a PDF above.")

    selected_file = st.selectbox("Select a document", available_files) if available_files else None

    if selected_file:
        if st.button("📝 Summarize", use_container_width=True):
            with st.spinner("Summarizing..."):
                data, error = safe_post("/summarize", {"filename": selected_file}, timeout=120)
            if error:
                st.error(error)
            else:
                st.session_state.summary = data.get("summary", "")

        if st.button("❓ Generate Quiz", use_container_width=True):
            with st.spinner("Generating quiz..."):
                data, error = safe_post("/quiz", {"filename": selected_file}, timeout=120)
            if error:
                st.error(error)
            else:
                st.session_state.quiz_raw = data.get("quiz", "")

        if st.button("🗂️ Generate Flashcards", use_container_width=True):
            with st.spinner("Generating flashcards..."):
                data, error = safe_post("/flashcards", {"filename": selected_file}, timeout=120)
            if error:
                st.error(error)
            else:
                st.session_state.flashcards_raw = data.get("flashcards", "")

# ---------------- Main: Chat ----------------
st.markdown("#### Chat with your documents")

for role, text, sources in st.session_state.chat_display:
    with st.chat_message(role):
        st.write(text)
        if sources:
            for s in sources:
                st.caption(f"📄 {s['file']}, page {s['page']}")

question = st.chat_input("Ask a question about your PDFs...")
if question:
    st.session_state.chat_display.append(("user", question, None))
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            data, error = safe_post("/chat", {
                "question": question,
                "session_id": st.session_state.session_id
            }, timeout=60)

        if error:
            st.error(error)
        else:
            answer = data.get("answer", "")
            sources = data.get("sources", [])
            st.write(answer)
            for s in sources:
                st.caption(f"📄 {s['file']}, page {s['page']}")
            st.session_state.chat_display.append(("assistant", answer, sources))

# ---------------- Summary / Quiz / Flashcards display ----------------
if "summary" in st.session_state:
    st.divider()
    st.markdown("#### 📝 Summary")
    st.write(st.session_state.summary)

if "quiz_raw" in st.session_state:
    st.divider()
    st.markdown("#### ❓ Quiz")
    try:
        clean = st.session_state.quiz_raw.replace("```json", "").replace("```", "").strip()
        quiz_items = json.loads(clean)
        for i, q in enumerate(quiz_items, 1):
            st.markdown(f"**Q{i}. {q['question']}**")
            choice = st.radio("Options", q["options"], key=f"quiz_{i}", label_visibility="collapsed")
            if st.button(f"Check Q{i}", key=f"check_{i}"):
                if choice == q["answer"]:
                    st.success("Correct!")
                else:
                    st.error(f"Incorrect — correct answer: {q['answer']}")
    except Exception:
        st.warning("Could not parse quiz as structured JSON. Raw output below:")
        st.text(st.session_state.quiz_raw)

if "flashcards_raw" in st.session_state:
    st.divider()
    st.markdown("#### 🗂️ Flashcards")
    try:
        clean = st.session_state.flashcards_raw.replace("```json", "").replace("```", "").strip()
        cards = json.loads(clean)
        for c in cards:
            with st.expander(c["term"]):
                st.write(c["definition"])
    except Exception:
        st.warning("Could not parse flashcards as structured JSON. Raw output below:")
        st.text(st.session_state.flashcards_raw)