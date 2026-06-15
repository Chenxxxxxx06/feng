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
      className="h-screen flex items-center justify-center"
      style={{
        backgroundImage: 'url(/fengmian.png)',
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
      }}
    >
      <div className="w-96 p-8 rounded-lg border border-border-default bg-bg-card glow-card">
        <div className="text-center mb-8">
          <span className="text-4xl text-accent-cyan">⟳</span>
          <h1 className="text-xl font-bold mt-2 tracking-wider">风调预顺</h1>
          <p className="text-text-muted text-xs mt-1">PHM预测性运维系统</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="text"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2.5 bg-bg-secondary border border-border-default rounded text-sm text-text-primary focus:outline-none focus:border-accent-blue transition-colors"
              required
            />
          </div>
          {isRegister && (
            <div>
              <input
                type="email"
                placeholder="邮箱"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2.5 bg-bg-secondary border border-border-default rounded text-sm text-text-primary focus:outline-none focus:border-accent-blue transition-colors"
                required
              />
            </div>
          )}
          <div>
            <input
              type="password"
              placeholder="密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2.5 bg-bg-secondary border border-border-default rounded text-sm text-text-primary focus:outline-none focus:border-accent-blue transition-colors"
              required
            />
          </div>

          {error && <p className="text-accent-red text-xs">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-accent-blue text-white rounded font-medium text-sm hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? '处理中...' : isRegister ? '注册' : '登录'}
          </button>
        </form>

        <p className="text-center mt-4 text-xs text-text-muted">
          {isRegister ? '已有账号？' : '没有账号？'}
          <button
            onClick={() => setIsRegister(!isRegister)}
            className="ml-1 text-accent-blue hover:underline"
          >
            {isRegister ? '去登录' : '去注册'}
          </button>
        </p>
      </div>
    </div>
  );
}
