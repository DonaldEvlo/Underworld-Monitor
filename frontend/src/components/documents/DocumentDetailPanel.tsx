import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  documentsApi,
  type DocumentDetail,
  type DocumentSummaryResponse,
  type TranslateResponse,
  type TranslationTargetLang,
} from "../../api/documents";
import { BoutonCopier } from "../ui/BoutonCopier";
import { Icon } from "../ui/Icon";
import { Modale } from "../ui/Modale";
import { dateHeure } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";
import { hrefSur } from "../../lib/liens";

function isNonEmptyStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}


// Panneau de detail d'un document collecte -- partage entre la page Documents
// (ouverture depuis la liste) et la page Detections (ouverture depuis une
// detection, pour voir directement le document qui la contient sans quitter
// le contexte de la detection).
interface Rattache<T> {
  pour: string;
  valeur: T;
}

function pourDocument<T>(rattache: Rattache<T> | null, documentId: string): T | null {
  return rattache && rattache.pour === documentId ? rattache.valeur : null;
}

export function DocumentDetailPanel({ documentId, onClose }: { documentId: string; onClose: () => void }) {

  const navigate = useNavigate();
  // `garderPendantChargement: false` : le panneau passe d'un document à
  // l'autre sans être démonté, et l'ancien contenu sous le titre du nouveau
  // serait trompeur sur un outil d'analyse.
  const requete = useRequete<DocumentDetail>(() => documentsApi.get(documentId), [documentId], {
    garderPendantChargement: false,
  });
  const detail = requete.donnees;
  const loading = requete.chargement;
  const error = requete.erreur;

  const [targetLang, setTargetLang] = useState<TranslationTargetLang>("fr");
  const [translating, setTranslating] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  // ⚠️ Traduction et résumé sont RATTACHÉS au document qui les a produits.
  // Avant, le résumé d'un document restait affiché sur le suivant (seule la
  // traduction était purgée), et une réponse arrivée après un changement de
  // document s'affichait sur le mauvais.
  const [traductionDe, setTraductionDe] = useState<Rattache<TranslateResponse> | null>(null);
  const [erreurTraductionDe, setErreurTraductionDe] = useState<Rattache<string> | null>(null);
  const [resumeDe, setResumeDe] = useState<Rattache<DocumentSummaryResponse> | null>(null);
  const [erreurResumeDe, setErreurResumeDe] = useState<Rattache<string> | null>(null);
  const translation = pourDocument(traductionDe, documentId);
  const translateError = pourDocument(erreurTraductionDe, documentId);
  const summary = pourDocument(resumeDe, documentId);
  const summaryError = pourDocument(erreurResumeDe, documentId);

  const mentionedUrlsRaw = detail?.source_meta?.mentioned_urls;
  const mentionedUrls = isNonEmptyStringArray(mentionedUrlsRaw) ? mentionedUrlsRaw : [];
  const contentLocked = detail?.source_meta?.content_locked === true;
  // Provenance interne à la source (ex : sous-forum Dread `/d/leaks`). Le dump
  // JSON des métadonnées la contient déjà, mais noyée — or c'est l'information
  // qui dit *où* dans la source le document a été trouvé.
  const subdread =
    typeof detail?.source_meta?.subdread === "string"
      ? detail.source_meta.subdread
      : null;

  function handleAddAsSource(url: string) {
    void navigate("/sources", { state: { prefill: { name: hostnameOf(url), url } } });
  }

  async function handleTranslate() {
    const id = documentId;
    setTranslating(true);
    setErreurTraductionDe(null);
    try {
      setTraductionDe({ pour: id, valeur: await documentsApi.translate(id, targetLang) });
    } catch (err) {
      setErreurTraductionDe({ pour: id, valeur: err instanceof Error ? err.message : "Erreur inconnue" });
    } finally {
      setTranslating(false);
    }
  }

  async function handleSummarize() {
    const id = documentId;
    setSummarizing(true);
    setErreurResumeDe(null);
    try {
      setResumeDe({ pour: id, valeur: await documentsApi.summarize(id) });
    } catch (err) {
      setErreurResumeDe({ pour: id, valeur: err instanceof Error ? err.message : "Erreur inconnue" });
    } finally {
      setSummarizing(false);
    }
  }

  return (
    <Modale
      titreId="titre-detail-document"
      onFermer={onClose}
      position="droite"
      classeVoile="bg-black/50"
      classePanneau="h-full w-full max-w-2xl overflow-y-auto border-l border-outline-variant bg-surface-container-lowest p-6"
    >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id="titre-detail-document" className="font-headline-md text-headline-md text-on-surface">Détail du document</h2>
          <button
            onClick={onClose}
            aria-label="Fermer le détail du document"
            className="rounded border border-transparent p-1.5 text-on-surface-variant transition-all hover:border-outline-variant hover:bg-surface-bright"
          >
            <Icon name="close" />
          </button>
        </div>

        {loading && <p className="text-body-sm text-on-surface-variant">Chargement...</p>}
        {error && <p className="text-body-sm text-error">Erreur : {error}</p>}

        {detail && (
          <div className="space-y-4">
            <div>
              <span className="font-caption text-caption uppercase text-on-surface-variant">Titre</span>
              <div className="flex items-center gap-2">
                <p className="font-bold text-on-surface">{detail.title || "(sans titre)"}</p>
                {contentLocked && (
                  <span
                    title="Le contenu réel de ce post est derrière un mur de type « réagir pour voir » — seul le texte d'accroche a pu être capturé."
                    className="flex shrink-0 items-center gap-1 rounded border border-warn/40 bg-warn-dim/40 px-1.5 py-0.5 font-mono-data text-10 text-warn"
                  >
                    <Icon name="lock" className="text-12" />
                    Contenu verrouillé
                  </span>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 rounded-lg border border-outline-variant bg-surface-container p-3 font-mono-data text-11">
              <div>
                <span className="text-on-surface-variant">Source</span>
                <p className="text-on-surface">{detail.source_name ?? "—"}</p>
              </div>
              <div>
                <span className="text-on-surface-variant">Collecteur</span>
                <p className="text-on-surface">
                  {detail.collector}@{detail.collector_version}
                </p>
              </div>
              <div>
                <span className="text-on-surface-variant">Auteur</span>
                <p className="text-on-surface">{detail.author ?? "—"}</p>
              </div>
              <div>
                <span className="text-on-surface-variant">Type</span>
                <p className="text-on-surface">{detail.source_type}</p>
              </div>
              <div>
                <span className="text-on-surface-variant">Publié le</span>
                <p className="text-on-surface">{dateHeure(detail.published_at)}</p>
              </div>
              <div>
                <span className="text-on-surface-variant">Collecté le</span>
                <p className="text-on-surface">{dateHeure(detail.fetched_at)}</p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <span className="font-caption text-caption uppercase text-on-surface-variant">URL</span>
                <BoutonCopier valeur={detail.url} libelle="Copier l'adresse" />
              </div>
              <p className="mt-1 break-all font-mono-data text-11 text-primary">
                <a href={hrefSur(detail.url)} target="_blank" rel="noreferrer">
                  {detail.url}
                </a>
              </p>
            </div>

            {subdread && (
              <div>
                <span className="font-caption text-caption uppercase text-on-surface-variant">
                  Sous-forum d'origine
                </span>
                <div className="mt-1">
                  <span className="rounded border border-primary/40 bg-primary/10 px-2 py-0.5 font-mono-data text-11 text-primary">
                    /d/{subdread}
                  </span>
                </div>
              </div>
            )}

            {detail.matched_keywords && detail.matched_keywords.length > 0 && (
              <div>
                <span className="font-caption text-caption uppercase text-on-surface-variant">
                  Mots-clés watchlist trouvés
                </span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {detail.matched_keywords.map((kw) => (
                    <span
                      key={kw}
                      className="rounded border border-tertiary/40 bg-tertiary-container/20 px-2 py-0.5 font-mono-data text-11 text-tertiary"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {mentionedUrls.length > 0 && (
              <div>
                <span className="font-caption text-caption uppercase text-on-surface-variant">
                  Liens mentionnés dans le contenu
                </span>
                <p className="mb-2 mt-0.5 text-11 text-on-surface-variant">
                  Repérés dans le texte, jamais visités.
                </p>
                <ul className="space-y-1.5">
                  {mentionedUrls.map((url) => (
                    <li
                      key={url}
                      className="flex items-center justify-between gap-2 rounded-lg border border-outline-variant bg-surface-container p-2"
                    >
                      <a
                        href={hrefSur(url)}
                        target="_blank"
                        rel="noreferrer"
                        className="truncate font-mono-data text-11 text-primary hover:underline"
                        title={url}
                      >
                        {url}
                      </a>
                      <button
                        onClick={() => void handleAddAsSource(url)}
                        title="Pré-remplir le formulaire d'ajout de source avec cette adresse"
                        className="flex shrink-0 items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-1 font-mono-data text-10 text-primary transition-all hover:bg-primary/20"
                      >
                        <Icon name="add_circle" className="text-13" />
                        Ajouter comme source
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.source_meta && Object.keys(detail.source_meta).length > 0 && (
              <div>
                <span className="font-caption text-caption uppercase text-on-surface-variant">
                  Métadonnées de source
                </span>
                <pre className="mt-1 overflow-x-auto rounded-lg border border-outline-variant bg-surface-container p-3 font-mono-data text-11 text-on-surface-variant">
                  {JSON.stringify(detail.source_meta, null, 2)}
                </pre>
              </div>
            )}

            <div>
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="font-caption text-caption uppercase text-on-surface-variant">Contenu</span>
                <div className="flex items-center gap-2">
                  <select
                    value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value as TranslationTargetLang)}
                    className="rounded border border-outline-variant bg-background px-2 py-1 font-mono-data text-11 outline-none focus:border-primary"
                  >
                    <option value="fr">Vers le français</option>
                    <option value="en">Vers l'anglais</option>
                  </select>
                  <button
                    onClick={() => void handleTranslate()}
                    disabled={translating}
                    className="flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-1 font-mono-data text-11 text-primary transition-all hover:bg-primary/20 disabled:opacity-40"
                  >
                    <Icon name="translate" className="text-13" />
                    {translating ? "Traduction..." : "Traduire"}
                  </button>
                  <button
                    onClick={() => void handleSummarize()}
                    disabled={summarizing}
                    title="Résumer ce document avec le modèle sélectionné"
                    className="flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-2 py-1 font-mono-data text-11 text-primary transition-all hover:bg-primary/20 disabled:opacity-40"
                  >
                    <Icon name="auto_awesome" className="text-13" />
                    {summarizing ? "Résumé..." : "Résumer"}
                  </button>
                </div>
              </div>

              {translateError && (
                <p className="mb-2 rounded border border-error/40 bg-error-container/20 p-2 text-body-sm text-error">
                  {translateError}
                </p>
              )}

              {translation && (
                <div className="mb-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="font-caption text-caption uppercase text-primary">
                      Traduction ({translation.source_lang} → {translation.target_lang})
                    </span>
                    <button
                      onClick={() => setTraductionDe(null)}
                      title="Masquer la traduction"
                      className="text-on-surface-variant hover:text-on-surface"
                    >
                      <Icon name="close" className="text-14" />
                    </button>
                  </div>
                  {translation.translated_title && (
                    <p className="mb-1.5 font-bold text-on-surface">{translation.translated_title}</p>
                  )}
                  <pre className="max-h-[40vh] overflow-y-auto whitespace-pre-wrap font-mono-data text-11 text-on-surface">
                    {translation.translated_content}
                  </pre>
                </div>
              )}

              {summaryError && (
                <p className="mb-2 rounded border border-error/40 bg-error-container/20 p-2 text-body-sm text-error">
                  Résumé indisponible : {summaryError}
                </p>
              )}

              {summary && (
                <div className="mb-3 rounded-lg border border-primary/30 bg-primary/5 p-3">
                  <p className="mb-1.5 font-caption text-caption uppercase text-on-surface-variant">
                    Résumé · {summary.model}
                    {/* L'écart doit rester visible : sans lui, le lecteur croit
                        que le résumé porte sur l'intégralité du document. */}
                    {summary.submitted_length < summary.content_length &&
                      ` · établi sur les ${summary.submitted_length.toLocaleString("fr-FR")} premiers caractères sur ${summary.content_length.toLocaleString("fr-FR")}`}
                  </p>
                  <p className="whitespace-pre-wrap text-body-sm text-on-surface">{summary.summary}</p>
                </div>
              )}

              <pre className="mt-1 max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-outline-variant bg-surface-container p-3 font-mono-data text-11 text-on-surface">
                {detail.content}
              </pre>
            </div>

            {detail.raw_html && (
              <details className="text-body-sm text-on-surface-variant">
                <summary className="cursor-pointer font-caption text-caption uppercase">
                  HTML brut ({detail.raw_html.length.toLocaleString("fr-FR")} caractères)
                </summary>
                <pre className="mt-1 max-h-[30vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-outline-variant bg-surface-container p-3 font-mono-data text-10">
                  {detail.raw_html}
                </pre>
              </details>
            )}
          </div>
        )}
    </Modale>
  );
}
