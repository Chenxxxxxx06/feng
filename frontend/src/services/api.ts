import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// Track if we've already redirected to login (prevent redirect loops)
let redirectingToLogin = false;

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
    if (typeof config.headers.delete === 'function') {
      config.headers.delete('Content-Type');
    } else {
      delete (config.headers as Record<string, unknown>)['Content-Type'];
    }
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status;

    // Only redirect to login on 401 if:
    // 1. We're NOT already on the login page
    // 2. We haven't already triggered a redirect
    // 3. The failed request was NOT a login attempt itself
    if (status === 401) {
      const isLoginPage = window.location.pathname === '/login';
      const isLoginAttempt = err.config?.url?.includes('/auth/login');
      const isRegisterAttempt = err.config?.url?.includes('/auth/register');

      if (!isLoginPage && !isLoginAttempt && !isRegisterAttempt && !redirectingToLogin) {
        redirectingToLogin = true;
        localStorage.removeItem('token');
        localStorage.removeItem('user');

        // Use replace to avoid back-button returning to broken state
        window.location.replace('/login');

        // Never resolve — we're navigating away
        return new Promise(() => {});
      }
    }

    return Promise.reject(err);
  },
);

// Reset redirect flag when arriving at login page (user had chance to re-auth)
if (typeof window !== 'undefined') {
  const originalPath = window.location.pathname;
  if (originalPath === '/login') {
    redirectingToLogin = false;
  }
}

export default api;
