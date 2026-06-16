import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import type { AISummary } from '../../types';

interface Props {
  pageType: string;
  pageData?: Record<string, unknown>;
}

interface AIProviderConfig {
  id: number;
  provider: string;
  display_name: string | null;
  default_model: string | null;
  model_options: string[];
  enabled: boolean;
  has_api_key: boolean;
  last_test_status: string | null;
}

function fallbackProviderModels(provider?: AIProviderConfig | null) {
  const key = provider?.provider?.toLowerCase() || '';
  if (key === 'qwen' || key === 'dashscope') return ['qwen-plus', 'qwen-turbo', 'qwen3.6-flash'];
  if (key === 'deepseek') return ['deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-flash'];
  return [provider?.default_model].filter(Boolean) as string[];
}

const SUMMARY_ERROR_TITLES: Record<string, string> = {
  ai_provider_not_found: 'AI供应商配置不存在',
  ai_provider_disabled: 'AI供应商已停用',
  api_key_missing: 'AI密钥未配置',
  provider_unbound: 'AI密钥未绑定供应商',
  provider_mismatch: '模型与密钥供应商不匹配',
  upstream_auth_failed: 'AI供应商鉴权失败',
  model_not_found: '模型不可用',
  upstream_rate_limited: 'AI额度或频率受限',
  upstream_server_error: 'AI供应商服务异常',
  upstream_timeout: 'AI请求超时',
  client_timeout: '前端等待AI总结超时',
  network_error: '无法连接AI供应商',
  upstream_unknown: 'AI调用失败',
};

function buildClientSummaryError(error: any, provider?: AIProviderConfig | null, model?: string): AISummary {
  const responseData = error?.response?.data || {};
  const detail = responseData.detail;
  const isClientTimeout = error?.code === 'ECONNABORTED' || String(error?.message || '').includes('timeout');
  const message = typeof detail === 'string'
    ? detail
    : responseData.error_message
      || (isClientTimeout ? '前端等待AI总结超过60秒。后端或供应商仍可能在处理，请稍后重试或切换更快模型。' : error?.message)
      || '请求首页AI总结失败，请检查后端服务、登录状态或网络连接。';
  return {
    status: 'error',
    error_code: responseData.error_code || (isClientTimeout ? 'client_timeout' : 'network_error'),
    error_message: message,
    model_status: {
      provider: provider ? (provider.display_name || provider.provider) : '默认配置',
      model: model || provider?.default_model || '-',
      mode: isClientTimeout ? 'client_timeout' : undefined,
      has_api_key: provider?.has_api_key,
    },
    conclusions: ['已切换为本地规则总结，未使用当前AI模型生成。'],
    suggestions: ['检查供应商配置、模型名称、API KEY、账户额度或网络连通性后重试。'],
  };
}

