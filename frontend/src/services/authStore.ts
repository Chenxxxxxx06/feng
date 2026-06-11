import { create } from 'zustand';
import api from './api';

interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  api_key: string | null;
  api_provider: string | null;
  model_preference: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  initialized: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchMe: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('token'),
  user: null,
  initialized: false,
  loading: false,

  login: async (username, password) => {
    set({ loading: true });
    try {
      const { data } = await api.post('/auth/login', { username, password });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      set({ token: data.access_token, user: data.user, initialized: true });
    } finally {
      set({ loading: false });
    }
  },

  register: async (username, email, password) => {
    set({ loading: true });
    try {
      const { data } = await api.post('/auth/register', { username, email, password });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('user', JSON.stringify(data.user));
      set({ token: data.access_token, user: data.user, initialized: true });
    } finally {
      set({ loading: false });
    }
  },

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    set({ token: null, user: null, initialized: true });
  },

  fetchMe: async () => {
    try {
      const { data } = await api.get('/auth/me');
      localStorage.setItem('user', JSON.stringify(data));
      set({ user: data, initialized: true });
    } catch {
      // Token invalid — clear and redirect handled by api interceptor
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      set({ token: null, user: null, initialized: true });
    }
  },
}));
