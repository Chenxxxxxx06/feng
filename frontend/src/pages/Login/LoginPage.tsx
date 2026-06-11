import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../services/authStore';

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const { login, register, loading } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      if (isRegister) await register(username, email, password);
      else await login(username, password);
      navigate('/dashboard');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'AUTHENTICATION FAILURE');
    }
  };

  return (
    <div
      className="h-screen flex items-center justify-center hex-bg scan-line relative overflow-hidden"
      style={{ background: '#020204' }}
    >
      {/* Top glow bar */}
      <div
        style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: '1px',
          background: 'linear-gradient(90deg, transparent, rgba(0,229,255,0.4), transparent)',
          opacity: 0.6,
        }}
      />

      {/* Auth panel */}
      <div
        className="relative z-10 w-[400px] p-8"
        style={{
          background: '#11141C',
          border: '1px solid rgba(0,229,255,0.12)',
          borderRadius: '4px',
          boxShadow: '0 0 40px rgba(0,0,0,0.8), 0 0 0 1px rgba(0,229,255,0.04)',
        }}
      >
        {/* Identity */}
        <div className="text-center mb-8">
          <div
            className="w-14 h-14 flex items-center justify-center mx-auto mb-4"
            style={{
              border: '1px solid rgba(0,229,255,0.2)',
              borderRadius: '2px',
              background: 'rgba(0,229,255,0.03)',
            }}
          >
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#00E5FF" strokeWidth="1.2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
            </svg>
          </div>
          <h1
            className="text-2xl font-semibold tracking-widest mb-1"
            style={{ fontFamily: '"Rajdhani","PingFang SC",sans-serif', color: '#E8ECF1', letterSpacing: '0.06em' }}
          >
            风调预顺
          </h1>
          <p className="font-mono text-[10px] uppercase tracking-widest" style={{ color: '#445566' }}>
            PHM::CONTROL_CENTER
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text" placeholder="USERNAME" value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="input-hud w-full" required
          />

          {isRegister && (
            <input
              type="email" placeholder="EMAIL" value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-hud w-full" required
            />
          )}

          <input
            type="password" placeholder="PASSWORD" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input-hud w-full" required
          />

          {error && (
            <p className="font-mono text-[10px] tracking-wider" style={{ color: '#FF1744' }}>
              {error}
            </p>
          )}

          <button
            type="submit" disabled={loading}
            className="btn-prime-filled w-full h-10 text-sm tracking-widest"
          >
            {loading ? 'PROCESSING...' : isRegister ? 'REGISTER' : 'LOGIN'}
          </button>
        </form>

        <p className="text-center mt-5 font-mono text-[10px] tracking-wider" style={{ color: '#445566' }}>
          {isRegister ? 'HAVE ACCOUNT?' : 'NO ACCOUNT?'}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="ml-2 transition-colors hover:text-neon-cyan"
            style={{ color: '#8899AA' }}
          >
            {isRegister ? '[LOGIN]' : '[REGISTER]'}
          </button>
        </p>
      </div>
    </div>
  );
}
