"use client";

import { useEffect, useRef, useState } from "react";
import {
  Bot,
  FileText,
  FolderOpen,
  KeyRound,
  LogOut,
  MessageSquare,
  Paperclip,
  Plus,
  Save,
  Send,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Conversation = { id: string; title?: string; updated_at?: number };
type Message = { role: "user" | "assistant"; content: string };
type Document = {
  id?: string;
  document_id?: string;
  filename?: string;
  status?: string;
};
type ProviderSetting = {
  model_name: string;
  enabled: boolean;
  configured: boolean;
};

function formatInline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={index}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

function AssistantResponse({ content }: { content: string }) {
  const lines = content.replace(/\r/g, "").split("\n");
  const elements: React.ReactNode[] = [];
  let bulletItems: string[] = [];

  const flushBullets = () => {
    if (!bulletItems.length) return;
    elements.push(
      <ul className="answer-list" key={`list-${elements.length}`}>
        {bulletItems.map((item, index) => <li key={index}>{formatInline(item)}</li>)}
      </ul>,
    );
    bulletItems = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    const bullet = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)/);
    if (bullet) {
      bulletItems.push(bullet[1]);
      return;
    }
    flushBullets();
    if (!line) return;
    const heading = line.match(/^#{1,3}\s+(.+)/);
    elements.push(heading ? <h4 key={index}>{formatInline(heading[1])}</h4> : <p key={index}>{formatInline(line)}</p>);
  });
  flushBullets();

  return <div className="assistant-response">{elements}</div>;
}

function conversationTitle(text: string) {
  const words = text.trim().split(/\s+/).filter(Boolean).slice(0, 2);
  if (words.length === 0) return "New Chat";
  const title = words.join(" ").toLowerCase();
  return title.charAt(0).toUpperCase() + title.slice(1);
}

