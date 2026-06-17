import { useRef, useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import html2canvas from 'html2canvas';
import api from '../../services/api';
import { useCopilotStore } from '../../services/copilotStore';
import { AgentExecutor } from '../../services/agent/AgentExecutor';
import { SkillRegistry } from '../../services/agent/SkillRegistry';
import type { ExecutionProgress } from '../../services/agent/types';
import type { Message } from '../../services/copilotStore';

const PANEL_W = 560;
const PANEL_H = 560;
const PANEL_MIN_W = 420;
const PANEL_MIN_H = 420;
const PANEL_MAX_W = 920;
const PANEL_MAX_H = 820;
const FAB_W = 56;
const FAB_H = 56;
const EDGE_GAP = 24;
const PANEL_SIZE_STORAGE_KEY = 'copilot.panelSize.v1';

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

function loadPanelSize() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PANEL_SIZE_STORAGE_KEY) || '{}') as { width?: number; height?: number };
    return {
      width: clamp(Number(parsed.width) || PANEL_W, PANEL_MIN_W, PANEL_MAX_W),
      height: clamp(Number(parsed.height) || PANEL_H, PANEL_MIN_H, PANEL_MAX_H),
    };
  } catch {
    return { width: PANEL_W, height: PANEL_H };
  }
}

export interface PageContext {
  turbine_id?: number;
  turbine_name?: string;
  fault_id?: number;
  fault_type?: string;
  [key: string]: unknown;
}

interface CopilotModelStatus {
  provider?: string;
  api_provider?: string;
  model?: string;
  label?: string;
  mode?: string;
  requires_api_key?: boolean;
  has_api_key?: boolean;
}

interface CopilotResponse {
  reply: string;
  status?: 'success' | 'error';
  error_code?: string;
  error_message?: string;
  model_status?: CopilotModelStatus;
  warnings?: string[];
  session_title?: string;
  context_sources?: ContextSource[];
}

interface ContextSource {
  context: string;
  label: string;
  tools?: string[];
}

interface AIProviderConfig {
  id: number;
  provider: string;
  display_name: string | null;
  base_url: string;
  default_model: string | null;
  model_options: string[];
  enabled: boolean;
  has_api_key: boolean;
  last_test_status: string | null;
}

type CopilotStreamEvent =
  | { type: 'meta'; model_status?: CopilotModelStatus; warnings?: string[]; context_sources?: ContextSource[] }
  | { type: 'delta'; delta?: string }
  | { type: 'title'; session_title?: string }
  | { type: 'done' }
  | ({ type: 'error' } & Partial<CopilotResponse>);

const AI_ERROR_TITLES: Record<string, string> = {
  api_key_missing: 'AI密钥未配置',
  provider_unbound: 'AI密钥未绑定供应商',
  provider_mismatch: '模型与密钥供应商不匹配',
  upstream_auth_failed: 'AI供应商鉴权失败',
  model_not_found: '模型不可用',
  upstream_rate_limited: 'AI额度或频率受限',
  upstream_server_error: 'AI供应商服务异常',
  upstream_timeout: 'AI请求超时',
  network_error: '无法连接AI供应商',
  upstream_unknown: 'AI调用失败',
  ai_config_not_ready: 'AI配置未就绪',
};

function formatCopilotError(data?: Partial<CopilotResponse>, fallback = 'AI服务暂不可用，请稍后重试') {
  const code = data?.error_code || 'upstream_unknown';
  const title = AI_ERROR_TITLES[code] || 'AI调用失败';
  const status = data?.model_status || {};
  const lines = [
    `**${title}**`,
    data?.error_message || data?.reply || fallback,
    '',
    `- 错误码: \`${code}\``,
  ];
  if (status.model || status.provider || status.api_provider || status.mode) {
    lines.push(`- 当前模型: \`${status.model || '-'}\``);
    lines.push(`- 模型供应商: \`${status.provider || '-'}\``);
    lines.push(`- 密钥供应商: \`${status.api_provider || '-'}\``);
    lines.push(`- 配置状态: \`${status.mode || '-'}\``);
    lines.push(`- 是否已有密钥: \`${status.has_api_key ? '是' : '否'}\``);
  }
  if (data?.warnings?.includes('screenshot_analysis_failed')) {
    lines.push('- 附加提示: 页面截图识别失败，本次已按文本上下文处理。');
  }
  return lines.join('\n');
}

