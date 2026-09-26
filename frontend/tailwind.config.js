/** @type {import('tailwindcss').Config} */
// `brand` is driven by CSS variables (src/index.css) so the whole UI re-themes
// per client sector (business / school / hospital) from the vendor-locked
// client profile -- see src/profile/ProfileContext.tsx.
const brand = Object.fromEntries(
  [50, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((step) => [step, `rgb(var(--brand-${step}) / <alpha-value>)`]),
);

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: { brand },
    },
  },
  plugins: [],
};
