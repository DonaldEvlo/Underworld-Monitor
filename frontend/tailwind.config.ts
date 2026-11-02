import type { Config } from "tailwindcss";

// Design system "Pulse" — un centre d'operations qui ausculte le dark web
// comme un moniteur vital ausculte un patient : signal continu, alerte nette
// quand quelque chose devie. Bleu-nuit profond + accent phosphorescent
// vert-cyan (trace d'oscilloscope), rampe semantique separee de l'accent.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Fond / surfaces -- bleu-nuit, plus froid et plus profond que
        // l'ancien graphite neutre.
        void: "#070b10",
        panel: "#0f151d",
        "panel-raised": "#161f29",
        "panel-sunken": "#04070a",
        line: "#213040",
        "line-soft": "#161f29",

        // Texte -- blanc legerement teinte vert-froid, coherent avec l'accent.
        ink: "#dce9e4",
        "ink-dim": "#7d92a0",
        // ⚠️ Était #4d5f6d : 2,5 à 3:1 sur les fonds, sous le minimum WCAG AA
        // (4,5:1), pour 174 textes souvent en 10 px — illisible au projecteur.
        // #748a9a : 5,1 (panel), 5,6 (sunken), 4,6 (raised), et reste sous
        // ink-dim (5,7) pour garder la hiérarchie. Mesuré le 2026-10-01.
        "ink-faint": "#748a9a",

        // Accent de marque -- vert-cyan phosphorescent, trace d'oscilloscope.
        // Utilise avec parcimonie (nav actif, CTA primaire, pouls des donnees
        // vivantes). Jamais pour du statut generique.
        signal: "#3ee8b8",
        "signal-dim": "#2bb18c",
        "signal-glow": "#3ee8b8",
        "on-signal": "#04140f",

        // Rampe semantique -- separee de l'accent, jamais melangee.
        ok: "#3ee8b8",
        "ok-dim": "#0f4a3b",
        warn: "#f5c451",
        "warn-dim": "#5c4408",
        critical: "#ff4d6a",
        "critical-dim": "#5c1225",
        info: "#5ec8f0",
        "info-dim": "#123a4d",

        // Alias retro-compatibles (composants pas encore migres) --
        // mappent vers le nouveau systeme pour eviter une refonte "big bang"
        // qui casse tout d'un coup.
        background: "#070b10",
        "on-background": "#dce9e4",
        surface: "#0f151d",
        "surface-dim": "#070b10",
        "surface-bright": "#161f29",
        "surface-container-lowest": "#04070a",
        "surface-container-low": "#0c121a",
        "surface-container": "#0f151d",
        "surface-container-high": "#161f29",
        "surface-container-highest": "#1c2733",
        "surface-variant": "#161f29",
        "on-surface": "#dce9e4",
        "on-surface-variant": "#7d92a0",
        outline: "#3d5064",
        "outline-variant": "#213040",
        primary: "#3ee8b8",
        "on-primary": "#04140f",
        "primary-container": "#2bb18c",
        "on-primary-container": "#d3fbef",
        secondary: "#7d92a0",
        "on-secondary": "#0f151d",
        tertiary: "#5ec8f0",
        "on-tertiary": "#04202e",
        error: "#ff4d6a",
        "on-error": "#2b0810",
        "error-container": "#5c1225",
        "on-error-container": "#ffd9de",
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        display: ["Space Grotesk", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
        caption: ["Inter"],
        "body-md": ["Inter"],
        "body-sm": ["Inter"],
        "headline-md": ["Space Grotesk"],
        "headline-lg": ["Space Grotesk"],
        "mono-data": ["JetBrains Mono"],
        "mono-label": ["JetBrains Mono"],
      },
      fontSize: {
        "headline-xl": ["34px", { lineHeight: "38px", letterSpacing: "-0.02em", fontWeight: "700" }],
        "headline-lg": ["24px", { lineHeight: "30px", letterSpacing: "-0.015em", fontWeight: "700" }],
        "headline-md": ["17px", { lineHeight: "23px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "body-md": ["14px", { lineHeight: "21px", fontWeight: "400" }],
        "body-sm": ["12.5px", { lineHeight: "18px", fontWeight: "400" }],
        "mono-label": ["12px", { lineHeight: "16px", letterSpacing: "0.01em", fontWeight: "500" }],
        "mono-data": ["12px", { lineHeight: "18px", fontWeight: "400" }],
        caption: ["10.5px", { lineHeight: "14px", letterSpacing: "0.08em", fontWeight: "600" }],
        // Échelle de TAILLES SEULES (sans interlignage ni graisse), pour les
        // 580 `text-[Npx]` qui étaient écrits en dur dans les composants
        // (2026-10-01). Les valeurs sont celles qui étaient utilisées : le rendu
        // est inchangé, mais l'ensemble des tailles est désormais déclaré ICI.
        // Ajouter une taille = l'ajouter à cette liste, pas l'inventer en place.
        "9": "9px",
        "9.5": "9.5px",
        "10": "10px",
        "10.5": "10.5px",
        "11": "11px",
        "11.5": "11.5px",
        "12": "12px",
        "13": "13px",
        "14": "14px",
        "15": "15px",
        "16": "16px",
        "17": "17px",
        "18": "18px",
        "19": "19px",
        "20": "20px",
        "22": "22px",
        "24": "24px",
        "26": "26px",
        "28": "28px",
        "30": "30px",
        "32": "32px",
        "38": "38px",
        "40": "40px",
      },
      borderRadius: {
        sm: "6px",
        DEFAULT: "10px",
        md: "12px",
        lg: "16px",
        xl: "22px",
        full: "9999px",
      },
      boxShadow: {
        panel: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -8px rgba(0,0,0,0.5)",
        raised: "0 2px 4px rgba(0,0,0,0.5), 0 16px 40px -12px rgba(0,0,0,0.6)",
        "signal-glow": "0 0 0 1px rgba(62,232,184,0.3), 0 0 24px -4px rgba(62,232,184,0.4)",
      },
      spacing: {
        unit: "4px",
        "container-padding": "20px",
        gutter: "12px",
      },
    },
  },
  plugins: [],
} satisfies Config;
