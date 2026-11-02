interface MaskedValueProps {
  value: string;
}

/**
 * Affiche une valeur déjà masquée par le backend (value_masked). Le flou au
 * repos rappelle visuellement qu'il s'agit d'une donnée sensible, même
 * partiellement affichée — jamais la valeur brute.
 */
export function MaskedValue({ value }: MaskedValueProps) {
  return (
    <span
      className="cursor-help font-mono-data text-mono-data blur-[2px] transition-all hover:blur-0"
      title="Donnée masquée — survol pour prévisualiser le format"
    >
      {value}
    </span>
  );
}
