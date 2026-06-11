import { useEffect, useState, useRef } from 'react';
import api from '../../services/api';
import { useAuthStore } from '../../services/authStore';
import CopilotFAB from '../../components/AIAssistant/CopilotFAB';

interface ThresholdConfig { id: number; hi_threshold: number; email_enabled: boolean; email_address: string | null; wechat_enabled: boolean }
interface PipelineSource { type: string; name: string; status: string; last_update: string | null; record_count: number; real_data_available: boolean; note: string }
interface PipelineStatus { sources: PipelineSource[]; overall_status: string; errors: string[] }

export default function SettingsPage() {
  const { user, fetchMe } = useAuthStore();
  const [hiThreshold, setHiThreshold] = useState('70');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('gpt-4');
  const [saved, setSaved] = useState(false);
  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null);
  const [testResults, setTestResults] = useState<Record<string, string>>({});
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [emailAddress, setEmailAddress] = useState(user?.email || '');
  const [wechatEnabled, setWechatEnabled] = useState(false);

  useEffect(() => {
    api.get('/settings/thresholds').then(({ data }) => {
      if (data.length > 0) {
        const config = data[0] as ThresholdConfig;
        setHiThreshold(String(config.hi_threshold));
        setEmailEnabled(config.email_enabled);
        setEmailAddress(config.email_address || '');
        setWechatEnabled(config.wechat_enabled);
      }
    });
    refreshPipeline();
  }, []);

  const refreshPipeline = async () => {
    const { data } = await api.get('/settings/pipeline-status');
    setPipeline(data);
  };

  const saveThreshold = async () => {
    const { data } = await api.put('/settings/thresholds', {
      hi_threshold: Number(hiThreshold),
      email_enabled: emailEnabled,
      email_address: emailAddress || null,
      wechat_enabled: wechatEnabled,
    });
    setHiThreshold(String(data.hi_threshold));
    setEmailEnabled(data.email_enabled);
    setEmailAddress(data.email_address || '');
    setWechatEnabled(data.wechat_enabled);
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const saveProfile = async () => {
    await api.put('/settings/profile', { api_key: apiKey || null, model_preference: model });
    fetchMe();
    setSaved(true); setTimeout(() => setSaved(false), 2000);
  };

  const testConnection = async (type: string) => {
    setTestResults((prev) => ({ ...prev, [type]: 'testing' }));
    try {
      const { data } = await api.post('/settings/data-sources/test', { source_type: type, connection_params: {} });
      setTestResults((prev) => ({ ...prev, [type]: data.status === 'success' ? 'success' : 'error' }));
    } catch {
      setTestResults((prev) => ({ ...prev, [type]: 'error' }));
    }
    setTimeout(refreshPipeline, 500);
  };

  const statusColor = (s: string) => {
    switch (s) {
      case 'connected': return 'bg-accent-green/20 text-accent-green';
      case 'partial': return 'bg-accent-yellow/20 text-accent-yellow';
      case 'disconnected': return 'bg-text-muted/20 text-text-muted';
      case 'error': return 'bg-accent-red/20 text-accent-red';
      default: return 'bg-text-muted/20 text-text-muted';
    }
  };
  const statusLabel = (s: string) => {
    switch (s) {
      case 'connected': return '已连接';
      case 'partial': return '部分可用';
      case 'disconnected': return '未连接';
      case 'error': return '错误';
      default: return s;
    }
  };

  const sourceIcons: Record<string, string> = { scada: '📊', vibration: '〰', image: '🖼', weather: '🌤' };

  return (
    <div className="h-full overflow-auto p-6 space-y-6">
      <h2 className="text-lg font-semibold">系统设置</h2>

      {/* Profile */}
      <div className="bg-bg-card border border-border-default rounded-lg p-5 space-y-4">
        <h3 className="text-sm font-medium">个人配置</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs text-text-muted block mb-1">API Key（留空，之后填入）</label>
            <input
              type="password"
              placeholder="chenxxxxxx"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            />
          </div>
          <div>
            <label className="text-xs text-text-muted block mb-1">模型选择</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            >
              <option value="gpt-4">GPT-4</option>
              <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
              <option value="deepseek-v3">DeepSeek V3</option>
              <option value="claude-4">Claude 4</option>
            </select>
          </div>
        </div>
        <button onClick={saveProfile} className="px-4 py-2 bg-accent-blue text-white rounded text-sm">
          保存配置
        </button>
        {saved && <span className="ml-3 text-xs text-accent-green">已保存</span>}
      </div>

      {/* Data Pipeline Status */}
      <div className="bg-bg-card border border-border-default rounded-lg p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">数据管道状态</h3>
          <div className="flex items-center gap-2">
            {pipeline && (
              <span className={`w-2 h-2 rounded-full ${pipeline.overall_status === 'healthy' ? 'bg-accent-green' : 'bg-accent-yellow'}`} />
            )}
            <span className="text-xs text-text-muted">
              {pipeline?.overall_status === 'healthy' ? '运行正常' : '部分降级'}
            </span>
            <button onClick={refreshPipeline} className="text-xs text-accent-blue hover:underline ml-2">刷新</button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {pipeline?.sources.map((s) => (
            <div key={s.type} className="bg-bg-hover rounded-lg p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-lg">{sourceIcons[s.type] || '📦'}</span>
                  <div>
                    <p className="text-sm">{s.name}</p>
                  </div>
                </div>
                <span className={`px-1.5 py-0.5 rounded text-[10px] ${statusColor(s.status)}`}>
                  {statusLabel(s.status)}
                </span>
              </div>
              <div className="text-[10px] text-text-muted space-y-0.5">
                {s.last_update && <p>最近更新: {new Date(s.last_update).toLocaleString('zh-CN')}</p>}
                {s.record_count > 0 && <p>数据量: {s.record_count.toLocaleString()} 条</p>}
                <p className={s.real_data_available ? 'text-accent-green' : 'text-accent-yellow'}>
                  {s.note}
                </p>
              </div>
              <div className="flex items-center justify-between mt-2">
                {testResults[s.type] && (
                  <span className={`text-[10px] ${
                    testResults[s.type] === 'testing' ? 'text-accent-blue' :
                    testResults[s.type] === 'success' ? 'text-accent-green' : 'text-accent-red'
                  }`}>
                    {testResults[s.type] === 'testing' ? '测试中...' :
                     testResults[s.type] === 'success' ? '连接成功' : '连接失败'}
                  </span>
                )}
                <button
                  onClick={() => testConnection(s.type)}
                  className="px-2 py-1 border border-border-default rounded text-[10px] text-text-secondary hover:text-accent-blue hover:border-accent-blue transition-colors"
                >
                  测试连接
                </button>
              </div>
            </div>
          ))}
        </div>

        {pipeline?.errors && pipeline.errors.length > 0 && (
          <div className="mt-3 p-3 bg-accent-red/5 border border-accent-red/20 rounded text-xs">
            <p className="text-accent-red font-medium mb-1">管道错误 ({pipeline.errors.length})</p>
            {pipeline.errors.map((e, i) => (
              <p key={i} className="text-text-muted font-mono">{e}</p>
            ))}
          </div>
        )}
      </div>

      {/* Threshold */}
      <div className="bg-bg-card border border-border-default rounded-lg p-5 space-y-4">
        <h3 className="text-sm font-medium">告警阈值配置</h3>
        <div className="flex items-center gap-4">
          <div>
            <label className="text-xs text-text-muted block mb-1">健康指数(HI)告警阈值</label>
            <input
              type="number"
              min="0" max="100"
              value={hiThreshold}
              onChange={(e) => setHiThreshold(e.target.value)}
              className="w-24 bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            />
          </div>
          <span className="text-xs text-text-muted mt-5">当HI值低于此阈值时触发告警</span>
        </div>

        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={emailEnabled} onChange={(e) => setEmailEnabled(e.target.checked)} className="rounded" />
            启用邮件通知
          </label>
          <input
            placeholder="默认通知邮箱"
            value={emailAddress}
            onChange={(e) => setEmailAddress(e.target.value)}
            className="w-72 bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          />
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={wechatEnabled} onChange={(e) => setWechatEnabled(e.target.checked)} className="rounded" />
            启用企业微信通知
          </label>
        </div>
        <button onClick={saveThreshold} className="px-4 py-2 bg-accent-blue text-white rounded text-sm">
          保存阈值
        </button>
      </div>
      {/* Personnel Management */}
      <PersonnelSection />

      <CopilotFAB />
    </div>
  );
}