export default function AIPanel({ pageType, pageData }: Props) {
  const [summary, setSummary] = useState<AISummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [triggered, setTriggered] = useState(false);
  const [providers, setProviders] = useState<AIProviderConfig[]>([]);
  const [providerId, setProviderId] = useState('');
  const [model, setModel] = useState('');

  const availableProviders = useMemo(() => providers.filter((provider) => (
    provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama')
  )), [providers]);

  const selectedProvider = useMemo(
    () => availableProviders.find((provider) => String(provider.id) === providerId) || null,
    [availableProviders, providerId],
  );

  const modelOptions = selectedProvider?.model_options?.length
    ? selectedProvider.model_options
    : fallbackProviderModels(selectedProvider);

  useEffect(() => {
    let cancelled = false;
    api.get<AIProviderConfig[]>('/settings/ai-providers')
      .then(({ data }) => {
        if (cancelled) return;
        setProviders(data);
        const enabled = data.filter((provider) => (
          provider.enabled && provider.last_test_status !== 'error' && (provider.has_api_key || provider.provider === 'ollama')
        ));
        if (!providerId && enabled.length > 0) {
          const first = enabled[0];
          setProviderId(String(first.id));
          setModel(first.default_model || first.model_options?.[0] || '');
        }
      })
      .catch(() => setProviders([]));
    return () => { cancelled = true; };
  }, [providerId]);

  const handleProviderChange = useCallback((nextProviderId: string) => {
    setProviderId(nextProviderId);
    const provider = availableProviders.find((item) => String(item.id) === nextProviderId);
    setModel(provider?.default_model || provider?.model_options?.[0] || '');
    setTriggered(false);
    setSummary(null);
  }, [availableProviders]);

  const handleModelChange = useCallback((nextModel: string) => {
    setModel(nextModel);
    setTriggered(false);
    setSummary(null);
  }, []);

  const fetchSummary = useCallback(() => {
    setTriggered(true);
    setLoading(true);
    api.post('/ai/summary', {
      page_type: pageType,
      page_data: pageData || {},
      provider_config_id: providerId ? Number(providerId) : undefined,
      model: model || undefined,
    }, { timeout: 60000 })
      .then(({ data }) => setSummary(data))
      .catch((error) => setSummary(buildClientSummaryError(error, selectedProvider, model)))
      .finally(() => setLoading(false));
  }, [pageType, pageData, providerId, model, selectedProvider]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden p-3">
      <div className="mb-2 flex shrink-0 items-center gap-1.5">
        <span className="text-accent-cyan text-xs">⚡</span>
        <h4 className="text-xs font-medium text-text-secondary">AI 智能总结</h4>
      </div>
      <div className="mb-2 grid shrink-0 grid-cols-2 gap-1.5">
        <select
          value={providerId}
          onChange={(event) => handleProviderChange(event.target.value)}
          className="min-w-0 rounded border border-border-default bg-bg-secondary px-2 py-1 text-[10px] text-text-primary focus:border-accent-cyan focus:outline-none"
        >
          <option value="">默认配置</option>
          {availableProviders.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.display_name || provider.provider}
            </option>
          ))}
        </select>
        <select
          value={model}
          onChange={(event) => handleModelChange(event.target.value)}
          disabled={!selectedProvider && modelOptions.length === 0}
          className="min-w-0 rounded border border-border-default bg-bg-secondary px-2 py-1 text-[10px] text-text-primary focus:border-accent-cyan focus:outline-none disabled:opacity-50"
        >
          {modelOptions.length === 0 && <option value="">默认模型</option>}
          {modelOptions.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto pr-1">
      {!triggered ? (
        <button
          onClick={fetchSummary}
          className="w-full rounded border border-accent-cyan/40 bg-accent-cyan/10 px-3 py-2 text-xs text-accent-cyan hover:bg-accent-cyan/20 transition-colors"
        >
          🤖 生成AI总结
        </button>
      ) : loading ? (
        <p className="text-xs text-text-muted animate-pulse">分析中...</p>
      ) : summary ? (
        <div className="space-y-2">
          {summary.status === 'error' && (
            <div className="rounded border border-accent-red/30 bg-accent-red/10 p-2 text-[10px] text-text-secondary">
              <p className="mb-1 font-medium text-accent-red">
                {SUMMARY_ERROR_TITLES[summary.error_code || ''] || 'AI总结生成失败'}
              </p>
              <p className="leading-4 text-accent-red/90">{summary.error_message || '未返回具体错误原因。'}</p>
              <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 font-mono text-[9px] text-text-muted">
                <span>错误码</span><span>{summary.error_code || '-'}</span>
                <span>模型</span><span className="truncate">{summary.model_status?.model || model || '-'}</span>
                <span>供应商</span><span className="truncate">{summary.model_status?.provider || selectedProvider?.display_name || selectedProvider?.provider || '-'}</span>
                <span>密钥</span><span>{summary.model_status?.has_api_key === false ? '未配置' : '已配置/未知'}</span>
              </div>
              <p className="mt-2 text-[10px] text-text-muted">以下为本地规则临时总结。</p>
            </div>
          )}
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">关键结论</p>
            <ul className="space-y-1">
              {summary.conclusions.map((c, i) => (
                <li key={i} className="text-xs text-text-primary flex gap-1.5">
                  <span className="text-accent-blue flex-shrink-0">{i + 1}.</span>
                  {c}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] text-text-muted uppercase tracking-wide mb-1">可执行建议</p>
            <ul className="space-y-1">
              {summary.suggestions.map((s, i) => (
                <li key={i} className="text-xs text-accent-yellow flex gap-1.5">
                  <span>▸</span>
                  {s}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <div className="rounded border border-accent-red/30 bg-accent-red/10 p-2 text-[10px] text-accent-red">
          <p className="font-medium">AI总结生成失败</p>
          <p className="mt-1">未收到后端响应，请检查登录状态、后端服务和网络连接。</p>
        </div>
      )}
      </div>
    </div>
  );
}
