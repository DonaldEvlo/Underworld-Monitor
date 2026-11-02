import { useState } from "react";
import { addressChangesApi, type AddressChangeApi } from "../../api/sources";
import { useRequete } from "../../hooks/useRequete";
import { ageRelatif } from "../../lib/alertes";
import { dateHeure } from "../../lib/format";
import { BoutonCopier } from "../ui/BoutonCopier";

const STATUTS: Record<AddressChangeApi["status"], { libelle: string; classe: string }> = {
  applied: { libelle: "basculée", classe: "bg-ok/[0.12] text-ok" },
  pending: { libelle: "à examiner", classe: "border border-warn/50 text-warn" },
  rejected: { libelle: "écartée", classe: "bg-panel-raised text-ink-faint" },
};
const ORIGINES = { site: "annoncée par le site", deepdarkcti: "liste deepdarkCTI" };

const court = (url: string) => url.replace(/^https?:\/\//, "").replace(/\.onion.*$/, "").slice(0, 14) + "….onion";

/**
 * Changements d'adresse des sources (2026-10-05).
 *
 * Deux tâches planifiées repèrent une nouvelle adresse — annoncée par le site
 * lui-même, ou donnée ONLINE par deepdarkCTI quand la nôtre ne l'est plus. La
 * source ne bascule SEULE que sur preuve : la nouvelle adresse publie les
 * mêmes victimes, et l'ancienne ne fonctionne plus. Le reste attend une
 * décision, ici.
 */
export function ChangementsAdresse({ admin, onBascule }: { admin: boolean; onBascule: () => void }) {
  const [version, setVersion] = useState(0);
  const req = useRequete(() => addressChangesApi.list(), [version]);
  const lignes = req.donnees ?? [];
  const [arme, setArme] = useState<string | null>(null);
  const [enCours, setEnCours] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  async function agir(nom: string, action: () => Promise<unknown>, apres?: string) {
    setEnCours(nom);
    setErreur(null);
    setMessage(null);
    try {
      await action();
      setArme(null);
      if (apres) setMessage(apres);
      setVersion((v) => v + 1);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Action impossible");
    } finally {
      setEnCours(null);
    }
  }

  const enAttente = lignes.filter((l) => l.status === "pending").length;

  return (
    <section className="rounded-[18px] border border-line bg-panel p-4">
      <div className="flex items-baseline gap-2">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">Changements d&apos;adresse</h2>
        {enAttente > 0 && (
          <span className="rounded-md border border-warn/50 px-1.5 py-0.5 font-mono-label text-10 text-warn">
            {enAttente} à examiner
          </span>
        )}
      </div>
      <p className="mt-1 text-body-sm text-ink-dim">
        Bascule automatique seulement si la nouvelle adresse publie les mêmes victimes et que l&apos;ancienne ne répond
        plus.
      </p>

      {admin && (
        <div className="mt-3 flex flex-wrap gap-2">
          {(["site", "deepdarkcti"] as const).map((o) => (
            <button
              key={o}
              disabled={enCours !== null}
              onClick={() =>
                void agir(
                  o,
                  () => addressChangesApi.run(o),
                  "Vérification lancée sur la file dédiée : résultat dans quelques minutes.",
                )
              }
              className="rounded-[10px] border border-line bg-panel-sunken px-3 py-1.5 text-12 text-ink transition-colors hover:border-signal/35 disabled:opacity-50"
            >
              {o === "site" ? "Vérifier les sites" : "Vérifier deepdarkCTI"}
            </button>
          ))}
          <button
            onClick={() => setVersion((v) => v + 1)}
            className="rounded-[10px] px-2 py-1.5 font-mono-label text-11 text-ink-dim hover:text-ink"
          >
            rafraîchir
          </button>
        </div>
      )}
      {message && <p className="mt-2 text-12 text-ok">{message}</p>}
      {erreur && <p className="mt-2 text-12 text-critical">{erreur}</p>}
      {req.erreur && <p className="mt-2 text-12 text-critical">{req.erreur}</p>}

      <div className="mt-3 flex flex-col gap-2">
        {lignes.length === 0 && !req.chargement && (
          <p className="text-body-sm text-ink-dim">Aucun changement d&apos;adresse repéré pour l&apos;instant.</p>
        )}
        {lignes.slice(0, 12).map((l) => {
          const s = STATUTS[l.status];
          return (
            <div key={l.id} className="rounded-xl border border-line bg-panel-sunken p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-ink">{l.source_name}</span>
                <span className={`rounded-md px-1.5 py-0.5 font-mono-label text-10 ${s.classe}`}>{s.libelle}</span>
                <span className="ml-auto font-mono-label text-10 text-ink-faint" title={dateHeure(l.last_checked_at)}>
                  {ageRelatif(l.last_checked_at)}
                </span>
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-1 font-mono-data text-11 text-ink-dim">
                <span title={l.old_url}>{court(l.old_url)}</span>→
                <span className="text-ink" title={l.new_url}>
                  {court(l.new_url)}
                </span>
                <BoutonCopier valeur={l.new_url} />
              </p>
              <p className="mt-1 text-12 text-ink-dim">
                {ORIGINES[l.origin]}
                {l.evidence ? ` — ${l.evidence}` : ""}
              </p>
              {l.reason && <p className="mt-1 text-12 text-ink">{l.reason}</p>}
              {l.decided_by && l.status !== "pending" && (
                <p className="mt-1 font-mono-label text-10 text-ink-faint">décision : {l.decided_by}</p>
              )}
              {admin && l.status === "pending" && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {arme === l.id ? (
                    <>
                      <button
                        disabled={enCours !== null}
                        onClick={() =>
                          void agir(`apply-${l.id}`, async () => {
                            await addressChangesApi.apply(l.id);
                            onBascule();
                          })
                        }
                        className="rounded-lg bg-warn px-2.5 py-1 text-12 font-semibold text-on-signal disabled:opacity-50"
                      >
                        Confirmer la bascule
                      </button>
                      <button onClick={() => setArme(null)} className="rounded-lg border border-line px-2.5 py-1 text-12 text-ink-dim">
                        Annuler
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setArme(l.id)}
                        className="rounded-lg border border-line bg-panel-raised px-2.5 py-1 text-12 text-ink hover:border-signal/40"
                        title="La source sera collectée à cette adresse. Vérifiez d'abord dans Tor Browser."
                      >
                        Basculer…
                      </button>
                      <button
                        disabled={enCours !== null}
                        onClick={() => void agir(`reject-${l.id}`, () => addressChangesApi.reject(l.id))}
                        className="rounded-lg border border-line px-2.5 py-1 text-12 text-ink-dim hover:text-ink disabled:opacity-50"
                      >
                        Écarter
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
