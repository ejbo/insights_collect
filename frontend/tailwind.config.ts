import type { Config } from "tailwindcss";

// Apple design tokens — see Skills/DESIGN-apple.md and CLAUDE.md.
// Do not inline hex values in components. If a token is missing, add it here.

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Brand & accent
        primary: {
          DEFAULT: "#0066cc",        // Action Blue
          focus: "#0071e3",          // Focus ring
          "on-dark": "#2997ff",      // Sky Link Blue
        },

        // Surface
        canvas: "#ffffff",
        parchment: "#f5f5f7",
        pearl: "#fafafc",
        tile: {
          DEFAULT: "#272729",
          2: "#2a2a2c",
          3: "#252527",
        },
        void: "#000000",
        chip: "#d2d2d7",

        // Text
        ink: {
          DEFAULT: "#1d1d1f",
          "muted-80": "#333333",
          "muted-48": "#7a7a7a",
        },
        "body-on-dark": "#ffffff",
        "body-muted": "#cccccc",

        // Hairlines
        "divider-soft": "#f0f0f0",
        hairline: "#e0e0e0",

        // Status (muted, low-saturation — see CLAUDE.md)
        status: {
          success: "#1d8a5b",
          danger: "#b3261e",
        },
      },

      fontFamily: {
        display:
          "'SF Pro Display', system-ui, -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif",
        text:
          "'SF Pro Text', system-ui, -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif",
        mono: "'SF Mono', ui-monospace, Menlo, monospace",
      },

      fontSize: {
        // [size, { lineHeight, letterSpacing, fontWeight }]
        "hero-display": ["56px", { lineHeight: "1.07", letterSpacing: "-0.28px", fontWeight: "600" }],
        "display-lg":   ["40px", { lineHeight: "1.10", letterSpacing: "0",        fontWeight: "600" }],
        "display-md":   ["34px", { lineHeight: "1.47", letterSpacing: "-0.374px", fontWeight: "600" }],
        lead:           ["28px", { lineHeight: "1.14", letterSpacing: "0.196px",  fontWeight: "400" }],
        "lead-airy":    ["24px", { lineHeight: "1.5",  letterSpacing: "0",        fontWeight: "300" }],
        tagline:        ["21px", { lineHeight: "1.19", letterSpacing: "0.231px",  fontWeight: "600" }],
        "body-strong":  ["17px", { lineHeight: "1.24", letterSpacing: "-0.374px", fontWeight: "600" }],
        body:           ["17px", { lineHeight: "1.47", letterSpacing: "-0.374px", fontWeight: "400" }],
        "dense-link":   ["17px", { lineHeight: "2.41", letterSpacing: "0",        fontWeight: "400" }],
        caption:        ["14px", { lineHeight: "1.43", letterSpacing: "-0.224px", fontWeight: "400" }],
        "caption-strong":["14px",{ lineHeight: "1.29", letterSpacing: "-0.224px", fontWeight: "600" }],
        "button-large": ["18px", { lineHeight: "1.0",  letterSpacing: "0",        fontWeight: "300" }],
        "button-utility":["14px",{ lineHeight: "1.29", letterSpacing: "-0.224px", fontWeight: "400" }],
        "fine-print":   ["12px", { lineHeight: "1.0",  letterSpacing: "-0.12px",  fontWeight: "400" }],
        "micro-legal":  ["10px", { lineHeight: "1.3",  letterSpacing: "-0.08px",  fontWeight: "400" }],
        "nav-link":     ["12px", { lineHeight: "1.0",  letterSpacing: "-0.12px",  fontWeight: "400" }],
      },

      spacing: {
        xxs: "4px",
        xs: "8px",
        sm: "12px",
        md: "17px",
        lg: "24px",
        xl: "32px",
        xxl: "48px",
        section: "80px",
      },

      borderRadius: {
        none: "0",
        xs: "5px",
        sm: "8px",
        md: "11px",
        lg: "18px",
        "tile-lg": "18px",
        pill: "9999px",
      },

      boxShadow: {
        // The single sanctioned shadow — for product imagery only.
        product: "rgba(0, 0, 0, 0.22) 3px 5px 30px 0",
      },

      backdropBlur: {
        frosted: "20px",
      },

      maxWidth: {
        text: "980px",
        grid: "1440px",
      },
    },
  },
  plugins: [],
};

export default config;
