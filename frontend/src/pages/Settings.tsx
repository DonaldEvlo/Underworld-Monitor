import { useState } from "react";
import { llmApi, type LLMOption } from "../api/llm";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { useRequete } from "../hooks/useRequete";

const PROVIDER_ICONS: Record<string, string> = {
  openai: "smart_toy",
  google: "auto_awesome",
  ollama: "dns",
};

/** Fournisseurs qui tournent SUR l'instance. Pour les autres, les extraits
 * soumis au modèle partent chez un tiers. */
const LOCAUX = new Set(["ollama"]);

/** Où le modèle choisi ici intervient — relevé dans le code, pas supposé. */
const USAGES = [
  {
    nom: "Résumé d'une alerte",
    quand: "à la demande · tâche planifiable",
    note: "établi sur les détections rattachées",
  },
  {
    nom: "Synthèse de l'ensemble",
    quand: "à la demande, page Alertes",
    note: "le périmètre résumé est affiché avec le texte",
  },
  {
    nom: "Résumé d'un document",
    quand: "à la demande",
    note: "12 000 premiers caractères au plus, écart affiché",
  },
  {
    nom: "Rapport PDF",
    quand: "à l'export",
    note: "synthèse seulement — faits et preuves produits par le code",
  },
];

/**
 * Choix du modèle LLM d'analyse.
 *
 * ⚠️ TROIS AFFIRMATIONS DE LA MAQUETTE ONT ÉTÉ CORRIGÉES :
 * - « exécution locale, aucun document ne quitte l'instance » n'est vrai que
 *   pour un modèle Ollama. Cette page propose aussi OpenAI et Google : l'écrire
 *   sans condition serait faux précisément quand l'enjeu est réel (des extraits
 *   d'annonces de fuite envoyés à un tiers). L'en-tête le dit selon le modèle.
 * - « il rédige et traduit » : la traduction n'utilise PAS ce modèle
 *   (ctranslate2 + Marian, en local).
 * - L'arbitrage des annonces incertaines tourne sur un modèle FIXE, indépendant
 *   de ce choix (mesuré : 90 % de justesse contre 60 % pour llama3).
 */
