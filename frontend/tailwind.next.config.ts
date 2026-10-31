import type { Config } from "tailwindcss";

// Every color, radius, shadow and type size of the redesigned panel comes from
// the tokens in src/next/design/tokens.css. Pages never use raw palette colors.
const token = (name: string) => `rgb(var(--c-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/next/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      canvas: token("canvas"),
      sidebar: token("sidebar"),
      surface: { DEFAULT: token("surface"), 2: token("surface-2"), 3: token("surface-3") },
      border: { DEFAULT: token("border"), strong: token("border-strong") },
      fg: { DEFAULT: token("fg"), 2: token("fg-2"), 3: token("fg-3") },
      accent: {
        DEFAULT: token("accent"),
        hover: token("accent-hover"),
        fill: token("accent-fill"),
        "fill-2": token("accent-fill-2"),
        "fill-hover": token("accent-fill-hover"),
        soft: token("accent-soft"),
        on: token("on-accent"),
      },
      "switch-on": token("switch-on"),
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
      xs: ["12.5px", { lineHeight: "17px" }],
      sm: ["14px", { lineHeight: "21px" }],
      base: ["15px", { lineHeight: "23px" }],
      md: ["17px", { lineHeight: "25px" }],
      lg: ["22px", { lineHeight: "29px" }],
      xl: ["34px", { lineHeight: "40px" }],
    },
    fontWeight: { normal: "400", medium: "500", semibold: "600", bold: "700" },
    borderRadius: {
      none: "0",
      sm: "6px",
      DEFAULT: "12px",
      md: "16px",
      lg: "22px",
      xl: "28px",
      full: "9999px",
    },
    boxShadow: {
      none: "none",
      raised: "var(--shadow-raised)",
      card: "var(--shadow-card)",
      popover: "var(--shadow-popover)",
      modal: "var(--shadow-modal)",
    },
    extend: {
      spacing: { sidebar: "224px", "sidebar-collapsed": "56px", toolbar: "52px", drawer: "380px" },
      transitionDuration: { fast: "150ms", base: "250ms" },
      transitionTimingFunction: { DEFAULT: "cubic-bezier(0.25, 0.1, 0.25, 1)" },
      maxWidth: { form: "880px" },
      ringColor: { DEFAULT: token("accent") },
    },
  },
  plugins: [],
} satisfies Config;
