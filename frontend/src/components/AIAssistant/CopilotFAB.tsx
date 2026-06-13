import { useRef, useEffect, useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import html2canvas from 'html2canvas';
import { marked } from 'marked';
import api from '../../services/api';
import { useCopilotStore } from '../../services/copilotStore';
import type { Message } from '../../services/copilotStore';
import { AgentExecutor } from '../../services/agent/AgentExecutor';
import { SkillRegistry } from '../../services/agent/SkillRegistry';
import type { AgentExecuteResponse, ExecutionProgress } from '../../services/agent/types';

const PANEL_W = 400;
const PANEL_H = 560;
const EDGE_GAP = 24;

export default function CopilotFAB({ initialMessage = '' }: { initialMessage?: string }) {
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

  const chatRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const initialSent = useRef(false);

  // ── Agent mode state ──
  const navigate = useNavigate();
  const [mode, setMode] = useState<'chat' | 'agent'>('chat');
  const [agentSteps, setAgentSteps] = useState<ExecutionProgress[]>([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [agentScreenshot, setAgentScreenshot] = useState<string | null>(null);

  // Initialize panel position to bottom-right when opened
  useEffect(() => {
    if (open) {
      const x = Math.max(0, window.innerWidth - PANEL_W - EDGE_GAP);
      const y = Math.max(0, window.innerHeight - PANEL_H - EDGE_GAP);
      setPanelPos({ x, y });
    }
  }, [open, setPanelPos]);

  // Clamp position on window resize
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

  // Drag handlers
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
        backgroundColor: '#080c12',
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
    if (!text || loading || agentRunning) return;
    const userMsg: Message = { role: 'user', content: text };
    addMessage(userMsg);
    if (!textOverride) setInput('');

    // ── Agent mode: classify first, then route ──
    if (mode === 'agent') {
      setAgentRunning(true);
      setAgentSteps([]);
      setAgentScreenshot(null);

      try {
        const classifyRes = await api.post('/agent/execute', {
          command: text,
          current_page: window.location.pathname.replace('/', '') || 'dashboard',
        }, { timeout: 30000 }) as { data: AgentExecuteResponse };
        const { data } = classifyRes;

        if (data.requires_clarification) {
          addMessage({ role: 'assistant', content: data.clarification_question || '请再说清楚一点' });
          setAgentRunning(false);
          return;
        }

        if (data.intent_type === 'action' || data.intent_type === 'mixed') {
          if (!data.atomic_steps.length) {
            addMessage({ role: 'error', content: '无法解析操作步骤，请尝试更具体的指令' });
            setAgentRunning(false);
            return;
          }
          // Execute action steps in browser
          const registry = new SkillRegistry(
            (path: string) => navigate(path),
            captureScreenshot,
          );
          const executor = new AgentExecutor(registry, (progress) => {
            setAgentSteps((prev) => {
              const idx = prev.findIndex((s) => s.stepIndex === progress.stepIndex);
              if (idx >= 0) { const copy = [...prev]; copy[idx] = progress; return copy; }
              return [...prev, progress];
            });
            if (progress.screenshot) setAgentScreenshot(progress.screenshot);
          });

          const result = await executor.executeSteps(data.atomic_steps);

          let reply = result.success
            ? `✅ ${result.message}\n\n${data.explanation}`
            : `❌ ${result.message}`;

          // Mixed intent: follow-up analysis with screenshot
          if (data.intent_type === 'mixed' && data.follow_up_analysis && result.success) {
            try {
              const shot = await captureScreenshot();
              if (shot) {
                const allMsgs = useCopilotStore.getState().messages
                  .filter((m) => m.role !== 'error').map((m) => ({ role: m.role, content: m.content }));
                const analysisPayload: Record<string, unknown> = {
                  messages: [
                    ...allMsgs,
                    { role: 'user', content: data.follow_up_analysis },
                  ],
                  page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard', url: window.location.href },
                  screenshot: shot,
                };
                const aiRes = await api.post('/ai/copilot', analysisPayload, { timeout: 60000 });
                reply += `\n\n---\n📊 **页面解读**:\n${aiRes.data.reply}`;
              }
            } catch {
              reply += '\n\n(页面解读暂时不可用)';
            }
          }

          addMessage({ role: 'assistant', content: reply });
        } else {
          // QA / diagnosis → use existing diagnosis pipeline, fallback to copilot
          let reply: string | null = null;
          const allMsgs = useCopilotStore.getState().messages
            .filter((m) => m.role !== 'error').map((m) => ({ role: m.role, content: m.content }));
          let screenshot: string | null = null;
          try { screenshot = await captureScreenshot(); } catch { /* ok */ }

          try {
            const diagPayload: Record<string, unknown> = {
              messages: allMsgs,
              page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard' },
            };
            if (screenshot) diagPayload.screenshot = screenshot;
            const diagRes = await api.post('/agent/diagnose', diagPayload, { timeout: 90000 });
            reply = diagRes.data.report || diagRes.data.message || JSON.stringify(diagRes.data);
          } catch {
            try {
              const payload: Record<string, unknown> = {
                messages: allMsgs,
                page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard', url: window.location.href },
              };
              if (screenshot) payload.screenshot = screenshot;
              const copilotRes = await api.post('/ai/copilot', payload, { timeout: 60000 });
              reply = copilotRes.data.reply;
            } catch {
              reply = null;
            }
          }

          if (reply) {
            addMessage({ role: 'assistant', content: reply });
          } else {
            addMessage({ role: 'error', content: 'AI服务暂不可用' });
          }
        }
      } catch {
        addMessage({ role: 'error', content: 'Agent服务暂不可用' });
      } finally {
        setAgentRunning(false);
      }
      return;
    }

    // ── Chat mode: use existing copilot flow ──
    setLoading(true);
    let screenshot: string | null = null;
    try { screenshot = await captureScreenshot(); } catch { /* ok */ }

    try {
      const allMsgs = useCopilotStore.getState().messages
        .filter((m) => m.role !== 'error').map((m) => ({ role: m.role, content: m.content }));
      const isDiagnosis = /风机|故障|振动|温度|异常|原因|怎么修|什么问|诊断|方案|备件|维修|停机|RL/.test(text);
      let reply: string;

      if (isDiagnosis) {
        try {
          const diagPayload: Record<string, unknown> = {
            messages: allMsgs,
            page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard' },
          };
          if (screenshot) diagPayload.screenshot = screenshot;
          const { data } = await api.post('/agent/diagnose', diagPayload, { timeout: 90000 });
          reply = data.report || data.message || JSON.stringify(data);
        } catch {
          const payload: Record<string, unknown> = {
            messages: allMsgs,
            page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard', url: window.location.href },
          };
          if (screenshot) payload.screenshot = screenshot;
          const { data } = await api.post('/ai/copilot', payload, { timeout: 60000 });
          reply = data.reply;
        }
      } else {
        const payload: Record<string, unknown> = {
          messages: allMsgs,
          page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard', url: window.location.href },
        };
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
          {/* Header with tabs — drag handle */}
          <div
            className="flex items-center justify-between px-3 py-2 border-b border-border-default bg-bg-secondary cursor-move select-none"
            onMouseDown={onDragStart}
          >
            <div className="flex items-center gap-1">
              <button
                onClick={() => setMode('chat')}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  mode === 'chat' ? 'bg-accent-blue/20 text-accent-blue' : 'text-text-muted hover:text-text-primary'
                }`}
              >💬 对话</button>
              <button
                onClick={() => setMode('agent')}
                className={`px-2.5 py-1 text-xs rounded transition-colors ${
                  mode === 'agent' ? 'bg-accent-blue/20 text-accent-blue' : 'text-text-muted hover:text-text-primary'
                }`}
              >🤖 Agent</button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-text-muted">Qwen · 在线</span>
              <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-primary text-lg">✕</button>
            </div>
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
                placeholder={mode === 'agent'
                  ? "输入操作指令, 如: 打开风场监控查看A风机"
                  : "输入问题, 如: A-003风机当前状态如何?"}
                className="flex-1 bg-bg-secondary border border-border-default rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
              />
              <button
                onClick={() => handleSend()}
                disabled={loading || agentRunning || !input.trim()}
                className="px-4 py-2 bg-accent-blue text-white rounded-lg text-xs hover:opacity-90 disabled:opacity-40 transition-opacity"
              >
                发送
              </button>
            </div>
            <div className="flex gap-2 mt-2">
              {(mode === 'agent'
                ? ['打开风场监控查看A风机', '查看3号风机详情', '切换到诊断页面']
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
