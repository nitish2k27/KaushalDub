import type { Config } from "tailwindcss";

// Colours are the mockup's design tokens (CSS variables in src/styles/index.css), so light/dark themes
// switch by changing the variables only.
const v = (name: string) => `var(--${name})`;
export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), ink: v("ink"), muted: v("muted"), line: v("line"),
        brand: { DEFAULT: v("brand"), ink: v("brand-ink"), soft: v("brand-soft") },
        accent: { DEFAULT: v("accent"), soft: v("accent-soft") },
        good: { DEFAULT: v("good"), soft: v("good-soft") },
        bad: { DEFAULT: v("bad"), soft: v("bad-soft") },
        vid: v("vid"),
      },
      fontFamily: { display: v("f-display"), body: v("f-body") },
      borderRadius: { card: "12px" },
    },
  },
  plugins: [],
} satisfies Config;
