/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: { primary: '#0a0e14', secondary: '#12161e', card: '#161c26', hover: '#1c2433' },
        border: { default: '#1e2a3a', active: '#2d4a6e' },
        text: { primary: '#e6edf3', secondary: '#8b949e', muted: '#5c6975' },
        accent: { blue: '#58a6ff', green: '#3fb950', yellow: '#d29922', red: '#f85149', cyan: '#39d2c0', purple: '#a371f7' },
      },
    },
  },
  plugins: [],
};
