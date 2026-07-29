import { create } from 'zustand';

export interface Message {
  id?: string;
  role: 'user' | 'assistant' | 'error';
  content: string;
  _progress?: boolean;
  _progressId?: string;
}

export interface CopilotSession {
  id: string;
  title: string;
  providerConfigId: number | null;
  providerName: string;
  model: string;
  pageType: string;
  summary?: string;
  createdAt: string;
  updatedAt: string;
  messages: Message[];
}

interface CopilotState {
  sessions: CopilotSession[];
  currentSessionId: string;
  messages: Message[];
  input: string;
  loading: boolean;
  open: boolean;
  panelPos: { x: number; y: number };
  fabPos: { x: number; y: number };
  createSession: (params?: Partial<Pick<CopilotSession, 'title' | 'providerConfigId' | 'providerName' | 'model' | 'pageType' | 'summary'>>) => string;
  switchSession: (id: string) => void;
  updateCurrentSessionMeta: (params: Partial<Pick<CopilotSession, 'title' | 'providerConfigId' | 'providerName' | 'model' | 'pageType' | 'summary'>>) => void;
  deleteSession: (id: string) => void;
  addMessage: (msg: Message) => void;
  removeMessage: (progressId: string) => void;
  updateMessage: (progressId: string, patch: Partial<Message>) => void;
  setInput: (val: string) => void;
  setLoading: (val: boolean) => void;
  setOpen: (val: boolean) => void;
  setPanelPos: (pos: { x: number; y: number }) => void;
  setFabPos: (pos: { x: number; y: number }) => void;
  clearMessages: () => void;
}

const GREETING: Message = {
  role: 'assistant',
      content: '你好！我是风调预顺AI助手。\n\n**我能做什么:**\n- 查询风机当前可用数据 (HI、RUL、历史SCADA)\n- 诊断故障原因 + 匹配知识库\n- 生成维修建议和排查步骤\n- 截图分析当前页面\n\n请描述你的问题，或点击 **Agent任务** 进行深度分析。',
};

const STORAGE_KEY = 'copilot.sessions.v2';
const CURRENT_SESSION_KEY = 'copilot.currentSessionId.v2';

const nowIso = () => new Date().toISOString();

