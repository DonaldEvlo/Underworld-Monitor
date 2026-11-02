import { entitiesApi } from "../../api/entities";
import { useRequete } from "../../hooks/useRequete";
import { jour } from "../../lib/format";
import { Icon } from "../ui/Icon";
import { Modale } from "../ui/Modale";

/** Où une entité candidate est citée : les documents qui la mentionnent,
 * avec leur source et leur date. Un clic ouvre le document dans le panneau
 * de détail habituel. */
export function CitationsCandidate({
  nom,
  onFermer,
  onOuvrirDocument,
}: {
  nom: string;
  onFermer: () => void;
  onOuvrirDocument: (id: string) => void;
}) {
  const req = useRequete(() => entitiesApi.candidateDocuments(nom), [nom]);
  const r = req.donnees;

  return (
    <Modale
      titreId="titre-citations"
      onFermer={onFermer}
      classePanneau="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-[18px] border border-line bg-panel p-5"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="titre-citations" className="truncate font-display text-17 font-bold text-ink">
            {nom}
          </h2>
          <p className="mt-0.5 text-body-sm text-ink-dim">
            {r ? `cité dans ${r.total} document(s)` : "recherche des citations…"}
          </p>
        </div>
        <button onClick={onFermer} className="rounded-md p-1.5 text-ink-dim hover:bg-panel-raised" aria-label="Fermer">
          <Icon name="close" className="text-18" />
        </button>
      </div>

      {req.erreur && <p className="mt-3 text-body-sm text-critical">Chargement impossible : {req.erreur}</p>}

      <div className="custom-scrollbar mt-3 flex flex-col gap-1.5 overflow-y-auto pr-1">
        {r?.items.map((doc) => (
          <button
            key={doc.id}
            onClick={() => onOuvrirDocument(doc.id)}
            className="rounded-lg border border-line bg-panel-sunken px-3 py-2 text-left transition-colors hover:border-signal/30"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-body-sm text-ink">{doc.title || "(sans titre)"}</span>
              <span className="shrink-0 font-mono-data text-11 text-ink-faint">{jour(doc.fetched_at)}</span>
            </div>
            <p className="mt-0.5 font-mono-label text-10.5 text-signal">{doc.source_name ?? doc.source_type}</p>
            <p className="mt-0.5 line-clamp-2 text-12 text-ink-dim">{doc.content_preview}</p>
          </button>
        ))}
        {r && r.total > r.items.length && (
          <p className="font-mono-label text-10.5 text-ink-faint">
            {r.items.length} affichés sur {r.total}, les plus récents d&apos;abord
          </p>
        )}
      </div>
    </Modale>
  );
}
