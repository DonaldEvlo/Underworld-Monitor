import { Link } from "react-router-dom";
import type { ActivityApi } from "../../api/activity";
import { documentsApi } from "../../api/documents";
import { useRequete } from "../../hooks/useRequete";

interface CeQuiBloqueProps {
  activite: ActivityApi | null;
}

function Bloc({
  valeur,
  titre,
  explication,
  ton,
  vers,
  action,
}: {
  valeur: number;
  titre: string;
  explication: string;
  ton: "warn" | "info" | "neutre";
  vers: string;
  action: string;
}) {
  const cadre = {
    warn: "border-warn/30",
    info: "border-info/25",
    neutre: "border-line",
  }[ton];
  const chiffre = {
    warn: "text-warn",
    info: "text-info",
    neutre: "text-ink",
  }[ton];

  return (
    <div className={`rounded-xl border bg-panel-sunken p-3 ${cadre}`}>
      <div className="flex items-baseline gap-2">
        <span className={`font-mono-data text-22 font-semibold tabular-nums ${chiffre}`}>
          {valeur}
        </span>
        <span className="text-body-sm font-semibold text-ink">{titre}</span>
      </div>
      <p className="mt-1 text-body-sm text-ink-dim">{explication}</p>
      <Link
        to={vers}
        className="mt-2 inline-block font-mono-label text-11 text-signal hover:underline"
      >
        {action} →
      </Link>
    </div>
  );
}

/** Les angles morts : ce que la plateforme ne peut PAS voir aujourd'hui.
 *
 * ⚠️ Ce panneau ne compte pas du travail, il compte des EMPECHEMENTS. Une
 * organisation sans selecteur ne produira jamais d'alerte quelle que soit la
 * collecte — c'est une panne silencieuse, invisible partout ailleurs dans
 * l'interface, qui se lisait comme un simple detail de saisie.
 */
export function CeQuiBloque({ activite }: CeQuiBloqueProps) {
  // `limit: 1` : on ne veut que le total, filtré EN SQL. Charger les
  // documents pour les compter côté navigateur donnerait un chiffre faux dès
  // que la pagination tronque. Un échec masque le bloc plutôt qu'inventer.
  const requete = useRequete(
    async () => (await documentsApi.list({ limit: 1, announcement_class: ["uncertain"] })).total,
    [],
  );
  const incertains: number | null = requete.donnees;

  if (!activite) return null;

  const rien =
    activite.entites_sans_selecteur === 0 &&
    activite.sources_en_echec === 0 &&
    (incertains ?? 0) === 0;

  return (
    <section className="pulse-panel p-4">
      <h2 className="font-display text-15 font-bold tracking-tight text-ink">
        Ce qui bloque la veille
      </h2>

      {rien ? (
        <p className="mt-3 text-body-sm text-ink-dim">
          Aucun angle mort.
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-2.5">
          {activite.entites_sans_selecteur > 0 && (
            <Bloc
              valeur={activite.entites_sans_selecteur}
              titre="organisations n'alerteront jamais"
              explication="Sans sélecteur, aucune alerte possible."
              ton="warn"
              vers="/entities"
              action="déclarer les sélecteurs"
            />
          )}
          {activite.sources_en_echec > 0 && (
            <Bloc
              valeur={activite.sources_en_echec}
              titre="sources en échec"
              explication="Souvent temporaire."
              ton="info"
              vers="/sources"
              action="tester la disponibilité"
            />
          )}
          {incertains !== null && incertains > 0 && (
            <Bloc
              valeur={incertains}
              titre="documents incertains"
              explication="Ni fuite ni bruit selon les règles."
              ton="neutre"
              vers="/documents"
              action="trier les incertains"
            />
          )}
        </div>
      )}
    </section>
  );
}
