import { create } from 'zustand';

export interface Message {
  role: 'user' | 'assistant' | 'error';
  content: string;
  _progress?: boolean;
  _progressId?: string;
}

interface CopilotState {
  messages: Message[];
  input: string;
  loading: boolean;
  open: boolean;
  panelPos: { x: number; y: number };
  fabPos: { x: number; y: number };
  addMessage: (msg: Message) => void;
  removeMessage: (progressId: string) => void;
  setInput: (val: string) => void;
  setLoading: (val: boolean) => void;
  setOpen: (val: boolean) => void;
  setPanelPos: (pos: { x: number; y: number }) => void;
  setFabPos: (pos: { x: number; y: number }) => void;
  clearMessages: () => void;
}

const GREETING: Message = {
  role: 'assistant',
  content: '你好！我是风调预顺AI助手。\n\n**我能做什么:**\n- 📊 查询风机实时数据 (HI、RUL、SCADA)\n- 🔍 诊断故障原因 + 匹配知识库\n- 📝 生成维修建议和排查步骤\n- 📸 截图分析当前页面\n\n请描述你的问题，或点击 **Agent任务** 进行深度分析。',
};

export const useCopilotStore = create<CopilotState>((set) => ({
  messages: [GREETING],
  input: '',
  loading: false,
  open: false,
  panelPos: { x: 0, y: 0 },
  fabPos: { x: -1, y: -1 }, // -1 means uninitialized, component will set on mount

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  removeMessage: (progressId) => set((s) => ({ messages: s.messages.filter(m => m._progressId !== progressId) })),
  setInput: (val) => set({ input: val }),
  setLoading: (val) => set({ loading: val }),
  setOpen: (val) => set({ open: val }),
  setPanelPos: (pos) => set({ panelPos: pos }),
  setFabPos: (pos) => set({ fabPos: pos }),
  clearMessages: () => set({ messages: [GREETING] }),
}));