function shouldAttachScreenshot(mode: 'chat' | 'agent', attachScreenshotOnce: boolean) {
  return mode === 'agent' || attachScreenshotOnce;
}

function compactChatMessages(messages: Array<{ role: string; content: string }>) {
  const budget = 6000;
  const kept: Array<{ role: string; content: string }> = [];
  let used = 0;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    const content = message.content || '';
    const cost = content.length + 32;
    if (kept.length >= 12 || (used + cost > budget && kept.length >= 4)) break;
    kept.unshift(message);
    used += cost;
  }
  return kept;
}

function fallbackProviderModels(provider?: AIProviderConfig | null) {
  const key = provider?.provider?.toLowerCase() || '';
  if (key === 'qwen' || key === 'dashscope') return ['qwen-plus', 'qwen-turbo', 'qwen3.6-flash'];
  if (key === 'deepseek') return ['deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-flash'];
  return [provider?.default_model].filter(Boolean) as string[];
}

const DATA_CONTEXT_STORAGE_KEY = 'copilot.selectedDataContexts.v1';

const DATA_CONTEXT_OPTIONS = [
  { id: 'dashboard', label: '风场监控', hint: '总览 / 区域 / 风机' },
  { id: 'diagnosis', label: '故障诊断', hint: '故障 / 置信度 / 振动' },
  { id: 'prediction', label: '预测决策', hint: 'RUL / 维护优先级' },
  { id: 'workorder', label: '维修工单', hint: '状态 / 派工 / 闭环' },
  { id: 'knowledge', label: '知识库', hint: '根因 / 方案 / 备件' },
  { id: 'current_turbine', label: '当前风机', hint: '选中对象数据' },
];

function loadSelectedDataContexts() {
  try {
    const raw = localStorage.getItem(DATA_CONTEXT_STORAGE_KEY);
    if (raw === null) return ['dashboard'];
    const parsed = JSON.parse(raw) as string[];
    const valid = parsed.filter((id) => DATA_CONTEXT_OPTIONS.some((item) => item.id === id));
    return valid;
  } catch {
    return ['dashboard'];
  }
}

