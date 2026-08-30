import os
import time

import requests
import streamlit as st

API_BASE_URL = os.getenv("RAG_API_URL", "http://localhost:8000").strip().rstrip("/")


def api_headers():
    token = st.session_state.get("auth_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def fetch_profile():
    try:
        response = requests.get(f"{API_BASE_URL}/profile", headers=api_headers(), timeout=15)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        return {}
    return {}


def fetch_conversations():
    try:
        response = requests.get(f"{API_BASE_URL}/chat/history", headers=api_headers(), timeout=15)
        if response.status_code == 200:
            st.session_state.conversations = response.json().get("conversations", [])
        else:
            st.session_state.conversations = []
    except requests.RequestException:
        st.session_state.conversations = []


def fetch_conversation_messages(conversation_id):
    try:
        response = requests.get(f"{API_BASE_URL}/chat/history/{conversation_id}", headers=api_headers(), timeout=15)
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
        response = requests.post(f"{API_BASE_URL}/chat/save", json=payload, headers=api_headers(), timeout=20)
        if response.status_code == 200:
            data = response.json()
            st.session_state.conversation_id = data.get("conversation_id")
            return data.get("conversation_id")
    except requests.RequestException:
        pass
    return conversation_id


if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "page" not in st.session_state:
    st.session_state.page = "new_chat"
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

if not st.session_state.auth_token:
    st.set_page_config(page_title="MultiRAG", page_icon="✨", layout="centered")
    st.title("Multi-Modal RAG Platform")
    st.subheader("تسجيل الدخول")
    auth_mode = st.radio("الإجراء", ["دخول", "إنشاء حساب"], horizontal=True, label_visibility="collapsed")
    username = st.text_input("اسم المستخدم")
    password = st.text_input("كلمة المرور", type="password")
    if st.button(auth_mode, type="primary", use_container_width=True):
        endpoint = "/auth/login" if auth_mode == "دخول" else "/auth/register"
        try:
            response = requests.post(
                f"{API_BASE_URL}{endpoint}",
                json={"username": username, "password": password},
                timeout=10,
            )
            if response.status_code == 200:
                if auth_mode == "إنشاء حساب":
                    st.success("تم إنشاء الحساب. سجّل الدخول الآن.")
                else:
                    payload = response.json()
                    st.session_state.auth_token = payload["token"]
                    st.session_state.username = payload["username"]
                    st.session_state.chat_messages = []
                    st.session_state.conversation_id = None
                    st.session_state.selected_conversation = None
                    st.session_state.page = "new_chat"
                    st.rerun()
            else:
                st.error(response.json().get("detail", "تعذر تنفيذ العملية"))
        except requests.RequestException:
            st.error("الـ backend غير متاح")
    st.stop()

st.set_page_config(page_title="MultiRAG", page_icon="✨", layout="wide")

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"] { background: #f5f7fb; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f172a, #1f2638); }
    [data-testid="stSidebar"] * { color: #edf2ff; }
    .brand-box { display: flex; align-items: center; gap: 10px; margin: 12px 0 18px; }
    .brand-mark {
        width: 28px; height: 28px; border-radius: 9px;
        background: linear-gradient(135deg, #8c7ef6, #6c5ce7);
        display: inline-flex; align-items: center; justify-content: center;
        font-size: 12px; font-weight: 800; color: white;
    }
    .brand-label { font-size: 22px; font-weight: 800; }
    .brand-sub { color: #bfc9db; font-size: 12px; margin-top: 2px; }
    .primary-button > button {
        background: linear-gradient(135deg, #745ef5, #8d66f5);
        border: none; border-radius: 12px; color: white; font-weight: 800; height: 48px;
    }
    .sidebar-list .stButton > button {
        width: 100%; text-align: left; border-radius: 12px; border: 1px solid rgba(255,255,255,0.06);
        background: rgba(255,255,255,0.02); color: #e8ecff; padding: 10px 12px;
    }
    .sidebar-list .stButton > button:hover { background: rgba(125, 112, 255, 0.14); }
    .sidebar-plan {
        background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 14px 12px; margin-top: 18px;
    }
    .sidebar-plan .plan-title { color: #f1f5ff; font-weight: 700; }
    .workspace-label { color: #bfc9db; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; margin: 20px 0 10px; }
    .main-shell { background: #f6f7fb; border-radius: 20px; }
    .main-title { font-size: 30px; font-weight: 800; margin: 0 0 4px; color: #1f2430; }
    .subtitle { color: #64748b; font-size: 14px; margin: 0 0 18px; }
    .chat-header {
        display: flex; align-items: center; justify-content: space-between; background: rgba(255,255,255,0.72);
        border: 1px solid #edf0f4; border-radius: 14px; padding: 12px 16px; margin-bottom: 10px;
    }
    .chat-header .title { font-size: 14px; color: #1f2430; font-weight: 700; }
    .header-actions { display: flex; gap: 8px; }
    .small-pill {
        background: white; border: 1px solid #e8edf4; border-radius: 10px; padding: 7px 12px; color: #374151; font-weight: 600; font-size: 12px;
    }
    .content-card {
        background: rgba(255,255,255,0.86); border: 1px solid #edf0f4; border-radius: 18px; padding: 18px 18px 8px; box-shadow: 0 2px 8px rgba(15,23,42,0.02);
    }
    .assistant-bubble {
        max-width: 100%;
        background: #ffffff; border: 1px solid #edf0f4; color: #2a3040; border-radius: 18px; padding: 16px 18px; margin: 14px 0; line-height: 1.65; font-size: 15px;
    }
    .user-bubble {
        max-width: 100%;
        background: #efeaff; border: 1px solid #e5dcff; color: #2a3040; border-radius: 18px; padding: 16px 18px; margin: 14px 0; line-height: 1.65; font-size: 15px;
    }
    .source-box {
        background: #f5f7fb; border: 1px solid #eaedf3; border-radius: 12px; padding: 12px 14px; color: #607089; font-size: 13px;
    }
    .bottom-input {
        background: white; border: 1px solid #ecedf2; border-radius: 18px; padding: 10px 12px 12px; box-shadow: 0 2px 10px rgba(15,23,42,0.02);
    }
    .bottom-input .stButton > button {
        background: transparent; border: 1px solid #e7ebf0; border-radius: 12px; color: #3d4c64; font-weight: 600;
    }
    .send-btn > button {
        background: linear-gradient(135deg, #7b67f5, #6d5ef3); border: none; border-radius: 12px; color: white; font-weight: 700;
    }
    .right-card {
        background: rgba(255,255,255,0.9); border: 1px solid #edf0f4; border-radius: 18px; padding: 18px 16px; box-shadow: 0 2px 10px rgba(15,23,42,0.02);
    }
    .avatar { width: 72px; height: 72px; border-radius: 50%; margin: 0 auto 12px; display:flex; align-items:center; justify-content:center; font-weight:800; font-size: 28px; color:white; background: linear-gradient(135deg, #d6c4ff, #7561f8); }
    .info-pill {
        display: inline-block; padding: 6px 12px; border-radius: 999px; background: #f0e9ff; color: #6b50ef; font-size: 12px; font-weight: 700;
    }
    .stat-box {
        background: #f7f9fd; border: 1px solid #eceff5; border-radius: 10px; padding: 10px 12px; text-align: center;
    }
    .stat-box .label { color: #6b7280; font-size: 12px; }
    .stat-box .value { color:#1f2937; font-size: 18px; font-weight: 800; }
    .right-menu .stButton > button {
        width: 100%; border: none; background: transparent; color: #2a3445; text-align: left; border-radius: 10px; padding: 10px 12px;
    }
    .theme-row .stButton > button { background: #f1f4fa; border: none; color: #273141; border-radius: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

profile = fetch_profile() if st.session_state.auth_token else {}
if profile:
    st.session_state.profile = profile

st.session_state.profile.setdefault("username", st.session_state.get("username", "Ahmed Mohamed"))

with st.sidebar:
    st.markdown(
        '<div class="brand-box"><div class="brand-mark">◈</div><div><div class="brand-label">MultiRAG</div><div class="brand-sub">Multimodal RAG Assistant</div></div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="primary-button">', unsafe_allow_html=True)
    if st.button("+ New Chat", key="sidebar_new_chat", use_container_width=True):
        st.session_state.page = "new_chat"
        st.session_state.chat_messages = []
        st.session_state.selected_conversation = None
        st.session_state.conversation_id = None
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<div class='workspace-label'>Chats</div>", unsafe_allow_html=True)
    if not st.session_state.conversations:
        fetch_conversations()

    st.markdown('<div class="sidebar-list">', unsafe_allow_html=True)
    for item in st.session_state.conversations:
        label = item.get("title") or "New chat"
        if st.button(label, key=f"conv_{item.get('id')}", use_container_width=True):
            st.session_state.page = "chat"
            st.session_state.selected_conversation = item.get("id")
            fetch_conversation_messages(item.get("id"))
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="sidebar-plan">', unsafe_allow_html=True)
    st.markdown('<div class="plan-title">Pro Plan</div>', unsafe_allow_html=True)
    st.caption("Unlock more capabilities and higher limits.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="primary-button" style="margin-top: 12px;">', unsafe_allow_html=True)
    st.button("Upgrade Now", key="upgrade_btn", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<div class='workspace-label'>Workspace</div>", unsafe_allow_html=True)
    st.caption(f"User: {st.session_state.profile.get('username', st.session_state.get('username', 'User'))}")
    st.caption(f"Uploads: {st.session_state.profile.get('storage_dir', 'N/A')}")

left, center, right = st.columns([0.8, 3.7, 1.7])

with center:
    if st.session_state.page == "settings":
        st.markdown('<div class="main-title">Provider settings</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtitle">Manage API keys and default models for supported providers.</div>', unsafe_allow_html=True)

        try:
            provider_response = requests.get(f"{API_BASE_URL}/settings/providers", headers=api_headers(), timeout=15)
            provider_data = provider_response.json() if provider_response.status_code == 200 else {"providers": {}}
        except requests.RequestException:
            provider_data = {"providers": {}}

        providers = provider_data.get("providers", {})
        provider_names = list(providers.keys()) or ["google", "openrouter", "groq"]
        selected_provider = st.radio("Provider", provider_names, horizontal=True, label_visibility="collapsed")
        selected = providers.get(selected_provider, {})
        api_key = st.text_input("API Key", value=selected.get("api_key", ""), type="password")
        model_name = st.text_input("Model name", value=selected.get("model_name", "") or "")
        enabled = st.checkbox("Enabled", value=bool(selected.get("enabled", True)))

        if st.button("Save settings", type="primary", use_container_width=True):
            payload = {"provider": selected_provider, "api_key": api_key, "model_name": model_name, "enabled": enabled}
            try:
                save_response = requests.post(f"{API_BASE_URL}/settings/providers", json=payload, headers=api_headers(), timeout=20)
                if save_response.status_code == 200:
                    st.success("تم حفظ إعدادات المزود")
                else:
                    st.error(save_response.json().get("detail", "تعذر حفظ الإعدادات"))
            except requests.RequestException:
                st.error("Backend غير متاح")

        st.markdown('<div class="source-box" style="margin-top:18px;"><strong>Supported providers:</strong> Google, OpenRouter, Groq</div>', unsafe_allow_html=True)

    elif st.session_state.page == "profile":
        st.markdown('<div class="main-title">Profile</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtitle">User details and workspace location.</div>', unsafe_allow_html=True)
        st.info(f"Username: {st.session_state.profile.get('username', st.session_state.get('username', 'User'))}")
        st.info(f"Storage path: {st.session_state.profile.get('storage_dir', 'N/A')}")

    else:
        st.markdown('<div class="chat-header">', unsafe_allow_html=True)
        st.markdown('<div class="title">What is Retrieval-Augmented Generation?</div>', unsafe_allow_html=True)
        head_cols = st.columns([1, 1])
        with head_cols[0]:
            st.markdown('<div class="small-pill">Share</div>', unsafe_allow_html=True)
        with head_cols[1]:
            st.markdown('<div class="small-pill" style="text-align:center;">⋯</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="content-card">', unsafe_allow_html=True)
        st.markdown('<div class="user-bubble">Can you explain what Retrieval-Augmented Generation (RAG) is and how it works? Also include a simple diagram of the pipeline.</div>', unsafe_allow_html=True)

        st.markdown(
            '<div class="assistant-bubble">Retrieval-Augmented Generation (RAG) is a technique that combines the strengths of information retrieval and text generation. It allows LLMs to access external knowledge sources before generating a response, resulting in more accurate and up-to-date answers.</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="assistant-bubble"><strong>How it works:</strong><br>1. Retrieve: The system retrieves relevant documents from a knowledge base.<br>2. Augment: The retrieved information is provided to the language model.<br>3. Generate: The model uses both the retrieved context and its internal knowledge to generate a response.</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="source-box" style="margin: 14px 0 10px;">Here is a simple diagram of the RAG pipeline:</div>',
            unsafe_allow_html=True,
        )

        diagram_cols = st.columns([1.2, 1.2, 1.2, 1.2])
        with diagram_cols[0]:
            st.markdown('<div style="padding: 10px; text-align: center; border: 1px dashed #dfe7f1; border-radius: 12px; background:#f9fafb;">User query</div>', unsafe_allow_html=True)
        with diagram_cols[1]:
            st.markdown('<div style="padding: 10px; text-align: center; border: 1px solid #dfe7f1; border-radius: 12px; background:#ecfdf5;">Retrieve</div>', unsafe_allow_html=True)
        with diagram_cols[2]:
            st.markdown('<div style="padding: 10px; text-align: center; border: 1px solid #dfe7f1; border-radius: 12px; background:#f5f3ff;">Knowledge base</div>', unsafe_allow_html=True)
        with diagram_cols[3]:
            st.markdown('<div style="padding: 10px; text-align: center; border: 1px solid #dfe7f1; border-radius: 12px; background:#fff7ed;">LLM + Response</div>', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div style="height: 14px;"></div>', unsafe_allow_html=True)
        st.markdown('<div class="source-box"><strong>Sources</strong> · Lewis et al., 2020 (RAG) · Gao et al., 2023 · LangChain Docs · Web</div>', unsafe_allow_html=True)

        st.markdown('<div style="height: 12px;"></div>', unsafe_allow_html=True)
        action_cols = st.columns([1, 3, 1.2])
        with action_cols[0]:
            st.markdown('<div class="small-pill" style="text-align:center;">Upload File</div>', unsafe_allow_html=True)
        with action_cols[1]:
            st.markdown('<div class="small-pill" style="text-align:center;">Image</div>', unsafe_allow_html=True)
        with action_cols[2]:
            st.markdown('<div class="small-pill" style="text-align:center;">PDF</div>', unsafe_allow_html=True)

        st.markdown('<div class="bottom-input" style="margin-top: 14px;">', unsafe_allow_html=True)
        prompt = st.text_input("Ask anything...", label_visibility="collapsed")
        send_cols = st.columns([5, 1])
        with send_cols[0]:
            st.caption("Upload File  Image  PDF  Web Link")
        with send_cols[1]:
            if st.button("➤", key="send_message", use_container_width=True):
                if prompt and prompt.strip():
                    st.session_state.chat_messages.append({"role": "user", "content": prompt.strip()})
                    title = prompt.strip()[:40] if prompt.strip() else "New chat"
                    cid = save_chat_message("user", prompt.strip(), st.session_state.get("conversation_id"), title=title)
                    st.session_state.conversation_id = cid or st.session_state.get("conversation_id")
                    try:
                        response = requests.post(f"{API_BASE_URL}/chat", json={"question": prompt.strip(), "k": 5}, headers=api_headers(), timeout=120)
                        if response.status_code == 200:
                            answer = response.json().get("answer", "No answer returned.")
                            st.session_state.chat_messages.append({"role": "assistant", "content": answer})
                            save_chat_message("assistant", answer, st.session_state.get("conversation_id"), title=title)
                            fetch_conversations()
                            st.rerun()
                        else:
                            st.error(response.text)
                    except requests.RequestException:
                        st.error("API unavailable")
                else:
                    st.warning("اكتب سؤالاً أولًا")
        st.markdown('</div>', unsafe_allow_html=True)

with right:
    st.markdown('<div class="right-card">', unsafe_allow_html=True)
    st.markdown('<div class="avatar">A</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="text-align:center; font-size: 22px; font-weight: 800; margin-bottom: 2px;">{st.session_state.profile.get("username", "Ahmed Mohamed")}</div>', unsafe_allow_html=True)
    st.markdown('<div style="text-align:center; color:#6b7280; margin-bottom: 14px;">ahmed.mohamed@gmail.com</div>', unsafe_allow_html=True)
    st.markdown('<div style="text-align:center; margin-bottom: 16px;"><span class="info-pill">Pro Plan</span></div>', unsafe_allow_html=True)

    cols = st.columns(2)
    with cols[0]:
        st.markdown('<div class="stat-box"><div class="label">Conversations</div><div class="value">128</div></div>', unsafe_allow_html=True)
    with cols[1]:
        st.markdown('<div class="stat-box"><div class="label">Messages</div><div class="value">432</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="right-menu" style="margin-top: 18px;">', unsafe_allow_html=True)
    if st.button("Profile", key="profile_nav", use_container_width=True):
        st.session_state.page = "profile"
        st.rerun()
    if st.button("Settings", key="settings_nav", use_container_width=True):
        st.session_state.page = "settings"
        st.rerun()
    if st.button("API Keys", key="api_nav", use_container_width=True):
        st.session_state.page = "settings"
        st.rerun()
    if st.button("Storage", key="storage_nav", use_container_width=True):
        st.session_state.page = "profile"
        st.rerun()
    if st.button("Logout", key="logout_nav", use_container_width=True):
        st.session_state.auth_token = None
        st.session_state.username = None
        st.session_state.chat_messages = []
        st.session_state.conversations = []
        st.session_state.selected_conversation = None
        st.session_state.conversation_id = None
        st.session_state.page = "new_chat"
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="theme-row" style="display:flex; gap:10px; margin-top: 18px;">', unsafe_allow_html=True)
    st.button("Theme", key="theme_button")
    st.button("☾", key="dark_button")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

