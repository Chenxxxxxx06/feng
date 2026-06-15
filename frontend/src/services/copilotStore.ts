import { create } from 'zustand';

export interface Message {
  role: 'user' | 'assistant' | 'error';
  content: string;
}

interface CopilotState {
  messages: Message[];
  input: string;
  loading: boolean;
  open: boolean;
  panelPos: { x: number; y: number };
  fabPos: { x: number; y: number };
  // Actions
  addMessage: (msg: Message) => void;
  setInput: (val: string) => void;
  setLoading: (val: boolean) => void;
  setOpen: (val: boolean) => void;
  setPanelPos: (pos: { x: number; y: number }) => void;
  setFabPos: (pos: { x: number; y: number }) => void;
  clearMessages: () => void;
}

const GREETING: Message = {
  role: 'assistant',
  content: '你好！我是风调预顺AI助手。我可以帮你分析风机数据、解释故障原因、生成维护建议。请随时提问。',
};

export const useCopilotStore = create<CopilotState>((set) => ({
  messages: [GREETING],
  input: '',
  loading: false,
  open: false,
  panelPos: { x: 0, y: 0 },
  fabPos: { x: -1, y: -1 }, // -1 means uninitialized, component will set on mount

  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  setInput: (val) => set({ input: val }),
  setLoading: (val) => set({ loading: val }),
  setOpen: (val) => set({ open: val }),
  setPanelPos: (pos) => set({ panelPos: pos }),
  setFabPos: (pos) => set({ fabPos: pos }),
  clearMessages: () => set({ messages: [GREETING] }),
}));
