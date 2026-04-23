/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#00C2FF', // Updated to match AI Assistant
        'background-light': '#f5f8f8',
        'background-dark': '#0f1e23',
        'surface-dark': '#162B32',
        'surface-light': '#FFFFFF',
        'text-dark-primary': '#FFFFFF',
        'text-dark-secondary': '#94A3B8',
        'text-light-primary': '#0F172A',
        'text-light-secondary': '#64748B',
        'border-dark': '#334155',
        'border-light': '#E2E8F0',
        'status-green': '#00C853',
        'status-yellow': '#FFAB00',
        'status-red': '#D50000',
        'action-blue': '#2962FF',
      },
      fontFamily: {
        display: ['Inter', 'sans-serif'],
      },
      borderRadius: {
        DEFAULT: '0.25rem',
        lg: '0.5rem',
        xl: '0.75rem',
        full: '9999px',
      },
    },
  },
  plugins: [],
}


