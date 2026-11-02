import type { ContexteDossier } from "./contexte";

/** Corroboration : quatre états, jamais un booléen. */
export function Corroboration({ c }: { c: ContexteDossier }) {
  const { alerte, confirmee, exclusive, sansObjet } = c;
  return (
    <>
      {/* ⚠️ QUATRE ÉTATS, JAMAIS UN BOOLÉEN. « Vue par nous seuls » n'est pas
          un doute, « jamais confrontée » est une absence de mesure. Les
          afficher tous les trois, en éteignant ceux qui ne s'appliquent
          pas, empêche de lire une absence comme une infirmation. */}
      <section className="pulse-panel p-4">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">
          Corroboration
        </h2>
        <div className="mt-2.5 flex flex-col gap-2">
          <div
            className={`flex items-center gap-2.5 rounded-xl border bg-panel-sunken p-2.5 ${
              confirmee ? "border-signal/25" : "border-line opacity-50"
            }`}
          >
            <span className={`h-2 w-2 shrink-0 rounded-full ${confirmee ? "bg-ok" : "border border-ok"}`} />
            <div className="min-w-0">
              <p className="text-body-sm font-semibold text-ink">Confirmée par un tiers</p>
              <p className="font-mono-label text-10.5 text-ink-dim">
                {confirmee
                  ? `${alerte.corroborated_count} détection(s) confirmée(s) · ${
                      (alerte.corroborated_groups ?? [alerte.corroborated_group ?? "gang —"]).join(", ")
                    }`
                  : "l'annonce figure aussi chez RansomLook"}
              </p>
            </div>
          </div>
          <div
            className={`flex items-center gap-2.5 rounded-xl border bg-panel-sunken p-2.5 ${
              exclusive ? "border-info/30" : "border-line opacity-50"
            }`}
          >
            <span className="h-2 w-2 shrink-0 rounded-full border border-info" />
            <div className="min-w-0">
              <p className="text-body-sm text-ink">Vue par nous seuls</p>
              <p className="font-mono-label text-10.5 text-ink-dim">ce n&apos;est pas un doute</p>
            </div>
          </div>
          <div
            className={`flex items-center gap-2.5 rounded-xl border border-dashed bg-panel-sunken p-2.5 ${
              !confirmee && !exclusive && !sansObjet ? "border-line-soft" : "border-line opacity-50"
            }`}
          >
            <span className="h-2 w-2 shrink-0 rounded-full border border-dashed border-ink-faint" />
            <div className="min-w-0">
              <p className="text-body-sm text-ink">Jamais confrontée</p>
              <p className="font-mono-label text-10.5 text-ink-dim">absence de mesure</p>
            </div>
          </div>
          <div
            className={`flex items-center gap-2.5 rounded-xl border bg-panel-sunken p-2.5 ${
              sansObjet ? "border-line-soft" : "border-line opacity-50"
            }`}
          >
            <span className="h-2 w-2 shrink-0 rounded-full bg-ink-faint" />
            <div className="min-w-0">
              <p className="text-body-sm text-ink">Sans objet</p>
              <p className="font-mono-label text-10.5 text-ink-dim">
                mention de forum ou infrastructure, pas une revendication
              </p>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
