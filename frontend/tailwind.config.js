/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        void: {
          deep: '#020204',
          base: '#0A0C10',
          elevated: '#11141C',
          card: '#161922',
        },
        neon: {
          cyan: '#00E5FF',
          'cyan-dim': 'rgba(0,229,255,0.08)',
          'cyan-glow': 'rgba(0,229,255,0.25)',
          blue: '#2979FF',
          'blue-dim': 'rgba(41,121,255,0.08)',
          amber: '#FF9100',
          'amber-dim': 'rgba(255,145,0,0.08)',
          red: '#FF1744',
          'red-dim': 'rgba(255,23,68,0.08)',
          green: '#00E676',
          'green-dim': 'rgba(0,230,118,0.08)',
        },
        border: {
          hud: 'rgba(0,229,255,0.12)',
          'hud-strong': 'rgba(0,229,255,0.25)',
          subtle: 'rgba(255,255,255,0.06)',
        },
        text: {
          pri: '#E8ECF1',
          sec: '#8899AA',
          dim: '#445566',
        },
      },
      fontFamily: {
        display: ['"Rajdhani"', '"PingFang SC"', 'sans-serif'],
        body: ['"Inter"', '"PingFang SC"', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'monospace'],
      },
      fontSize: {
        'kpi': ['3rem', { lineHeight: '1', fontWeight: '600', letterSpacing: '0.02em' }],
        'kpi-sm': ['2rem', { lineHeight: '1', fontWeight: '600', letterSpacing: '0.02em' }],
      },
    },
  },
  plugins: [],
};
