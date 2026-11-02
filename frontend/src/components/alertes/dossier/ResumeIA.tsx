import { alertsApi } from "../../../api/alerts";
import type { ContexteDossier } from "./contexte";

/** Résumé rédigé par le modèle, avec son assiette. */
export function ResumeIA({ c }: { c: ContexteDossier }) {
  const { alerte, enCours, agir } = c;
  return (
    <section className="pulse-panel p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-label text-10 uppercase tracking-widest text-signal">
          Résumé IA
        </span>
        {!alerte.summary && (
          <button
            disabled={enCours !== null}
            onClick={() => void agir("sum", () => alertsApi.summarize(alerte.id))}
            className="rounded-md border border-signal/30 bg-signal/10 px-2 py-1 font-mono-label text-10 text-signal disabled:opacity-40"
          >
            {enCours === "sum" ? "rédaction…" : "rédiger"}
          </button>
        )}
      </div>
      {alerte.summary ? (
        <>
          <p className="mt-2.5 whitespace-pre-wrap text-body-sm text-ink">{alerte.summary}</p>
          {/* ⚠️ Un verdict dont on ignore l'auteur et l'assiette n'est pas
              auditable. Le périmètre est écrit sous le texte. */}
          <p className="mt-2.5 border-t border-line-soft pt-2.5 font-mono-label text-10 leading-4 text-ink-faint">
            établi sur {alerte.detection_count} détections rattachées
            <br />
            à relire avant transmission — le modèle n&apos;établit aucun fait
          </p>
        </>
      ) : (
        <p className="mt-2.5 text-body-sm text-ink-dim">
          Pas encore résumée.
        </p>
      )}
    </section>
  );
}
