import { useEffect, useMemo, useState } from 'react';
import api from '../../services/api';
import { useAuthStore } from '../../services/authStore';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

interface ThresholdConfig {
  id: number;
  hi_threshold: number;
  email_enabled: boolean;
  email_address: string | null;
  wechat_enabled: boolean;
}

interface PipelineSource {
  type: string;
  name: string;
  status: string;
  last_update: string | null;
  record_count: number;
  real_data_available: boolean;
  note: string;
}

interface PipelineStatus {
  sources: PipelineSource[];
  overall_status: string;
  errors: string[];
}

interface Personnel {
  id: number;
  name: string;
  skills: string[];
  region: string;
  load: number;
  email: string;
}

interface ActivityLog {
  id: number;
  time: string;
  action: string;
  result: string;
  level: 'success' | 'info' | 'error';
}

type SectionKey = 'overview' | 'personal' | 'ai' | 'alerts' | 'pipeline' | 'personnel' | 'logs';

interface CurrentUser {
  id: number;
  username: string;
  email: string;
  role: string;
  api_key: string | null;
  api_provider: string | null;
  model_preference: string;
}

interface PersonalForm {
  displayName: string;
  email: string;
  phone: string;
  region: string;
  landingPage: string;
  digestFrequency: string;
}

interface PersonalPreferences {
  desktopDigest: boolean;
  compactWorkspace: boolean;
  riskFirst: boolean;
  autoOpenCopilot: boolean;
}

interface AIModelOption {
  value: string;
  label: string;
  provider: string;
  note: string;
  requiresKey: boolean;
}

const aiModelOptions: AIModelOption[] = [
  { value: 'qwen-plus', label: '通义千问 qwen-plus', provider: '通义千问 DashScope', note: '中文运维总结，质量/成本均衡', requiresKey: true },
  { value: 'qwen-turbo', label: '通义千问 qwen-turbo', provider: '通义千问 DashScope', note: '更快更便宜，适合页面摘要', requiresKey: true },
  { value: 'qwen3.6-flash', label: '通义千问 qwen3.6-flash', provider: '通义千问 DashScope', note: '轻量快速模型', requiresKey: true },
  { value: 'deepseek-v4-flash', label: 'DeepSeek deepseek-v4-flash', provider: 'DeepSeek', note: '低成本通用对话', requiresKey: true },
  { value: 'deepseek-chat', label: 'DeepSeek deepseek-chat', provider: 'DeepSeek', note: '历史稳定配置', requiresKey: true },
  { value: 'deepseek-reasoner', label: 'DeepSeek deepseek-reasoner', provider: 'DeepSeek', note: '推理任务更强', requiresKey: true },
  { value: 'glm-5-flash', label: '智谱 GLM-5-Flash', provider: '智谱GLM', note: '中文场景低成本', requiresKey: true },
  { value: 'kimi-k2.6', label: 'Kimi kimi-k2.6', provider: 'Kimi Moonshot', note: '长上下文友好', requiresKey: true },
  { value: 'gpt-4o-mini', label: 'OpenAI gpt-4o-mini', provider: 'OpenAI', note: '轻量多用途', requiresKey: true },
  { value: 'gpt-4.1', label: 'OpenAI gpt-4.1', provider: 'OpenAI', note: '高质量通用模型', requiresKey: true },
  { value: 'gpt-4', label: 'OpenAI gpt-4', provider: 'OpenAI', note: '历史配置', requiresKey: true },
  { value: 'gpt-3.5-turbo', label: 'OpenAI gpt-3.5-turbo', provider: 'OpenAI', note: '历史配置', requiresKey: true },
  { value: 'claude-sonnet-4-6', label: 'Claude claude-sonnet-4-6', provider: 'Claude', note: '高质量分析', requiresKey: true },
  { value: 'claude-haiku-4-5', label: 'Claude claude-haiku-4-5', provider: 'Claude', note: '快速低成本', requiresKey: true },
  { value: 'gemini-2.5-flash', label: 'Gemini gemini-2.5-flash', provider: 'Google Gemini', note: '免费层友好', requiresKey: true },
  { value: 'gemini-3.5-flash', label: 'Gemini gemini-3.5-flash', provider: 'Google Gemini', note: '新一代快速模型', requiresKey: true },
  { value: 'ollama-local', label: 'Ollama qwen2.5', provider: 'Ollama本地模型', note: '本地运行，不需要API Key', requiresKey: false },
];

const getModelOption = (model: string) => aiModelOptions.find((option) => option.value === model);
const normalizeModelPreference = (model?: string) => {
  const aliases: Record<string, string> = {
    'qwen3.5-flash': 'qwen3.6-flash',
    'deepseek-v3': 'deepseek-chat',
    'claude-sonnet-4': 'claude-sonnet-4-6',
    'claude-4': 'claude-sonnet-4-6',
  };
  return aliases[model || ''] || model || 'qwen-plus';
};

const sections: { key: SectionKey; label: string; desc: string }[] = [
  { key: 'overview', label: '总览', desc: '系统状态与最近操作' },
  { key: 'personal', label: '个人设置', desc: '账号资料与工作偏好' },
  { key: 'ai', label: 'AI设置', desc: '模型密钥和服务检查' },
  { key: 'alerts', label: '告警规则', desc: 'HI阈值和通知方式' },
  { key: 'pipeline', label: '数据源管理', desc: 'SCADA/振动/图像/气象' },
  { key: 'personnel', label: '人员管理', desc: '维护人员和负载' },
  { key: 'logs', label: '操作日志', desc: '本次配置变更记录' },
];

const sourceIcons: Record<string, string> = {
  scada: 'SC',
  vibration: 'VI',
  image: 'IM',
  weather: 'WE',
};

const sourceKindLabel: Record<string, string> = {
  scada: '运行遥测',
  vibration: '状态监测',
  image: '视觉巡检',
  weather: '环境数据',
};

const statusTone = (status: string) => {
  switch (status) {
    case 'connected':
      return 'border-accent-green/40 bg-accent-green/10 text-accent-green';
    case 'partial':
      return 'border-accent-yellow/40 bg-accent-yellow/10 text-accent-yellow';
    case 'error':
      return 'border-accent-red/40 bg-accent-red/10 text-accent-red';
    default:
      return 'border-border-default bg-bg-secondary text-text-muted';
  }
};

const statusLabel = (status: string) => {
  switch (status) {
    case 'connected':
      return '已连接';
    case 'partial':
      return '部分可用';
    case 'disconnected':
      return '未连接';
    case 'error':
      return '错误';
    default:
      return status;
  }
};

const loadTone = (load: number) => {
  if (load >= 4) return 'text-accent-red';
  if (load >= 2) return 'text-accent-yellow';
  return 'text-accent-green';
};

