import os
import time
import requests
import streamlit as st

API_BASE_URL = os.getenv("RAG_API_URL", "http://localhost:8000").strip().rstrip("/")


# ==========================================
# BACKEND API HELPERS (Unchanged Logic)
# ==========================================

def api_headers():
    token = st.session_state.get("auth_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def api_request(method, path, *, retry_on_refresh=True, **kwargs):
    """Send an authenticated request and rotate the access token once when needed."""
    try:
        response = requests.request(method, f"{API_BASE_URL}{path}", headers=api_headers(), **kwargs)
    except requests.RequestException:
        raise
    if response.status_code != 401 or not retry_on_refresh or not st.session_state.get("refresh_token"):
        return response
    try:
        refresh = requests.post(f"{API_BASE_URL}/auth/refresh", json={"refresh_token": st.session_state.refresh_token}, timeout=15)
        if refresh.status_code != 200:
            return response
        tokens = refresh.json()
        st.session_state.auth_token = tokens["token"]
        st.session_state.refresh_token = tokens["refresh_token"]
        return requests.request(method, f"{API_BASE_URL}{path}", headers=api_headers(), **kwargs)
    except requests.RequestException:
        return response


def logout_from_backend():
    if not st.session_state.get("auth_token"):
        return
    try:
        api_request(
            "POST", "/auth/logout",
            params={"refresh_token": st.session_state.get("refresh_token", "")},
            timeout=10,
        )
    except requests.RequestException:
        pass


def fetch_profile():
    try:
        response = api_request("GET", "/profile", timeout=15)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return {}
    return {}


def fetch_conversations():
    try:
        response = api_request("GET", "/chat/history", timeout=15)
        if response.status_code == 200:
            st.session_state.conversations = response.json().get("conversations", [])
        else:
            st.session_state.conversations = []
    except requests.RequestException:
        st.session_state.conversations = []


def fetch_conversation_messages(conversation_id):
    try:
        response = api_request("GET", f"/chat/history/{conversation_id}", timeout=15)
        if response.status_code == 200:
            st.session_state.chat_messages = response.json().get("messages", [])
            st.session_state.conversation_id = conversation_id
            return True
    except requests.RequestException:
        return False
    return False


def save_chat_message(role, content, conversation_id=None, title=None):
    if not st.session_state.get("auth_token"):
        return None
    payload = {
        "role": role,
        "content": content,
        "conversation_id": conversation_id,
        "title": title,
        "created_at": time.time(),
    }
    try:
        response = api_request("POST", "/chat/save", json=payload, timeout=20)
        if response.status_code == 200:
            data = response.json()
            st.session_state.conversation_id = data.get("conversation_id")
            return data.get("conversation_id")
    except requests.RequestException:
        pass
    return conversation_id


def upload_file_to_backend(file_obj, conversation_id):
    if file_obj is None:
        return
    files = {"file": (file_obj.name, file_obj.getvalue(), file_obj.type or "application/octet-stream")}
    try:
        response = api_request("POST", "/upload_file", data={"conversation_id": conversation_id}, files=files, timeout=120)
        if response.status_code in (200, 202):
            payload = response.json()
            st.session_state.last_uploaded = file_obj.name
            st.session_state.upload_jobs[payload.get("document_id")] = {"filename": file_obj.name, "status": payload.get("status", "uploaded")}
            st.toast(f"Uploaded: {file_obj.name}", icon="✅")
        else:
            st.warning(f"{file_obj.name}: {response.text}")
    except requests.RequestException:
        st.error("Upload failed: backend unavailable")


def refresh_upload_jobs():
    conversation_id = st.session_state.get("conversation_id")
    if not conversation_id:
        return
    for document_id in list(st.session_state.upload_jobs):
        try:
            response = api_request("GET", f"/documents/{document_id}", params={"conversation_id": conversation_id}, timeout=10)
            if response.status_code == 200:
                st.session_state.upload_jobs[document_id] = response.json()
        except requests.RequestException:
            continue


# ==========================================
# SESSION STATE INITIALIZATION
# ==========================================

if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None
if "page" not in st.session_state:
    st.session_state.page = "chat"
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "conversations" not in st.session_state:
    st.session_state.conversations = []
if "profile" not in st.session_state:
    st.session_state.profile = {}
if "selected_conversation" not in st.session_state:
    st.session_state.selected_conversation = None
if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "output_text" not in st.session_state:
    st.session_state.output_text = ""
if "last_uploaded" not in st.session_state:
    st.session_state.last_uploaded = ""
if "upload_jobs" not in st.session_state:
    st.session_state.upload_jobs = {}
if "last_sources" not in st.session_state:
    st.session_state.last_sources = []
if "last_context_mode" not in st.session_state:
    st.session_state.last_context_mode = "none"
if "uploaded_file_ids" not in st.session_state:
    st.session_state.uploaded_file_ids = set()
if "upload_widget_version" not in st.session_state:
    st.session_state.upload_widget_version = 0

# ==========================================
# AUTHENTICATION PAGE (Light Mode)
# ==========================================

if not st.session_state.auth_token:
    st.set_page_config(page_title="MultiRAG - Login", page_icon="✨", layout="centered")
    
    st.markdown("""
        <style>
            html, body, [data-testid="stAppViewContainer"] {
                background-color: #f8fafc;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            .auth-card {
                background: white;
                padding: 40px;
                border-radius: 16px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.05);
                border: 1px solid #e2e8f0;
                margin-top: 50px;
            }
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown('<h1 style="text-align: center; color: #0f172a;">MultiRAG</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align: center; color: #64748b; margin-bottom: 20px;">Multimodal RAG Assistant</p>', unsafe_allow_html=True)
    
    auth_mode = st.radio("Action", ["Login", "Create account"], horizontal=True, label_visibility="collapsed")
    username = st.text_input("Username", placeholder="Enter your username")
    password = st.text_input("Password", type="password", placeholder="Enter your password")

    if st.button(auth_mode, type="primary", use_container_width=True):
        endpoint = "/auth/login" if auth_mode == "Login" else "/auth/register"
        try:
            response = requests.post(
                f"{API_BASE_URL}{endpoint}",
                json={"username": username, "password": password},
                timeout=10,
            )
            if response.status_code == 200:
                if auth_mode == "Create account":
                    st.success("Account created. Please sign in.")
                else:
                    payload = response.json()
                    st.session_state.auth_token = payload["token"]
                    st.session_state.refresh_token = payload.get("refresh_token")
                    st.session_state.username = payload["username"]
                    st.session_state.page = "chat"
                    st.session_state.chat_messages = []
                    st.session_state.conversation_id = None
                    st.session_state.selected_conversation = None
                    st.rerun()
            else:
                st.error(response.json().get("detail", "Operation failed"))
        except requests.RequestException:
            st.error("Backend is unavailable")
    st.stop()

# ==========================================
# MAIN APPLICATION LAYOUT (Light Mode UI)
# ==========================================

st.set_page_config(page_title="MultiRAG", page_icon="✨", layout="wide")

# Custom Light Theme & Layout Fixes CSS
st.markdown(
    """
    <style>
    :root {
        --bg-main: #f8fafc;
        --sidebar-bg: #ffffff;
        --card-bg: #ffffff;
        --text-dark: #0f172a;
        --text-muted: #64748b;
        --primary: #2563eb;
        --primary-light: #dbeafe;
        --border-color: #e2e8f0;
    }

    html, body, [data-testid="stAppViewContainer"] {
        background-color: var(--bg-main);
        color: var(--text-dark);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* Left Sidebar Styling */
    [data-testid="stSidebar"] {
        background-color: var(--sidebar-bg) !important;
        border-right: 1px solid var(--border-color);
        padding-top: 1rem;
    }

    /* Profile Badge at Top of Sidebar */
    .user-profile-badge {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 14px;
        background: #f1f5f9;
        border-radius: 12px;
        margin-bottom: 20px;
        border: 1px solid #e2e8f0;
    }
    .user-avatar {
        width: 38px;
        height: 38px;
        border-radius: 50%;
        background: var(--primary);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 1rem;
    }
    .user-name {
        font-weight: 600;
        color: var(--text-dark);
        font-size: 0.95rem;
    }

    .brand-title {
        font-size: 2rem;
        font-weight: 800;
        color: var(--text-dark);
        margin-bottom: 0px;
        line-height: 1.1;
    }
    .brand-sub {
        font-size: 0.88rem;
        color: var(--text-muted);
        margin-bottom: 20px;
    }

    /* Sidebar Buttons */
    .stButton > button {
        border-radius: 10px !important;
        border: 1px solid var(--border-color) !important;
        background-color: #ffffff !important;
        color: var(--text-dark) !important;
        font-weight: 600 !important;
        transition: all 0.2s ease;
    }
    
    .stButton > button:hover {
        background-color: #f1f5f9 !important;
        border-color: #cbd5e1 !important;
    }

    /* Fix Sidebar Chat Item Alignment (Issue 3) */
    [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
        align-items: center !important;
        gap: 6px !important;
        margin-bottom: 4px;
    }

    .sidebar-section-title {
        color: var(--text-muted);
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-top: 20px;
        margin-bottom: 10px;
    }

    /* Chat Messages & Cards */
    .chat-bubble-user {
        background-color: var(--primary-light);
        color: #1e3a8a;
        padding: 14px 18px;
        border-radius: 16px 16px 2px 16px;
        margin-bottom: 12px;
        max-width: 80%;
        margin-left: auto;
        font-size: 0.95rem;
    }

    .chat-bubble-assistant {
        background-color: #ffffff;
        color: var(--text-dark);
        border: 1px solid var(--border-color);
        padding: 14px 18px;
        border-radius: 16px 16px 16px 2px;
        margin-bottom: 12px;
        max-width: 85%;
        font-size: 0.95rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }

    /* File Attachment Badge */
    .file-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: #ffffff;
        border: 1px solid #cbd5e1;
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 0.82rem;
        color: #475569;
        margin-bottom: 10px;
    }

    /* Modern Unified Input Card Styling (Issue 2) */
    [data-testid="stForm"] {
        border: 1px solid #cbd5e1 !important;
        border-radius: 16px !important;
        padding: 16px !important;
        background-color: #ffffff !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.03) !important;
    }

    [data-testid="stForm"] textarea {
        border: none !important;
        box-shadow: none !important;
        background-color: transparent !important;
        padding: 0 !important;
    }

    [data-testid="stForm"] textarea:focus {
        outline: none !important;
        box-shadow: none !important;
    }

    /* Hide Streamlit Header Padding */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        max-width: 900px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Fetch user profile & status
profile = fetch_profile() if st.session_state.auth_token else {}
if profile:
    st.session_state.profile = profile
user_name = st.session_state.profile.get("username", st.session_state.get("username", "Ahmed1"))
first_letter = (user_name or "A")[0].upper()

refresh_upload_jobs()

# ==========================================
# LEFT SIDEBAR
# ==========================================

with st.sidebar:
    # 1. User Profile at the Top
    st.markdown(
        f"""
        <div class="user-profile-badge">
            <div class="user-avatar">{first_letter}</div>
            <div class="user-name">{user_name}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. MultiRAG Title
    st.markdown('<div class="brand-title">MultiRAG</div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Multimodal RAG Assistant</div>', unsafe_allow_html=True)

    # 3. New Chat Button
    if st.button("+ New Chat", use_container_width=True, type="primary"):
        st.session_state.page = "chat"
        st.session_state.selected_conversation = None
        st.session_state.conversation_id = None
        st.session_state.chat_messages = []
        st.session_state.output_text = ""
        st.session_state.last_uploaded = ""
        st.session_state.upload_jobs = {}
        st.session_state.last_sources = []
        st.session_state.last_context_mode = "none"
        st.session_state.uploaded_file_ids = set()
        st.session_state.upload_widget_version += 1
        st.rerun()

    # 4. CHATS History List (Issue 3 Fixed Layout)
    st.markdown("<div class='sidebar-section-title'>CHATS</div>", unsafe_allow_html=True)
    if not st.session_state.conversations:
        fetch_conversations()
        
    for item in st.session_state.conversations:
        label = item.get("title") or "New chat"
        conv_id = item.get("id")
        
        # Proper ratio [8, 2] keeps the delete button inside the chat item bounds
        col1, col2 = st.columns([8, 2])
        
        with col1:
            if st.button(f"💬 {label}", key=f"conv_{conv_id}", use_container_width=True):
                st.session_state.page = "chat"
                st.session_state.selected_conversation = conv_id
                st.session_state.output_text = ""
                st.session_state.last_uploaded = ""
                st.session_state.upload_jobs = {}
                st.session_state.last_sources = []
                st.session_state.last_context_mode = "none"
                st.session_state.uploaded_file_ids = set()
                st.session_state.upload_widget_version += 1
                fetch_conversation_messages(conv_id)
                st.rerun()
        
        with col2:
            if st.button("🗑️", key=f"delete_{conv_id}", help="Delete this chat", use_container_width=True):
                try:
                    response = api_request("DELETE", f"/chat/history/{conv_id}", timeout=10)
                    if response.status_code == 200:
                        st.toast("Chat deleted", icon="✅")
                        if st.session_state.selected_conversation == conv_id:
                            st.session_state.selected_conversation = None
                            st.session_state.chat_messages = []
                        fetch_conversations()
                        st.rerun()
                    else:
                        st.error("Failed to delete chat")
                except requests.RequestException:
                    st.error("Could not delete chat")

    st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
    
    # 5. Footer Actions
    if st.button("Add API Key", use_container_width=True):
        st.session_state.page = "api_keys"
        st.rerun()

    if st.button("Logout", use_container_width=True):
        logout_from_backend()
        st.session_state.auth_token = None
        st.session_state.refresh_token = None
        st.session_state.username = None
        st.session_state.page = "chat"
        st.session_state.chat_messages = []
        st.session_state.conversations = []
        st.session_state.selected_conversation = None
        st.session_state.conversation_id = None
        st.session_state.output_text = ""
        st.rerun()

# ==========================================
# MAIN CONTENT VIEW
# ==========================================

# API KEYS SETTINGS PAGE
if st.session_state.page == "api_keys":
    st.title("API Keys Configuration")
    try:
        response = api_request("GET", "/settings/providers", timeout=15)
        providers = response.json().get("providers", {}) if response.status_code == 200 else {}
    except requests.RequestException:
        providers = {}

    provider_names = list(providers.keys()) or ["google", "openrouter", "groq"]
    selected_provider = st.selectbox("Provider", provider_names)
    selected = providers.get(selected_provider, {})
    api_key = st.text_input("API Key", value="", type="password", placeholder="Leave empty to keep current key")
    
    if selected.get("configured"):
        st.caption("A key is already configured.")
        
    model_name = st.text_input("Model Name", value=selected.get("model_name", "") or "")
    enabled = st.checkbox("Enabled", value=bool(selected.get("enabled", True)))

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Save API key", type="primary", use_container_width=True):
            payload = {"provider": selected_provider, "api_key": api_key, "model_name": model_name, "enabled": enabled}
            try:
                save_response = api_request("POST", "/settings/providers", json=payload, timeout=20)
                if save_response.status_code == 200:
                    st.success("Saved successfully")
                else:
                    st.error(save_response.json().get("detail", "Failed to save"))
            except requests.RequestException:
                st.error("Backend unavailable")
    with col2:
        if st.button("Back to chat", use_container_width=True):
            st.session_state.page = "chat"
            st.rerun()

# CHAT VIEW
else:
    # Display Existing Conversation Messages
    if st.session_state.selected_conversation:
        if not st.session_state.chat_messages:
            fetch_conversation_messages(st.session_state.selected_conversation)
        
        for message in st.session_state.chat_messages:
            role = message.get("role", "assistant")
            content = message.get("content", "")
            if role == "user":
                st.markdown(f'<div class="chat-bubble-user">{content}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-bubble-assistant">{content}</div>', unsafe_allow_html=True)

    elif not st.session_state.output_text:
        st.markdown(
            """
            <div style="text-align: center; padding: 40px 20px; color: #64748b;">
                <h3>Upload your file to begin</h3>
                <p>The system will use it as context for the conversation.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Output Display (For active request)
    if st.session_state.output_text:
        st.markdown(f'<div class="chat-bubble-assistant"><b>Output:</b><br>{st.session_state.output_text}</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Unified File Badge (If uploaded)
    if st.session_state.last_uploaded:
        st.markdown(
            f'<div class="file-badge">📄 {st.session_state.last_uploaded} (in context)</div>',
            unsafe_allow_html=True,
        )

    # Process Status Jobs
    for job in st.session_state.upload_jobs.values():
        label = job.get("filename", "Uploaded document")
        state = job.get("status", "queued")
        if state in {"uploaded", "queued", "processing"}:
            st.info(f"{label}: processing…")
        elif state == "ready":
            st.toast(f"{label}: Ready for questions", icon="✅")

    # ==========================================
    # UNIFIED COMPOSER / INPUT FORM (Issues 1 & 2 Fixed)
    # ==========================================
    with st.form("chat_form", clear_on_submit=False):
        prompt = st.text_area(
            "Message",
            placeholder="Type your message here...",
            label_visibility="collapsed",
            height=80,
        )

        col_attach, col_btn = st.columns([5, 1])

        with col_attach:
            # Single Uploader for Documents and Images
            uploaded_file = st.file_uploader(
                "Upload Context File",
                type=["pdf", "png", "jpg", "jpeg", "gif", "txt", "md"],
                key=f"unified_upload_{st.session_state.upload_widget_version}",
                label_visibility="collapsed",
            )

        with col_btn:
            st.markdown("<div style='margin-top: 2px;'></div>", unsafe_allow_html=True)
            submit_btn = st.form_submit_button("Send ➔", type="primary", use_container_width=True)

        # File classification and automatic upload
        is_image = False
        is_doc = False

        if uploaded_file is not None:
            ext = uploaded_file.name.split(".")[-1].lower()
            if ext in ["png", "jpg", "jpeg", "gif"]:
                is_image = True
            elif ext in ["pdf", "txt", "md"]:
                is_doc = True

        if submit_btn:
            if not prompt or not prompt.strip():
                st.warning("Please enter a message first")
            else:
                st.session_state.output_text = ""
                st.session_state.last_sources = []
                st.session_state.last_context_mode = "image" if is_image else "document" if is_doc else "text"

                title = prompt.strip()[:40] if prompt.strip() else "New chat"
                cid = save_chat_message("user", prompt.strip(), st.session_state.get("conversation_id"), title=title)
                st.session_state.conversation_id = cid or st.session_state.get("conversation_id")
                if is_doc and uploaded_file.file_id not in st.session_state.uploaded_file_ids:
                    upload_file_to_backend(uploaded_file, st.session_state.conversation_id)
                    st.session_state.uploaded_file_ids.add(uploaded_file.file_id)

                try:
                    with st.spinner("Processing..."):
                        if is_image:
                            st.info(f"📸 Sending image: {uploaded_file.name}")
                            response = api_request(
                                "POST", "/chat_with_image",
                                data={"question": prompt.strip(), "k": "5", "conversation_id": st.session_state.conversation_id},
                                files={"image": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type or "image/png")},
                                timeout=120
                            )
                        else:
                            response = api_request(
                                "POST", "/chat",
                                json={"question": prompt.strip(), "k": 5, "conversation_id": st.session_state.conversation_id},
                                timeout=120
                            )

                        if response.status_code == 200:
                            payload = response.json()
                            answer = payload.get("answer", "No answer returned.")
                            st.session_state.output_text = answer
                            if is_image:
                                st.session_state.last_sources = []
                                st.session_state.last_context_mode = "image"
                            else:
                                st.session_state.last_sources = payload.get("sources", [])
                                st.session_state.last_context_mode = "document" if st.session_state.last_sources else "text"
                            save_chat_message("assistant", answer, cid, title=title)
                            fetch_conversations()
                            st.rerun()
                        else:
                            try:
                                st.error(response.json().get("detail", "The request could not be completed."))
                            except ValueError:
                                st.error("The request could not be completed. Please try again.")
                except requests.RequestException:
                    st.error("API unavailable")

    # Sources Citations Display
    if st.session_state.last_context_mode != "image" and st.session_state.last_sources:
        st.markdown("### Sources")
        for source in st.session_state.last_sources:
            page = source.get("page_number")
            label = f"📖 {source.get('filename', 'Document')}{f' — page {page}' if page else ''}"
            with st.expander(label):
                document_id = source.get("document_id")
                if document_id and page:
                    try:
                        cited_page = api_request("GET", f"/documents/{document_id}/pages/{page}", params={"conversation_id": st.session_state.conversation_id}, timeout=15)
                        if cited_page.status_code == 200:
                            st.write(cited_page.json().get("text", ""))
                        else:
                            st.caption("The cited page is no longer available.")
                    except requests.RequestException:
                        st.caption("Could not load the cited page.")