import { useState, useRef, useEffect } from 'react';
import api from '../../services/api';

interface Message { role: 'user' | 'assistant' | 'error'; content: string }

export default function CopilotFAB() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'SYS::AI_READY. 风调预顺控制中心在线。我可以解析风机数据、诊断故障、生成维护建议。' },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;
    const userMsg: Message = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    try {
      const { data } = await api.post('/ai/copilot', {
        messages: [...messages, userMsg].map((m) => ({ role: m.role, content: m.content })),
        page_context: { page_type: window.location.pathname.replace('/', '') || 'dashboard', url: window.location.href },
      });
      setMessages((prev) => [...prev, { role: 'assistant', content: data.reply }]);
    } catch {
      setMessages((prev) => [...prev, { role: 'error', content: 'ERR::AI_SERVICE_UNAVAILABLE' }]);
    } finally { setLoading(false); }
  };

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 flex items-center justify-center transition-all hover:scale-105"
          style={{
            width: 48, height: 48,
            border: '1px solid rgba(0,229,255,0.3)',
            borderRadius: '2px',
            background: 'rgba(0,229,255,0.06)',
            boxShadow: '0 0 20px rgba(0,229,255,0.12)',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00E5FF" strokeWidth="1.5">
            <path d="M12 2a5 5 0 0 1 5 5v1a5 5 0 0 1-5 5 5 5 0 0 1-5-5V7a5 5 0 0 1 5-5z"/>
            <path d="M3 14c0 4.97 4.03 9 9 9s9-4.03 9-9"/>
          </svg>
          <span
            className="absolute top-0 right-0 w-3 h-3 rounded-full border-2 animate-pulse"
            style={{ background: '#00E676', borderColor: '#020204' }}
          />
        </button>
      )}

      {open && (
        <div
          className="fixed bottom-6 right-6 z-50 flex flex-col overflow-hidden"
          style={{
            width: 420, height: 540,
            background: '#11141C',
            border: '1px solid rgba(0,229,255,0.15)',
            borderRadius: '4px',
            boxShadow: '0 0 40px rgba(0,0,0,0.8), 0 0 0 1px rgba(0,229,255,0.04)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 flex-shrink-0"
            style={{ borderBottom: '1px solid rgba(0,229,255,0.12)', background: '#0A0C10' }}>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 flex items-center justify-center"
                style={{ border: '1px solid rgba(0,229,255,0.2)', borderRadius: '2px', background: 'rgba(0,229,255,0.04)' }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#00E5FF" strokeWidth="1.5">
                  <path d="M12 2a5 5 0 0 1 5 5v1a5 5 0 0 1-5 5 5 5 0 0 1-5-5V7a5 5 0 0 1 5-5z"/>
                  <path d="M3 14c0 4.97 4.03 9 9 9s9-4.03 9-9"/>
                </svg>
              </div>
              <div>
                <h3 className="text-xs font-semibold font-display tracking-wider" style={{ color: '#E8ECF1' }}>AI COPILOT</h3>
                <p className="font-mono text-[9px] tracking-wider" style={{ color: '#00E676' }}>ONLINE</p>
              </div>
            </div>
            <button onClick={() => setOpen(false)}
              className="w-6 h-6 flex items-center justify-center transition-colors"
              style={{ color: '#445566' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = '#E8ECF1')}
              onMouseLeave={(e) => (e.currentTarget.style.color = '#445566')}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          {/* Messages */}
          <div ref={chatRef} className="flex-1 overflow-auto p-3 space-y-2.5 text-[12px]">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className="max-w-[88%] px-3 py-2.5" style={{
                  background: m.role === 'user' ? 'rgba(0,229,255,0.05)' : m.role === 'error' ? 'rgba(255,23,68,0.05)' : 'rgba(255,255,255,0.03)',
                  border: m.role === 'user' ? '1px solid rgba(0,229,255,0.15)' : m.role === 'error' ? '1px solid rgba(255,23,68,0.15)' : '1px solid rgba(255,255,255,0.06)',
                  borderRadius: '2px',
                  color: m.role === 'error' ? '#FF1744' : '#E8ECF1',
                }}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && <p className="font-mono text-[10px] tracking-wider animate-pulse" style={{ color: '#00E5FF' }}>PROCESSING...</p>}
          </div>

          {/* Input */}
          <div className="p-3 flex-shrink-0" style={{ borderTop: '1px solid rgba(0,229,255,0.12)' }}>
            <div className="flex gap-1.5">
              <span className="font-mono text-[10px] self-center flex-shrink-0" style={{ color: '#00E5FF' }}>&gt;</span>
              <input value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                placeholder="QUERY..."
                className="input-hud flex-1 text-[11px]" style={{ padding: '7px 10px' }} />
              <button onClick={handleSend} disabled={loading || !input.trim()}
                className="btn-prime-filled text-[10px] px-3" style={{ opacity: loading || !input.trim() ? 0.3 : 1 }}>
                SEND
              </button>
            </div>
            <div className="flex gap-1 mt-2">
              {['STATUS', 'FAULTS', 'TREND'].map((q) => (
                <button key={q} onClick={() => setInput(q)}
                  className="chip text-[9px] cursor-pointer">{q}</button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
