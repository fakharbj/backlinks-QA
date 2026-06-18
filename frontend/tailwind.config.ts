import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#18202b",
        muted: "#667085",
        panel: "#ffffff",
        line: "#d8dee8",
        field: "#f5f7fa",
        ocean: "#0f766e",
        plum: "#6d28d9",
        ember: "#b45309",
        danger: "#b42318"
      },
      boxShadow: {
        focus: "0 0 0 3px rgba(15, 118, 110, .16)"
      }
    }
  },
  plugins: []
};

export default config;
