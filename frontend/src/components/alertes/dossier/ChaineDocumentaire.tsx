import { Link } from "react-router-dom";
import { Icon } from "../../ui/Icon";
import { MaskedValue } from "../../ui/MaskedValue";
import { dateHeure } from "../../../lib/format";
import { libelleType, type ContexteDossier } from "./contexte";

/** Chaîne documentaire : source → document → détection → alerte. */
export function ChaineDocumentaire({ c }: { c: ContexteDossier }) {
  const { alerte, documents, preuves } = c;
  return (
    <>
      {/* ---- chaîne documentaire ---- */}
      <section className="pulse-panel p-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">
            Chaîne documentaire
          </h2>
          <p className="font-mono-label text-10.5 text-ink-faint">
            source → document → détection → alerte
          </p>
          <Link
            to={`/alerts/${alerte.id}/chaine`}
            className="ml-auto flex items-center gap-1 font-mono-label text-11 text-signal"
          >
            ouvrir l&apos;investigation
            <Icon name="chevron_right" className="text-13" />
          </Link>
        </div>

        {documents.length === 0 ? (
          <p className="mt-3 text-body-sm text-ink-dim">
            Chargement des documents d&apos;origine…
          </p>
        ) : (
          <div className="mt-3 flex flex-col gap-2.5">
            {documents.map((doc) => (
              <div key={doc.document_id} className="rounded-xl border border-line bg-panel-sunken p-3">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <span className="rounded-md border border-line px-1.5 py-0.5 font-mono-label text-10 text-ink-dim">
                    {doc.source_name ?? "source inconnue"}
                  </span>
                  <span className="font-mono-data text-11 text-ink-dim">
                    {doc.published_at ? dateHeure(doc.published_at) : "non daté"}
                  </span>
                  <span className="font-mono-data text-11 text-ink-faint">
                    {doc.detections.length} détection(s)
                  </span>
                  <Link
                    to={`/documents?doc=${doc.document_id}`}
                    className="ml-auto flex items-center gap-1 font-mono-label text-11 text-signal"
                  >
                    Ouvrir le document
                    <Icon name="chevron_right" className="text-13" />
                  </Link>
                </div>
                {doc.title && (
                  <p className="mt-1.5 truncate text-body-sm text-ink">{doc.title}</p>
                )}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {doc.detections.slice(0, 6).map((d) => (
                    <span
                      key={d.id}
                      className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-1.5 py-0.5"
                    >
                      <span className="font-mono-label text-10 text-ink-faint">
                        {libelleType(d.type)}
                      </span>
                      <MaskedValue value={d.value_masked} />
                    </span>
                  ))}
                  {doc.detections.length > 6 && (
                    <span className="self-center font-mono-label text-10 text-ink-faint">
                      + {doc.detections.length - 6}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <p className="mt-3 font-mono-label text-10 text-ink-faint">
          {alerte.detection_count} détections rattachées
          {preuves && preuves.document_count > documents.length
            ? ` · ${preuves.document_count} documents au total, ${documents.length} affichés`
            : ""}
        </p>
      </section>
    </>
  );
}
