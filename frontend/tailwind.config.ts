import type { Config } from "tailwindcss";

// Tokens resolve to CSS variables (space-separated RGB channels) so the whole UI
// re-themes for light/dark while keeping Tailwind's `/<alpha>` opacity modifiers.
const tok = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: tok("--ink"),
        muted: tok("--muted"),
        panel: tok("--panel"),
        panel2: tok("--panel2"),
        line: tok("--line"),
        field: tok("--field"),
        ocean: tok("--ocean"),
        plum: tok("--plum"),
        ember: tok("--ember"),
        danger: tok("--danger"),
        accent: tok("--accent")
      },
      borderRadius: {
        lg: "0.6rem",
        xl: "0.85rem",
        "2xl": "1.1rem"
      },
      boxShadow: {
        focus: "0 0 0 3px rgb(var(--ocean) / 0.18)",
        card: "0 1px 2px rgb(var(--shadow) / 0.05), 0 1px 3px rgb(var(--shadow) / 0.06)",
        soft: "0 6px 22px -8px rgb(var(--shadow) / 0.14)",
        pop: "0 16px 40px -12px rgb(var(--shadow) / 0.28)"
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"]
      }
    }
  },
  plugins: []
};

export default config;