export default function SettingsPage() {
  const { user, fetchMe } = useAuthStore();
  const [activeSection, setActiveSection] = useState<SectionKey>('overview');
  const [hiThreshold, setHiThreshold] = useState('70');
  const [emailEnabled, setEmailEnabled] = useState(false);
  const [emailAddress, setEmailAddress] = useState('');
  const [wechatEnabled, setWechatEnabled] = useState(false);
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState(user?.model_preference || 'gpt-4');
  const [personalForm, setPersonalForm] = useState<PersonalForm>({
    displayName: user?.username || '',
    email: user?.email || '',
    phone: '',
    region: '陕北',
    landingPage: 'dashboard',
    digestFrequency: 'daily',
  });
  const [personalPrefs, setPersonalPrefs] = useState<PersonalPreferences>({
    desktopDigest: true,
    compactWorkspace: false,
    riskFirst: true,
    autoOpenCopilot: false,
  });
  const [personalSaved, setPersonalSaved] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState('');
  const [thresholdSaved, setThresholdSaved] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, string>>({});
  const [personnel, setPersonnel] = useState<Personnel[]>([]);
  const [personnelLoading, setPersonnelLoading] = useState(false);
  const [personnelFilter, setPersonnelFilter] = useState('');
  const [personnelError, setPersonnelError] = useState('');
  const [adminPwd, setAdminPwd] = useState('');
  const [unlocked, setUnlocked] = useState(user?.role === 'admin');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [personForm, setPersonForm] = useState({ name: '', skills: '', region: '陕北', email: '' });
  const [aiTestStatus, setAiTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
  const [aiTestMessage, setAiTestMessage] = useState('');
  const [logs, setLogs] = useState<ActivityLog[]>([
    {
      id: 1,
      time: new Date().toLocaleString('zh-CN'),
      action: '打开系统设置',
      result: '加载当前配置',
      level: 'info',
    },
  ]);

  useEffect(() => {
    if (!user) fetchMe();
    loadThresholds();
    refreshPipeline();
    refreshPersonnel();
  }, []);

  useEffect(() => {
    if (user?.model_preference) setModel(normalizeModelPreference(user.model_preference));
    if (user) {
      setPersonalForm((prev) => ({
        ...prev,
        displayName: prev.displayName || user.username,
        email: prev.email || user.email,
      }));
    }
    if (user?.role === 'admin') setUnlocked(true);
  }, [user]);

  const addLog = (action: string, result: string, level: ActivityLog['level'] = 'success') => {
    setLogs((prev) => [
      { id: Date.now(), time: new Date().toLocaleString('zh-CN'), action, result, level },
      ...prev,
    ].slice(0, 12));
  };

  const loadThresholds = async () => {
    const { data } = await api.get<ThresholdConfig[]>('/settings/thresholds');
    if (data.length > 0) {
      const config = data[0];
      setHiThreshold(String(config.hi_threshold));
      setEmailEnabled(config.email_enabled);
      setEmailAddress(config.email_address || '');
      setWechatEnabled(config.wechat_enabled);
    }
  };

  const refreshPipeline = async () => {
    setPipelineLoading(true);
    try {
      const { data } = await api.get('/settings/pipeline-status');
      setPipeline(data);
    } finally {
      setPipelineLoading(false);
    }
  };

  const refreshPersonnel = async () => {
    setPersonnelLoading(true);
    try {
      const { data } = await api.get('/personnel/');
      setPersonnel(data);
    } catch {
      setPersonnelError('人员列表加载失败');
    } finally {
      setPersonnelLoading(false);
    }
  };

  const saveThreshold = async () => {
    await api.put('/settings/thresholds', {
      hi_threshold: Number(hiThreshold),
      email_enabled: emailEnabled,
      email_address: emailEnabled ? emailAddress || null : null,
      wechat_enabled: wechatEnabled,
    });
    setThresholdSaved(true);
    addLog('保存告警规则', `HI阈值更新为 ${hiThreshold}`);
    setTimeout(() => setThresholdSaved(false), 2200);
  };

  const savePersonalSettings = () => {
    setPersonalSaved(true);
    addLog('保存个人设置', `${personalForm.displayName || user?.username || '当前账号'} 的工作偏好已更新`);
    setTimeout(() => setPersonalSaved(false), 2200);
  };

  const saveProfile = async () => {
    const option = getModelOption(model);
    const payload: { api_key?: string; api_provider?: string; model_preference: string } = {
      model_preference: model,
    };
    if (apiKey.trim()) {
      payload.api_key = apiKey.trim();
      payload.api_provider = option?.provider;
    }

    try {
      setProfileError('');
      await api.put('/settings/profile', payload);
      await fetchMe();
      setApiKey('');
      setProfileSaved(true);
      addLog('保存AI设置', `默认模型切换为 ${option?.label || model}`);
      setTimeout(() => setProfileSaved(false), 2200);
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setProfileError(detail || 'AI设置保存失败，请检查密钥供应商和模型是否匹配');
      addLog('保存AI设置', detail || 'AI设置保存失败', 'error');
    }
  };

  const testAiConnection = async () => {
    setAiTestStatus('testing');
    setAiTestMessage('');
    try {
      const { data } = await api.post('/ai/summary', {
        page_type: 'settings',
        page_data: { model, has_api_key: Boolean(apiKey || user?.api_key) },
      });
      setAiTestStatus('success');
      const mode = data.mode;
      const provider = data.provider || getModelOption(model)?.provider || 'AI服务';
      const actualModel = data.model || model;
      const message = mode === 'remote'
        ? `已连接 ${provider} · ${actualModel}`
        : mode === 'provider_mismatch'
          ? `模型与密钥不匹配：当前密钥属于 ${data.api_provider || '其他供应商'}，不能用于 ${provider}`
          : mode === 'key_unbound'
            ? '已有密钥未绑定供应商，请重新输入密钥并保存'
            : `未配置密钥，当前使用本地兜底，不产生AI调用费用`;
      setAiTestMessage(message);
      addLog('测试AI连接', message);
    } catch {
      setAiTestStatus('error');
      setAiTestMessage('AI服务请求失败，请确认已保存密钥、模型和网络可用');
      addLog('测试AI连接', 'AI服务请求失败', 'error');
    }
  };

  const testConnection = async (type: string) => {
    setTestResults((prev) => ({ ...prev, [type]: 'testing' }));
    try {
      const { data } = await api.post('/settings/data-sources/test', {
        source_type: type,
        connection_params: { mode: 'manual-test' },
      });
      setTestResults((prev) => ({ ...prev, [type]: data.status === 'success' ? 'success' : 'error' }));
      addLog('测试数据源', `${sourceKindLabel[type] || type} 连接测试完成`);
    } catch {
      setTestResults((prev) => ({ ...prev, [type]: 'error' }));
      addLog('测试数据源', `${sourceKindLabel[type] || type} 连接失败`, 'error');
    }
    setTimeout(refreshPipeline, 500);
  };

  const unlockPersonnel = async () => {
    try {
      const { data } = await api.post('/auth/login', { username: 'admin', password: adminPwd });
      if (data.access_token) {
        setUnlocked(true);
        setPersonnelError('');
        addLog('解锁人员管理', '管理员校验通过');
      }
    } catch {
      setPersonnelError('管理员密码错误');
    }
  };

  const resetPersonForm = () => {
    setEditingId(null);
    setPersonForm({ name: '', skills: '', region: '陕北', email: '' });
  };

  const submitPerson = async () => {
    if (!personForm.name || !personForm.email) {
      setPersonnelError('请填写姓名和邮箱');
      return;
    }
    const payload = {
      name: personForm.name,
      email: personForm.email,
      region: personForm.region,
      skills: personForm.skills.split(',').map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (editingId) {
        await api.put(`/personnel/${editingId}`, payload);
        addLog('更新人员', `${payload.name} 信息已更新`);
      } else {
        await api.post('/personnel/', payload);
        addLog('新增人员', `${payload.name} 已加入维护人员`);
      }
      resetPersonForm();
      setPersonnelError('');
      refreshPersonnel();
    } catch {
      setPersonnelError('人员保存失败，请检查姓名或邮箱是否重复');
    }
  };

  const startEditPerson = (person: Personnel) => {
    setEditingId(person.id);
    setPersonForm({
      name: person.name,
      skills: person.skills.join(', '),
      region: person.region,
      email: person.email,
    });
  };

  const removePerson = async (person: Personnel) => {
    if (!window.confirm(`确认停用 ${person.name} 吗？`)) return;
    await api.delete(`/personnel/${person.id}`);
    addLog('停用人员', `${person.name} 已从可派工人员中移除`);
    refreshPersonnel();
  };

  const connectedCount = pipeline?.sources.filter((s) => s.status === 'connected' || s.status === 'partial').length || 0;
  const totalRecords = pipeline?.sources.reduce((sum, s) => sum + s.record_count, 0) || 0;
  const highLoadCount = personnel.filter((p) => p.load >= 3).length;
  const filteredPersonnel = useMemo(() => {
    if (!personnelFilter) return personnel;
    return personnel.filter((p) => p.region === personnelFilter);
  }, [personnel, personnelFilter]);

  return (
    <div className="h-full overflow-hidden bg-bg-primary p-5">
      <div className="h-full flex flex-col gap-4">
        <header className="shrink-0 border-b border-border-default pb-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs text-text-muted">配置中心</p>
              <h2 className="mt-1 text-xl font-semibold text-text-primary">系统设置</h2>
              <p className="mt-1 text-xs text-text-secondary">
                管理告警策略、数据接入、AI服务和维护人员，所有配置会同步到后端接口。
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              <StatusMetric label="系统状态" value={pipeline?.overall_status === 'degraded' ? '部分降级' : '运行正常'} tone={pipeline?.overall_status === 'degraded' ? 'yellow' : 'green'} />
              <StatusMetric label="数据源" value={`${connectedCount}/${pipeline?.sources.length || 4}`} tone={connectedCount >= 3 ? 'green' : 'yellow'} />
              <StatusMetric label="HI阈值" value={hiThreshold} tone={Number(hiThreshold) < 65 ? 'red' : 'blue'} />
              <StatusMetric label="人员" value={`${personnel.length}人`} tone={highLoadCount ? 'yellow' : 'blue'} />
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 grid grid-cols-1 gap-4 lg:grid-cols-[230px_minmax(0,1fr)]">
          <aside className="rounded-lg border border-border-default bg-bg-card/70 p-2 lg:overflow-auto">
            <nav className="grid gap-1">
              {sections.map((section) => (
                <button
                  key={section.key}
                  onClick={() => setActiveSection(section.key)}
                  className={`text-left rounded-md px-3 py-3 transition-colors ${
                    activeSection === section.key
                      ? 'bg-accent-blue/10 text-accent-blue ring-1 ring-accent-blue/30'
                      : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                  }`}
                >
                  <span className="block text-sm font-medium">{section.label}</span>
                  <span className="mt-0.5 block text-[10px] text-text-muted">{section.desc}</span>
                </button>
              ))}
            </nav>
          </aside>

          <main className="min-h-0 overflow-auto rounded-lg border border-border-default bg-bg-card/60">
            {activeSection === 'overview' && (
              <OverviewSection
                pipeline={pipeline}
                personnel={personnel}
                logs={logs}
                hiThreshold={Number(hiThreshold)}
                totalRecords={totalRecords}
                onNavigate={setActiveSection}
              />
            )}
            {activeSection === 'personal' && (
              <PersonalSettingsSection
                user={user}
                form={personalForm}
                prefs={personalPrefs}
                personalSaved={personalSaved}
                onFormChange={setPersonalForm}
                onPrefsChange={setPersonalPrefs}
                onSave={savePersonalSettings}
              />
            )}
            {activeSection === 'ai' && (
              <AISettingsSection
                user={user}
                apiKey={apiKey}
                model={model}
                profileSaved={profileSaved}
                profileError={profileError}
                aiTestStatus={aiTestStatus}
                aiTestMessage={aiTestMessage}
                onApiKeyChange={setApiKey}
                onModelChange={setModel}
                onSave={saveProfile}
                onTestAi={testAiConnection}
              />
            )}
            {activeSection === 'alerts' && (
              <AlertSection
                hiThreshold={hiThreshold}
                emailEnabled={emailEnabled}
                emailAddress={emailAddress}
                wechatEnabled={wechatEnabled}
                thresholdSaved={thresholdSaved}
                onHiChange={setHiThreshold}
                onEmailEnabledChange={setEmailEnabled}
                onEmailAddressChange={setEmailAddress}
                onWechatEnabledChange={setWechatEnabled}
                onSave={saveThreshold}
              />
            )}
            {activeSection === 'pipeline' && (
              <PipelineSection
                pipeline={pipeline}
                pipelineLoading={pipelineLoading}
                testResults={testResults}
                onRefresh={refreshPipeline}
                onTest={testConnection}
              />
            )}
            {activeSection === 'personnel' && (
              <PersonnelSection
                userRole={user?.role}
                unlocked={unlocked}
                adminPwd={adminPwd}
                personnel={filteredPersonnel}
                personnelLoading={personnelLoading}
                personnelError={personnelError}
                personnelFilter={personnelFilter}
                editingId={editingId}
                personForm={personForm}
                onAdminPwdChange={setAdminPwd}
                onUnlock={unlockPersonnel}
                onFilterChange={setPersonnelFilter}
                onFormChange={setPersonForm}
                onSubmit={submitPerson}
                onCancelEdit={resetPersonForm}
                onEdit={startEditPerson}
                onRemove={removePerson}
              />
            )}
            {activeSection === 'logs' && <LogsSection logs={logs} />}
          </main>
        </div>
      </div>
      <CopilotFAB pageContext={{
        active_section: activeSection,
      }} />
    </div>
  );
}

function StatusMetric({ label, value, tone }: { label: string; value: string; tone: 'green' | 'yellow' | 'red' | 'blue' }) {
  const toneClass = {
    green: 'text-accent-green border-accent-green/30 bg-accent-green/10',
    yellow: 'text-accent-yellow border-accent-yellow/30 bg-accent-yellow/10',
    red: 'text-accent-red border-accent-red/30 bg-accent-red/10',
    blue: 'text-accent-blue border-accent-blue/30 bg-accent-blue/10',
  }[tone];
  return (
    <div className={`min-w-[112px] rounded-md border px-3 py-2 ${toneClass}`}>
      <p className="text-[10px] opacity-80">{label}</p>
      <p className="mt-0.5 text-sm font-semibold">{value}</p>
    </div>
  );
}

function SectionShell({ title, description, children, actions }: { title: string; description: string; children: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <section className="p-5">
      <div className="mb-5 flex flex-col gap-3 border-b border-border-default pb-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-base font-semibold text-text-primary">{title}</h3>
          <p className="mt-1 text-xs text-text-muted">{description}</p>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

function OverviewSection({
  pipeline,
  personnel,
  logs,
  hiThreshold,
  totalRecords,
  onNavigate,
}: {
  pipeline: PipelineStatus | null;
  personnel: Personnel[];
  logs: ActivityLog[];
  hiThreshold: number;
  totalRecords: number;
  onNavigate: (key: SectionKey) => void;
}) {
  const degraded = pipeline?.overall_status === 'degraded';
  return (
    <SectionShell title="运行总览" description="集中查看系统关键配置、数据接入和最近操作。">
      <div className="grid gap-3 lg:grid-cols-4">
        <OverviewTile label="后端服务" value={degraded ? '部分降级' : '正常'} hint={degraded ? '存在管道错误' : '接口响应正常'} tone={degraded ? 'yellow' : 'green'} />
        <OverviewTile label="数据记录" value={totalRecords.toLocaleString()} hint="当前管道累计记录" tone="blue" />
        <OverviewTile label="维护人员" value={`${personnel.length}人`} hint="可参与派工" tone="blue" />
        <OverviewTile label="告警阈值" value={`HI < ${hiThreshold}`} hint="触发健康告警" tone={hiThreshold < 65 ? 'red' : 'yellow'} />
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-sm font-medium">告警区间</h4>
              <p className="mt-1 text-xs text-text-muted">健康指数越低，维护优先级越高。</p>
            </div>
            <button onClick={() => onNavigate('alerts')} className="industrial-btn">调整规则</button>
          </div>
          <div className="mt-4 h-3 overflow-hidden rounded-full bg-bg-hover">
            <div className="float-left h-full w-[40%] bg-accent-red" />
            <div className="float-left h-full w-[30%] bg-accent-yellow" />
            <div className="float-left h-full w-[30%] bg-accent-green" />
          </div>
          <div className="mt-2 grid grid-cols-3 text-[10px] text-text-muted">
            <span>故障 0-59</span>
            <span className="text-center">预警 60-79</span>
            <span className="text-right">正常 80-100</span>
          </div>
        </div>

        <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium">最近操作</h4>
            <button onClick={() => onNavigate('logs')} className="text-xs text-accent-blue hover:underline">查看全部</button>
          </div>
          <div className="mt-3 space-y-3">
            {logs.slice(0, 4).map((log) => (
              <LogRow key={log.id} log={log} compact />
            ))}
          </div>
        </div>
      </div>
    </SectionShell>
  );
}

function OverviewTile({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: 'green' | 'yellow' | 'red' | 'blue' }) {
  const dot = {
    green: 'bg-accent-green',
    yellow: 'bg-accent-yellow',
    red: 'bg-accent-red',
    blue: 'bg-accent-blue',
  }[tone];
  return (
    <div className="rounded-lg border border-border-default bg-bg-secondary/70 p-4">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${dot}`} />
        <span className="text-xs text-text-muted">{label}</span>
      </div>
      <p className="mt-3 text-xl font-semibold">{value}</p>
      <p className="mt-1 text-[10px] text-text-muted">{hint}</p>
    </div>
  );
}

function PersonalSettingsSection({
  user,
  form,
  prefs,
  personalSaved,
  onFormChange,
  onPrefsChange,
  onSave,
}: {
  user: CurrentUser | null;
  form: PersonalForm;
  prefs: PersonalPreferences;
  personalSaved: boolean;
  onFormChange: (value: PersonalForm) => void;
  onPrefsChange: (value: PersonalPreferences) => void;
  onSave: () => void;
}) {
  return (
    <SectionShell
      title="个人设置"
      description="维护当前账号的展示资料、默认工作台和本地使用偏好。"
      actions={
        <>
          {personalSaved && <span className="text-xs text-accent-green">个人设置已保存</span>}
          <button onClick={onSave} className="industrial-btn industrial-btn-primary">保存个人设置</button>
        </>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-5">
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h4 className="text-sm font-medium">账号资料</h4>
                <p className="mt-1 text-xs text-text-muted">当前后端仅开放AI偏好保存，资料项先作为本地偏好记录。</p>
              </div>
              <span className="rounded-full border border-accent-blue/30 bg-accent-blue/10 px-2 py-1 text-[10px] text-accent-blue">
                {user?.role || '未登录'}
              </span>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <label className="block">
                <span className="text-xs text-text-muted">显示名称</span>
                <input
                  value={form.displayName}
                  onChange={(e) => onFormChange({ ...form, displayName: e.target.value })}
                  placeholder={user?.username || '请输入显示名称'}
                  className="industrial-input mt-1 w-full"
                />
              </label>
              <label className="block">
                <span className="text-xs text-text-muted">联系邮箱</span>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => onFormChange({ ...form, email: e.target.value })}
                  placeholder={user?.email || 'ops@example.com'}
                  className="industrial-input mt-1 w-full"
                />
              </label>
              <label className="block">
                <span className="text-xs text-text-muted">联系电话</span>
                <input
                  value={form.phone}
                  onChange={(e) => onFormChange({ ...form, phone: e.target.value })}
                  placeholder="用于紧急工单通知"
                  className="industrial-input mt-1 w-full"
                />
              </label>
              <label className="block">
                <span className="text-xs text-text-muted">负责区域</span>
                <select value={form.region} onChange={(e) => onFormChange({ ...form, region: e.target.value })} className="industrial-input mt-1 w-full">
                  <option value="陕北">陕北</option>
                  <option value="关中">关中</option>
                  <option value="陕南">陕南</option>
                  <option value="全场">全场</option>
                </select>
              </label>
            </div>
          </div>

          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">工作台偏好</h4>
            <p className="mt-1 text-xs text-text-muted">决定进入系统后的默认视图和日常摘要节奏。</p>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <label className="block">
                <span className="text-xs text-text-muted">默认首页</span>
                <select value={form.landingPage} onChange={(e) => onFormChange({ ...form, landingPage: e.target.value })} className="industrial-input mt-1 w-full">
                  <option value="dashboard">风场监控</option>
                  <option value="diagnosis">故障诊断</option>
                  <option value="prediction">预测决策</option>
                  <option value="workorder">维修工单</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-text-muted">摘要频率</span>
                <select value={form.digestFrequency} onChange={(e) => onFormChange({ ...form, digestFrequency: e.target.value })} className="industrial-input mt-1 w-full">
                  <option value="realtime">实时提醒</option>
                  <option value="daily">每日汇总</option>
                  <option value="weekly">每周汇总</option>
                  <option value="off">不主动推送</option>
                </select>
              </label>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <ToggleRow
              title="桌面摘要"
              desc="打开系统时展示关键告警和待办数量。"
              checked={prefs.desktopDigest}
              onChange={(checked) => onPrefsChange({ ...prefs, desktopDigest: checked })}
            />
            <ToggleRow
              title="紧凑模式"
              desc="压缩表格和面板间距，适合值班大屏旁路查看。"
              checked={prefs.compactWorkspace}
              onChange={(checked) => onPrefsChange({ ...prefs, compactWorkspace: checked })}
            />
            <ToggleRow
              title="风险优先"
              desc="列表默认将故障、低HI和RUL不足项目排在前面。"
              checked={prefs.riskFirst}
              onChange={(checked) => onPrefsChange({ ...prefs, riskFirst: checked })}
            />
            <ToggleRow
              title="自动打开AI助手"
              desc="进入诊断和预测页面时自动准备当前页面上下文。"
              checked={prefs.autoOpenCopilot}
              onChange={(checked) => onPrefsChange({ ...prefs, autoOpenCopilot: checked })}
            />
          </div>
        </div>

        <div className="space-y-5">
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">账号状态</h4>
            <div className="mt-4 grid gap-3">
              <InfoLine label="账号ID" value={user?.id ? String(user.id) : '-'} />
              <InfoLine label="登录名" value={user?.username || '-'} />
              <InfoLine label="邮箱" value={user?.email || '-'} />
              <InfoLine label="权限角色" value={user?.role || '-'} />
            </div>
          </div>
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">本次偏好预览</h4>
            <div className="mt-4 space-y-3 text-xs text-text-secondary">
              <p>默认进入：{landingPageLabel(form.landingPage)}</p>
              <p>负责区域：{form.region}</p>
              <p>摘要节奏：{digestLabel(form.digestFrequency)}</p>
              <p>风险优先：{prefs.riskFirst ? '开启' : '关闭'}</p>
            </div>
          </div>
        </div>
      </div>
    </SectionShell>
  );
}

function AISettingsSection({
  user,
  apiKey,
  model,
  profileSaved,
  profileError,
  aiTestStatus,
  aiTestMessage,
  onApiKeyChange,
  onModelChange,
  onSave,
  onTestAi,
}: {
  user: CurrentUser | null;
  apiKey: string;
  model: string;
  profileSaved: boolean;
  profileError: string;
  aiTestStatus: 'idle' | 'testing' | 'success' | 'error';
  aiTestMessage: string;
  onApiKeyChange: (value: string) => void;
  onModelChange: (value: string) => void;
  onSave: () => void;
  onTestAi: () => void;
}) {
  const currentModel = getModelOption(model);
  const hasTypedKey = Boolean(apiKey.trim());
  const hasSavedKey = Boolean(user?.api_key);
  const savedProvider = user?.api_provider || '';
  const selectedProvider = currentModel?.provider || '';
  const selectedRequiresKey = currentModel?.requiresKey !== false;
  const hasSavedOrTypedKey = hasSavedKey || hasTypedKey;
  const savedKeyUnbound = selectedRequiresKey && hasSavedKey && !savedProvider && !hasTypedKey;
  const providerMismatch = selectedRequiresKey && hasSavedKey && Boolean(savedProvider) && savedProvider !== selectedProvider && !hasTypedKey;
  const localModelWithTypedKey = !selectedRequiresKey && hasTypedKey;
  const canSaveAISettings = !savedKeyUnbound && !providerMismatch && !localModelWithTypedKey;
  const savedModelPreference = normalizeModelPreference(user?.model_preference);
  const hasUnsavedAIChanges = hasTypedKey || savedModelPreference !== model;
  const canTestAISettings = canSaveAISettings && !hasUnsavedAIChanges && aiTestStatus !== 'testing';
  const keyStatusTone = savedKeyUnbound || providerMismatch || localModelWithTypedKey
    ? 'border-accent-red/30 bg-accent-red/10 text-accent-red'
    : hasSavedOrTypedKey
      ? 'border-accent-green/30 bg-accent-green/10 text-accent-green'
      : 'border-accent-yellow/30 bg-accent-yellow/10 text-accent-yellow';
  const keyStatusLabel = !selectedRequiresKey
    ? (localModelWithTypedKey ? '本地模型无需密钥' : '本地模型')
    : hasTypedKey
      ? `将绑定 ${selectedProvider}`
      : savedKeyUnbound
        ? '密钥未绑定'
        : providerMismatch
          ? '供应商不匹配'
          : hasSavedKey
            ? `${savedProvider}密钥`
            : '本地兜底';
  const bindingMessage = localModelWithTypedKey
    ? '当前选择本地模型，不需要输入AI服务密钥；请清空密钥框后保存。'
    : hasTypedKey
      ? `保存后，这个新密钥会被绑定为 ${selectedProvider} 密钥，只能用于 ${selectedProvider} 模型。`
      : savedKeyUnbound
        ? '已有密钥来自旧版本，未记录供应商。请重新输入该供应商密钥并保存一次。'
        : providerMismatch
          ? `当前保存的是 ${savedProvider} 密钥，不能选择 ${selectedProvider} 模型。请切回 ${savedProvider} 模型，或输入 ${selectedProvider} 的新密钥。`
          : '';
  const providerRows = [
    { name: '通义千问 DashScope', model: 'qwen-plus / qwen-turbo / qwen3.6-flash', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'DeepSeek', model: 'deepseek-v4-flash / chat / reasoner', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: '智谱GLM', model: 'glm-5-flash', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'Kimi Moonshot', model: 'kimi-k2.6', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'Google Gemini', model: 'gemini-2.5-flash / gemini-3.5-flash', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'Claude', model: 'claude-sonnet-4-6 / claude-haiku-4-5', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'OpenAI', model: 'gpt-4o-mini / gpt-4.1 / gpt-4', cost: '有密钥时按供应商Token计费', state: '已接入' },
    { name: 'Ollama本地模型', model: 'qwen / llama / deepseek', cost: '软件免费，消耗本机算力', state: '适合演示兜底' },
  ];

  return (
    <SectionShell
      title="AI设置"
      description="配置智能总结、故障分析和运维助手实际调用的模型；保存后由后端按模型路由到对应供应商。"
      actions={
        <>
          {profileSaved && <span className="text-xs text-accent-green">AI设置已保存</span>}
          <button
            onClick={onSave}
            disabled={!canSaveAISettings}
            className={`industrial-btn industrial-btn-primary ${!canSaveAISettings ? 'cursor-not-allowed opacity-50' : ''}`}
          >
            保存AI设置
          </button>
        </>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h4 className="text-sm font-medium">模型与密钥</h4>
                <p className="mt-1 text-xs text-text-muted">密钥不在前端回显；输入新密钥后会通过后端个人配置接口保存。</p>
              </div>
              <span className={`rounded-full border px-2 py-1 text-[10px] ${keyStatusTone}`}>
                {keyStatusLabel}
              </span>
            </div>
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <label className="block">
                <span className="text-xs text-text-muted">API Key</span>
                <input
                  type="password"
                  autoComplete="off"
                  placeholder={user?.api_key ? '已配置，输入新密钥可替换' : '请输入AI服务密钥'}
                  value={apiKey}
                  onChange={(e) => onApiKeyChange(e.target.value)}
                  className="industrial-input mt-1 w-full"
                />
              </label>
              <label className="block">
                <span className="text-xs text-text-muted">默认模型</span>
                <select value={model} onChange={(e) => onModelChange(e.target.value)} className="industrial-input mt-1 w-full">
                  {aiModelOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              <InfoLine label="当前账号" value={user?.username || '-'} />
              <InfoLine label="实际模型ID" value={currentModel?.value || model} />
              <InfoLine label="供应商" value={currentModel?.provider || '默认通义千问'} />
            </div>
            <div className="mt-3 rounded-md border border-border-default bg-bg-card px-3 py-2 text-xs text-text-secondary">
              {bindingMessage || (currentModel?.requiresKey === false
                ? '当前选择本地模型，不需要AI服务密钥；如果本机未启动Ollama，后端会回退到本地规则结果。'
                : hasSavedOrTypedKey
                  ? `保存后将使用 ${currentModel?.provider || 'AI供应商'} 的 ${currentModel?.value || model}，调用远程模型可能按供应商规则计费。`
                  : '当前未配置AI服务密钥，后端不会调用远程收费模型，会使用本地兜底结果，不产生AI调用费用。')}
            </div>
            {profileError && (
              <div className="mt-3 rounded-md border border-accent-red/30 bg-accent-red/10 px-3 py-2 text-xs text-accent-red">
                {profileError}
              </div>
            )}
            {savedProvider && (
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <InfoLine label="已保存密钥供应商" value={savedProvider} />
                <InfoLine label="当前模型供应商" value={selectedProvider || '-'} />
              </div>
            )}
          </div>

          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">已接入供应商</h4>
            <p className="mt-1 text-xs text-text-muted">下列模型值会直接传给对应供应商，页面显示名与后端实际调用模型保持一致。</p>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {providerRows.map((provider) => (
                <ProviderRow key={provider.name} {...provider} />
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-5">
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">AI服务检查</h4>
            <p className="mt-1 text-xs text-text-muted">
              {hasUnsavedAIChanges ? '当前模型或密钥尚未保存，请先保存AI设置再测试。' : '测试当前已保存的密钥供应商和模型是否匹配并可用。'}
            </p>
            <button
              onClick={onTestAi}
              className={`industrial-btn mt-4 w-full ${!canTestAISettings ? 'cursor-not-allowed opacity-50' : ''}`}
              disabled={!canTestAISettings}
            >
              {aiTestStatus === 'testing' ? '测试中...' : '测试AI连接'}
            </button>
            {aiTestStatus !== 'idle' && (
              <p className={`mt-3 text-xs ${aiTestStatus === 'success' ? 'text-accent-green' : aiTestStatus === 'error' ? 'text-accent-red' : 'text-accent-blue'}`}>
                {aiTestMessage || (aiTestStatus === 'success' ? 'AI服务响应正常' : aiTestStatus === 'error' ? 'AI服务请求失败' : '正在等待AI响应')}
              </p>
            )}
          </div>

          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">接入准备清单</h4>
            <div className="mt-4 space-y-3">
              <PlanStep index="1" title="选择供应商" desc="课程演示建议优先通义千问或DeepSeek，国内可访问且成本低。" />
              <PlanStep index="2" title="后端保存密钥" desc="密钥放在.env或后端加密字段，避免写入前端代码和仓库。" />
              <PlanStep index="3" title="统一调用适配" desc="把base_url、model、api_key传给OpenAI兼容客户端，页面只调用后端接口。" />
              <PlanStep index="4" title="增加限流兜底" desc="失败时使用本地规则结果，避免诊断页面因为AI不可用而中断。" />
            </div>
          </div>
        </div>
      </div>
    </SectionShell>
  );
}

function ToggleRow({ title, desc, checked, onChange }: { title: string; desc: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="flex items-start justify-between gap-4 rounded-lg border border-border-default bg-bg-secondary/60 p-4">
      <span>
        <span className="block text-sm font-medium text-text-primary">{title}</span>
        <span className="mt-1 block text-xs text-text-muted">{desc}</span>
      </span>
      <input className="mt-1" type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function ProviderRow({ name, model, cost, state }: { name: string; model: string; cost: string; state: string }) {
  return (
    <div className="rounded-md border border-border-default bg-bg-card px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium text-text-primary">{name}</p>
          <p className="mt-1 text-[10px] text-text-muted">{model}</p>
        </div>
        <span className="rounded-full border border-accent-blue/30 bg-accent-blue/10 px-2 py-0.5 text-[10px] text-accent-blue">{state}</span>
      </div>
      <p className="mt-3 text-xs text-text-secondary">{cost}</p>
    </div>
  );
}

function PlanStep({ index, title, desc }: { index: string; title: string; desc: string }) {
  return (
    <div className="flex gap-3 rounded-md border border-border-default bg-bg-card px-3 py-3">
      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-accent-blue/10 text-xs font-semibold text-accent-blue">{index}</span>
      <span>
        <span className="block text-xs font-medium text-text-primary">{title}</span>
        <span className="mt-1 block text-[10px] leading-relaxed text-text-muted">{desc}</span>
      </span>
    </div>
  );
}

function landingPageLabel(value: string) {
  const labels: Record<string, string> = {
    dashboard: '风场监控',
    diagnosis: '故障诊断',
    prediction: '预测决策',
    workorder: '维修工单',
  };
  return labels[value] || value;
}

function digestLabel(value: string) {
  const labels: Record<string, string> = {
    realtime: '实时提醒',
    daily: '每日汇总',
    weekly: '每周汇总',
    off: '不主动推送',
  };
  return labels[value] || value;
}

function AlertSection({
  hiThreshold,
  emailEnabled,
  emailAddress,
  wechatEnabled,
  thresholdSaved,
  onHiChange,
  onEmailEnabledChange,
  onEmailAddressChange,
  onWechatEnabledChange,
  onSave,
}: {
  hiThreshold: string;
  emailEnabled: boolean;
  emailAddress: string;
  wechatEnabled: boolean;
  thresholdSaved: boolean;
  onHiChange: (value: string) => void;
  onEmailEnabledChange: (value: boolean) => void;
  onEmailAddressChange: (value: string) => void;
  onWechatEnabledChange: (value: boolean) => void;
  onSave: () => void;
}) {
  const threshold = Number(hiThreshold);
  return (
    <SectionShell
      title="告警规则"
      description="配置HI健康指数阈值和通知方式，用于风机健康预警。"
      actions={
        <>
          {thresholdSaved && <span className="text-xs text-accent-green">阈值已保存</span>}
          <button onClick={onSave} className="industrial-btn industrial-btn-primary">保存规则</button>
        </>
      }
    >
      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h4 className="text-sm font-medium">健康指数阈值</h4>
              <p className="mt-1 text-xs text-text-muted">当风机HI低于该值时触发告警并进入重点跟踪。</p>
            </div>
            <input
              type="number"
              min="0"
              max="100"
              value={hiThreshold}
              onChange={(e) => onHiChange(e.target.value)}
              className="industrial-input w-24 text-center text-lg font-semibold"
            />
          </div>
          <input
            type="range"
            min="0"
            max="100"
            value={hiThreshold}
            onChange={(e) => onHiChange(e.target.value)}
            className="mt-6 w-full accent-blue-500"
          />
          <div className="mt-4 rounded-md border border-border-default bg-bg-card p-3">
            <div className="h-2 overflow-hidden rounded-full">
              <div className="float-left h-full w-[60%] bg-accent-red" />
              <div className="float-left h-full w-[20%] bg-accent-yellow" />
              <div className="float-left h-full w-[20%] bg-accent-green" />
            </div>
            <div className="mt-2 grid grid-cols-3 text-[10px] text-text-muted">
              <span>故障区间 &lt; 60</span>
              <span className="text-center">预警区间 60-79</span>
              <span className="text-right">正常区间 &gt;= 80</span>
            </div>
          </div>
          <p className={`mt-3 text-xs ${threshold < 60 ? 'text-accent-red' : threshold < 80 ? 'text-accent-yellow' : 'text-accent-green'}`}>
            当前配置：HI低于 {threshold || 0} 时触发告警。
          </p>
        </div>

        <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
          <h4 className="text-sm font-medium">通知方式</h4>
          <p className="mt-1 text-xs text-text-muted">保存后由后端记录邮件和企业微信通知开关。</p>
          <div className="mt-4 space-y-3">
            <label className="flex items-center justify-between rounded-md border border-border-default bg-bg-card px-3 py-2">
              <span className="text-sm">邮件通知</span>
              <input type="checkbox" checked={emailEnabled} onChange={(e) => onEmailEnabledChange(e.target.checked)} />
            </label>
            {emailEnabled && (
              <input
                value={emailAddress}
                onChange={(e) => onEmailAddressChange(e.target.value)}
                placeholder="ops@example.com"
                className="industrial-input w-full"
              />
            )}
            <label className="flex items-center justify-between rounded-md border border-border-default bg-bg-card px-3 py-2">
              <span className="text-sm">企业微信通知</span>
              <input type="checkbox" checked={wechatEnabled} onChange={(e) => onWechatEnabledChange(e.target.checked)} />
            </label>
            <div className="rounded-md border border-border-default bg-bg-card px-3 py-2">
              <p className="text-sm">扩展触发项</p>
              <div className="mt-2 grid gap-2 text-xs text-text-secondary">
                <span>RUL低于90天：建议维护提醒</span>
                <span>新故障产生：推送故障诊断摘要</span>
                <span>工单超期：提醒责任人与管理员</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </SectionShell>
  );
}

function PipelineSection({
  pipeline,
  pipelineLoading,
  testResults,
  onRefresh,
  onTest,
}: {
  pipeline: PipelineStatus | null;
  pipelineLoading: boolean;
  testResults: Record<string, string>;
  onRefresh: () => void;
  onTest: (type: string) => void;
}) {
  return (
    <SectionShell
      title="数据源管理"
      description="检查SCADA、振动、叶片图像和气象数据的接入状态。"
      actions={<button onClick={onRefresh} className="industrial-btn">{pipelineLoading ? '刷新中...' : '刷新状态'}</button>}
    >
      <div className="grid gap-3 xl:grid-cols-2">
        {pipeline?.sources.map((source) => (
          <div key={source.type} className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-md border border-border-default bg-bg-card text-xs font-semibold text-accent-blue">
                  {sourceIcons[source.type] || 'DS'}
                </span>
                <div>
                  <h4 className="text-sm font-medium">{source.name}</h4>
                  <p className="mt-1 text-xs text-text-muted">{sourceKindLabel[source.type] || '数据源'}</p>
                </div>
              </div>
              <span className={`rounded-full border px-2 py-1 text-[10px] ${statusTone(source.status)}`}>
                {statusLabel(source.status)}
              </span>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <InfoLine label="数据量" value={source.record_count ? `${source.record_count.toLocaleString()}条` : '-'} />
              <InfoLine label="数据类型" value={source.real_data_available ? '真实数据' : '模拟/待接入'} />
              <InfoLine label="最近更新" value={source.last_update ? new Date(source.last_update).toLocaleDateString('zh-CN') : '-'} />
            </div>
            <p className={`mt-3 text-xs ${source.real_data_available ? 'text-accent-green' : 'text-accent-yellow'}`}>
              {source.note}
            </p>
            <div className="mt-4 flex items-center justify-between">
              <span className={`text-xs ${
                testResults[source.type] === 'testing' ? 'text-accent-blue' :
                testResults[source.type] === 'success' ? 'text-accent-green' :
                testResults[source.type] === 'error' ? 'text-accent-red' : 'text-text-muted'
              }`}>
                {testResults[source.type] === 'testing' ? '正在测试...' :
                 testResults[source.type] === 'success' ? '连接测试完成' :
                 testResults[source.type] === 'error' ? '连接失败' : '等待操作'}
              </span>
              <button onClick={() => onTest(source.type)} className="industrial-btn">测试连接</button>
            </div>
          </div>
        ))}
      </div>

      {pipeline?.errors && pipeline.errors.length > 0 && (
        <div className="mt-5 rounded-lg border border-accent-red/30 bg-accent-red/5 p-4">
          <p className="text-sm font-medium text-accent-red">管道错误 ({pipeline.errors.length})</p>
          <div className="mt-2 space-y-1">
            {pipeline.errors.map((error, index) => (
              <p key={index} className="font-mono text-xs text-text-muted">{error}</p>
            ))}
          </div>
        </div>
      )}
    </SectionShell>
  );
}

function PersonnelSection({
  userRole,
  unlocked,
  adminPwd,
  personnel,
  personnelLoading,
  personnelError,
  personnelFilter,
  editingId,
  personForm,
  onAdminPwdChange,
  onUnlock,
  onFilterChange,
  onFormChange,
  onSubmit,
  onCancelEdit,
  onEdit,
  onRemove,
}: {
  userRole?: string;
  unlocked: boolean;
  adminPwd: string;
  personnel: Personnel[];
  personnelLoading: boolean;
  personnelError: string;
  personnelFilter: string;
  editingId: number | null;
  personForm: { name: string; skills: string; region: string; email: string };
  onAdminPwdChange: (value: string) => void;
  onUnlock: () => void;
  onFilterChange: (value: string) => void;
  onFormChange: (value: { name: string; skills: string; region: string; email: string }) => void;
  onSubmit: () => void;
  onCancelEdit: () => void;
  onEdit: (person: Personnel) => void;
  onRemove: (person: Personnel) => void;
}) {
  return (
    <SectionShell
      title="人员管理"
      description="维护技术人员信息，工单页面会使用这里的人员列表进行派工。"
      actions={
        <select value={personnelFilter} onChange={(e) => onFilterChange(e.target.value)} className="industrial-input">
          <option value="">全部区域</option>
          <option value="陕北">陕北</option>
          <option value="关中">关中</option>
          <option value="陕南">陕南</option>
        </select>
      }
    >
      {!unlocked ? (
        <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
          <p className="text-sm font-medium">需要管理员校验</p>
          <p className="mt-1 text-xs text-text-muted">当前角色：{userRole || '-'}，请输入管理员密码后编辑人员信息。</p>
          <div className="mt-4 flex max-w-md gap-2">
            <input
              type="password"
              placeholder="管理员密码"
              value={adminPwd}
              onChange={(e) => onAdminPwdChange(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onUnlock()}
              className="industrial-input flex-1"
            />
            <button onClick={onUnlock} className="industrial-btn industrial-btn-primary">解锁</button>
          </div>
          {personnelError && <p className="mt-2 text-xs text-accent-red">{personnelError}</p>}
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
          <div className="rounded-lg border border-border-default bg-bg-secondary/60 p-4">
            <h4 className="text-sm font-medium">{editingId ? '编辑人员' : '新增人员'}</h4>
            <div className="mt-4 space-y-3">
              <input placeholder="姓名" value={personForm.name} onChange={(e) => onFormChange({ ...personForm, name: e.target.value })} className="industrial-input w-full" />
              <input placeholder="邮箱" value={personForm.email} onChange={(e) => onFormChange({ ...personForm, email: e.target.value })} className="industrial-input w-full" />
              <input placeholder="技能，逗号分隔" value={personForm.skills} onChange={(e) => onFormChange({ ...personForm, skills: e.target.value })} className="industrial-input w-full" />
              <select value={personForm.region} onChange={(e) => onFormChange({ ...personForm, region: e.target.value })} className="industrial-input w-full">
                <option>陕北</option>
                <option>关中</option>
                <option>陕南</option>
              </select>
            </div>
            <div className="mt-4 flex gap-2">
              <button onClick={onSubmit} className="industrial-btn industrial-btn-primary flex-1">{editingId ? '保存修改' : '添加人员'}</button>
              {editingId && <button onClick={onCancelEdit} className="industrial-btn">取消</button>}
            </div>
            {personnelError && <p className="mt-3 text-xs text-accent-red">{personnelError}</p>}
          </div>

          <div className="min-w-0 rounded-lg border border-border-default bg-bg-secondary/60">
            <div className="grid grid-cols-[90px_1fr_70px_90px_120px] gap-3 border-b border-border-default px-4 py-3 text-xs text-text-muted">
              <span>姓名</span>
              <span>技能</span>
              <span>区域</span>
              <span>负载</span>
              <span className="text-right">操作</span>
            </div>
            <div className="max-h-[420px] overflow-auto">
              {personnelLoading ? (
                <p className="p-4 text-sm text-text-muted">人员加载中...</p>
              ) : personnel.length === 0 ? (
                <p className="p-4 text-sm text-text-muted">暂无人员</p>
              ) : (
                personnel.map((person) => (
                  <div key={person.id} className="grid grid-cols-[90px_1fr_70px_90px_120px] gap-3 border-b border-border-default px-4 py-3 text-xs last:border-0">
                    <span className="font-medium text-text-primary">{person.name}</span>
                    <span className="flex flex-wrap gap-1">
                      {person.skills.map((skill) => (
                        <span key={skill} className="rounded bg-accent-blue/10 px-1.5 py-0.5 text-[10px] text-accent-blue">{skill}</span>
                      ))}
                    </span>
                    <span className="text-text-secondary">{person.region}</span>
                    <span className={loadTone(person.load)}>负载 {person.load}/5</span>
                    <span className="flex justify-end gap-2">
                      <button onClick={() => onEdit(person)} className="text-accent-blue hover:underline">编辑</button>
                      <button onClick={() => onRemove(person)} className="text-accent-red hover:underline">停用</button>
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </SectionShell>
  );
}

function LogsSection({ logs }: { logs: ActivityLog[] }) {
  return (
    <SectionShell title="操作日志" description="展示本次进入系统设置后的配置变更、连接测试和人员维护记录。">
      <div className="rounded-lg border border-border-default bg-bg-secondary/60">
        {logs.map((log) => <LogRow key={log.id} log={log} />)}
      </div>
    </SectionShell>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border-default bg-bg-card px-3 py-2">
      <p className="text-[10px] text-text-muted">{label}</p>
      <p className="mt-1 truncate text-xs text-text-primary">{value}</p>
    </div>
  );
}

function LogRow({ log, compact = false }: { log: ActivityLog; compact?: boolean }) {
  const toneClass = {
    success: 'bg-accent-green',
    info: 'bg-accent-blue',
    error: 'bg-accent-red',
  }[log.level];
  return (
    <div className={`flex items-start gap-3 border-b border-border-default last:border-0 ${compact ? 'py-1.5' : 'px-4 py-3'}`}>
      <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${toneClass}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <p className="truncate text-xs font-medium text-text-primary">{log.action}</p>
          {!compact && <span className="shrink-0 text-[10px] text-text-muted">{log.time}</span>}
        </div>
        <p className="mt-0.5 text-[10px] text-text-muted">{log.result}</p>
      </div>
    </div>
  );
}
