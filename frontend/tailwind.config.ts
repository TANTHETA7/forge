import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        forge: {
          bg: "#050505",
          sidebar: "#090909",
          topbar: "#060606",
          search: "#0b0b0b",
          panel: "#0d0d0d",
          card: "#0d0d0d",
          "card-hover": "#141414",
          elevated: "#151515",
          border: "#1c1c1c",
          "border-subtle": "#151515",
          "border-focus": "#f97316",
          accent: "#f97316",
          "accent-hover": "#ea580c",
          "accent-subtle": "rgba(249, 115, 22, 0.10)",
          "text-primary": "#f5f5f5",
          "text-secondary": "#a0a0a0",
          "text-muted": "#666666",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
