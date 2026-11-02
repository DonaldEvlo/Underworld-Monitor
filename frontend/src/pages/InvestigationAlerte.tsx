import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  alertsApi,
  type AlertApi,
  type AlertDetectionApi,
  type AlertEvidenceResponse,
} from "../api/alerts";
import { documentsApi, type DocumentDetail } from "../api/documents";
import { entitiesApi, type EntityApi, type SelectorApi } from "../api/entities";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { MaskedValue } from "../components/ui/MaskedValue";
import { domaineAlerte, referenceCourte, sujetAlerte } from "../lib/alertes";
import { detectionTypeLabels, severityCadre, severityLabels, severityTexte } from "../lib/taxonomy";
import { dateHeureCourte } from "../lib/format";
import { useRequete } from "../hooks/useRequete";

const APERCU_MAX = 2400;


interface DetectionDansDocument extends AlertDetectionApi {
  documentId: string;
}


function libelleType(type: string): string {
  return detectionTypeLabels[type as keyof typeof detectionTypeLabels] ?? type;
}

function normaliserDomaine(valeur: string): string {
  const v = valeur.trim().toLowerCase().replace(/\.$/, "");
  const domaine = v.includes("@") ? (v.split("@").pop() ?? v) : v;
  return domaine.replace(/^@/, "").replace(/^www\./, "");
}

/** Le selecteur qui explique le rattachement — reproduction D'AFFICHAGE.
 *
 * ⚠️ Le serveur ne memorise pas QUEL selecteur a rattache une detection : il
 * rattache, c'est tout. On rejoue ici la meme regle (`matching.py`) pour la
 * montrer : comparaison par STRUCTURE DE DOMAINE, jamais par sous-chaine —
 * `not-acme.com` ne matche pas `acme.com`. Pour une adresse masquee, seul le
 * domaine apres `@` est comparable. Ce calcul n'a aucun effet : il explique,
 * il ne decide pas.
 */
function selecteurQuiRattache(valeur: string, selecteurs: SelectorApi[]): SelectorApi | null {
  const cible = normaliserDomaine(valeur);
  for (const s of selecteurs) {
    if (s.type === "keyword") {
      if (valeur.trim().toLowerCase() === s.value.trim().toLowerCase()) return s;
      continue;
    }
    const sel = normaliserDomaine(s.value);
    if (cible === sel || cible.endsWith(`.${sel}`)) return s;
  }
  return null;
}

