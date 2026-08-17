import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: {
          0: "#f5f7fb",
          1: "#ffffff",
          2: "#f8fafc",
          3: "#eef2ff",
          4: "#e2e8f0",
        },
        border: {
          DEFAULT: "#e2e8f0",
          hover: "#cbd5e1",
        },
        accent: {
          DEFAULT: "#2f5bff",
          hover: "#1f4be0",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
