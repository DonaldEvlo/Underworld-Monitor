import { useId } from "react";

interface LogoFailleProps {
  /** Cote du carre de rendu, en pixels. 20 dans la barre laterale, 24 a la connexion. */
  size?: number;
  className?: string;
  /** Texte alternatif. Absent = marque purement decorative (le nom est ecrit a cote). */
  title?: string;
}

/** Marque « la faille » — un perimetre hexagonal ferme, tranche d'une diagonale.
 *
 * La forme dit ce que l'outil observe : une enceinte, et l'endroit exact ou elle
 * s'est ouverte. Elle remplace le pictogramme `monitor_heart` emprunte a Material
 * Symbols, qui n'etait pas une marque et dependait d'une police distante.
 *
 * ⚠️ LA COUPE EST UN MASQUE, PAS UN TRAIT DE LA COULEUR DU FOND. La maquette
 * peignait l'entaille avec la couleur d'arriere-plan (`#04070a`) : ca ne tient
 * que sur un fond opaque et connu. Or la marque est posee sur `bg-signal/12`
 * dans la barre laterale et sur `bg-signal/15` a la connexion — deux fonds
 * TRANSLUCIDES. Un trait opaque y aurait dessine une balafre sombre visible.
 * Le masque evide reellement le trace, donc la coupe laisse voir ce qu'il y a
 * derriere, quel qu'il soit.
 *
 * La couleur vient de `currentColor` : la marque se recolore avec les classes
 * `text-*` comme le reste de l'interface, et suit donc la rampe semantique sans
 * qu'on ait a lui passer un hexadecimal.
 */
export function LogoFaille({ size = 20, className = "", title }: LogoFailleProps) {
  // ⚠️ Identifiant unique par instance : deux marques dans le meme document
  // (barre laterale + en-tete) partageraient sinon le meme `id` de masque, et
  // le navigateur applique le PREMIER trouve. `useId` est stable entre le rendu
  // serveur et le client, contrairement a un compteur maison.
  const brut = useId();
  const masque = `faille-${brut.replace(/:/g, "")}`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
    >
      {title && <title>{title}</title>}
      <defs>
        <mask id={masque} maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">
          <rect x="0" y="0" width="48" height="48" fill="#fff" />
          {/* La bande qui evide : meme diagonale que l'arete, plus large.
              ⚠️ Elle DEPASSE la forme aux deux bouts. Dans la maquette elle
              s'arretait pile sur l'arete inferieure gauche (13,40) : la coupe
              y mordait sans traverser, et detachait un eclat isole du
              perimetre — lisible comme un defaut de rendu, pas comme une
              intention. Prolongee de 6 unites de part et d'autre le long de
              la meme diagonale, l'ouverture est franche aux deux extremites. */}
          <path d="M9.4 44.8 L40.6 3.2" stroke="#000" strokeWidth="7" strokeLinecap="butt" />
        </mask>
      </defs>

      {/* Le perimetre, ouvert par le masque. */}
      <path
        d="M24 3 L42 13.5 L42 34.5 L24 45 L6 34.5 L6 13.5 Z"
        stroke="currentColor"
        strokeWidth="3.2"
        strokeLinejoin="miter"
        mask={`url(#${masque})`}
      />
      {/* L'arete de la faille : le seul detail qui survit au 16 px. */}
      <path d="M17.5 36 L32.5 12" stroke="currentColor" strokeWidth="3.2" strokeLinecap="butt" />
    </svg>
  );
}
