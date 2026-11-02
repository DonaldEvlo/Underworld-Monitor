/** Un fait établi : libellé, valeur, et la note qui dit d'où il vient. */
export function Fait({
  label,
  valeur,
  note,
  ton = "neutre",
}: {
  label: string;
  valeur: string;
  note: string;
  ton?: "neutre" | "ok" | "critique" | "warn";
}) {
  const couleur = {
    neutre: "text-ink",
    ok: "text-ok",
    critique: "text-critical",
    warn: "text-warn",
  }[ton];
  return (
    <div className="rounded-xl border border-line bg-panel-sunken p-3">
      <p className="font-mono-label text-10 uppercase tracking-widest text-ink-faint">{label}</p>
      <p className={`mt-1 font-mono-data text-14 ${couleur}`}>{valeur}</p>
      <p className="mt-1 text-body-sm text-ink-dim">{note}</p>
    </div>
  );
}
