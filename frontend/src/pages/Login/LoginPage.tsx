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
      className="h-screen flex items-center justify-center bg-bg-primary"
      style={{
        backgroundImage: 'radial-gradient(circle at 22% 18%, rgba(59, 130, 246, 0.28), transparent 32%), radial-gradient(circle at 80% 72%, rgba(34, 211, 238, 0.18), transparent 30%), linear-gradient(120deg, #071A35 0%, #0A1F3F 56%, #061225 100%)',
        backgroundPosition: 'center',
        backgroundSize: 'cover',
      }}
    >
      <div className="w-96 p-8 ops-panel shadow-2xl">
        <div className="text-center mb-8">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-accent-blue/20 text-sm font-bold text-accent-cyan shadow-glow-blue">PHM</div>
          <h1 className="text-xl font-bold mt-3 tracking-wider gradient-text">风调预顺</h1>
          <p className="text-text-muted text-xs mt-1">PHM预测性运维系统</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <input
              type="text"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2.5 text-sm text-text-primary"
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
                className="w-full px-3 py-2.5 text-sm text-text-primary"
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
              className="w-full px-3 py-2.5 text-sm text-text-primary"
              required
            />
          </div>

          {error && <p className="text-accent-red text-xs">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="ops-btn ops-btn-primary w-full py-2.5 text-sm disabled:opacity-50"
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
