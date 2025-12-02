import streamlit as st
import requests
from io import BytesIO

# General settings
st.set_page_config(
    page_title="Agentic RAG Client",
    page_icon="🤖",
    layout="wide"
)

# ======= Global CSS Styling =======
st.markdown(
    """
    <style>
    .main-title {
        font-size: 36px; 
        font-weight: 700; 
        color: #2E86C1;
        text-align: center;
        margin-bottom: 20px;
    }
    .sub-box {
        padding: 15px;
        border-radius: 12px;
        background-color: #F8F9F9;
        border: 1px solid #D5D8DC;
        margin-bottom: 20px;
    }
    .chat-card {
        padding: 12px;
        border-radius: 10px;
        background-color: #EBF5FB;
        margin: 5px 0;
    }
    .user-card {
        background-color: #FDEDEC;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------------------
#        Main Title
# ------------------------------
st.markdown('<div class="main-title">🤖 Multimodal-RAG-Core</div>', unsafe_allow_html=True)
st.write("نظام للتفاعل مع API يعمل من خلال ngrok (Kaggle Notebook).")

# ------------------------------
#        Sidebar
# ------------------------------
with st.sidebar:
    st.header("⚙️ إعدادات الاتصال")

    # Fix: adding .strip() to remove trailing spaces
    raw_url = st.text_input(
        "🌍 رابط السيرفر (ngrok)",
        placeholder="مثال: https://xxxx-xx-xx.ngrok-free.app"
    )
    api_base_url = raw_url.strip().strip("/") if raw_url else ""

    st.divider()
    st.header("📄 رفع ملفات (PDF / صور)")

    # File uploader for PDF & images
    files = st.file_uploader(
        "اختر ملف أو صورة",
        accept_multiple_files=True,
        type=["pdf", "png", "jpg", "jpeg"]
    )

    # Upload files & build DB
    if st.button("⬆️ رفع الملفات وبناء قاعدة البيانات"):
        if not api_base_url:
            st.error("⚠️ برجاء إدخال رابط ngrok أولاً!")
        elif not files:
            st.error("⚠️ برجاء اختيار ملف واحد على الأقل!")
        else:
            with st.spinner("⏳ جاري رفع الملفات…"):
                for f in files:
                    file_data = {"file": (f.name, f, f"type/{f.type}")}

                    resp = requests.post(f"{api_base_url}/upload_file", files=file_data)

                    if resp.status_code == 200:
                        st.success(f"✅ {f.name} تم رفعه بنجاح")
                    else:
                        st.error(f"❌ خطأ أثناء رفع {f.name}: {resp.text}")

# ------------------------------
#        Chat Section
# ------------------------------
st.subheader("💬 المحادثة")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous messages
for msg in st.session_state.messages:
    if msg["role"] == "user":
        # If user sent an image, display it
        content = msg["content"]
        if "image" in msg:
            st.image(msg["image"], width=250)
            content = f"**[تم إرسال صورة]**\n{content}"
        st.markdown(f'<div class="chat-card user-card">👤 {content}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-card">🤖 {msg["content"]}</div>', unsafe_allow_html=True)

# Image uploader for chat message
current_chat_image = st.file_uploader(
    "صورة للمحادثة الحالية (اختياري)",
    type=["png", "jpg", "jpeg", "webp"],
    accept_multiple_files=False,
    key="chat_image_uploader"
)

# User text input
prompt = st.chat_input("اكتب سؤالك…")

if prompt:
    # Store user message
    user_msg_data = {"role": "user", "content": prompt}

    # If an image is attached → use multimodal endpoint
    if current_chat_image is not None:
        endpoint = f"{api_base_url}/chat_with_image"

        user_msg_data["image"] = current_chat_image

        files = {
            'image': (current_chat_image.name, current_chat_image.getvalue(), current_chat_image.type)
        }
        data = {'question': prompt, 'k': 5}

        st.session_state.messages.append(user_msg_data)
        st.markdown(f'<div class="chat-card user-card">👤 **[صورة مرفقة]** {prompt}</div>', unsafe_allow_html=True)

    else:
        # No image → normal chat endpoint
        endpoint = f"{api_base_url}/chat"
        files = None
        data = {"question": prompt}

        st.session_state.messages.append(user_msg_data)
        st.markdown(f'<div class="chat-card user-card">👤 {prompt}</div>', unsafe_allow_html=True)

    if not api_base_url:
        st.error("⚠️ برجاء إدخال رابط السيرفر في الشريط الجانبي!")
    else:
        with st.spinner("🤖 Thinking…"):
            try:
                # Send POST request depending on mode
                if files:
                    resp = requests.post(endpoint, files=files, data=data)
                else:
                    resp = requests.post(endpoint, json=data)

                # Parse API response
                if resp.status_code == 200:
                    answer = resp.json().get("answer", "❓ لا يوجد رد.")
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    st.markdown(f'<div class="chat-card">🤖 {answer}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"❌ خطأ: {resp.text}")

            except Exception as e:
                st.error(f"❌ خطأ في الاتصال: {e}")
