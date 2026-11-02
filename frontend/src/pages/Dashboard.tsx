import { Link } from "react-router-dom";
import { detectionsApi, type DetectionListItem } from "../api/detections";
import { documentsApi } from "../api/documents";
import { sourcesApi, type SourceApi } from "../api/sources";
import { AppLayout } from "../components/layout/AppLayout";
import { BandeauSignal } from "../components/dashboard/BandeauSignal";
import { CeQuiBloque } from "../components/dashboard/CeQuiBloque";
import { FileDeVeille } from "../components/dashboard/FileDeVeille";
import { FluxRecent } from "../components/dashboard/FluxRecent";
import { useVeilleBadges } from "../hooks/useVeilleBadges";
import { useRequete } from "../hooks/useRequete";

/** Nombre de detections listees dans le flux 24 h. */
const TAILLE_FLUX = 8;

/** Poste de veille — ce que l'analyste ouvre le matin.
 *
 * ⚠️ CET ECRAN COMPTAIT AU LIEU DE PRIORISER. Il annoncait des volumes
 * (documents, detections, sources) mais ne disait pas PAR QUOI COMMENCER :
 * l'unique alerte critique du corpus s'y noyait parmi vingt-quatre moyennes.
 * L'ordre est desormais : ce qu'il faut traiter en premier, la file, ce qui
 * bloque la veille — et la volumetrie en pied de panneau, une seule fois.
 */
export function Dashboard() {
  // Trois chargements indépendants : l'échec de l'un ne masque pas les autres.
  // Les sources ne remontent pas d'erreur (le bandeau sait afficher « aucune »).
  const sourcesReq = useRequete(() => sourcesApi.list(), []);
  const documentsReq = useRequete(() => documentsApi.list({ limit: 1 }), []);
  const detectionsReq = useRequete(() => detectionsApi.list({ limit: TAILLE_FLUX }), []);
  const sources: SourceApi[] = sourcesReq.donnees ?? [];
  // ⚠️ `null` = pas encore chargé, `0` = base réellement vide.
  const documentCount: number | null = documentsReq.donnees?.total ?? null;
  const detectionTotal: number | null = detectionsReq.donnees?.total ?? null;
  const detectionsRecentes: DetectionListItem[] = detectionsReq.donnees?.items ?? [];
  const erreur = documentsReq.erreur ?? detectionsReq.erreur;
  // Partage avec la barre laterale : meme appel, meme cache de 60 s.
  const activite = useVeilleBadges();

  // ⚠️ `null` = pas encore charge, `0` = base reellement vide. Les confondre
  // ferait clignoter l'ecran d'amorcage a chaque ouverture de page.
  const corpusVide = documentCount === 0 && sources.length === 0;

  return (
    // Pas de champ de recherche : la page n'en implemente pas, et un champ
    // grise qui promet exactement ce que l'analyste cherche est pire que pas
    // de champ du tout.
    <AppLayout title="Poste de veille">
      {erreur && (
        <p className="mb-4 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger certaines données : {erreur}
        </p>
      )}

      <BandeauSignal sources={sources} sourcesEnEchec={activite?.sources_en_echec ?? 0} />

      {corpusVide ? (
        <div className="pulse-panel flex flex-col items-center gap-2.5 px-8 py-14 text-center">
          <h2 className="font-display text-headline-lg text-ink">Aucune collecte enregistrée</h2>
          <p className="max-w-lg text-body-md text-ink-dim">
            La base est vide : rien n&apos;a encore été lu. Déclarez une source, puis lancez une
            collecte. Le poste de veille apparaîtra ensuite.
          </p>
          <div className="mt-3 flex flex-wrap justify-center gap-2.5">
            <Link
              to="/sources"
              className="rounded-lg bg-signal px-4 py-2 text-body-sm font-bold text-on-signal transition-opacity hover:opacity-90"
            >
              Déclarer une source
            </Link>
            <Link
              to="/collecte"
              className="rounded-lg border border-line bg-panel-raised px-4 py-2 text-body-sm text-ink transition-colors hover:border-signal/40"
            >
              Lancer une collecte
            </Link>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 items-start gap-gutter xl:grid-cols-[minmax(0,1fr)_21.5rem]">
          <FileDeVeille />
          <div className="flex flex-col gap-3.5">
            <CeQuiBloque activite={activite} />
            <FluxRecent
              detections={detectionsRecentes}
              documentCount={documentCount}
              detectionTotal={detectionTotal}
            />
          </div>
        </div>
      )}
    </AppLayout>
  );
}