function PersonnelSection() {
  const [unlocked, setUnlocked] = useState(false);
  const [pwd, setPwd] = useState('');
  const [error, setError] = useState('');
  const [personnel, setPersonnel] = useState<any[]>([]);
  const [newPerson, setNewPerson] = useState({ name: '', skills: '', region: '陕北', email: '' });

  const refreshPersonnel = async () => {
    const { data } = await api.get('/personnel/');
    setPersonnel(data);
  };

  useEffect(() => { refreshPersonnel().catch(() => {}); }, [unlocked]);

  const handleUnlock = async () => {
    try {
      const { data } = await api.post('/auth/login', { username: 'admin', password: pwd });
      if (data.access_token) { setUnlocked(true); setError(''); }
    } catch { setError('密码错误'); }
  };

  const addPerson = async () => {
    if (!newPerson.name) return;
    const { data } = await api.post('/personnel/', {
      name: newPerson.name,
      skills: newPerson.skills.split(',').map((s: string) => s.trim()),
      region: newPerson.region,
      email: newPerson.email,
    });
    setPersonnel([...personnel, data]);
    setNewPerson({ name: '', skills: '', region: '陕北', email: '' });
  };

  const removePerson = async (id: number) => {
    await api.delete(`/personnel/${id}`);
    setPersonnel(personnel.filter(p => p.id !== id));
  };

  return (
    <div className="bg-bg-card border border-border-default rounded-lg p-5 space-y-4">
      <h3 className="text-sm font-medium">👥 人员管理 <span className="text-[10px] text-text-muted ml-2">需要管理员密码</span></h3>

      {!unlocked ? (
        <div className="flex items-center gap-3">
          <input type="password" placeholder="管理员密码" value={pwd} onChange={(e) => setPwd(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleUnlock()}
            className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary w-48 focus:outline-none focus:border-accent-blue" />
          <button onClick={handleUnlock} className="px-4 py-2 bg-accent-blue text-white rounded text-sm">解锁</button>
          {error && <span className="text-accent-red text-xs">{error}</span>}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Add new */}
          <div className="flex gap-2">
            <input placeholder="姓名" value={newPerson.name} onChange={(e) => setNewPerson({ ...newPerson, name: e.target.value })}
              className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary w-24 focus:outline-none focus:border-accent-blue" />
            <input placeholder="技能(逗号分隔)" value={newPerson.skills} onChange={(e) => setNewPerson({ ...newPerson, skills: e.target.value })}
              className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary flex-1 focus:outline-none focus:border-accent-blue" />
            <select value={newPerson.region} onChange={(e) => setNewPerson({ ...newPerson, region: e.target.value })}
              className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary">
              <option>陕北</option><option>关中</option><option>陕南</option>
            </select>
            <input placeholder="邮箱" value={newPerson.email} onChange={(e) => setNewPerson({ ...newPerson, email: e.target.value })}
              className="bg-bg-secondary border border-border-default rounded px-3 py-2 text-sm text-text-primary w-40 focus:outline-none focus:border-accent-blue" />
            <button onClick={addPerson} className="px-4 py-2 bg-accent-green text-white rounded text-sm whitespace-nowrap">+ 添加</button>
          </div>

          {/* List */}
          <div className="space-y-1 max-h-48 overflow-auto">
            {personnel.map((p) => (
              <div key={p.id} className="flex items-center gap-3 bg-bg-hover rounded px-3 py-2 text-xs">
                <span className="w-14 font-medium">{p.name}</span>
                <span className="flex gap-1">
                  {p.skills.map((s: string) => (
                    <span key={s} className="px-1.5 py-0.5 rounded bg-accent-blue/10 text-accent-blue text-[10px]">{s}</span>
                  ))}
                </span>
                <span className="text-text-muted">{p.region}</span>
                <span className="text-text-muted">{p.email}</span>
                <span className={`ml-auto ${p.load >= 3 ? 'text-accent-red' : p.load >= 2 ? 'text-accent-yellow' : 'text-accent-green'}`}>负载: {p.load}/5</span>
                <button onClick={() => removePerson(p.id)} className="text-text-muted hover:text-accent-red ml-2">✕</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
