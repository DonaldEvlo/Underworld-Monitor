import { useState } from "react";
import { watchlistApi, type KeywordApi } from "../../api/watchlist";
import { useAuth } from "../../context/auth-context";
import { peutAdministrer } from "../../lib/roles";
import { Icon } from "../ui/Icon";
import { LectureSeule } from "../ui/LectureSeule";
import { jour } from "../../lib/format";
import { useRequete } from "../../hooks/useRequete";

/**
 * CRUD complet sur la watchlist de termes surveillés. Autonome (charge ses
 * propres données) — utilisé à la fois sur la page Watchlist et en section de
 * la page Sources.
 *
 * ⚠️ LA MAQUETTE PROMETTAIT « ALERTE À LA RÉAPPARITION ». C'est faux : une
 * correspondance marque le document PERTINENT (`is_relevant`), elle ne crée
 * aucune alerte — seule une organisation déclarée avec un sélecteur en
 * produit. Écrire l'inverse ferait croire à l'analyste qu'il est prévenu alors
 * qu'il ne l'est pas : le pire défaut possible pour un outil de veille.
 */
export function WatchlistPanel() {
  const requete = useRequete(() => watchlistApi.list(), []);
  const keywords: KeywordApi[] = requete.donnees ?? [];
  const modifierKeywords = requete.modifier;
  const setKeywords = (fn: (precedent: KeywordApi[]) => KeywordApi[]) =>
    modifierKeywords((precedent) => fn(precedent ?? []));
  const [term, setTerm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadError = requete.erreur;
  const loaded = !requete.chargement;

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTerm, setEditTerm] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  // Lecture en PEUT_VOIR_LE_CORPUS, ecriture en PEUT_ADMINISTRER : la liste
  // reste visible, les gestes disparaissent.
  const { user } = useAuth();
  const admin = peutAdministrer(user?.role);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!term.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await watchlistApi.create({ term: term.trim() });
      setKeywords((prev) => [created, ...prev]);
      setTerm("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    // ⚠️ Une erreur non captée ici DISPARAIT : l'analyste conclurait que son
    // clic n'a rien fait alors que l'opération a échoué.
    try {
      await watchlistApi.remove(id);
      setKeywords((prev) => prev.filter((k) => k.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Suppression impossible");
    }
  }

  /** Suspendre sans supprimer : garder le terme et son historique, arrêter
   * seulement de marquer les nouveaux documents. */
  async function basculer(kw: KeywordApi) {
    setError(null);
    try {
      const maj = await watchlistApi.update(kw.id, { active: !kw.active });
      setKeywords((prev) => prev.map((k) => (k.id === kw.id ? maj : k)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Modification impossible");
    }
  }

  function startEdit(kw: KeywordApi) {
    setEditingId(kw.id);
    setEditTerm(kw.term);
    setEditError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
  }

  async function saveEdit(id: string) {
    if (!editTerm.trim()) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const updated = await watchlistApi.update(id, { term: editTerm.trim() });
      setKeywords((prev) => prev.map((k) => (k.id === id ? updated : k)));
      setEditingId(null);
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSavingEdit(false);
    }
  }

  const actifs = keywords.filter((k) => k.active).length;

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-center gap-3">
        <p className="font-mono-label text-11 text-ink-dim">
          termes cherchés dans chaque page collectée · une correspondance marque le document
          pertinent — elle ne crée pas d&apos;alerte
        </p>
        {admin && (
        <form onSubmit={(e) => void handleSubmit(e)} className="ml-auto flex gap-2">
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="ex : acme.com"
            spellCheck={false}
            disabled={submitting}
            aria-label="Terme à surveiller"
            className="w-56 rounded-[10px] border border-line bg-panel-sunken px-3 py-[7px] font-mono-data text-12 text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={submitting || !term.trim()}
            className="rounded-[10px] bg-signal px-3 py-[7px] text-12 font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {submitting ? "Ajout…" : "Ajouter une valeur"}
          </button>
        </form>
        )}
      </div>

      {!admin && <LectureSeule quoi="la modification de la watchlist" />}

      {error && <p className="text-body-sm text-critical">{error}</p>}
      {loadError && (
        <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
          Impossible de charger la watchlist : {loadError}
        </p>
      )}

      {loaded && !loadError && keywords.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-[18px] border border-signal/[0.14] bg-panel px-8 py-12 text-center">
          <p className="font-display text-17 font-bold text-ink">Aucun terme surveillé</p>
          <p className="max-w-md text-body-sm text-ink-dim">
            Un terme — domaine client, nom de dirigeant, produit — marque comme pertinent chaque
            document collecté qui le contient. Pour être <em>prévenu</em>, déclarez plutôt une
            organisation avec ce sélecteur.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {keywords.map((kw) => {
            const isEditing = editingId === kw.id;
            return (
              <div
                key={kw.id}
                className={`group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 rounded-[14px] border bg-panel px-4 py-3 md:grid-cols-[minmax(0,1fr)_13rem_7.5rem_6.5rem_4.5rem] ${
                  kw.active ? "border-line" : "border-line-soft"
                }`}
              >
                <div className="min-w-0">
                  {isEditing ? (
                    <>
                      <input
                        autoFocus
                        value={editTerm}
                        onChange={(e) => setEditTerm(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveEdit(kw.id);
                          if (e.key === "Escape") cancelEdit();
                        }}
                        disabled={savingEdit}
                        aria-label="Modifier le terme"
                        className="w-full rounded-lg border border-signal/60 bg-panel-sunken px-2 py-1 font-mono-data text-12 text-ink outline-none disabled:opacity-50"
                      />
                      {editError && <p className="mt-1 text-11 text-critical">{editError}</p>}
                    </>
                  ) : (
                    <span
                      className={`block truncate font-mono-data text-12 ${
                        kw.active ? "text-ink" : "text-ink-faint line-through"
                      }`}
                    >
                      {kw.term}
                    </span>
                  )}
                </div>

                <span className="hidden text-body-sm text-ink-dim md:block">
                  sous-chaîne, insensible à la casse
                </span>

                {admin ? (
                  <button
                    onClick={() => void basculer(kw)}
                    title={kw.active ? "Suspendre sans supprimer" : "Réactiver"}
                    className={`hidden w-fit font-mono-data text-11 transition-opacity hover:opacity-80 md:block ${
                      kw.active ? "text-signal" : "text-ink-faint"
                    }`}
                  >
                    {kw.active ? "active" : "suspendue"}
                  </button>
                ) : (
                  <span
                    className={`hidden w-fit font-mono-data text-11 md:block ${
                      kw.active ? "text-signal" : "text-ink-faint"
                    }`}
                  >
                    {kw.active ? "active" : "suspendue"}
                  </span>
                )}

                <span className="hidden text-right font-mono-data text-11 text-ink-faint md:block">
                  {jour(kw.created_at)}
                </span>

                <div className="flex justify-end gap-1">
                  {!admin ? null : isEditing ? (
                    <>
                      <button
                        onClick={() => void saveEdit(kw.id)}
                        disabled={savingEdit || !editTerm.trim()}
                        className="rounded-md p-1.5 text-signal transition-colors hover:bg-signal/15 disabled:opacity-50"
                        title="Enregistrer"
                      >
                        <Icon name="check" className="text-16" />
                      </button>
                      <button
                        onClick={cancelEdit}
                        disabled={savingEdit}
                        className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-panel-raised"
                        title="Annuler"
                      >
                        <Icon name="close" className="text-16" />
                      </button>
                    </>
                  ) : (
                    <div className="flex gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                      <button
                        onClick={() => startEdit(kw)}
                        className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-signal/15 hover:text-signal"
                        title="Modifier"
                      >
                        <Icon name="edit" className="text-16" />
                      </button>
                      <button
                        onClick={() => void handleDelete(kw.id)}
                        className="rounded-md p-1.5 text-ink-dim transition-colors hover:bg-critical/15 hover:text-critical"
                        title="Retirer"
                      >
                        <Icon name="delete" className="text-16" />
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {keywords.length > 0 && (
        <p className="font-mono-label text-10 text-ink-faint">
          {actifs} terme(s) actif(s) sur {keywords.length}
        </p>
      )}
    </div>
  );
}
