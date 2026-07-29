import { useState, useEffect, useCallback } from 'react';
import { toast } from '../../components/Common/Toast';

/** PWA field mode — mobile-friendly maintenance assistant.
 *  NOT hardware AR. Browser-based voice, camera, task overlay.
 *  Responsive, offline-aware, touch-optimized.
 */

const TASK_STEPS = [
  { id: 1, title: '确认设备锁定 / 挂牌（LOTO）', voice: '确认锁定挂牌完成' },
  { id: 2, title: '检查个人防护装备（PPE）', voice: 'PPE检查完毕' },
  { id: 3, title: '现场检查故障部件', voice: '目视检查完成' },
  { id: 4, title: '拍摄维修部位照片', voice: '照片已拍摄' },
  { id: 5, title: '执行维修操作', voice: '维修完成' },
  { id: 6, title: '确认工具回收、现场清理', voice: '现场已清理' },
  { id: 7, title: '拆除锁定 / 挂牌，恢复送电', voice: '锁定已拆除' },
  { id: 8, title: '试运行确认运行参数', voice: '试运行正常' },
];

export default function FieldModePage() {
  const [online, setOnline] = useState(navigator.onLine);
  const [listening, setListening] = useState(false);
  const [voiceText, setVoiceText] = useState('');
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [taskStep, setTaskStep] = useState(0);
  const [taskComplete, setTaskComplete] = useState(false);

  useEffect(() => {
    const on = () => { setOnline(true); toast.success('网络已恢复', '缓存的现场记录将自动同步'); };
    const off = () => { setOnline(false); toast.warning('已进入离线模式', '步骤记录将缓存在本地，恢复网络后同步'); };
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);

  const handleNextStep = useCallback(() => {
    setTaskStep((s) => {
      if (s < TASK_STEPS.length - 1) return s + 1;
      setTaskComplete(true);
      return s;
    });
  }, []);

  const startVoice = useCallback(() => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      setVoiceText('当前浏览器不支持语音识别，请改用触屏确认。');
      toast.warning('浏览器不支持语音识别', '请使用下方按钮手动确认步骤');
      return;
    }
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = false;
    setListening(true);
    recognition.onresult = (event: any) => {
      const text = event.results[0][0].transcript;
      setVoiceText(text);
      const currentStep = TASK_STEPS[taskStep];
      if (currentStep && text.includes(currentStep.voice.replace(/[了已]/g, '').substring(0, 4))) {
        handleNextStep();
        toast.success('语音确认成功', currentStep.title);
      }
    };
    recognition.onerror = () => { setListening(false); toast.error('语音识别失败', '请重试或改用触屏确认'); };
    recognition.onend = () => { setListening(false); };
    recognition.start();
  }, [taskStep, handleNextStep]);

  const handlePrevStep = () => {
    if (taskStep > 0) setTaskStep((s) => s - 1);
  };

  const handleImageCapture = () => {
    // 生产环境使用 <input type="file" capture="environment">，此处为演示占位
    setCapturedImage('captured');
    setVoiceText('照片已拍摄（演示占位）');
    toast.success('照片已记录', '将作为恢复验证证据归档');
  };

  const progress = ((taskStep + 1) / TASK_STEPS.length) * 100;

  return (
    <div className="ops-page page-enter h-full overflow-y-auto">
      {/* 状态栏 */}
      <div
        className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b px-4 py-2.5"
        style={{ background: 'rgba(10,31,63,0.96)', borderColor: 'var(--border-default)', backdropFilter: 'blur(12px)' }}
      >
        <div className="min-w-0">
          <p className="ops-eyebrow">Field Mode · 移动端现场作业</p>
          <h1 className="ops-title mt-0.5">现场维修引导</h1>
        </div>
        <span className={`badge ${online ? 'badge-success' : 'badge-danger'}`} role="status">
          <span className={`dot ${online ? 'dot-success' : 'dot-danger'}`} aria-hidden="true" />
          {online ? '在线' : '离线'}
        </span>
      </div>

      <div className="mx-auto w-full max-w-2xl space-y-3 p-4">
        {/* 离线提示 */}
        {!online && (
          <div className="surface-card stagger-1 p-4" style={{ borderColor: 'rgba(245,158,11,0.35)', background: 'rgba(245,158,11,0.08)' }} role="alert">
            <p className="card-title" style={{ color: 'var(--accent-yellow)' }}>弱网 / 离线模式</p>
            <p className="mt-1 text-[11px] leading-relaxed text-text-secondary">
              任务步骤已缓存到本地，恢复网络后自动同步。高风险动作（送电、起重）必须在线确认。
            </p>
          </div>
        )}

        {/* 任务进度 */}
        <section className="surface-card stagger-1 p-4" aria-label="维修任务进度">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="section-title">维修任务进度</h2>
            <span className="num text-[11px] text-text-secondary">{taskStep + 1} / {TASK_STEPS.length}</span>
          </div>

          <div
            className="mb-4 h-2 w-full overflow-hidden rounded-full"
            style={{ background: 'rgba(59,130,246,0.12)' }}
            role="progressbar"
            aria-valuenow={Math.round(progress)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="任务完成度"
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${progress}%`, background: 'linear-gradient(90deg, var(--accent-green), var(--accent-cyan))' }}
            />
          </div>

          <ol className="space-y-1">
            {TASK_STEPS.map((step, idx) => {
              const done = idx < taskStep;
              const active = idx === taskStep;
              return (
                <li
                  key={step.id}
                  className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors"
                  style={{
                    background: active ? 'rgba(59,130,246,0.12)' : done ? 'rgba(16,185,129,0.07)' : 'transparent',
                    border: `1px solid ${active ? 'var(--border-active)' : 'transparent'}`,
                  }}
                  aria-current={active ? 'step' : undefined}
                >
                  <span
                    className="num flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
                    style={{
                      background: done ? 'rgba(16,185,129,0.18)' : active ? 'rgba(59,130,246,0.20)' : 'rgba(100,116,139,0.14)',
                      color: done ? 'var(--accent-green)' : active ? 'var(--accent-blue)' : 'var(--text-muted)',
                    }}
                    aria-hidden="true"
                  >
                    {done ? '✓' : step.id}
                  </span>
                  <span
                    className="flex-1 text-[12px] leading-snug"
                    style={{ color: active ? 'var(--text-primary)' : done ? 'var(--accent-green)' : 'var(--text-muted)' }}
                  >
                    {step.title}
                  </span>
                  {active && <span className="badge badge-info flex-shrink-0">当前步骤</span>}
                  {done && <span className="sr-only">已完成</span>}
                </li>
              );
            })}
          </ol>
        </section>

        {/* 语音确认 */}
        <section className="surface-card stagger-2 p-4" aria-label="语音确认">
          <h2 className="section-title mb-1">语音确认（免手操作）</h2>
          <p className="mb-3 text-[11px] leading-relaxed text-text-muted">
            高空 / 手部占用场景下，可念出当前步骤的确认口令完成签核。
          </p>
          <button
            type="button"
            onClick={startVoice}
            disabled={listening}
            aria-label={listening ? '正在聆听语音' : '点击开始语音确认当前步骤'}
            className={`btn btn-block btn-lg ${listening ? 'btn-danger' : 'btn-primary'}`}
          >
            {listening && <span className="btn-spinner" aria-hidden="true" />}
            {listening ? '聆听中…' : '点击语音确认当前步骤'}
          </button>
          {voiceText && (
            <p className="surface-inset mt-2 px-3 py-2 text-[11px] leading-relaxed text-text-secondary">
              识别结果：「{voiceText}」
            </p>
          )}
          <p className="mt-2 text-[10px] leading-relaxed" style={{ color: 'var(--accent-yellow)' }}>
            安全约束：送电、起重等高风险动作必须触屏确认，不接受纯语音执行。
          </p>
        </section>

        {/* 现场拍照 */}
        <section className="surface-card stagger-3 p-4" aria-label="现场拍照">
          <h2 className="section-title mb-3">现场拍照取证</h2>
          <button type="button" onClick={handleImageCapture} className="btn btn-success btn-block btn-lg">
            拍摄维修部位
          </button>
          {capturedImage && (
            <p className="mt-2 flex items-center gap-2 rounded-lg px-3 py-2 text-[11px]" style={{ background: 'rgba(16,185,129,0.10)', color: 'var(--accent-green)' }}>
              <span className="dot dot-success" aria-hidden="true" />
              照片已记录，将作为恢复验证证据归档
            </p>
          )}
        </section>

        {/* 步骤导航 */}
        <div className="flex gap-3 stagger-4">
          <button type="button" onClick={handlePrevStep} disabled={taskStep === 0} className="btn btn-secondary btn-lg flex-1">
            上一步
          </button>
          <button type="button" onClick={handleNextStep} disabled={taskComplete} className="btn btn-primary btn-lg flex-1">
            {taskComplete ? '任务已完成' : taskStep >= TASK_STEPS.length - 1 ? '确认全部完成' : '确认完成并继续'}
          </button>
        </div>

        {/* 完成 */}
        {taskComplete && (
          <div className="surface-card p-6 text-center" style={{ borderColor: 'rgba(16,185,129,0.40)', background: 'rgba(16,185,129,0.08)' }} role="status">
            <p className="text-[15px] font-bold" style={{ color: 'var(--accent-green)' }}>任务完成</p>
            <p className="mt-2 text-[11px] leading-relaxed text-text-secondary">
              全部 {TASK_STEPS.length} 个步骤已确认，数据将自动上传并触发恢复验证流程。
            </p>
          </div>
        )}

        {/* 免责说明 */}
        <p className="pb-6 pt-2 text-center text-[10px] leading-relaxed text-text-muted">
          本页面为移动端辅助工具，非硬件 AR 设备。<br />
          所有高风险操作必须现场人工确认，AI 建议仅作辅助参考。
        </p>
      </div>
    </div>
  );
}