const makeSession = (params?: Partial<Pick<CopilotSession, 'title' | 'providerConfigId' | 'providerName' | 'model' | 'pageType' | 'summary'>>): CopilotSession => ({
  id: `session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
  title: params?.title || '新建AI会话',
  providerConfigId: params?.providerConfigId ?? null,
  providerName: params?.providerName || '',
  model: params?.model || '',
  pageType: params?.pageType || 'dashboard',
  summary: params?.summary,
  createdAt: nowIso(),
  updatedAt: nowIso(),
  messages: [GREETING],
});

const safeWindow = () => (typeof window === 'undefined' ? null : window);

const loadSessions = () => {
  const win = safeWindow();
  if (!win) return { sessions: [makeSession()], currentSessionId: '' };
  try {
    const parsed = JSON.parse(win.localStorage.getItem(STORAGE_KEY) || '[]') as CopilotSession[];
    const validSessions = Array.isArray(parsed) && parsed.length > 0 ? parsed : [makeSession()];
    const savedCurrent = win.localStorage.getItem(CURRENT_SESSION_KEY);
    const current = validSessions.find((session) => session.id === savedCurrent)?.id || validSessions[0].id;
    return { sessions: validSessions, currentSessionId: current };
  } catch {
    const fallback = makeSession();
    return { sessions: [fallback], currentSessionId: fallback.id };
  }
};

const persistSessions = (sessions: CopilotSession[], currentSessionId: string) => {
  const win = safeWindow();
  if (!win) return;
  win.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  win.localStorage.setItem(CURRENT_SESSION_KEY, currentSessionId);
};

// Streaming deltas call updateMessage on every chunk; throttle persistence to
// avoid a localStorage write storm. The trailing timer reads the latest state.
let persistTimer: ReturnType<typeof setTimeout> | null = null;
const schedulePersist = (get: () => { sessions: CopilotSession[]; currentSessionId: string }) => {
  if (persistTimer !== null) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    const s = get();
    persistSessions(s.sessions, s.currentSessionId);
  }, 500);
};

const isEmptySession = (session?: CopilotSession | null) => (
  !session || !session.messages.some((message) => message.role === 'user')
);

const loaded = loadSessions();
if (!loaded.currentSessionId) loaded.currentSessionId = loaded.sessions[0].id;
const currentSession = loaded.sessions.find((session) => session.id === loaded.currentSessionId) || loaded.sessions[0];

export const useCopilotStore = create<CopilotState>((set, get) => ({
  sessions: loaded.sessions,
  currentSessionId: loaded.currentSessionId,
  messages: currentSession.messages?.length ? currentSession.messages : [GREETING],
  input: '',
  loading: false,
  open: false,
  panelPos: { x: 0, y: 0 },
  fabPos: { x: -1, y: -1 }, // -1 means uninitialized, component will set on mount

  createSession: (params) => {
    const session = makeSession(params);
    set((s) => {
      const sessions = [
        session,
        ...s.sessions.filter((item) => item.id !== s.currentSessionId || !isEmptySession(item)),
      ];
      persistSessions(sessions, session.id);
      return { sessions, currentSessionId: session.id, messages: session.messages };
    });
    return session.id;
  },
  switchSession: (id) => set((s) => {
    if (id === s.currentSessionId) return s;
    const filteredSessions = s.sessions.filter((item) => item.id !== s.currentSessionId || !isEmptySession(item));
    const session = filteredSessions.find((item) => item.id === id);
    if (!session) return s;
    persistSessions(filteredSessions, id);
    return { sessions: filteredSessions, currentSessionId: id, messages: session.messages?.length ? session.messages : [GREETING] };
  }),
  updateCurrentSessionMeta: (params) => set((s) => {
    const sessions = s.sessions.map((session) => (
      session.id === s.currentSessionId
        ? { ...session, ...params, updatedAt: nowIso() }
        : session
    ));
    persistSessions(sessions, s.currentSessionId);
    return { sessions };
  }),
  deleteSession: (id) => set((s) => {
    const remaining = s.sessions.filter((session) => session.id !== id);
    const sessions = remaining.length > 0 ? remaining : [makeSession()];
    const currentSessionId = s.currentSessionId === id ? sessions[0].id : s.currentSessionId;
    const current = sessions.find((session) => session.id === currentSessionId) || sessions[0];
    persistSessions(sessions, current.id);
    return { sessions, currentSessionId: current.id, messages: current.messages?.length ? current.messages : [GREETING] };
  }),
  addMessage: (msg) => set((s) => {
    const withId = msg.id ? msg : { ...msg, id: `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` };
    const messages = [...s.messages, withId];
    const sessions = s.sessions.map((session) => (
      session.id === s.currentSessionId
        ? {
            ...session,
            messages,
            updatedAt: nowIso(),
          }
        : session
    ));
    persistSessions(sessions, s.currentSessionId);
    return { messages, sessions };
  }),
  removeMessage: (progressId) => set((s) => {
    const messages = s.messages.filter(m => m._progressId !== progressId);
    const sessions = s.sessions.map((session) => (
      session.id === s.currentSessionId ? { ...session, messages, updatedAt: nowIso() } : session
    ));
    persistSessions(sessions, s.currentSessionId);
    return { messages, sessions };
  }),
  updateMessage: (progressId, patch) => set((s) => {
    const messages = s.messages.map((message) => (
      message._progressId === progressId ? { ...message, ...patch } : message
    ));
    const sessions = s.sessions.map((session) => (
      session.id === s.currentSessionId ? { ...session, messages, updatedAt: nowIso() } : session
    ));
    if (patch._progress === false) {
      // Stream finished (or errored): flush the final content immediately.
      if (persistTimer !== null) { clearTimeout(persistTimer); persistTimer = null; }
      persistSessions(sessions, s.currentSessionId);
    } else {
      schedulePersist(get);
    }
    return { messages, sessions };
  }),
  setInput: (val) => set({ input: val }),
  setLoading: (val) => set({ loading: val }),
  setOpen: (val) => set({ open: val }),
  setPanelPos: (pos) => set({ panelPos: pos }),
  setFabPos: (pos) => set({ fabPos: pos }),
  clearMessages: () => set((s) => {
    const sessions = s.sessions.map((session) => (
      session.id === s.currentSessionId ? { ...session, messages: [GREETING], updatedAt: nowIso() } : session
    ));
    persistSessions(sessions, s.currentSessionId);
    return { messages: [GREETING], sessions };
  }),
}));
