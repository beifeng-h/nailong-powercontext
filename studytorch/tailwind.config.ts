import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef4ff",
          100: "#dbe6ff",
          200: "#bed2ff",
          300: "#93b4ff",
          400: "#6b8eff",
          500: "#4a63f5",
          600: "#3547e0",
          700: "#2c38b8",
          800: "#293294",
          900: "#262f75",
        },
      },
    },
  },
  plugins: [],
};

export default config;
