/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Archivo', 'system-ui', 'sans-serif'],
        body: ['Archivo', 'system-ui', 'sans-serif'],
        serif: ['"Instrument Serif"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        surface: {
          DEFAULT: 'rgb(var(--c-bg) / <alpha-value>)',
          card: 'rgb(var(--c-panel) / <alpha-value>)',
          elevated: 'rgb(var(--c-panel-2) / <alpha-value>)',
          hover: 'rgb(var(--c-hover) / <alpha-value>)',
        },
        border: {
          DEFAULT: 'rgb(var(--c-line) / <alpha-value>)',
          subtle: 'rgb(var(--c-line-subtle) / <alpha-value>)',
        },
        ink: {
          DEFAULT: 'rgb(var(--c-ink) / <alpha-value>)',
          dim: 'rgb(var(--c-ink-dim) / <alpha-value>)',
          faint: 'rgb(var(--c-ink-faint) / <alpha-value>)',
        },
        accent: {
          DEFAULT: 'rgb(var(--c-amber) / <alpha-value>)',
          secondary: 'rgb(var(--c-teal) / <alpha-value>)',
          muted: 'rgb(var(--c-amber-dim) / <alpha-value>)',
        },
        teal: 'rgb(var(--c-teal) / <alpha-value>)',
        danger: 'rgb(var(--c-danger) / <alpha-value>)',
        ok: 'rgb(var(--c-ok) / <alpha-value>)',
        warn: 'rgb(var(--c-warn) / <alpha-value>)',
        tag: {
          pink: 'rgb(var(--c-tag-pink) / <alpha-value>)',
          blue: 'rgb(var(--c-tag-blue) / <alpha-value>)',
          purple: 'rgb(var(--c-tag-purple) / <alpha-value>)',
        },
        studio: {
          teal: 'rgb(var(--c-teal) / <alpha-value>)',
          sky: 'rgb(var(--c-tag-blue) / <alpha-value>)',
          indigo: 'rgb(var(--c-tag-purple) / <alpha-value>)',
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.4s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
        'scale-in': 'scaleIn 0.2s ease-out',
        'rise': 'rise 0.5s cubic-bezier(0.22, 1, 0.36, 1) both',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideDown: {
          '0%': { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseGlow: {
          '0%, 100%': { boxShadow: '0 0 8px rgba(255, 180, 84, 0.18)' },
          '50%': { boxShadow: '0 0 22px rgba(255, 180, 84, 0.38)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        rise: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}
