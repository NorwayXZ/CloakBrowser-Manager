import type { Config } from "tailwindcss";

// Every color, radius, shadow and type size of the redesigned panel comes from
// the tokens in src/next/design/tokens.css. Pages never use raw palette colors.
const token = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ["./next/index.html", "./src/next/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      canvas: token("canvas"),
      surface: { DEFAULT: token("surface"), 2: token("surface-2"), 3: token("surface-3") },
      border: { DEFAULT: token("border"), strong: token("border-strong") },
      fg: { DEFAULT: token("fg"), 2: token("fg-2"), 3: token("fg-3") },
      accent: { DEFAULT: token("accent"), hover: token("accent-hover"), soft: token("accent-soft"), on: token("on-accent") },
      success: { DEFAULT: token("success"), soft: token("success-soft") },
      warning: { DEFAULT: token("warning"), soft: token("warning-soft") },
      danger: { DEFAULT: token("danger"), hover: token("danger-hover"), soft: token("danger-soft"), on: token("on-danger") },
      info: { DEFAULT: token("info"), soft: token("info-soft") },
      backdrop: token("backdrop"),
    },
    fontFamily: {
      sans: ["var(--font-sans)"],
      mono: ["var(--font-mono)"],
    },
    fontSize: {
      xs: ["12px", { lineHeight: "16px" }],
      sm: ["13px", { lineHeight: "20px" }],
      base: ["14px", { lineHeight: "22px" }],
      md: ["16px", { lineHeight: "24px" }],
      lg: ["20px", { lineHeight: "28px" }],
      xl: ["24px", { lineHeight: "32px" }],
    },
    fontWeight: { normal: "400", medium: "500", semibold: "600" },
    borderRadius: {
      none: "0",
      sm: "4px",
      DEFAULT: "6px",
      md: "8px",
      lg: "12px",
      full: "9999px",
    },
    boxShadow: {
      none: "none",
      raised: "var(--shadow-raised)",
      popover: "var(--shadow-popover)",
      modal: "var(--shadow-modal)",
    },
    extend: {
      spacing: { sidebar: "224px", "sidebar-collapsed": "56px", toolbar: "52px", drawer: "380px" },
      transitionDuration: { fast: "120ms", base: "200ms" },
      maxWidth: { form: "880px" },
      ringColor: { DEFAULT: token("accent") },
    },
  },
  plugins: [],
} satisfies Config;
