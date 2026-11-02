import { BoutonCopier } from "../../ui/BoutonCopier";
import { Icon } from "../../ui/Icon";
import { dateHeure } from "../../../lib/format";
import type { ContexteDossier } from "./contexte";
import { hrefSur } from "../../../lib/liens";

/** Preuve : ce que nous avons lu, et ce qu'un tiers publie. */
export function PreuveDossier({ c }: { c: ContexteDossier }) {
  const { alerte, documentPrincipal, avance } = c;
  return (
    <>
      {/* ---- preuve ---- */}
      <section className="pulse-panel p-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">Preuve</h2>
        </div>

        <div className="mt-3 flex flex-col gap-2.5">
          {/* Confirmation EXTERNE en tête : c'est la seule preuve qui ne
              vienne ni du gang ni d'un agrégateur lisant le même site. */}
          {alerte.press_confirmed_at ? (
            <div className="rounded-xl border border-ok/30 bg-panel-sunken p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-ok/[0.12] px-1.5 py-0.5 font-mono-label text-10 text-ok">
                  INCIDENT CONFIRMÉ · presse
                </span>
                <span className="font-mono-label text-10 text-ink-faint">
                  source extérieure au gang
                </span>
              </div>
              {alerte.press_source_url && (
                <a
                  href={hrefSur(alerte.press_source_url)}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1.5 break-all font-mono-data text-13 text-ok hover:underline"
                >
                  {alerte.press_source_url}
                  <Icon name="open_in_new" className="text-13" />
                </a>
              )}
              <p className="mt-1 font-mono-label text-10 text-ink-faint">
                confirmation observée le {dateHeure(alerte.press_confirmed_at)}
                {alerte.press_evidence_url && (
                  <>
                    {" · "}
                    <a
                      href={hrefSur(alerte.press_evidence_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-ink-dim hover:underline"
                    >
                      fiche ransomware.live
                    </a>
                  </>
                )}
              </p>
            </div>
          ) : (
            alerte.corroborated_group && (
              <p className="font-mono-label text-10 text-ink-faint">
                Aucune confirmation par la presse (elle couvre surtout les grandes
                organisations).
              </p>
            )
          )}
          {documentPrincipal ? (
            <div className="rounded-xl border border-dashed border-line bg-panel-sunken p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-panel-raised px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
                  TOR · non cliquable
                </span>
                <span className="font-mono-label text-10 text-ink-faint">
                  à ouvrir dans Tor Browser
                </span>
                <span className="flex-1" />
                <BoutonCopier valeur={documentPrincipal.url} libelle="Copier l'adresse" />
              </div>
              {/* ⚠️ Affichée, JAMAIS cliquable : un lien ordinaire vers un
                  `.onion` ne mène nulle part depuis un navigateur normal. */}
              <p className="mt-1.5 select-all break-all font-mono-data text-13 text-ink-dim">
                {documentPrincipal.url}
              </p>
              <p className="mt-1 font-mono-label text-10 text-ink-faint">
                collecté le {dateHeure(documentPrincipal.fetched_at)} par le collecteur{" "}
                {documentPrincipal.collector}
              </p>
            </div>
          ) : (
            <p className="text-body-sm text-ink-dim">
              Aucun document source rattaché n&apos;a pu être chargé.
            </p>
          )}

          {alerte.corroboration_evidence_url ? (
            <div className="rounded-xl border border-signal/25 bg-panel-sunken p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-md bg-signal/[0.12] px-1.5 py-0.5 font-mono-label text-10 text-signal">
                  CLEARNET · citable
                </span>
                <span className="font-mono-label text-10 text-ink-faint">
                  agrégateur tiers — lit le même site que nous
                </span>
              </div>
              <a
                href={hrefSur(alerte.corroboration_evidence_url)}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex items-center gap-1.5 break-all font-mono-data text-13 text-signal hover:underline"
              >
                {alerte.corroboration_evidence_url}
                <Icon name="open_in_new" className="text-13" />
              </a>
              <p className="mt-1 font-mono-label text-10 text-ink-faint">
                {alerte.corroboration_first_seen_at
                  ? `première indexation par un agrégateur le ${dateHeure(alerte.corroboration_first_seen_at)}`
                  : `confrontée le ${dateHeure(alerte.corroborated_at)}`}
                {alerte.corroborated_group ? ` · gang attribué : ${alerte.corroborated_group}` : ""}
                {avance ? ` · ${avance}` : ""}
              </p>
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-panel-sunken p-3">
              <p className="font-mono-label text-10 text-ink-faint">
                AUCUNE PREUVE CITABLE HORS TOR
              </p>
              <p className="mt-1 text-body-sm text-ink-dim">
                Cette alerte ne peut être étayée que par le site de l&apos;attaquant. Pour la
                transmettre à un tiers, seul le rapport PDF fait foi.
              </p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
