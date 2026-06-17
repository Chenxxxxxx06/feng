import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../services/authStore';
import loginBackground from '../../assets/fengmian.png';

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
      if (isRegister) {
        await register(username, email, password);
      } else {
        await login(username, password);
      }
      navigate('/dashboard');
    } catch (err: any) {
      setError(err.response?.data?.detail || '操作失败');
    }
  };

  return (
    <div
      className="h-screen flex items-center justify-center bg-bg-primary px-4"
      style={{
        backgroundImage: `linear-gradient(120deg, rgba(3, 10, 24, 0.86) 0%, rgba(7, 26, 53, 0.70) 48%, rgba(3, 10, 24, 0.90) 100%), url(${loginBackground})`,
        backgroundPosition: 'center',
        backgroundSize: 'cover',
      }}
    >
      <div className="w-full max-w-sm rounded-2xl border border-white/15 bg-bg-panel/90 p-8 shadow-2xl backdrop-blur-md">
        <div className="text-center mb-8">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl border border-accent-cyan/30 bg-accent-blue/25 text-sm font-bold text-accent-cyan shadow-glow-blue">PHM</div>
          <h1 className="text-xl font-bold mt-3 tracking-wider text-white">风调预顺</h1>
          <p className="text-text-secondary text-xs mt-1">PHM预测性运维系统</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">用户名</label>
            <input
              type="text"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg border border-accent-blue/30 bg-bg-deep/95 px-3 py-2.5 text-sm text-white placeholder:text-text-secondary outline-none transition-colors focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/20"
              required
            />
          </div>
          {isRegister && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">邮箱</label>
              <input
                type="email"
                placeholder="邮箱"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-accent-blue/30 bg-bg-deep/95 px-3 py-2.5 text-sm text-white placeholder:text-text-secondary outline-none transition-colors focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/20"
                required
              />
            </div>
          )}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">密码</label>
            <input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-accent-blue/30 bg-bg-deep/95 px-3 py-2.5 text-sm text-white placeholder:text-text-secondary outline-none transition-colors focus:border-accent-cyan focus:ring-2 focus:ring-accent-cyan/20"
              required
            />
          </div>

          {error && <p className="rounded border border-accent-red/30 bg-accent-red/10 px-3 py-2 text-xs text-accent-red">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="ops-btn ops-btn-primary w-full py-2.5 text-sm disabled:opacity-50"
          >
            {loading ? '处理中...' : isRegister ? '注册' : '登录'}
          </button>
        </form>

        <p className="text-center mt-4 text-xs text-text-secondary">
          {isRegister ? '已有账号？' : '没有账号？'}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="ml-1 font-medium text-accent-cyan hover:underline"
          >
            {isRegister ? '去登录' : '去注册'}
          </button>
        </p>
      </div>
    </div>
  );
}
