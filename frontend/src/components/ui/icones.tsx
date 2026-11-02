import type { ReactElement } from "react";

/** Jeu d'icones EMBARQUE, dessine au trait sur une grille de 24.
 *
 * ⚠️ POURQUOI CE FICHIER EXISTE. Les icones venaient de « Material Symbols
 * Outlined », charge par un `<link>` vers fonts.googleapis.com. Quand cette
 * feuille de style n'arrive pas — poste hors ligne, proxy d'entreprise, reseau
 * filtre —, le navigateur n'a plus de glyphe et affiche LE NOM DE L'ICONE EN
 * TOUTES LETTRES : « shield_person », « delete_forever », « account_circle ».
 * Constate en conditions reelles. L'interface d'un outil de veille ne peut pas
 * dependre d'un tiers pour rester lisible, et le projet embarque deja ses
 * trois polices de texte dans `public/fonts` : les icones etaient la seule
 * dependance distante qui restait.
 *
 * Style unique : trait de 1,7, extremites et jonctions arrondies, aucune
 * surface pleine — coherent avec la marque « la faille ».
 */
export const ICONES: Record<string, ReactElement> = {
  arrow_downward: <path d="M12 4.6v14.8M6.4 13.8L12 19.4l5.6-5.6" />,
  arrow_upward: <path d="M12 19.4V4.6M6.4 10.2L12 4.6l5.6 5.6" />,
  bolt: <path d="M13.6 2.6L5.4 13.6h5.2l-1 7.8 8-11h-5.2z" />,
  cancel: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" />
    </>
  ),
  edit_calendar: (
    <>
      <rect x="3.4" y="5.4" width="13.4" height="14.4" rx="2" />
      <path d="M3.4 10h13.4M7.4 3.4v4M12.8 3.4v4" />
      <path d="M14.6 19.8l4.6-4.6 1.6 1.6-4.6 4.6h-1.6z" />
    </>
  ),
  expand_less: <path d="M6.4 14.6L12 9l5.6 5.6" />,
  expand_more: <path d="M6.4 9.4L12 15l5.6-5.6" />,
  more_time: (
    <>
      <circle cx="10.4" cy="13.2" r="7" />
      <path d="M10.4 9.4v3.8h3" />
      <path d="M18.6 4.4v5M16.1 6.9h5" />
    </>
  ),
  network_check: (
    <>
      <path d="M2.8 11a13 13 0 0 1 18.4 0" />
      <path d="M6.2 14.4a8.2 8.2 0 0 1 11.6 0" />
      <path d="M9.6 17.8a3.4 3.4 0 0 1 4.8 0" />
      <path d="M12 20.6v.2" />
    </>
  ),
  pause: <path d="M9.4 5.4v13.2M14.6 5.4v13.2" />,
  picture_as_pdf: (
    <>
      <path d="M7 3.2h7l5 5v12.6H7z" />
      <path d="M14 3.2v5h5" />
      <path d="M9.6 17.6v-4.8h1.5a1.4 1.4 0 0 1 0 2.8H9.6" />
      <path d="M13.8 12.8v4.8h1.1a1.6 1.6 0 0 0 1.6-1.6v-1.6a1.6 1.6 0 0 0-1.6-1.6z" />
    </>
  ),
  play_arrow: <path d="M7.6 4.8l11 7.2-11 7.2z" />,
  psychology: (
    <>
      <path d="M14.8 20.6v-2.7h1.9a1.5 1.5 0 0 0 1.5-1.5v-2.1h1.8l-2.2-4a7.1 7.1 0 1 0-9.9 7v3.3z" />
      <circle cx="12" cy="10.2" r="2.2" />
    </>
  ),
  search_insights: (
    <>
      <circle cx="10.4" cy="10.4" r="6.2" />
      <path d="M15 15l5.4 5.4" />
      <path d="M8.4 12.4v-2M10.4 12.4v-4M12.4 12.4v-2.8" />
    </>
  ),
  toggle_off: (
    <>
      <rect x="2.6" y="7.4" width="18.8" height="9.2" rx="4.6" />
      <circle cx="7.6" cy="12" r="2.7" />
    </>
  ),
  toggle_on: (
    <>
      <rect x="2.6" y="7.4" width="18.8" height="9.2" rx="4.6" />
      <circle cx="16.4" cy="12" r="2.7" />
    </>
  ),
  account_circle: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <circle cx="12" cy="10" r="2.9" />
      <path d="M6.2 19.1a6.6 6.6 0 0 1 11.6 0" />
    </>
  ),
  add: <path d="M12 5v14M5 12h14" />,
  add_circle: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 8.2v7.6M8.2 12h7.6" />
    </>
  ),
  auto_awesome: (
    <>
      <path d="M11 3.2l1.7 4.4 4.4 1.7-4.4 1.7-1.7 4.4-1.7-4.4L4.9 9.3l4.4-1.7z" />
      <path d="M18 15.2l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
    </>
  ),
  check: <path d="M4.8 12.6l4.8 4.8L19.4 6.6" />,
  content_copy: (
    <>
      <rect x="8.4" y="8.4" width="11.2" height="11.2" rx="2" />
      <path d="M15.6 8.4V6.4a2 2 0 0 0-2-2H6.4a2 2 0 0 0-2 2v7.2a2 2 0 0 0 2 2h2" />
    </>
  ),
  check_circle: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M8.1 12.2l2.7 2.7 5.3-5.6" />
    </>
  ),
  chevron_left: <path d="M14.8 5.6L8.4 12l6.4 6.4" />,
  chevron_right: <path d="M9.2 5.6L15.6 12l-6.4 6.4" />,
  // Panneau lateral : cadre + rail gauche, plus un chevron qui indique le SENS
  // de l'action. Dessinees ensemble pour rester symetriques.
  //
  // ⚠️ `chevron_left` MANQUAIT au jeu embarque alors qu'il etait appele : le
  // composant `Icon` rend alors `null` (par conception, pour ne jamais
  // afficher le nom brut de l'icone). Le bouton de repli etait donc SANS
  // icone en mode deploye, sans aucune erreur -- seulement un avertissement
  // console en developpement. C'est exactement le « trou silencieux » que la
  // docstring d'`Icon` annonce ; verifier qu'un nom existe avant de l'appeler.
  left_panel_close: (
    <>
      <rect x="3.2" y="4.4" width="17.6" height="15.2" rx="2.4" />
      <path d="M9.4 4.4v15.2M17 9.6L14.4 12l2.6 2.4" />
    </>
  ),
  left_panel_open: (
    <>
      <rect x="3.2" y="4.4" width="17.6" height="15.2" rx="2.4" />
      <path d="M9.4 4.4v15.2M14.4 9.6L17 12l-2.6 2.4" />
    </>
  ),
  close: <path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8" />,
  cloud_download: (
    <>
      <path d="M6.6 13.9a3.8 3.8 0 0 1 .6-7.5 5.4 5.4 0 0 1 10.3 1.5 3.5 3.5 0 0 1-.4 6" />
      <path d="M12 11.6v8.2M8.9 16.7l3.1 3.1 3.1-3.1" />
    </>
  ),
  delete: (
    <>
      <path d="M4.8 6.8h14.4M9.4 6.8V4.6h5.2v2.2" />
      <path d="M6.6 6.8l.9 12.8h9l.9-12.8" />
      <path d="M10.4 10.4v5.8M13.6 10.4v5.8" />
    </>
  ),
  delete_forever: (
    <>
      <path d="M4.8 6.8h14.4M9.4 6.8V4.6h5.2v2.2" />
      <path d="M6.6 6.8l.9 12.8h9l.9-12.8" />
      <path d="M10.1 10.6l3.8 5M13.9 10.6l-3.8 5" />
    </>
  ),
  description: (
    <>
      <path d="M7 3.2h7l5 5v12.6H7z" />
      <path d="M14 3.2v5h5" />
      <path d="M9.6 13.2h6.8M9.6 16.4h4.8" />
    </>
  ),
  download: <path d="M12 4.2v11.4M8.2 11.9l3.8 3.7 3.8-3.7M5 19.6h14" />,
  dynamic_feed: (
    <>
      <path d="M8.2 4.6h11.2v10.6" />
      <rect x="4.6" y="8.2" width="11.2" height="11.2" rx="2" />
      <path d="M7.6 12.4h5.2M7.6 15.4h3.4" />
    </>
  ),
  edit: (
    <>
      <path d="M5 19l3.1-.8L19.6 6.7a1.9 1.9 0 0 0-2.7-2.7L5.4 15.6z" />
      <path d="M15.6 6.6l2.7 2.7" />
    </>
  ),
  explore_off: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M15.2 8.8l-2 5.2-5.2 2 2-5.2z" />
      <path d="M4.6 4.6l14.8 14.8" />
    </>
  ),
  fact_check: (
    <>
      <path d="M6.8 3.2h10.4v17.6L12 17.6l-5.2 3.2z" />
      <path d="M9.6 9.4l2 2 3.4-3.6" />
    </>
  ),
  filter_center_focus: (
    <>
      <path d="M4.2 8.6V4.2h4.4M15.4 4.2h4.4v4.4M19.8 15.4v4.4h-4.4M8.6 19.8H4.2v-4.4" />
      <circle cx="12" cy="12" r="2.6" />
    </>
  ),
  groups: (
    <>
      <circle cx="9" cy="9.4" r="2.5" />
      <circle cx="16.4" cy="10.4" r="2.1" />
      <path d="M3.6 18.4c1-2.5 2.9-3.7 5.4-3.7s4.4 1.2 5.4 3.7" />
      <path d="M15.8 14.6c2 .2 3.5 1.4 4.3 3.5" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 11.2v5.4M12 7.6v.3" />
    </>
  ),
  link: (
    <>
      <path d="M10.2 13.8a4.1 4.1 0 0 0 5.8 0l2.9-2.9a4.1 4.1 0 1 0-5.8-5.8l-1.2 1.2" />
      <path d="M13.8 10.2a4.1 4.1 0 0 0-5.8 0l-2.9 2.9a4.1 4.1 0 1 0 5.8 5.8l1.2-1.2" />
    </>
  ),
  lock: (
    <>
      <rect x="4.6" y="10.4" width="14.8" height="9.8" rx="2" />
      <path d="M8.4 10.4V7.7a3.6 3.6 0 0 1 7.2 0v2.7" />
    </>
  ),
  login: (
    <>
      <path d="M13.8 4.6H18a1.6 1.6 0 0 1 1.6 1.6v11.6A1.6 1.6 0 0 1 18 19.4h-4.2" />
      <path d="M4.4 12h10M10.8 8.4l3.6 3.6-3.6 3.6" />
    </>
  ),
  logout: (
    <>
      <path d="M10.2 4.6H6a1.6 1.6 0 0 0-1.6 1.6v11.6A1.6 1.6 0 0 0 6 19.4h4.2" />
      <path d="M19.6 12h-10M16 8.4l3.6 3.6-3.6 3.6" />
    </>
  ),
  manage_search: (
    <>
      <path d="M3 7.2h4M3 11h4M3 14.8h2.8" />
      <circle cx="13.4" cy="11" r="5.2" />
      <path d="M17.4 15.2l3.6 3.6" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  model_training: (
    <>
      <path d="M20.2 12a8.2 8.2 0 1 1-3.3-6.6" />
      <path d="M20.2 4.4v4.6h-4.6" />
      <path d="M11.4 9.6l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1z" />
    </>
  ),
  // Le pouls : l'identite visuelle du produit depuis l'origine.
  monitor_heart: <path d="M3 12h3.6l2.1-5.4 3.1 10.8 2.1-5.4H21" />,
  notifications: (
    <>
      <path d="M12 3.8a6.1 6.1 0 0 0-6.1 6.1v4.2L3.8 17h16.4l-2.1-2.9V9.9A6.1 6.1 0 0 0 12 3.8z" />
      <path d="M9.9 20h4.2" />
    </>
  ),
  notifications_active: (
    <>
      <path d="M12 4.8a5.6 5.6 0 0 0-5.6 5.6v3.8L4.5 17h15l-1.9-2.8v-3.8A5.6 5.6 0 0 0 12 4.8z" />
      <path d="M10.1 20h3.8" />
      <path d="M3.4 7.6a6.4 6.4 0 0 1 2.2-3.6M20.6 7.6a6.4 6.4 0 0 0-2.2-3.6" />
    </>
  ),
  open_in_new: (
    <>
      <path d="M14 4.4h5.6V10" />
      <path d="M19.6 4.4l-8.4 8.4" />
      <path d="M18 13.8v5.8H4.4V6h5.8" />
    </>
  ),
  person: (
    <>
      <circle cx="12" cy="8.4" r="3.5" />
      <path d="M5.4 19.6c1.4-3.3 3.8-4.9 6.6-4.9s5.2 1.6 6.6 4.9" />
    </>
  ),
  policy: (
    <>
      <path d="M12 3.2l7.4 3v5.4c0 4.6-3 7.8-7.4 9.4-4.4-1.6-7.4-4.8-7.4-9.4V6.2z" />
      <path d="M9.2 11.8l2 2 3.6-3.8" />
    </>
  ),
  progress_activity: <path d="M12 3.4a8.6 8.6 0 1 1-8.6 8.6" />,
  public: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M3.3 12h17.4" />
      <path d="M12 3.3c4 4.7 4 12.7 0 17.4-4-4.7-4-12.7 0-17.4z" />
    </>
  ),
  query_stats: (
    <>
      <path d="M4 20h16" />
      <path d="M7 20v-4.6M11 20v-8.4M15 20v-3.4M19 20v-6.6" />
      <path d="M5.8 11.2l4.4-4.4 3 3 5.4-5.2" />
    </>
  ),
  remove: <path d="M5 12h14" />,
  schedule: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 6.8v5.4l3.4 2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.2" />
      <path d="M15.6 15.6L20.4 20.4" />
    </>
  ),
  send: (
    <>
      <path d="M20.4 4.6L4.2 11.4l6.6 2.4 2.4 6.6z" />
      <path d="M20.4 4.6l-9.6 9.2" />
    </>
  ),
  settings_ethernet: (
    <>
      <path d="M8.2 6.8L4 12l4.2 5.2M15.8 6.8L20 12l-4.2 5.2" />
      <path d="M10.4 12h.1M12 12h.1M13.6 12h.1" />
    </>
  ),
  shield: <path d="M12 3.2l7.4 3v5.4c0 4.6-3 7.8-7.4 9.4-4.4-1.6-7.4-4.8-7.4-9.4V6.2z" />,
  shield_person: (
    <>
      <path d="M12 3.2l7.4 3v5.4c0 4.6-3 7.8-7.4 9.4-4.4-1.6-7.4-4.8-7.4-9.4V6.2z" />
      <circle cx="12" cy="10.2" r="1.9" />
      <path d="M8.7 15.8c.8-1.7 1.9-2.5 3.3-2.5s2.5.8 3.3 2.5" />
    </>
  ),
  smart_toy: (
    <>
      <rect x="3.6" y="8.2" width="16.8" height="10.6" rx="3" />
      <circle cx="9" cy="13.2" r="1.15" />
      <circle cx="15" cy="13.2" r="1.15" />
      <path d="M12 5.2v3" />
      <circle cx="12" cy="4.2" r="1.1" />
    </>
  ),
  // Une source de collecte : un entrepot, pas un fichier de code.
  source: (
    <>
      <ellipse cx="12" cy="6.2" rx="7" ry="3" />
      <path d="M5 6.2v11.6c0 1.7 3.1 3 7 3s7-1.3 7-3V6.2" />
      <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
    </>
  ),
  summarize: (
    <>
      <path d="M7 3.2h7l5 5v12.6H7z" />
      <path d="M14 3.2v5h5" />
      <path d="M9.6 12.6h6.8M9.6 15.8h4" />
    </>
  ),
  terminal: (
    <>
      <rect x="3.4" y="4.8" width="17.2" height="14.4" rx="2" />
      <path d="M7.4 9.6l2.6 2.6-2.6 2.6" />
      <path d="M12.6 15h4.2" />
    </>
  ),
  timer: (
    <>
      <circle cx="12" cy="13.4" r="7.4" />
      <path d="M12 9.4v4h3.2" />
      <path d="M9.4 3h5.2" />
      <path d="M18.8 7.4l1.6-1.6" />
    </>
  ),
  translate: (
    <>
      <path d="M3.6 6.4h8.2M7.7 4.4v2" />
      <path d="M10.4 6.4c-.5 4.2-3 7.6-6.8 9.4" />
      <path d="M5.6 10.2c1.3 2.4 3.3 4.2 5.8 5.2" />
      <path d="M13 20.4l3.8-8.8 3.8 8.8M14.4 17.4h4.8" />
    </>
  ),
  travel_explore: (
    <>
      <circle cx="10.2" cy="10.2" r="6.6" />
      <path d="M3.6 10.2h13.2" />
      <path d="M10.2 3.6c3.1 3.6 3.1 9.6 0 13.2-3.1-3.6-3.1-9.6 0-13.2z" />
      <circle cx="16.8" cy="16.8" r="3" />
      <path d="M19 19l2.4 2.4" />
    </>
  ),
  upload: <path d="M12 19.8V8.4M8.2 12.1L12 8.4l3.8 3.7M5 4.4h14" />,
  verified: (
    <>
      <path d="M9.2 3.2h5.6l4 4v5.6l-4 4H9.2l-4-4V7.2z" />
      <path d="M9.2 10.2l2.2 2.2 4-4.2" />
    </>
  ),
  visibility: (
    <>
      <path d="M2.6 12S6.4 5.6 12 5.6 21.4 12 21.4 12 17.6 18.4 12 18.4 2.6 12 2.6 12z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  warning: (
    <>
      <path d="M12 3.6l9.4 16.4H2.6z" />
      <path d="M12 10v4.6M12 17.4v.2" />
    </>
  ),
  // Noms utilises par la taxonomie des sources (`sourceTypeIcons`) et par la
  // page Modele LLM (`PROVIDER_ICONS`) : absents du premier releve, ils
  // auraient disparu sans bruit hors developpement.
  security: <path d="M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z" />,
  content_paste: (
    <path d="M9 4h6v3H9zM9 5.5H6.5A1.5 1.5 0 0 0 5 7v12.5A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V7a1.5 1.5 0 0 0-1.5-1.5H15" />
  ),
  forum: <path d="M4 5h11v8H8l-4 3zM9 13v2h7l4 3V9h-4" />,
  dns: <path d="M4 4h16v6H4zM4 14h16v6H4zM7.5 7h.01M7.5 17h.01" />,
};
