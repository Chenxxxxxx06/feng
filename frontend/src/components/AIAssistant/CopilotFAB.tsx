import { useState, useRef, useEffect, useCallback } from 'react';
import html2canvas from 'html2canvas';
import api from '../../services/api';

const PANEL_W = 400;
const PANEL_H = 560;
const EDGE_GAP = 24;

interface Message {
  role: 'user' | 'assistant' | 'error';
  content: string;
}

export default function CopilotFAB({ initialMessage = '' }: { initialMessage?: string }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: '你好！我是风调预顺AI助手。我可以帮你分析风机数据、解释故障原因、生成维护建议。请随时提问。' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const [panelPos, setPanelPos] = useState({ x: 0, y: 0 });

  // Initialize panel position to bottom-right when opened
  useEffect(() => {
    if (open) {
      const x = Math.max(0, window.innerWidth - PANEL_W - EDGE_GAP);
      const y = Math.max(0, window.innerHeight - PANEL_H - EDGE_GAP);
      setPanelPos({ x, y });
    }
  }, [open]);

  // Clamp position on window resize
  useEffect(() => {
    const handleResize = () => {
      setPanelPos((prev) => ({
        x: Math.max(0, Math.min(prev.x, window.innerWidth - PANEL_W)),
        y: Math.max(0, Math.min(prev.y, window.innerHeight - PANEL_H)),
      }));
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Drag handlers
  const onDragStart = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    dragOffset.current = {
      x: e.clientX - panelPos.x,
      y: e.clientY - panelPos.y,
    };
    // Prevent text selection during drag
    e.preventDefault();
  }, [panelPos]);

  useEffect(() => {
    const onDragMove = (e: MouseEvent) => {
      if (!isDragging.current) return;
      const x = Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - PANEL_W));
      const y = Math.max(0, Math.min(e.clientY - dragOffset.current.y, window.innerHeight - PANEL_H));
      setPanelPos({ x, y });
    };
    const onDragEnd = () => {
      isDragging.current = false;
    };
    document.addEventListener('mousemove', onDragMove);
    document.addEventListener('mouseup', onDragEnd);
    return () => {
      document.removeEventListener('mousemove', onDragMove);
      document.removeEventListener('mouseup', onDragEnd);
    };
  }, []);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  // Auto-send initialMessage from parent (e.g. KnowledgeBase "AI诊断" button)
  useEffect(() => {
    if (initialMessage) {
      setOpen(true);
      setTimeout(() => handleSend(initialMessage), 200);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialMessage]);

  const captureScreenshot = async (): Promise<string | null> => {
    try {
      const mainEl = document.querySelector('main');
      if (!mainEl) return null;

      const canvas = await html2canvas(mainEl as HTMLElement, {
        useCORS: true,
        allowTaint: true,
        scale: 0.5,
        ignoreElements: (el) => el.closest('[data-copilot-ignore]') !== null,
        backgroundColor: '#080c12',
      });

      // Compress to JPEG at quality 0.6 to limit payload size
      const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
      return dataUrl.split(',')[1]; // strip "data:image/jpeg;base64," prefix
    } catch (err) {
      console.warn('Screenshot capture failed:', err);
      return null;
    }
  };

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    const userMsg: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    if (!textOverride) setInput('');
    setLoading(true);

    // Capture screenshot (best-effort, failure does not block chat)
    let screenshot: string | null = null;
    try {
      screenshot = await captureScreenshot();
    } catch {
      // Silently fall back to text-only mode
    }

    try {
      const payload: Record<string, unknown> = {
        messages: [...messages, userMsg].map((m) => ({ role: m.role, content: m.content })),
        page_context: {
          page_type: window.location.pathname.replace('/', '') || 'dashboard',
          url: window.location.href,
        },
      };
      if (screenshot) {
        payload.screenshot = screenshot;
      }

      const { data } = await api.post('/ai/copilot', payload, { timeout: 60000 });
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
    } catch {
      setMessages((prev) => [...prev, { role: 'error', content: 'AI服务暂不可用, 请稍后重试' }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <>
      {/* Floating Action Button */}
      {!open && (
        <button
          data-copilot-ignore
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-accent-blue shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center"
          style={{ boxShadow: '0 0 20px rgba(88,166,255,0.4)' }}
        >
          <span className="text-2xl">💬</span>
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-accent-green border-2 border-bg-primary animate-pulse" />
        </button>
      )}

      {/* Chat Panel — draggable */}
      {open && (
        <div
          ref={panelRef}
          data-copilot-ignore
          className="fixed z-50 shadow-2xl flex flex-col overflow-hidden rounded-xl border border-border-default bg-bg-card"
          style={{ left: panelPos.x, top: panelPos.y, width: PANEL_W, height: PANEL_H }}
        >
          {/* Header — drag handle */}
          <div
            className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-bg-secondary cursor-move select-none"
            onMouseDown={onDragStart}
          >
            <div className="flex items-center gap-2">
              <span className="text-lg">🤖</span>
              <div>
                <h3 className="text-sm font-medium">风调AI助手</h3>
                <p className="text-[10px] text-accent-green">Qwen-Plus · 在线</p>
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-primary text-lg">✕</button>
          </div>

          {/* Messages */}
          <div ref={chatRef} className="flex-1 overflow-auto p-4 space-y-3 text-xs">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 ${
                  m.role === 'user'
                    ? 'bg-accent-blue/20 text-text-primary'
                    : m.role === 'error'
                    ? 'bg-accent-red/10 text-accent-red'
                    : 'bg-bg-hover text-text-primary'
                }`}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && <p className="text-text-muted animate-pulse">AI思考中...</p>}
          </div>

          {/* Input */}
          <div className="p-3 border-t border-border-default">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入问题, 如: A-003风机当前状态如何?"
                className="flex-1 bg-bg-secondary border border-border-default rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              />
              <button
                onClick={() => handleSend()}
                disabled={loading || !input.trim()}
                className="px-4 py-2 bg-accent-blue text-white rounded-lg text-xs hover:opacity-90 disabled:opacity-40 transition-opacity"
              >
                发送
              </button>
            </div>
            <div className="flex gap-2 mt-2">
              {['总结当前状态', '最近故障', '健康趋势分析'].map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="text-[10px] px-2 py-1 rounded border border-border-default text-text-muted hover:text-accent-blue hover:border-accent-blue transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
