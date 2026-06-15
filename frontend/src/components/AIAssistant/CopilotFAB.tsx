import { useRef, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import html2canvas from 'html2canvas';
import api from '../../services/api';
import { useCopilotStore } from '../../services/copilotStore';
import type { Message } from '../../services/copilotStore';

const PANEL_W = 400;
const PANEL_H = 560;
const FAB_W = 56;
const FAB_H = 56;
const EDGE_GAP = 24;

export interface PageContext {
  turbine_id?: number;
  turbine_name?: string;
  fault_id?: number;
  fault_type?: string;
  [key: string]: unknown;
}

export default function CopilotFAB({ initialMessage = '', pageContext }: { initialMessage?: string; pageContext?: PageContext }) {
  const messages = useCopilotStore((s) => s.messages);
  const input = useCopilotStore((s) => s.input);
  const loading = useCopilotStore((s) => s.loading);
  const open = useCopilotStore((s) => s.open);
  const panelPos = useCopilotStore((s) => s.panelPos);
  const addMessage = useCopilotStore((s) => s.addMessage);
  const setInput = useCopilotStore((s) => s.setInput);
  const setLoading = useCopilotStore((s) => s.setLoading);
  const setOpen = useCopilotStore((s) => s.setOpen);
  const setPanelPos = useCopilotStore((s) => s.setPanelPos);
  const fabPos = useCopilotStore((s) => s.fabPos);
  const setFabPos = useCopilotStore((s) => s.setFabPos);
  const navigate = useNavigate();

  const chatRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const initialSent = useRef(false);
  const fabRef = useRef<HTMLButtonElement>(null);
  const fabDragging = useRef(false);
  const fabDragOffset = useRef({ x: 0, y: 0 });
  const fabHasMoved = useRef(false);
  const fabDragStart = useRef({ x: 0, y: 0 });
  const fabPosRef = useRef({ x: 0, y: 0 });
  const [mode, setMode] = useState<'chat' | 'agent'>('chat');

  // Keep fabPosRef in sync with store
  useEffect(() => { fabPosRef.current = fabPos; }, [fabPos]);

  // Initialize panel position to bottom-right when opened
  useEffect(() => {
    if (open) {
      const x = Math.max(0, window.innerWidth - PANEL_W - EDGE_GAP);
      const y = Math.max(0, window.innerHeight - PANEL_H - EDGE_GAP);
      setPanelPos({ x, y });
    }
  }, [open, setPanelPos]);

  // Initialize FAB position to bottom-right on first mount (sentinel -1 = uninitialized)
  useEffect(() => {
    if (fabPos.x === -1 && fabPos.y === -1) {
      setFabPos({
        x: Math.max(0, window.innerWidth - FAB_W - EDGE_GAP),
        y: Math.max(0, window.innerHeight - FAB_H - EDGE_GAP),
      });
    }
  }, [fabPos, setFabPos]);

  // Clamp panel position on window resize
  useEffect(() => {
    const handleResize = () => {
      setPanelPos({
        x: Math.max(0, Math.min(panelPos.x, window.innerWidth - PANEL_W)),
        y: Math.max(0, Math.min(panelPos.y, window.innerHeight - PANEL_H)),
      });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [panelPos.x, panelPos.y, setPanelPos]);

  // Clamp FAB position on window resize
  useEffect(() => {
    const handleResize = () => {
      setFabPos({
        x: Math.max(0, Math.min(fabPos.x, window.innerWidth - FAB_W)),
        y: Math.max(0, Math.min(fabPos.y, window.innerHeight - FAB_H)),
      });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [fabPos.x, fabPos.y, setFabPos]);

  // Drag handlers (panel)
  const onDragStart = useCallback((e: React.MouseEvent) => {
    isDragging.current = true;
    dragOffset.current = {
      x: e.clientX - panelPos.x,
      y: e.clientY - panelPos.y,
    };
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
  }, [setPanelPos]);

  // FAB drag handlers — direct DOM manipulation for zero-lag dragging
  const onFabMouseDown = useCallback((e: React.MouseEvent) => {
    fabDragging.current = true;
    fabHasMoved.current = false;
    fabDragStart.current = { x: e.clientX, y: e.clientY };
    const currentX = fabPosRef.current.x;
    const currentY = fabPosRef.current.y;
    fabDragOffset.current = {
      x: e.clientX - currentX,
      y: e.clientY - currentY,
    };
    // Disable transition during drag for instant response
    if (fabRef.current) fabRef.current.style.transition = 'none';
  }, []);

  useEffect(() => {
    const onFabDragMove = (e: MouseEvent) => {
      if (!fabDragging.current) return;
      if (Math.abs(e.clientX - fabDragStart.current.x) > 3 || Math.abs(e.clientY - fabDragStart.current.y) > 3) {
        fabHasMoved.current = true;
      }
      const x = Math.max(0, Math.min(e.clientX - fabDragOffset.current.x, window.innerWidth - FAB_W));
      const y = Math.max(0, Math.min(e.clientY - fabDragOffset.current.y, window.innerHeight - FAB_H));
      // Direct DOM update — no React re-render
      fabPosRef.current = { x, y };
      if (fabRef.current) {
        fabRef.current.style.left = x + 'px';
        fabRef.current.style.top = y + 'px';
      }
    };
    const onFabDragEnd = () => {
      fabDragging.current = false;
      // Commit final position to store (single re-render)
      setFabPos({ ...fabPosRef.current });
      // Re-enable transition for smooth hover effect
      if (fabRef.current) fabRef.current.style.transition = '';
    };
    document.addEventListener('mousemove', onFabDragMove);
    document.addEventListener('mouseup', onFabDragEnd);
    return () => {
      document.removeEventListener('mousemove', onFabDragMove);
      document.removeEventListener('mouseup', onFabDragEnd);
    };
  }, [setFabPos]);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  // Auto-send initialMessage from parent (e.g. KnowledgeBase "AI诊断" button)
  useEffect(() => {
    if (!initialMessage || initialSent.current) return;
    initialSent.current = true;
    setOpen(true);
    const timer = setTimeout(() => handleSend(initialMessage), 200);
    return () => clearTimeout(timer);
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
        backgroundColor: '#071A35',
      });

      const dataUrl = canvas.toDataURL('image/jpeg', 0.6);
      return dataUrl.split(',')[1];
    } catch (err) {
      console.warn('Screenshot capture failed:', err);
      return null;
    }
  };

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text) return;
    const userMsg: Message = { role: 'user', content: text };
    addMessage(userMsg);
    if (!textOverride) setInput('');
    setLoading(true);
    let screenshot: string | null = null;
    try { screenshot = await captureScreenshot(); } catch { /* ok */ }

    // Build page_context: merge auto-detected info with page-specific context from props
    const baseContext: Record<string, unknown> = {
      page_type: window.location.pathname.replace('/', '') || 'dashboard',
      url: window.location.href,
    };
    if (pageContext) Object.assign(baseContext, pageContext);

    try {
      // Get all messages currently in store (including the one just added)
      const currentMsgs = useCopilotStore.getState().messages;
      const allMsgs = [...currentMsgs].map((m) => ({ role: m.role, content: m.content }));

      let reply: string;

      if (mode === 'agent') {
        // Agent 任务模式 — 规划 → 执行 → 总结
        const { data } = await api.post('/agent/task', { messages: allMsgs, page_context: baseContext }, { timeout: 90000 });
        reply = data.report || data.message || JSON.stringify(data);

        // Execute frontend actions (e.g. navigate to another page)
        const actions: Array<{ type: string; url: string }> = data.actions || [];
        for (const action of actions) {
          if (action.type === 'navigate' && action.url) {
            // Use navigate for smooth SPA transition, close the panel
            setTimeout(() => { setOpen(false); navigate(action.url); }, 300);
          }
        }
      } else {
        // AI 对话模式 — 走 Copilot 对话链路
        const payload: Record<string, unknown> = { messages: allMsgs, page_context: baseContext };
        if (screenshot) payload.screenshot = screenshot;
        const { data } = await api.post('/ai/copilot', payload, { timeout: 60000 });
        reply = data.reply;
      }

      addMessage({ role: 'assistant', content: reply });
    } catch {
      addMessage({ role: 'error', content: 'AI服务暂不可用, 请稍后重试' });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <>
      {/* Floating Action Button — draggable */}
      {fabPos.x >= 0 && !open && (
        <button
          ref={fabRef}
          data-copilot-ignore
          onMouseDown={onFabMouseDown}
          onClick={() => { if (!fabHasMoved.current) setOpen(true); }}
          className="fixed z-50 w-14 h-14 rounded-full bg-accent-blue shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center select-none"
          style={{ left: fabPos.x, top: fabPos.y, boxShadow: '0 0 20px rgba(88,166,255,0.4)' }}
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
                <p className="text-[10px] text-accent-green">
                  {mode === 'agent' ? 'Agent任务 · 自动执行' : 'Qwen-Plus · 在线'}
                </p>
              </div>
            </div>
          </div>

          {/* Mode Toggle — AI对话 / Agent诊断 */}
          <div className="flex gap-1 px-4 py-2 border-b border-border-default bg-bg-secondary">
            <button
              onClick={() => setMode('chat')}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                mode === 'chat'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
              }`}
            >
              💬 AI对话
            </button>
            <button
              onClick={() => setMode('agent')}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                mode === 'agent'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
              }`}
            >
              🔧 Agent任务
            </button>
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
                  {m.role === 'assistant' ? (
                    <Markdown content={m.content} />
                  ) : (
                    m.content
                  )}
                </div>
              </div>
            ))}
            {(loading || agentRunning) && <p className="text-text-muted animate-pulse">{agentRunning ? 'Agent执行中...' : 'AI思考中...'}</p>}
          </div>

          {/* Agent Progress */}
          {mode === 'agent' && agentSteps.length > 0 && (
            <div className="px-4 py-2 space-y-1 border-t border-border-default bg-bg-secondary/50 max-h-[180px] overflow-auto">
              {agentSteps.map((s, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[10px]">
                  <span>{
                    s.status === 'done' ? '✅' : s.status === 'failed' ? '❌' :
                    s.status === 'running' ? '⏳' : '○'
                  }</span>
                  <span className={s.status === 'failed' ? 'text-accent-red' : 'text-text-secondary'}>
                    {s.message}
                  </span>
                  {s.error && <span className="text-accent-red ml-1">— {s.error}</span>}
                </div>
              ))}
              {agentScreenshot && (
                <img src={`data:image/jpeg;base64,${agentScreenshot}`}
                  className="mt-1 rounded border border-border-default w-full" alt="截图" />
              )}
            </div>
          )}

          {/* Input */}
          <div className="p-3 border-t border-border-default">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  mode === 'agent'
                    ? '输入任务指令，如：查看故障诊断页面'
                    : '输入问题, 如: 当前风场运行状态如何?'
                }
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
              {(mode === 'agent'
                ? ['查看故障诊断页面', '查看维护人员工作量', '查看所有工单']
                : ['总结当前状态', '最近故障', '健康趋势分析']
              ).map((q) => (
                <button
                  key={q}
                  onClick={() => { mode === 'agent' ? handleSend(q) : setInput(q); }}
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

function Markdown({ content }: { content: string }) {
  const html = useMemo(() => {
    try {
      return marked(content, { breaks: true, gfm: true });
    } catch {
      return content;
    }
  }, [content]);

  return (
    <div
      className="copilot-markdown text-xs leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
