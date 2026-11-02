import { ICONES } from "./icones";

interface IconProps {
  name: string;
  className?: string;
}

/** Icone du produit, dessinee et embarquee (voir `icones.tsx`).
 *
 * ⚠️ TAILLE EN `1em`, PAS EN PIXELS. Les appels existants dimensionnent les
 * icones par la taille de police (`text-19`, `text-16`) — heritage de
 * la police de symboles qu'on remplace. En rendant le SVG a `1em`, ces dizaines
 * d'appels continuent de fonctionner sans etre touches, et une icone posee dans
 * un texte suit naturellement sa taille.
 *
 * La couleur vient de `currentColor` : `text-signal`, `text-critical` et la
 * rampe semantique s'appliquent comme avant.
 */
export function Icon({ name, className = "" }: IconProps) {
  const dessin = ICONES[name];

  // ⚠️ Nom inconnu : on ne rend RIEN de visible. L'ancienne implementation
  // affichait le nom brut en toutes lettres des que le glyphe manquait
  // (« delete_forever » au milieu d'un bouton) — un defaut de chargement ne
  // doit jamais devenir du texte dans l'interface.
  //
  // ⚠️ Mais un trou SILENCIEUX est son propre piege : un bouton d'action sans
  // icone passe inapercu a la relecture. Constate — un premier releve des
  // noms utilises en avait manque seize, passes par ternaire ou par prop.
  // En developpement, l'oubli parle.
  if (!dessin) {
    if (import.meta.env.DEV) {
      console.warn(`Icone absente du jeu embarque : « ${name} » (voir icones.tsx)`);
    }
    return null;
  }

  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`inline-block shrink-0 align-middle ${className}`}
    >
      {dessin}
    </svg>
  );
}