export function Settings() {
  const requete = useRequete(async () => {
    const [opts, current] = await Promise.all([llmApi.options(), llmApi.getSelected()]);
    return { options: opts, modele: current.model };
  }, []);
  const options: LLMOption[] = requete.donnees?.options ?? [];
  // Choix en cours et choix ENREGISTRÉ : tant que l'analyste n'a rien touché,
  // les deux valent la valeur du serveur.
  const [choix, setSelected] = useState<string | null>(null);
  const [enregistreLocal, setEnregistre] = useState<string | null>(null);
  const enregistre = enregistreLocal ?? requete.donnees?.modele ?? "";
  const selected = choix ?? enregistre;
  const [erreurAction, setLoadError] = useState<string | null>(null);
  const loadError = requete.erreur ?? erreurAction;
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    setSaving(true);
    setSaved(false);
    try {
      await llmApi.select(selected);
      setEnregistre(selected);
      setSaved(true);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setSaving(false);
    }
  }

  // L'en-tête décrit le modèle EN SERVICE, pas celui qu'on survole.
  const actif = options.find((o) => o.id === enregistre) ?? null;
  const local = actif ? LOCAUX.has(actif.provider) : null;

  return (
    <AppLayout title="Modèle LLM">
      <div className="flex flex-col gap-3.5">
        <section className="pulse-panel flex flex-wrap items-center gap-x-7 gap-y-3 px-5 py-4">
          <div className="min-w-0">
            <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">
              Modèle en service
            </p>
            <p className="mt-0.5 font-display text-18 font-bold tracking-tight text-ink">
              {actif?.label ?? (enregistre || "—")}
            </p>
            <p
              className={`mt-0.5 font-mono-label text-11 ${
                local === false ? "text-warn" : "text-ink-dim"
              }`}
            >
              {local === null
                ? "chargement…"
                : local
                  ? "exécution locale · les extraits soumis ne quittent pas l'instance"
                  : "exécution distante · les extraits soumis partent chez le fournisseur"}
            </p>
          </div>
          <span className="hidden h-11 w-px bg-line md:block" />
          <div>
            <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">
              Température
            </p>
            <p className="mt-1 font-mono-data text-15 text-ink">0</p>
            <p className="font-mono-label text-10 text-ink-faint">résumés et synthèses</p>
          </div>
          <div>
            <p className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-faint">
              Fenêtre lue
            </p>
            <p className="mt-1 font-mono-data text-15 text-warn">12 000 car.</p>
            <p className="font-mono-label text-10 text-ink-faint">par document résumé</p>
          </div>
        </section>

        {loadError && (
          <p className="rounded border border-critical/40 bg-critical/10 p-3 text-body-sm text-critical">
            {loadError}
          </p>
        )}

        <div className="grid items-start gap-3.5 xl:grid-cols-[minmax(0,1fr)_21.5rem]">
          <div className="flex flex-col gap-3.5">
            <section className="rounded-[18px] border border-line bg-panel p-4">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                  Choisir le modèle
                </h2>
              </div>

              <div className="mt-3 flex flex-col gap-2">
                {options.map((option) => {
                  const choisi = selected === option.id;
                  return (
                    <label
                      key={option.id}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
                        choisi
                          ? "border-signal/45 bg-signal/[0.06]"
                          : "border-line bg-panel-sunken hover:border-signal/25"
                      } ${!option.available ? "cursor-not-allowed opacity-50" : ""}`}
                    >
                      <input
                        type="radio"
                        name="llm-model"
                        checked={choisi}
                        disabled={!option.available}
                        onChange={() => setSelected(option.id)}
                        className="accent-signal"
                      />
                      <Icon
                        name={PROVIDER_ICONS[option.provider] ?? "psychology"}
                        className="text-18 text-ink-dim"
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-body-sm text-ink">{option.label}</p>
                        <p className="truncate font-mono-label text-10 text-ink-faint">
                          {option.id}
                        </p>
                      </div>
                      <span
                        className={`font-mono-label text-10 ${
                          LOCAUX.has(option.provider) ? "text-ink-dim" : "text-warn"
                        }`}
                      >
                        {LOCAUX.has(option.provider) ? "local" : "distant"}
                      </span>
                      {!option.available && (
                        <span className="font-mono-label text-10 uppercase text-ink-dim">
                          clé API manquante
                        </span>
                      )}
                    </label>
                  );
                })}
                {options.length === 0 && !loadError && (
                  <p className="text-body-sm text-ink-dim">Chargement des modèles disponibles…</p>
                )}
              </div>

              <div className="mt-4 flex items-center gap-3">
                <button
                  onClick={() => void handleSave()}
                  disabled={saving || !selected || selected === enregistre}
                  className="rounded-[10px] bg-signal px-4 py-2 text-body-sm font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {saving ? "Enregistrement…" : "Enregistrer"}
                </button>
                {saved && (
                  <span className="flex items-center gap-1 text-body-sm text-signal">
                    <Icon name="check_circle" className="text-16" />
                    Enregistré
                  </span>
                )}
              </div>
            </section>

            <section className="rounded-[18px] border border-line bg-panel p-4">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                  Où ce modèle intervient
                </h2>
              </div>
              <div className="mt-3 flex flex-col gap-1.5">
                {USAGES.map((u) => (
                  <div
                    key={u.nom}
                    className="grid grid-cols-1 gap-1 rounded-xl border border-line bg-panel-sunken px-3 py-2.5 md:grid-cols-[minmax(0,1fr)_12rem_16rem] md:items-center md:gap-3"
                  >
                    <span className="text-body-sm font-semibold text-ink">{u.nom}</span>
                    <span className="font-mono-data text-11 text-ink-dim">{u.quand}</span>
                    <span className="font-mono-data text-11 text-ink-faint">{u.note}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex flex-col gap-1.5 border-t border-line-soft pt-3">
                <p className="text-body-sm text-ink-dim">
                  <span className="font-semibold text-ink">Pas ce modèle :</span> l&apos;arbitrage
                  des annonces incertaines utilise qwen3:8b.
                </p>
                <p className="text-body-sm text-ink-dim">
                  <span className="font-semibold text-ink">Pas un LLM :</span> la traduction
                  passe par un modèle local, sans appel réseau.
                </p>
              </div>
            </section>
          </div>

          <aside className="pulse-panel p-4">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">Garde-fous</h2>
            <ul className="mt-2.5 flex flex-col gap-2.5 text-body-sm">
              {[
                ["ok", "Aucune sortie du modèle ne modifie une gravité ni un rattachement : l'échelle est calculée par les règles."],
                ["ok", "Le verdict du modèle sur une annonce est stocké à part : il ne remplace jamais le classement des règles."],
                ["ok", "Chaque résumé dit sur quoi il a été établi — un résumé sans assiette n'est pas vérifiable."],
                ["ok", "Un modèle indisponible ne fait pas échouer le rapport : faits et preuves restent produits par le code."],
                [local === false ? "warn" : "ok", local === false
                  ? "Modèle distant : les extraits d'annonces soumis quittent l'instance."
                  : "Modèle local : aucun extrait ne quitte l'instance."],
              ].map(([ton, texte]) => (
                <li key={texte} className="flex gap-2.5">
                  <Icon
                    name={ton === "warn" ? "warning" : "check"}
                    className={`mt-0.5 text-15 ${ton === "warn" ? "text-warn" : "text-signal"}`}
                  />
                  <span className={ton === "warn" ? "text-warn" : "text-ink"}>{texte}</span>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      </div>
    </AppLayout>
  );
}