async function postCopilotStream(
  payload: Record<string, unknown>,
  onEvent: (event: CopilotStreamEvent) => void,
) {
  const token = localStorage.getItem('token');
  const response = await fetch('/api/ai/copilot/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });

  if (response.status === 401) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.replace('/login');
    throw new Error('unauthorized');
  }
  if (!response.ok || !response.body) {
    throw new Error(`stream request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      onEvent(JSON.parse(line) as CopilotStreamEvent);
    }
  }

  buffer += decoder.decode();
  if (buffer.trim()) onEvent(JSON.parse(buffer) as CopilotStreamEvent);
}

export default function CopilotFAB({ initialMessage = '', pageContext }: { initialMessage?: string; pageContext?: PageContext }) {
  const sessions = useCopilotStore((s) => s.sessions);
  const currentSessionId = useCopilotStore((s) => s.currentSessionId);
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
  const createSession = useCopilotStore((s) => s.createSession);
  const switchSession = useCopilotStore((s) => s.switchSession);
  const updateCurrentSessionMeta = useCopilotStore((s) => s.updateCurrentSessionMeta);
  const deleteSession = useCopilotStore((s) => s.deleteSession);
  const updateMessage = useCopilotStore((s) => s.updateMessage);
  const navigate = useNavigate();

  const chatRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);
  const isResizing = useRef(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const resizeStart = useRef({ x: 0, y: 0, width: PANEL_W, height: PANEL_H });
  const initialSent = useRef(false);
  const fabRef = useRef<HTMLButtonElement>(null);
  const fabDragging = useRef(false);
  const fabDragOffset = useRef({ x: 0, y: 0 });

  // Agent executor — runs atomic skill steps in browser
  const executor = useMemo(() => {
    const shot = async () => {
      try {
        const main = document.querySelector('main') || document.body;
        const canvas = await Promise.race([
          html2canvas(main as HTMLElement, { scale: 0.4, logging: false, useCORS: false }),
          new Promise<never>((_, reject) => setTimeout(() => reject(new Error('screenshot timeout')), 6000)),
        ]);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.5);
        return dataUrl.split(',')[1] || null;
      } catch { return null; }
    };
    const registry = new SkillRegistry(
      (path: string) => navigate(path),
      async () => shot(),
    );
    return new AgentExecutor(registry, (p: ExecutionProgress) => {
      const icon = p.status === 'running' ? '⏳' : p.status === 'done' ? '✅' : '❌';
      const progressId = `step-${p.stepIndex}`;
      useCopilotStore.getState().removeMessage(progressId);
      addMessage({ role: 'assistant', content: `${icon} ${p.message}`, _progress: p.status === 'running', _progressId: progressId });
    });
  }, [navigate]);

function renderMessageContent(text: string, isProgress?: boolean) {
  if (isProgress) return <span>{text}</span>;
  // Simple markdown: **bold**, `code`, > quote, - list, \n breaks
  const lines = text.split('\n');
  return (
    <div className="space-y-1">
      {lines.map((line, i) => {
        if (!line.trim()) return <br key={i} />;
        const html = line
          .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
          .replace(/`(.+?)`/g, '<code class="bg-bg-card px-1 rounded text-[10px]">$1</code>');
        if (line.startsWith('> ')) {
          return <div key={i} className="text-text-muted border-l-2 border-border-default pl-2 text-[11px]" dangerouslySetInnerHTML={{ __html: html.slice(2) }} />;
        }
        if (/^\d+\.\s/.test(line) || line.startsWith('- ')) {
          return <div key={i} className="flex gap-1"><span className="text-accent-blue">•</span><span dangerouslySetInnerHTML={{ __html: html.replace(/^\d+\.\s|-\s/, '') }} /></div>;
        }
        if (line.includes('数据') || line.includes('知识') || line.includes('意图') || line.includes('汇总')) {
          return <div key={i} className="font-medium text-accent-cyan text-[11px]" dangerouslySetInnerHTML={{ __html: html }} />;
        }
        return <p key={i} className="text-xs" dangerouslySetInnerHTML={{ __html: html }} />;
      })}
    </div>
  );
}
  const fabHasMoved = useRef(false);
  const fabDragStart = useRef({ x: 0, y: 0 });
  const fabPosRef = useRef({ x: 0, y: 0 });
  const [mode, setMode] = useState<'chat' | 'agent'>('chat');
  const [attachScreenshotOnce, setAttachScreenshotOnce] = useState(false);
  const [aiProviders, setAiProviders] = useState<AIProviderConfig[]>([]);
  const [modelDraft, setModelDraft] = useState('');
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null);
  const [selectedContextIds, setSelectedContextIds] = useState<string[]>(loadSelectedDataContexts);
  const [panelSize, setPanelSize] = useState(loadPanelSize);
  const panelSizeRef = useRef(panelSize);
  const currentSession = sessions.find((session) => session.id === currentSessionId) || sessions[0];
  const pendingDeleteSession = pendingDeleteSessionId
    ? sessions.find((session) => session.id === pendingDeleteSessionId)
    : null;
  const conversationStarted = messages.some((message) => message.role === 'user' && !message._progress);
  const modelLocked = conversationStarted;
  const availableProviders = aiProviders.filter((provider) => (
    provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama')
  ));
  const selectedProvider = currentSession?.providerConfigId
    ? aiProviders.find((provider) => provider.id === currentSession.providerConfigId)
    : null;
  const selectedModelOptions = selectedProvider?.model_options?.length
    ? selectedProvider.model_options
    : fallbackProviderModels(selectedProvider);

  const applySessionModel = useCallback((provider: AIProviderConfig, model: string) => {
    updateCurrentSessionMeta({
      providerConfigId: provider.id,
      providerName: provider.display_name || provider.provider,
      model: model || provider.default_model || provider.model_options?.[0] || '',
      pageType: window.location.pathname.replace('/', '') || 'dashboard',
    });
  }, [updateCurrentSessionMeta]);

  const createBlankSession = useCallback(() => {
    const provider = selectedProvider || availableProviders[0];
    createSession({
      title: '新建AI会话',
      providerConfigId: provider?.id ?? null,
      providerName: provider ? (provider.display_name || provider.provider) : '',
      model: provider?.default_model || provider?.model_options?.[0] || '',
      pageType: window.location.pathname.replace('/', '') || 'dashboard',
    });
  }, [availableProviders, createSession, selectedProvider]);

  const handleProviderSelect = useCallback((providerId: string) => {
    if (modelLocked) return;
    const provider = aiProviders.find((item) => item.id === Number(providerId));
    if (!provider) return;
    const nextModel = provider.default_model || provider.model_options?.[0] || '';
    setModelDraft(nextModel);
    applySessionModel(provider, nextModel);
  }, [aiProviders, applySessionModel, modelLocked]);

  const handleModelSelect = useCallback((model: string) => {
    if (modelLocked) return;
    setModelDraft(model);
    if (selectedProvider) applySessionModel(selectedProvider, model);
  }, [applySessionModel, modelLocked, selectedProvider]);

  const toggleDataContext = useCallback((contextId: string) => {
    setSelectedContextIds((current) => {
      const exists = current.includes(contextId);
      const next = exists
        ? current.filter((id) => id !== contextId)
        : [...current, contextId];
      localStorage.setItem(DATA_CONTEXT_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const confirmDeleteSession = useCallback(() => {
    if (!pendingDeleteSessionId) return;
    deleteSession(pendingDeleteSessionId);
    setPendingDeleteSessionId(null);
  }, [deleteSession, pendingDeleteSessionId]);

  // Keep fabPosRef in sync with store
  useEffect(() => { fabPosRef.current = fabPos; }, [fabPos]);
  useEffect(() => { panelSizeRef.current = panelSize; }, [panelSize]);

  useEffect(() => {
    setModelDraft(currentSession?.model || selectedProvider?.default_model || selectedProvider?.model_options?.[0] || '');
  }, [currentSession?.id, currentSession?.model, selectedProvider?.default_model, selectedProvider?.model_options]);

  const loadProviders = useCallback(async () => {
    try {
      const { data } = await api.get<AIProviderConfig[]>('/settings/ai-providers');
      setAiProviders(data);
      const enabled = data.filter((provider) => provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama'));
      const state = useCopilotStore.getState();
      const session = state.sessions.find((item) => item.id === state.currentSessionId);
      const isEmpty = !session?.messages.some((message) => message.role === 'user');
      if (enabled.length > 0 && session && isEmpty && !session.providerConfigId) {
        const provider = enabled[0];
        state.updateCurrentSessionMeta({
          providerConfigId: provider.id,
          providerName: provider.display_name || provider.provider,
          model: provider.default_model || provider.model_options?.[0] || '',
          pageType: window.location.pathname.replace('/', '') || 'dashboard',
        });
      }
    } catch {
      setAiProviders([]);
    }
  }, []);

  useEffect(() => {
    loadProviders();
    window.addEventListener('ai-providers-updated', loadProviders);
    window.addEventListener('focus', loadProviders);
    return () => {
      window.removeEventListener('ai-providers-updated', loadProviders);
      window.removeEventListener('focus', loadProviders);
    };
  }, [loadProviders]);

  useEffect(() => {
    if (open) loadProviders();
  }, [loadProviders, open]);

  // Initialize panel position to bottom-right when opened
  useEffect(() => {
    if (open) {
      const size = panelSizeRef.current;
      const x = Math.max(0, window.innerWidth - size.width - EDGE_GAP);
      const y = Math.max(0, window.innerHeight - size.height - EDGE_GAP);
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
      const size = panelSizeRef.current;
      setPanelPos({
        x: Math.max(0, Math.min(panelPos.x, window.innerWidth - size.width)),
        y: Math.max(0, Math.min(panelPos.y, window.innerHeight - size.height)),
      });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [panelPos.x, panelPos.y, setPanelPos]);

  // Auto-open on diagnosis/prediction pages when preference enabled
  useEffect(() => {
    const autoOpen = localStorage.getItem('autoOpenCopilot') === 'true';
    const path = window.location.pathname;
    if (autoOpen && (path.includes('diagnosis') || path.includes('prediction'))) {
      const timer = setTimeout(() => setOpen(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

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
      const size = panelSizeRef.current;
      const x = Math.max(0, Math.min(e.clientX - dragOffset.current.x, window.innerWidth - size.width));
      const y = Math.max(0, Math.min(e.clientY - dragOffset.current.y, window.innerHeight - size.height));
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

  const onResizeStart = useCallback((e: React.MouseEvent) => {
    isResizing.current = true;
    resizeStart.current = {
      x: e.clientX,
      y: e.clientY,
      width: panelSize.width,
      height: panelSize.height,
    };
    document.body.style.cursor = 'nwse-resize';
    document.body.style.userSelect = 'none';
    e.stopPropagation();
    e.preventDefault();
  }, [panelSize.height, panelSize.width]);

  useEffect(() => {
    const onResizeMove = (e: MouseEvent) => {
      if (!isResizing.current) return;
      const maxWidth = Math.min(PANEL_MAX_W, window.innerWidth - panelPos.x);
      const maxHeight = Math.min(PANEL_MAX_H, window.innerHeight - panelPos.y);
      const next = {
        width: clamp(resizeStart.current.width + e.clientX - resizeStart.current.x, PANEL_MIN_W, Math.max(PANEL_MIN_W, maxWidth)),
        height: clamp(resizeStart.current.height + e.clientY - resizeStart.current.y, PANEL_MIN_H, Math.max(PANEL_MIN_H, maxHeight)),
      };
      panelSizeRef.current = next;
      setPanelSize(next);
      localStorage.setItem(PANEL_SIZE_STORAGE_KEY, JSON.stringify(next));
    };
    const onResizeEnd = () => {
      isResizing.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onResizeMove);
    document.addEventListener('mouseup', onResizeEnd);
    return () => {
      document.removeEventListener('mousemove', onResizeMove);
      document.removeEventListener('mouseup', onResizeEnd);
    };
  }, [panelPos.x, panelPos.y]);

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
    if (mode === 'chat' && (!currentSession?.providerConfigId || !currentSession.model)) {
      addMessage({
        role: 'error',
        content: '**AI会话未选择模型**\n请先在会话栏选择供应商和模型；如果没有可选项，请到系统设置的 AI 设置页保存供应商配置。',
      });
      return;
    }
    const userMsg: Message = { role: 'user', content: text };
    addMessage(userMsg);
    if (!textOverride) setInput('');
    setLoading(true);

    let screenshot: string | null = null;
    if (shouldAttachScreenshot(mode, attachScreenshotOnce)) {
      try {
        screenshot = await captureScreenshot();
      } catch {
        // Silently fall back to text-only mode
      }
    }

    // Build page_context: merge auto-detected info with page-specific context from props
    const baseContext: Record<string, unknown> = {
      page_type: window.location.pathname.replace('/', '') || 'dashboard',
      url: window.location.href,
    };
    if (pageContext) Object.assign(baseContext, pageContext);

    try {
      // Get all messages currently in store (including the one just added)
      const currentMsgs = useCopilotStore.getState().messages;
      const allMsgs = [...currentMsgs]
        .filter((m) => (m.role === 'user' || m.role === 'assistant') && !m._progress)
        .map((m) => ({ role: m.role, content: m.content }));
      const session = useCopilotStore.getState().sessions.find((item) => item.id === useCopilotStore.getState().currentSessionId);
      const compactMsgs = compactChatMessages(allMsgs);
      const sessionMsgs = session?.summary
        ? [{ role: 'system', content: `这是从上一会话继承的摘要，请作为背景参考，不要逐字复述：\n${session.summary}` }, ...compactMsgs]
        : compactMsgs;

      let reply: string | null = null;

      if (mode === 'agent') {
        // Step 1: intent classify + plan
        const progressId = Date.now().toString();
        addMessage({ role: 'assistant', content: `分析意图中...`, _progress: true, _progressId: progressId });

        const execPayload: Record<string, unknown> = {
          command: text,
          current_page: baseContext.page_type || 'dashboard',
        };
        const { data: plan } = await api.post('/agent/execute', execPayload, { timeout: 30000 });
        useCopilotStore.getState().removeMessage(progressId);

        const intentType = plan.intent_type || 'qa';
        const planSteps: string[] = [];
        planSteps.push(`意图分析: ${intentType} (${((plan.confidence || 0) * 100).toFixed(0)}%)`);
        if (plan.explanation) planSteps.push(plan.explanation);

        if ((intentType === 'action' || intentType === 'mixed') && plan.atomic_steps?.length > 0) {
          planSteps.push(`执行 ${plan.atomic_steps.length} 个操作步骤...`);
          addMessage({ role: 'assistant', content: planSteps.join('\n'), _progress: true, _progressId: progressId });

          const execResult = await executor.executeSteps(plan.atomic_steps);
          useCopilotStore.getState().removeMessage(progressId);

          if (!execResult.success) {
            reply = `> ${planSteps.join('\n> ')}\n\n${execResult.message}`;
          } else if (intentType === 'mixed' && plan.follow_up_analysis) {
            addMessage({ role: 'assistant', content: '分析执行结果...', _progress: true, _progressId: progressId });
            const diagPayload: Record<string, unknown> = {
              messages: [...allMsgs, { role: 'system', content: plan.follow_up_analysis }],
              page_context: baseContext,
            };
            try {
              const { data: diag } = await api.post('/agent/diagnose', diagPayload, { timeout: 60000 });
              useCopilotStore.getState().removeMessage(progressId);
              const diagParts = planSteps.slice();
              if (diag.report) diagParts.push(diag.report);
              else if (diag.message) diagParts.push(diag.message);
              reply = diagParts.join('\n\n');
            } catch {
              useCopilotStore.getState().removeMessage(progressId);
              reply = `${planSteps.join('\n')}\n\n操作已完成`;
            }
          } else {
            reply = `${planSteps.join('\n')}\n\n操作已完成`;
          }
        } else {
          planSteps.push('查询知识库与分析...');
          addMessage({ role: 'assistant', content: planSteps.join('\n'), _progress: true, _progressId: progressId });

          const diagPayload: Record<string, unknown> = { messages: allMsgs, page_context: baseContext };
          if (screenshot) diagPayload.screenshot = screenshot;
          try {
            const { data: diag } = await api.post('/agent/diagnose', diagPayload, { timeout: 120000 });
            useCopilotStore.getState().removeMessage(progressId);
            const parts = planSteps.slice();
            if (diag.report) parts.push(diag.report);
            else if (diag.message) parts.push(diag.message);
            else parts.push(JSON.stringify(diag));
            reply = parts.join('\n\n');
          } catch {
            useCopilotStore.getState().removeMessage(progressId);
            reply = `${planSteps.join('\n')}\n\n抱歉，AI分析服务暂不可用。`;
          }
        }
      } else {
        // AI 对话模式 — 走 Copilot 对话链路
        const payload: Record<string, unknown> = {
          messages: sessionMsgs,
          page_context: baseContext,
          selected_contexts: selectedContextIds,
          session_id: session?.id,
          provider_config_id: session?.providerConfigId,
          model: session?.model,
          session_title_needed: !session?.title || session.title === '新建AI会话' || session.title.endsWith(' - 新模型'),
        };
        if (screenshot) payload.screenshot = screenshot;
        const streamId = `stream-${Date.now()}`;
        let streamedReply = '';
        let contextSources: ContextSource[] = [];
        let streamFailed = false;
        addMessage({ role: 'assistant', content: 'AI生成中...', _progress: true, _progressId: streamId });
        await postCopilotStream(payload, (event) => {
          if (event.type === 'meta') {
            contextSources = event.context_sources || [];
            return;
          }
          if (event.type === 'delta') {
            streamedReply += event.delta || '';
            updateMessage(streamId, { content: streamedReply || 'AI生成中...', _progress: true });
            return;
          }
          if (event.type === 'title' && event.session_title) {
            updateCurrentSessionMeta({ title: event.session_title });
            return;
          }
          if (event.type === 'error') {
            streamFailed = true;
            updateMessage(streamId, {
              role: 'error',
              content: formatCopilotError(event),
              _progress: false,
            });
          }
        });
        if (streamFailed) return;
        if (contextSources.length) {
          const labels = contextSources
            .map((source) => source.tools?.length ? `${source.label}（${source.tools.join('、')}）` : source.label)
            .join('、');
          streamedReply = `${streamedReply}\n\n> 本次参考数据：${labels}`;
        }
        updateMessage(streamId, {
          content: streamedReply || '本次未收到AI回复内容。',
          _progress: false,
        });
      }

      if (reply !== null) addMessage({ role: 'assistant', content: reply });
    } catch (error: any) {
      addMessage({
        role: 'error',
        content: formatCopilotError(error?.response?.data, 'AI服务请求失败，请确认后端服务、登录状态和网络连接正常。'),
      });
    } finally {
      setAttachScreenshotOnce(false);
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
          className="fixed z-[850] w-14 h-14 rounded-full bg-accent-blue shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center select-none"
          style={{ left: fabPos.x, top: fabPos.y, boxShadow: '0 0 20px rgba(59,130,246,0.4)' }}
        >
          <span className="text-lg font-bold">AI</span>
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-accent-green border-2 border-bg-primary animate-pulse" />
        </button>
      )}

      {/* Chat Panel — draggable */}
      {open && (
        <div
          ref={panelRef}
          data-copilot-ignore
          className="fixed z-[850] shadow-2xl flex flex-col overflow-hidden ops-panel rounded-2xl"
          style={{ left: panelPos.x, top: panelPos.y, width: panelSize.width, height: panelSize.height }}
        >
          {/* Header — drag handle */}
          <div
            className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-bg-panel/95 cursor-move select-none"
            onMouseDown={onDragStart}
          >
            <div className="flex items-center gap-2">
              <span className="ops-icon rounded-full bg-accent-blue/20 text-[10px] font-bold text-accent-blue">AI</span>
              <div>
                <h3 className="text-sm font-medium">风调AI助手</h3>
                <p className="text-[10px] text-accent-green">
                  {mode === 'agent'
                    ? 'Agent任务 · 自动执行'
                    : `${currentSession?.model || '未选择模型'} · 在线`}
                </p>
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-text-muted hover:text-text-primary text-lg">✕</button>
          </div>

          {/* Mode Toggle — AI对话 / Agent诊断 */}
          <div className="flex gap-1 px-4 py-2 border-b border-border-default bg-bg-panel/90">
            <button
              onClick={() => setMode('chat')}
                className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                  mode === 'chat'
                    ? 'bg-accent-blue text-white'
                    : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
                }`}
            >
              AI 对话
            </button>
            <button
              onClick={() => setMode('agent')}
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                mode === 'agent'
                  ? 'bg-accent-blue text-white'
                  : 'text-text-muted hover:text-text-primary hover:bg-bg-hover'
              }`}
            >
              Agent 任务
            </button>
          </div>

          <div className="flex min-h-0 flex-1">
            <aside className="w-36 shrink-0 border-r border-border-default bg-bg-secondary/70 px-2 py-3">
              <div className="mb-2 px-1">
                <p className="text-[11px] font-medium text-text-primary">数据栏</p>
                <p className="mt-0.5 text-[9px] leading-3 text-text-muted">可选；不选则由AI自行判断需求</p>
              </div>
              <div className="space-y-1">
                {DATA_CONTEXT_OPTIONS.map((item) => {
                  const active = selectedContextIds.includes(item.id);
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => toggleDataContext(item.id)}
                      title={item.hint}
                      className={`w-full rounded-md border px-2 py-1.5 text-left transition-colors ${
                        active
                          ? 'border-accent-blue bg-accent-blue/15 text-text-primary'
                          : 'border-border-default bg-bg-card text-text-muted hover:border-accent-blue hover:text-text-primary'
                      }`}
                    >
                      <span className="block text-[11px] font-medium leading-4">{item.label}</span>
                      <span className="block truncate text-[9px] leading-3 opacity-75">{item.hint}</span>
                    </button>
                  );
                })}
              </div>
            </aside>

            <div className="flex min-w-0 flex-1 flex-col">
          {/* Session and model controls */}
          <div className="px-4 py-2 border-b border-border-default bg-bg-secondary space-y-2">
            <div className="flex gap-2">
              <select
                value={currentSessionId}
                onChange={(e) => switchSession(e.target.value)}
                className="min-w-0 flex-1 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue"
              >
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.title} · {session.model || '未选模型'}
                  </option>
                ))}
              </select>
              <button
                onClick={createBlankSession}
                className="px-2 py-1.5 rounded-md border border-border-default text-[11px] text-text-secondary hover:text-accent-blue hover:border-accent-blue"
                title="新建会话"
              >
                新建
              </button>
              <button
                onClick={() => setPendingDeleteSessionId(currentSessionId)}
                disabled={sessions.length <= 1}
                className="px-2 py-1.5 rounded-md border border-border-default text-[11px] text-text-secondary hover:text-accent-red hover:border-accent-red disabled:opacity-40"
                title="删除当前会话"
              >
                删除
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={currentSession?.providerConfigId || ''}
                onChange={(e) => handleProviderSelect(e.target.value)}
                disabled={modelLocked}
                title={modelLocked ? '会话已开始，供应商已锁定' : '选择本会话供应商'}
                className="min-w-0 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-60"
              >
                <option value="">选择供应商</option>
                {availableProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.display_name || provider.provider}
                    {provider.last_test_status === 'error' ? ' (连接异常)' : ''}
                  </option>
                ))}
              </select>
              <select
                value={modelDraft}
                onChange={(e) => handleModelSelect(e.target.value)}
                disabled={modelLocked || !selectedProvider}
                title={modelLocked ? '会话已开始，模型已锁定' : '选择本会话模型'}
                className="min-w-0 bg-bg-card border border-border-default rounded-md px-2 py-1.5 text-[11px] text-text-primary focus:outline-none focus:border-accent-blue disabled:opacity-60"
              >
                {selectedModelOptions.length === 0 && <option value="">无可选模型</option>}
                {selectedModelOptions.map((model) => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>
            {modelLocked && (
              <p className="text-[10px] text-text-muted">当前会话已开始，供应商和模型已锁定；需要切换模型时请新建会话。</p>
            )}
            {availableProviders.length === 0 && (
              <p className="text-[10px] text-accent-yellow">
                暂无可用AI供应商，请先到系统设置的 AI 设置页保存并测试供应商配置。
              </p>
            )}
            {pendingDeleteSession && (
              <div className="rounded-md border border-accent-red/30 bg-accent-red/10 px-3 py-2">
                <p className="text-[11px] font-medium text-accent-red">确认删除当前会话？</p>
                <p className="mt-1 line-clamp-2 text-[10px] text-text-secondary">
                  {pendingDeleteSession.title} · {pendingDeleteSession.model || '未选模型'}
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setPendingDeleteSessionId(null)}
                    className="rounded border border-border-default px-3 py-1.5 text-[11px] text-text-secondary hover:text-text-primary"
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={confirmDeleteSession}
                    className="rounded border border-accent-red/40 bg-accent-red/15 px-3 py-1.5 text-[11px] text-accent-red hover:bg-accent-red/20"
                  >
                    删除
                  </button>
                </div>
              </div>
            )}
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
                    : m._progress
                    ? 'bg-accent-cyan/10 text-accent-cyan animate-pulse'
                    : 'bg-bg-hover text-text-primary'
                }`}>
                  {renderMessageContent(m.content, m._progress)}
                </div>
              </div>
            ))}
            {loading && <p className="text-text-muted animate-pulse">AI 思考中...</p>}
          </div>

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
                className="flex-1 rounded-lg border border-accent-blue/25 bg-bg-deep px-3 py-2 text-xs text-text-primary placeholder:text-text-secondary focus:border-accent-cyan focus:outline-none focus:ring-2 focus:ring-accent-cyan/15"
              />
              {mode === 'chat' && (
                <button
                  type="button"
                  onClick={() => setAttachScreenshotOnce((value) => !value)}
                  disabled={loading}
                  title="仅本次发送附加当前页面截图"
                  className={`px-3 py-2 rounded-lg border text-xs transition-colors disabled:opacity-40 ${
                    attachScreenshotOnce
                      ? 'border-accent-blue bg-accent-blue/15 text-accent-blue'
                      : 'border-border-default text-text-muted hover:text-accent-blue hover:border-accent-blue'
                  }`}
                >
                  {attachScreenshotOnce ? '已附图' : '附图'}
                </button>
              )}
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
                  onClick={() => { setInput(q); }}
                  className="rounded border border-accent-blue/25 bg-bg-card px-2 py-1 text-[10px] text-text-secondary transition-colors hover:border-accent-cyan hover:bg-accent-cyan/10 hover:text-accent-cyan"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
            </div>
          </div>
          <button
            type="button"
            aria-label="调整AI助手窗口大小"
            title="拖动调整窗口大小"
            onMouseDown={onResizeStart}
            className="absolute bottom-0 right-0 z-10 h-5 w-5 cursor-nwse-resize rounded-tl-md border-l border-t border-border-default bg-bg-secondary/90 text-[10px] text-text-muted hover:text-accent-blue"
          >
            <span className="absolute bottom-1 right-1 h-2.5 w-2.5 border-b border-r border-current" />
          </button>
        </div>
      )}
    </>
  );
}