function echapper(texte: string): string {
  return texte.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Surligne dans le texte les valeurs retrouvees TELLES QUELLES.
 *
 * ⚠️ Seules les valeurs non masquees se retrouvent : un domaine, un volume. Une
 * adresse est stockee masquee (`i***@…`) et ne correspond a aucun passage du
 * texte — on ne la « retrouve » pas en devinant, on le dit sous le texte.
 */
function surligner(texte: string, valeurs: string[]): React.ReactNode {
  const aiguilles = [...new Set(valeurs)]
    .filter((v) => v.length >= 3 && !v.includes("*"))
    .sort((a, b) => b.length - a.length);
  if (aiguilles.length === 0) return texte;
  const motif = new RegExp(`(${aiguilles.map(echapper).join("|")})`, "gi");
  return texte.split(motif).map((morceau, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded-[3px] bg-signal/[0.14] px-0.5 text-signal">
        {morceau}
      </mark>
    ) : (
      morceau
    ),
  );
}

/** Investigation : alerte → détection → document source, sur un seul écran.
 *
 * ⚠️ QUATRIÈME DÉFAUT MESURÉ : rien ne reliait visuellement ces trois objets.
 * Le produit revendique la vérifiabilité ; une alerte qu'on ne peut pas
 * remonter jusqu'à la ligne de texte collectée n'est qu'une affirmation.
 */
export function InvestigationAlerte() {
  const { id = "" } = useParams();
  const [selection, setSelection] = useState<string | null>(null);
  const [traductions, setTraductions] = useState<Record<string, string>>({});
  const [traduire, setTraduire] = useState(false);
  const [traductionEnCours, setTraductionEnCours] = useState(false);

  const [erreurAction, setErreurAction] = useState<string | null>(null);

  // Même motif que le dossier : changer d'alerte sans démonter ne doit pas
  // laisser l'ancienne chaîne à l'écran.
  const [idCharge, setIdCharge] = useState(id);
  if (idCharge !== id) {
    setIdCharge(id);
    setSelection(null);
    setErreurAction(null);
  }

  // Seule la réponse de l'alerte AFFICHÉE est retenue, et l'ancienne chaîne
  // ne reste pas à l'écran pendant le chargement d'une autre.
  const chaine = useRequete(
    async () => {
      const [a, entites, p] = await Promise.all([alertsApi.get(id), entitiesApi.list(), alertsApi.documents(id)]);
      return { alerte: a, entitesParId: Object.fromEntries(entites.map((e) => [e.id, e])), preuves: p };
    },
    [id],
    { garderPendantChargement: false },
  );
  const alerte: AlertApi | null = chaine.donnees?.alerte ?? null;
  const entitesParId: Record<string, EntityApi> = chaine.donnees?.entitesParId ?? {};
  const preuves: AlertEvidenceResponse | null = chaine.donnees?.preuves ?? null;
  const erreur = chaine.erreur ?? erreurAction;

  const detections = useMemo<DetectionDansDocument[]>(
    () =>
      (preuves?.documents ?? []).flatMap((doc) =>
        doc.detections.map((d) => ({ ...d, documentId: doc.document_id })),
      ),
    [preuves],
  );

  const choisie = detections.find((d) => d.id === selection) ?? detections[0] ?? null;
  const documentId = choisie?.documentId ?? null;
  const resume = preuves?.documents.find((d) => d.document_id === documentId) ?? null;
  // Un échec laisse l'aperçu du résumé à l'écran (repli ci-dessous).
  const documentReq = useRequete<DocumentDetail>(() => documentsApi.get(documentId ?? ""), [documentId], {
    actif: documentId !== null,
    garderPendantChargement: false,
  });
  const detail: DocumentDetail | undefined = documentReq.donnees ?? undefined;

  async function basculerTraduction() {
    if (!documentId) return;
    if (traduire || traductions[documentId]) {
      setTraduire((t) => !t);
      return;
    }
    setTraductionEnCours(true);
    try {
      const r = await documentsApi.translate(documentId, "fr");
      setTraductions((prec) => ({ ...prec, [documentId]: r.translated_content }));
      setTraduire(true);
    } catch (err) {
      setErreurAction(err instanceof Error ? err.message : "Traduction impossible");
    } finally {
      setTraductionEnCours(false);
    }
  }

  if (!alerte || !preuves) {
    return (
      <AppLayout title="Investigation">
        <p className="text-body-sm text-ink-dim">
          {erreur ? `Impossible de charger la chaîne : ${erreur}` : "Chargement de la chaîne…"}
        </p>
      </AppLayout>
    );
  }

  const entite = alerte.entity_id ? entitesParId[alerte.entity_id] : undefined;
  const selecteur = choisie && entite ? selecteurQuiRattache(choisie.value_masked, entite.selectors) : null;
  const domaine = domaineAlerte(alerte, entitesParId);

  const texteSource =
    traduire && documentId && traductions[documentId]
      ? traductions[documentId]
      : (detail?.content ?? resume?.content_preview ?? "");
  const tronque = texteSource.length > APERCU_MAX;
  const texteAffiche = tronque ? texteSource.slice(0, APERCU_MAX) : texteSource;
  const valeursDuDocument = (resume?.detections ?? []).map((d) => d.value_masked);

  return (
    <AppLayout title="Investigation">
      <div className="mb-3.5 flex flex-wrap items-center gap-3">
        <Link
          to={`/alerts/${alerte.id}`}
          className="flex items-center gap-1.5 font-mono-label text-11 text-ink-dim transition-colors hover:text-ink"
        >
          <Icon name="chevron_right" className="rotate-180 text-13" />
          dossier
        </Link>
        <span className="font-mono-label text-11 text-ink-faint">
          {referenceCourte(alerte)}
          {domaine ? ` · ${domaine}` : ""}
        </span>
        <span className="ml-auto font-mono-label text-11 text-ink-dim">
          une alerte non remontable jusqu&apos;au texte collecté n&apos;est qu&apos;une affirmation
        </span>
      </div>

      {erreur && (
        <p className="mb-3.5 rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          {erreur}
        </p>
      )}

      <div className="grid items-stretch gap-3.5 xl:grid-cols-[18.75rem_20rem_minmax(0,1fr)]">
        {/* ---- 1 · alerte ---- */}
        <section className="pulse-panel flex flex-col gap-2.5 p-4">
          <p className="font-mono-label text-10 uppercase tracking-widest text-ink-faint">
            1 · Alerte
          </p>
          <div className={`rounded-xl border bg-panel-sunken p-3 ${severityCadre[alerte.severity]}`}>
            <p className="font-semibold text-ink">{sujetAlerte(alerte, entitesParId)}</p>
            <p className={`mt-0.5 font-mono-data text-11 ${severityTexte[alerte.severity]}`}>
              {severityLabels[alerte.severity].toLowerCase()} · {alerte.detection_count} détections
            </p>
          </div>

          <p className="mt-1.5 font-mono-label text-10 uppercase tracking-widest text-ink-faint">
            Sélecteur qui a rattaché
          </p>
          {selecteur ? (
            <div className="rounded-xl border border-line bg-panel-sunken px-3 py-2.5 font-mono-data text-12 text-ink">
              {selecteur.type === "keyword" ? "mot-clé" : "domaine"} = {selecteur.value}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-line bg-panel-sunken px-3 py-2.5 text-body-sm text-ink-dim">
              {alerte.entity_id
                ? "Aucun sélecteur ne rend compte de cette valeur à l'affichage."
                : "Alerte régionale : aucune organisation, donc aucun sélecteur."}
            </div>
          )}
          <span className="flex-1" />
          {resume && (
            <p className="font-mono-label text-10 text-ink-faint">
              source : {resume.source_name ?? "inconnue"} · collecteur {resume.collector}
            </p>
          )}
        </section>

        {/* ---- 2 · détections ---- */}
        <section className="flex flex-col gap-2 rounded-[18px] border border-line bg-panel p-4">
          <div className="flex items-baseline gap-2">
            <p className="font-mono-label text-10 uppercase tracking-widest text-ink-faint">
              2 · Détections
            </p>
            <span className="ml-auto font-mono-label text-10 text-ink-faint">
              {alerte.detection_count}
            </span>
          </div>
          <div className="custom-scrollbar flex max-h-[34rem] flex-col gap-2 overflow-y-auto pr-1">
            {detections.map((d) => {
              const active = d.id === choisie?.id;
              return (
                <button
                  key={d.id}
                  onClick={() => {
                    setSelection(d.id);
                    setTraduire(false);
                  }}
                  aria-pressed={active}
                  className={`rounded-xl border px-3 py-2 text-left transition-colors ${
                    active
                      ? "border-signal/45 bg-signal/[0.07]"
                      : "border-line bg-panel-sunken hover:border-signal/30"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono-label text-10 text-ink-dim">
                      {libelleType(d.type)}
                    </span>
                    {/* ⚠️ « Validée » = checksum vérifié (Luhn, mod-97), pas
                        fait confirmé. Sans checksum, on dit « motif ». */}
                    <span
                      className={`ml-auto font-mono-label text-10 ${
                        d.validated ? "text-ok" : "text-ink-faint"
                      }`}
                    >
                      {d.validated ? "validée" : "motif"}
                    </span>
                  </div>
                  <div className="mt-1 truncate">
                    <MaskedValue value={d.value_masked} />
                  </div>
                </button>
              );
            })}
          </div>
          <p className="mt-auto font-mono-label text-10 text-ink-faint">
            « validée » = checksum vérifié, pas fait confirmé
            {preuves.document_count > preuves.documents.length
              ? ` · ${preuves.documents.length} documents chargés sur ${preuves.document_count}`
              : ""}
          </p>
        </section>

        {/* ---- 3 · document source ---- */}
        <section className="pulse-panel flex min-w-0 flex-col gap-2.5 p-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <p className="font-mono-label text-10 uppercase tracking-widest text-ink-faint">
              3 · Document source
            </p>
            {documentId && (
              <span className="ml-auto font-mono-label text-10 text-ink-faint">
                {documentId.slice(0, 8)}
              </span>
            )}
          </div>

          {resume ? (
            <>
              <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                {[
                  ["Source", resume.source_name ?? "—"],
                  ["Publié", dateHeureCourte(resume.published_at, "non daté")],
                  ["Collecté", dateHeureCourte(resume.fetched_at, "non daté")],
                  [
                    "Longueur",
                    detail ? `${detail.content.length.toLocaleString("fr-FR")} car.` : "…",
                  ],
                ].map(([libelle, valeur]) => (
                  <div key={libelle} className="rounded-[10px] border border-line bg-panel-sunken px-2.5 py-2">
                    <p className="font-mono-label text-9 uppercase text-ink-faint">{libelle}</p>
                    <p className="truncate font-mono-data text-12 text-ink">{valeur}</p>
                  </div>
                ))}
              </div>

              <div className="flex-1 rounded-xl border border-line bg-panel-sunken px-4 py-3.5 font-mono-data text-12 leading-5 text-ink">
                <p className="text-ink-faint">
                  — texte de l&apos;annonce publique, tel que collecté
                  {traduire ? " · traduit en français" : ""} —
                </p>
                <p className="mt-2 whitespace-pre-wrap break-words">
                  {surligner(texteAffiche, valeursDuDocument)}
                </p>
                {tronque && (
                  <p className="mt-3 text-ink-faint">
                    […] {(texteSource.length - APERCU_MAX).toLocaleString("fr-FR")} caractères
                    restants
                  </p>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono-label text-10 text-ink-faint">
                  surlignage = valeurs retrouvées telles quelles ; les valeurs masquées ne
                  figurent pas en clair dans le texte
                </span>
                <span className="flex-1" />
                <button
                  onClick={() => void basculerTraduction()}
                  disabled={traductionEnCours || !detail}
                  className="rounded-[10px] border border-line bg-panel-raised px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/40 disabled:opacity-40"
                >
                  {traductionEnCours ? "Traduction…" : traduire ? "Texte d'origine" : "Traduire FR"}
                </button>
                <Link
                  to={`/documents?doc=${resume.document_id}`}
                  className="rounded-[10px] border border-line bg-panel-raised px-3 py-1.5 text-body-sm text-ink transition-colors hover:border-signal/40"
                >
                  Voir le document
                </Link>
              </div>
            </>
          ) : (
            <p className="text-body-sm text-ink-dim">Aucun document source rattaché.</p>
          )}
        </section>
      </div>
    </AppLayout>
  );
}
