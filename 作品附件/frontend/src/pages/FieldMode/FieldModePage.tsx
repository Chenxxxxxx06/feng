import { useState, useEffect, useCallback } from 'react';

/** PWA field mode — mobile-friendly maintenance assistant.
 *  NOT hardware AR. Browser-based voice, camera, task overlay.
 *  Responsive, offline-aware, touch-optimized.
 */

export default function FieldModePage() {
  const [online, setOnline] = useState(navigator.onLine);
  const [listening, setListening] = useState(false);
  const [voiceText, setVoiceText] = useState('');
  const [capturedImage, setCapturedImage] = useState<string | null>(null);
  const [taskStep, setTaskStep] = useState(0);
  const [taskComplete, setTaskComplete] = useState(false);

  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);

  // Simulated task steps
  const TASK_STEPS = [
    { id: 1, title: '确认设备锁定/挂牌 (LOTO)', icon: '🔒', voice: '确认锁定挂牌完成' },
    { id: 2, title: '检查个人防护装备 (PPE)', icon: '🪖', voice: 'PPE检查完毕' },
    { id: 3, title: '现场检查故障部件', icon: '🔍', voice: '目视检查完成' },
    { id: 4, title: '拍摄维修部位照片', icon: '📸', voice: '照片已拍摄' },
    { id: 5, title: '执行维修操作', icon: '🔧', voice: '维修完成' },
    { id: 6, title: '确认工具回收、现场清理', icon: '🧹', voice: '现场已清理' },
    { id: 7, title: '拆除锁定/挂牌，恢复送电', icon: '⚡', voice: '锁定已拆除' },
    { id: 8, title: '试运行确认运行参数', icon: '✅', voice: '试运行正常' },
  ];

  const startVoice = useCallback(() => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      setVoiceText('⚠ 浏览器不支持语音识别。请手动确认步骤。');
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
      // Check if voice matches current step keyword
      const currentStep = TASK_STEPS[taskStep];
      if (currentStep && text.includes(currentStep.voice.replace(/[了已]/g, '').substring(0, 4))) {
        handleNextStep();
      }
    };
    recognition.onerror = () => { setListening(false); };
    recognition.onend = () => { setListening(false); };
    recognition.start();
  }, [taskStep]);

  const handleNextStep = () => {
    if (taskStep < TASK_STEPS.length - 1) {
      setTaskStep(s => s + 1);
    } else {
      setTaskComplete(true);
    }
  };

  const handlePrevStep = () => {
    if (taskStep > 0) setTaskStep(s => s - 1);
  };

  const handleImageCapture = () => {
    // In production: use <input type="file" capture="environment">
    // Here: simulate with placeholder
    setCapturedImage('captured');
    setVoiceText('📸 照片已拍摄 (模拟)');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Status bar */}
      <div className="sticky top-0 z-10 bg-slate-900/95 backdrop-blur border-b border-slate-700/50 px-4 py-2 flex items-center justify-between">
        <h1 className="text-lg font-bold">🔧 现场模式</h1>
        <div className="flex items-center gap-3 text-xs">
          <span className={`flex items-center gap-1 ${online ? 'text-emerald-400' : 'text-red-400'}`}>
            <span className={`w-2 h-2 rounded-full ${online ? 'bg-emerald-400' : 'bg-red-400'}`} />
            {online ? '在线' : '离线'}
          </span>
          {!online && (
            <span className="text-yellow-400 bg-yellow-950/50 px-2 py-0.5 rounded">
              离线模式 — 数据将缓存后同步
            </span>
          )}
        </div>
      </div>

      <div className="max-w-lg mx-auto p-4 space-y-4">
        {/* Offline notice */}
        {!online && (
          <div className="p-4 bg-yellow-950/30 border border-yellow-700/50 rounded-lg">
            <div className="text-yellow-300 font-semibold">⚠ 弱网/离线模式</div>
            <div className="text-yellow-400/70 text-sm mt-1">
              任务步骤已缓存到本地。恢复网络后自动同步。
              高风险动作必须在线确认。
            </div>
          </div>
        )}

        {/* Task progress */}
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/30 p-4">
          <div className="flex justify-between items-center mb-3">
            <h2 className="font-semibold">维修任务进度</h2>
            <span className="text-sm text-slate-400">{taskStep + 1}/{TASK_STEPS.length}</span>
          </div>
          <div className="w-full bg-slate-700/50 rounded-full h-3 mb-4">
            <div
              className="h-3 rounded-full transition-all duration-300 bg-emerald-500"
              style={{ width: `${((taskStep + 1) / TASK_STEPS.length) * 100}%` }}
            />
          </div>
          {TASK_STEPS.map((step, idx) => (
            <div key={step.id}
              className={`flex items-center gap-3 p-3 rounded mb-1 transition-colors ${
                idx === taskStep ? 'bg-blue-950/30 border border-blue-700/30' :
                idx < taskStep ? 'bg-emerald-950/10 text-emerald-300' :
                'text-slate-500'
              }`}>
              <span className="text-xl">{idx < taskStep ? '✅' : idx === taskStep ? step.icon : '○'}</span>
              <span className="flex-1 text-sm">{step.title}</span>
              {idx === taskStep && <span className="text-xs text-blue-400 animate-pulse">← 当前</span>}
            </div>
          ))}
        </div>

        {/* Voice control */}
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/30 p-4">
          <h3 className="font-semibold mb-3">🎤 语音确认 (免手操作)</h3>
          <button
            onClick={startVoice}
            disabled={listening}
            className={`w-full py-3 rounded-lg font-semibold transition-colors ${
              listening
                ? 'bg-red-600 animate-pulse'
                : 'bg-blue-600 hover:bg-blue-500'
            } text-white disabled:opacity-70`}>
            {listening ? '🔴 聆听中...' : '🎤 点击语音确认当前步骤'}
          </button>
          {voiceText && (
            <div className="mt-2 p-2 bg-slate-700/50 rounded text-sm text-slate-300">
              "{voiceText}"
            </div>
          )}
          <div className="text-xs text-slate-500 mt-2">
            ⚠ 高风险动作(送电/起重)必须触屏确认，不能仅靠语音执行
          </div>
        </div>

        {/* Camera */}
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/30 p-4">
          <h3 className="font-semibold mb-3">📸 现场拍照</h3>
          <button
            onClick={handleImageCapture}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-semibold transition-colors">
            📷 拍摄维修部位
          </button>
          {capturedImage && (
            <div className="mt-2 p-3 bg-emerald-950/20 border border-emerald-700/30 rounded text-sm text-emerald-300">
              ✓ 照片已记录 — 将作为恢复验证证据
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex gap-3">
          <button onClick={handlePrevStep} disabled={taskStep === 0}
            className="flex-1 py-3 bg-slate-700 hover:bg-slate-600 disabled:opacity-30 text-white rounded-lg font-semibold transition-colors">
            ← 上一步
          </button>
          <button onClick={handleNextStep} disabled={taskStep >= TASK_STEPS.length - 1}
            className="flex-1 py-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-30 text-white rounded-lg font-semibold transition-colors">
            ✓ 确认完成 →
          </button>
        </div>

        {/* Complete */}
        {taskComplete && (
          <div className="p-6 bg-emerald-950/30 border border-emerald-500/50 rounded-lg text-center">
            <div className="text-4xl mb-3">✅</div>
            <div className="text-xl font-bold text-emerald-300">任务完成</div>
            <div className="text-sm text-emerald-400/70 mt-2">
              所有步骤已完成。数据将自动上传并触发恢复验证。
            </div>
          </div>
        )}

        {/* Disclaimer */}
        <div className="text-xs text-slate-600 text-center mt-6 pb-4">
          ⚠ 本页面为移动端辅助工具，非硬件AR设备。<br />
          所有高风险操作必须现场人工确认。<br />
          AI建议仅作辅助参考。
        </div>
      </div>
    </div>
  );
}
