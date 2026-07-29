/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#071A35',
          900: '#0A1F3F',
          800: '#0D2447',
          700: '#102A43',
          600: '#15325A',
        },
        electric: {
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
        },
        cyan: {
          400: '#22D3EE',
          500: '#06B6D4',
        },
        success: {
          DEFAULT: '#10B981',
          soft: 'rgba(16,185,129,0.12)',
        },
        warning: {
          DEFAULT: '#F59E0B',
          soft: 'rgba(245,158,11,0.12)',
        },
        danger: {
          DEFAULT: '#EF4444',
          soft: 'rgba(239,68,68,0.12)',
        },
        orange: {
          DEFAULT: '#F97316',
          soft: 'rgba(249,115,22,0.12)',
        },
        text: {
          primary: '#F1F5F9',
          secondary: '#94A3B8',
          // 与 global.css 的 --text-muted 保持一致（对比度 5.1:1，满足 WCAG AA）
          muted: '#7C8CA5',
        },
        bg: {
          primary: '#071A35',
          secondary: '#0A1F3F',
          card: '#0D2447',
          elevated: '#102A43',
          hover: 'rgba(59,130,246,0.08)',
          active: 'rgba(59,130,246,0.14)',
          deep: '#071A35',
        },
        accent: {
          blue: '#3B82F6',
          cyan: '#22D3EE',
          green: '#10B981',
          yellow: '#F59E0B',
          orange: '#F97316',
          red: '#EF4444',
          purple: '#8B5CF6',
        },
        border: {
          subtle: 'rgba(59,130,246,0.08)',
          default: 'rgba(59,130,246,0.12)',
          active: 'rgba(59,130,246,0.30)',
          glow: 'rgba(59,130,246,0.45)',
        },
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '24px',
      },
      boxShadow: {
        'card': '0 1px 3px rgba(0,0,0,0.3), 0 2px 8px rgba(59,130,246,0.06)',
        'card-hover': '0 4px 16px rgba(0,0,0,0.4), 0 2px 12px rgba(59,130,246,0.12)',
        'card-lg': '0 4px 24px rgba(0,0,0,0.5), 0 0 40px rgba(59,130,246,0.06)',
        'glow-blue': '0 0 20px rgba(59,130,246,0.25)',
        'glow-cyan': '0 0 16px rgba(34,211,238,0.2)',
        'glow-red': '0 0 16px rgba(239,68,68,0.2)',
        'glow-green': '0 0 16px rgba(16,185,129,0.2)',
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', '-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Microsoft YaHei"', '"Helvetica Neue"', 'sans-serif'],
        mono: ['"SF Mono"', '"JetBrains Mono"', '"Fira Code"', '"Consolas"', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulseSlow 3s ease-in-out infinite',
        'pulse-alert': 'pulseAlert 2s ease-in-out infinite',
        'spin-slow': 'spin 8s linear infinite',
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'glow': 'glow 3s ease-in-out infinite',
      },
      keyframes: {
        pulseSlow: { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.6' } },
        pulseAlert: { '0%, 100%': { boxShadow: '0 0 4px rgba(239,68,68,0.4)' }, '50%': { boxShadow: '0 0 16px rgba(239,68,68,0.8)' } },
        fadeIn: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(12px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        glow: { '0%, 100%': { filter: 'brightness(1)' }, '50%': { filter: 'brightness(1.15)' } },
      },
    },
  },
  plugins: [],
};
