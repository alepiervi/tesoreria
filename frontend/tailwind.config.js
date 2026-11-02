/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,jsx}", "./public/index.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Instrument Sans'", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: "#15171C",
        muted: "#5B6170",
        line: "#E3E5E8",
        soft: "#EEF0F2",
        page: "#F5F6F4",
        side: { DEFAULT: "#15171C", hover: "#23262E", active: "#2B2F39", text: "#C3C8D2" },
        accent: { DEFAULT: "#2346D8", dark: "#16309E", soft: "#EAEEFC", mid: "#8FA2EE" },
        warn: { DEFAULT: "#E8772E", text: "#8A3A0B", dark: "#6E2F08", soft: "#FBEEE5", amount: "#A8480F" },
      },
    },
  },
  plugins: [],
};