async function request(path: string, options: RequestInit = {}) {
  const token = localStorage.getItem("rag_token");
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response = await fetch(`${API}${path}`, { ...options, headers });
  if (response.status === 401 && path !== "/auth/refresh") {
    const refreshToken = localStorage.getItem("rag_refresh_token");
    if (refreshToken) {
      const refreshResponse = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      const refreshed = await refreshResponse.json().catch(() => ({}));
      if (refreshResponse.ok && refreshed.token && refreshed.refresh_token) {
        localStorage.setItem("rag_token", refreshed.token);
        localStorage.setItem("rag_refresh_token", refreshed.refresh_token);
        headers.set("Authorization", `Bearer ${refreshed.token}`);
        response = await fetch(`${API}${path}`, { ...options, headers });
      } else {
        localStorage.removeItem("rag_token");
        localStorage.removeItem("rag_refresh_token");
        localStorage.removeItem("rag_username");
        window.location.reload();
        throw new Error("انتهت الجلسة، يرجى تسجيل الدخول من جديد");
      }
    } else if (token) {
      localStorage.removeItem("rag_token");
      localStorage.removeItem("rag_username");
      window.location.reload();
      throw new Error("انتهت الجلسة، يرجى تسجيل الدخول من جديد");
    }
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(data.detail || data.message || "حدث خطأ غير متوقع");
  return data;
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [loginMode, setLoginMode] = useState(true);
  const [authUsername, setAuthUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [question, setQuestion] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [providerSettings, setProviderSettings] = useState<
    Record<string, ProviderSetting>
  >({});
  const [selectedProvider, setSelectedProvider] = useState("google");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerModel, setProviderModel] = useState("");
  const [providerEnabled, setProviderEnabled] = useState(true);
  const [settingsMessage, setSettingsMessage] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem("rag_token");
    const refresh = localStorage.getItem("rag_refresh_token");
    const name = localStorage.getItem("rag_username");
    if (saved && refresh) {
      setToken(saved);
      setUsername(name || "");
    } else if (saved) {
      localStorage.removeItem("rag_token");
      localStorage.removeItem("rag_username");
    }
  }, []);
  useEffect(() => {
    if (token) loadConversations();
  }, [token]);
  useEffect(() => {
    if (token) loadProviderSettings();
  }, [token]);
  useEffect(() => {
    messagesRef.current?.scrollTo({
      top: messagesRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  async function loadConversations() {
    try {
      const data = await request("/chat/history");
      setConversations(data.conversations || []);
    } catch {
      setConversations([]);
    }
  }
  async function loadProviderSettings() {
    try {
      const data = await request("/settings/providers");
      const settings = data.providers || {};
      setProviderSettings(settings);
      const firstProvider = Object.keys(settings)[0] || "google";
      setSelectedProvider((current) =>
        settings[current] ? current : firstProvider,
      );
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : "تعذر تحميل إعدادات المزود",
      );
    }
  }
  function selectProvider(provider: string) {
    const setting = providerSettings[provider];
    setSelectedProvider(provider);
    setProviderApiKey("");
    setProviderModel(setting?.model_name || "");
    setProviderEnabled(setting?.enabled ?? true);
    setSettingsMessage("");
    setSettingsError("");
  }
  async function saveProviderSettings(event: React.FormEvent) {
    event.preventDefault();
    if (!providerModel.trim()) {
      setSettingsError("اكتب اسم النموذج أولًا");
      return;
    }
    setSavingSettings(true);
    setSettingsMessage("");
    setSettingsError("");
    try {
      const data = await request("/settings/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: selectedProvider,
          api_key: providerApiKey,
          model_name: providerModel,
          enabled: providerEnabled,
        }),
      });
      setProviderSettings((current) => ({
        ...current,
        [selectedProvider]: {
          ...current[selectedProvider],
          model_name: providerModel,
          enabled: providerEnabled,
          configured: data.configured,
        },
      }));
      setProviderApiKey("");
      setSettingsMessage("تم حفظ إعدادات المزود بنجاح");
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : "تعذر حفظ الإعدادات",
      );
    } finally {
      setSavingSettings(false);
    }
  }
  async function resetProviderSettings() {
    setSavingSettings(true);
    setSettingsMessage("");
    setSettingsError("");
    try {
      const resetData = await request("/settings/providers/reset", { method: "POST" });
      await loadProviderSettings();
      setSelectedProvider("google");
      setProviderApiKey("");
      setProviderModel(resetData.model || "");
      setProviderEnabled(true);
      setSettingsMessage("تم الرجوع إلى Google والإعدادات الافتراضية");
    } catch (error) {
      setSettingsError(
        error instanceof Error ? error.message : "تعذر استرجاع الإعدادات الافتراضية",
      );
    } finally {
      setSavingSettings(false);
    }
  }
  async function selectConversation(id: string) {
    setConversationId(id);
    try {
      const [history, docs] = await Promise.all([
        request(`/chat/history/${id}`),
        request(`/documents?conversation_id=${id}`),
      ]);
      setMessages(history.messages || []);
      setDocuments(docs.documents || []);
    } catch (error) {
      setAuthError(
        error instanceof Error ? error.message : "تعذر فتح المحادثة",
      );
    }
  }
  async function authenticate(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setAuthError("");
    try {
      if (!loginMode)
        await request("/auth/register", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: authUsername, password }),
        });
      const data = await request("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: authUsername, password }),
      });
      localStorage.setItem("rag_token", data.token);
      localStorage.setItem("rag_refresh_token", data.refresh_token);
      localStorage.setItem("rag_username", data.username);
      setToken(data.token);
      setUsername(data.username);
    } catch (error) {
      setAuthError(
        error instanceof Error ? error.message : "تعذر تسجيل الدخول",
      );
    } finally {
      setLoading(false);
    }
  }
  function logout() {
    localStorage.removeItem("rag_token");
    localStorage.removeItem("rag_refresh_token");
    localStorage.removeItem("rag_username");
    setToken(null);
    setMessages([]);
    setConversations([]);
  }
  async function newChat() {
    setMessages([]);
    setDocuments([]);
    setConversationId("");
    setImageFile(null);
  }
  async function sendMessage(event?: React.FormEvent) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || sending) return;
    setSending(true);
    setQuestion("");
    try {
      const saved = await request("/chat/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: "user",
          content: text,
          conversation_id: conversationId || null,
          title: conversationTitle(text),
        }),
      });
      const id = saved.conversation_id;
      setConversationId(id);
      setMessages((current) => [...current, { role: "user", content: text }]);
      let answer;
      if (imageFile) {
        const form = new FormData();
        form.append("question", text);
        form.append("conversation_id", id);
        form.append("k", "5");
        form.append("image", imageFile);
        answer = await request("/chat_with_image", {
          method: "POST",
          body: form,
        });
      } else {
        answer = await request("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: text, k: 5, conversation_id: id }),
        });
      }
      const content =
        answer.answer ||
        answer.response ||
        answer.content ||
        "لم يصل رد من النموذج.";
      setMessages((current) => [...current, { role: "assistant", content }]);
      await request("/chat/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role: "assistant",
          content,
          conversation_id: id,
        }),
      });
      await loadConversations();
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: error instanceof Error ? error.message : "تعذر تنفيذ الطلب",
        },
      ]);
    } finally {
      setSending(false);
    }
  }
  async function uploadFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    if (conversationId) form.append("conversation_id", conversationId);
    form.append("file", file);
    setUploading(true);
    try {
      const data = await request("/upload_file", {
        method: "POST",
        body: form,
      });
      setConversationId(data.conversation_id);
      if (file.type.startsWith("image/")) setImageFile(file);
      setDocuments((current) => [
        ...current,
        {
          document_id: data.document_id,
          filename: file.name,
          status: data.status,
        },
      ]);
      await loadConversations();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "تعذر رفع الملف");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  }
  async function deleteConversation(id: string) {
    try {
      await request(`/chat/history/${id}`, { method: "DELETE" });
      if (id === conversationId) newChat();
      await loadConversations();
    } catch (error) {
      setAuthError(
        error instanceof Error ? error.message : "تعذر حذف المحادثة",
      );
    }
  }

  if (!token)
    return (
      <main className="auth">
        <form className="auth-card" onSubmit={authenticate}>
          <div className="brand">
            <div className="brand-mark">N</div>
            <div>
              <strong>NOVA</strong>
              <small>KNOWLEDGE STUDIO</small>
            </div>
          </div>
          <h1>{loginMode ? "مرحبًا بعودتك" : "أنشئ مساحتك"}</h1>
          <p>حوّل مستنداتك إلى إجابات واضحة يمكن الوثوق بها.</p>
          {authError && <div className="error">{authError}</div>}
          <div className="field">
            <label>اسم المستخدم</label>
            <input
              required
              minLength={3}
              value={authUsername}
              onChange={(e) => setAuthUsername(e.target.value)}
              placeholder="مثال: ahmed"
            />
          </div>
          <div className="field">
            <label>كلمة المرور</label>
            <input
              required
              minLength={8}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8 أحرف على الأقل"
            />
          </div>
          <button className="primary" disabled={loading}>
            {loading
              ? "جارٍ المعالجة..."
              : loginMode
                ? "دخول إلى المساحة"
                : "إنشاء الحساب"}
          </button>
          <button
            type="button"
            className="switch"
            onClick={() => {
              setLoginMode(!loginMode);
              setAuthError("");
            }}
          >
            {loginMode
              ? "ليس لديك حساب؟ أنشئ حسابًا"
              : "لديك حساب؟ سجّل الدخول"}
          </button>
        </form>
      </main>
    );

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div>
            <strong>NOVA</strong>
            <small>KNOWLEDGE STUDIO</small>
          </div>
        </div>
        <button className="new-chat" onClick={newChat}>
          <Plus size={17} /> محادثة جديدة
        </button>
        <div className="section-label">المحادثات الأخيرة</div>
        <div className="conversation-list">
          {conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`conversation ${conversation.id === conversationId ? "active" : ""}`}
            >
              <button
                className="conversation"
                onClick={() => selectConversation(conversation.id)}
              >
                <MessageSquare size={15} />
                <span>{conversation.title || "محادثة بدون عنوان"}</span>
              </button>
              <button
                className="icon-btn"
                onClick={() => deleteConversation(conversation.id)}
                aria-label="حذف"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
        <div className="profile">
          <div className="avatar">{username.slice(0, 1).toUpperCase()}</div>
          <div>
            <strong>{username}</strong>
            <small>حساب شخصي</small>
          </div>
          <button
            className="icon-btn"
            onClick={logout}
            aria-label="تسجيل الخروج"
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      <section className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">MULTIMODAL RAG / 01</div>
            <h1>مساحة المعرفة</h1>
          </div>
          <div className="topbar-actions">
            <button
              className="settings-trigger"
              onClick={() => {
                setSettingsOpen(true);
                selectProvider(selectedProvider);
              }}
            >
              <Settings size={16} /> إعدادات النموذج
            </button>
            <div className="status">
              <span className="dot" /> النظام متصل
            </div>
          </div>
        </header>
        {settingsOpen && (
          <div className="settings-backdrop" role="presentation">
            <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
              <div className="settings-heading">
                <div>
                  <div className="eyebrow">MODEL PROVIDER</div>
                  <h2 id="settings-title">إعدادات النموذج</h2>
                </div>
                <button className="icon-btn" onClick={() => setSettingsOpen(false)} aria-label="إغلاق">
                  <X size={18} />
                </button>
              </div>
              <p className="settings-note">أضف مفتاحك واختر النموذج الذي سيستخدمه حسابك في المحادثات.</p>
              {settingsError && <div className="error">{settingsError}</div>}
              {settingsMessage && <div className="success">{settingsMessage}</div>}
              <form onSubmit={saveProviderSettings}>
                <div className="field">
                  <label htmlFor="provider">المزود</label>
                  <select id="provider" value={selectedProvider} onChange={(event) => selectProvider(event.target.value)}>
                    {Object.keys(providerSettings).filter((provider) => provider === "google" || provider === "openrouter").map((provider) => (
                      <option key={provider} value={provider}>{provider === "google" ? "Google Gemini" : "OpenRouter"}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="provider-key">مفتاح API</label>
                  <input id="provider-key" type="password" value={providerApiKey} onChange={(event) => setProviderApiKey(event.target.value)} placeholder={providerSettings[selectedProvider]?.configured ? "مفتاح محفوظ، اتركه فارغًا للاحتفاظ به" : "أدخل مفتاح API"} autoComplete="off" />
                  {providerSettings[selectedProvider]?.configured && <small className="configured"><KeyRound size={13} /> مفتاح محفوظ لهذا المزود</small>}
                </div>
                <div className="field">
                  <label htmlFor="provider-model">اسم النموذج</label>
                  <input id="provider-model" required value={providerModel} onChange={(event) => setProviderModel(event.target.value)} placeholder="مثال: gemini-2.5-flash" />
                </div>
                <label className="toggle-row"><input type="checkbox" checked={providerEnabled} onChange={(event) => setProviderEnabled(event.target.checked)} /> <span>استخدام هذا المزود</span></label>
                <button className="primary settings-save" disabled={savingSettings}><Save size={16} /> {savingSettings ? "جارٍ الحفظ..." : "حفظ الإعدادات"}</button>
                <button type="button" className="settings-reset" onClick={resetProviderSettings} disabled={savingSettings}>الرجوع للإعدادات الافتراضية</button>
              </form>
            </section>
          </div>
        )}
        <div className="content">
          <div className="welcome">
            <div>
              <div className="eyebrow">مرحبًا، {username}</div>
              <h2>
                اسأل بفضول.
                <br />
                اكتشف بوضوح.
              </h2>
              <p>ابدأ محادثة مع مستنداتك، ودع NOVA يجد المعنى خلف كل صفحة.</p>
            </div>
            <Sparkles className="leaf" />
          </div>
          {authError && <div className="error">{authError}</div>}
          <div className="workspace">
            <section className="chat-panel">
              <div className="messages" ref={messagesRef}>
                {messages.length === 0 ? (
                  <div className="empty">
                    <Sparkles size={29} color="#1f6b50" />
                    <h3>ما الذي تريد معرفته؟</h3>
                    <p>
                      ارفع مستندًا أو ابدأ بسؤال جديد. سأساعدك في القراءة
                      والتحليل والتلخيص.
                    </p>
                  </div>
                ) : (
                  messages.map((message, index) => (
                    <div
                      className={`message ${message.role}`}
                      key={`${index}-${message.content.slice(0, 10)}`}
                    >
                      <div className="message-avatar">
                        {message.role === "assistant" ? (
                          <Bot size={15} />
                        ) : (
                          <UserRound size={15} />
                        )}
                      </div>
                      <div className="message-bubble">
                        {message.role === "assistant" ? (
                          <AssistantResponse content={message.content} />
                        ) : (
                          message.content
                        )}
                      </div>
                    </div>
                  ))
                )}
                {sending && (
                  <div className="message assistant">
                    <div className="message-avatar">
                      <Bot size={15} />
                    </div>
                    <div className="message-bubble">
                      أفكر في إجابة مناسبة...
                    </div>
                  </div>
                )}
              </div>
              <form className="composer" onSubmit={sendMessage}>
                <div className="composer-box">
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        sendMessage();
                      }
                    }}
                    placeholder="اكتب سؤالك هنا..."
                  />
                  <button
                    className="send"
                    disabled={sending || !question.trim()}
                    aria-label="إرسال"
                  >
                    <Send size={17} />
                  </button>
                </div>
              </form>
            </section>
            <aside className="documents">
              <h3>مصادر المعرفة</h3>
              <p>ارفع ملفاتك ليستخدمها NOVA كمرجع في الإجابات.</p>
              <label className="upload">
                <Upload size={16} /> {uploading ? "جارٍ الرفع..." : "رفع مستند"}
                <input
                  type="file"
                  accept=".pdf,.txt,.md,.png,.jpg,.jpeg"
                  onChange={uploadFile}
                  disabled={uploading}
                />
              </label>
              {documents.map((document, index) => (
                <div
                  className="doc"
                  key={document.document_id || document.id || index}
                >
                  <FileText size={16} />
                  <span>{document.filename || "مستند"}</span>
                </div>
              ))}
              {documents.length === 0 && (
                <div className="doc">
                  <FolderOpen size={16} />
                  <span>لا توجد مستندات بعد</span>
                </div>
              )}
            </aside>
          </div>
        </div>
      </section>
    </main>
  );
}
