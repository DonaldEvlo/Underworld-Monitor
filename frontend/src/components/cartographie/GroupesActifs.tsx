import type { GroupStatApi } from "../../api/stats";
import { Icon } from "../ui/Icon";

/**
 * Les groupes attaquants les plus actifs, et où ils frappent.
 *
 * ⚠️ Sélectionner un groupe FILTRE le globe sur ses seules victimes : c'est
 * ce qui transforme une carte descriptive en outil d'analyse — « qui frappe
 * où » plutôt que « combien au total ».
 *
 * ⚠️ Le nombre de pays est un nombre de pays IDENTIFIABLES. ~70 % des domaines
 * de victimes sont des gTLD (.com/.net) et ne portent aucun indice de pays :
 * « 23 pays » ne veut pas dire « 23 pays touchés ».
 */
function depuis(iso: string | null): string {
  // ⚠️ `null` = ce site ne date pas ses annonces, PAS « inactif ». Le dire.
  if (!iso) return "ne date pas ses annonces";
  const jours = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (jours <= 0) return "aujourd'hui";
  if (jours === 1) return "hier";
  if (jours < 31) return `il y a ${jours} j`;
  return `il y a ${Math.floor(jours / 30)} mois`;
}

export function GroupesActifs({
  groupes,
  selection,
  onSelect,
}: {
  groupes: GroupStatApi[];
  selection: string | null;
  onSelect: (sourceId: string | null) => void;
}) {
  return (
    <section className="pulse-panel p-4">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <h3 className="font-display text-15 font-bold tracking-tight text-ink">
            Groupes que nous collectons
          </h3>
          <span className="font-mono-label text-10.5 text-ink-faint">
            {groupes.length} groupes
          </span>
        </div>
        {selection && (
          <button
            onClick={() => onSelect(null)}
            className="flex items-center gap-1 rounded-md border border-line px-2 py-1 font-mono-data text-11 text-ink-dim transition-colors hover:bg-panel-raised"
          >
            <Icon name="close" className="text-13" />
            Tout voir
          </button>
        )}
      </div>
      <p className="mb-3 text-body-sm text-ink-dim">
        Choisissez un groupe : le globe et les deux panneaux ci-dessous ne gardent que ses
        victimes.
      </p>

      <div className="custom-scrollbar flex max-h-[24rem] flex-col gap-2 overflow-y-auto pr-1">
        {groupes.map((groupe) => {
          const actif = selection === groupe.source_id;
          // ⚠️ LA BARRE DIT UN RAPPORT, PAS UN VOLUME. Le volume est déjà le
          // nombre affiché à droite ; ce qu'on ne lisait nulle part, c'est
          // quelle PART des revendications d'un groupe est confirmée par un
          // observateur indépendant. C'est la distinction centrale du produit.
          const confirmees = Math.min(groupe.corroborated_domains, groupe.victim_domains);
          const partConfirmee = groupe.victim_domains
            ? (confirmees / groupe.victim_domains) * 100
            : 0;

          return (
            <button
              key={groupe.source_id}
              onClick={() => onSelect(actif ? null : groupe.source_id)}
              aria-pressed={actif}
              className={`rounded-xl border px-3 py-2.5 text-left transition-colors ${
                actif
                  ? "border-signal/45 bg-signal/[0.06] shadow-[0_0_0_1px_rgba(62,232,184,0.16)]"
                  : "border-line bg-panel-sunken hover:border-signal/30"
              }`}
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={`text-body-sm font-semibold ${actif ? "text-signal" : "text-ink"}`}
                >
                  {groupe.name}
                </span>
                <span className="font-mono-label text-10.5 text-ink-faint">
                  {depuis(groupe.last_published_at)}
                </span>
                {!groupe.active && (
                  <span className="rounded border border-line px-1.5 font-mono-label text-10 text-ink-dim">
                    non collecté
                  </span>
                )}
                <span
                  className={`ml-auto font-mono-data text-11 tabular-nums ${
                    actif ? "text-signal" : "text-ink"
                  }`}
                >
                  {groupe.victim_domains}
                </span>
              </div>

              <div className="mt-2 flex h-[7px] overflow-hidden rounded bg-panel-raised">
                <div className="bg-ok" style={{ width: `${partConfirmee}%` }} />
                <div className="bg-critical" style={{ width: `${100 - partConfirmee}%` }} />
              </div>

              <p className="mt-1.5 font-mono-label text-10 text-ink-dim">
                {groupe.countries.length === 0 ? (
                  // ⚠️ « 0 pays » n'est pas « aucune victime » : ce groupe ne
                  // frappe peut-être que des organisations en gTLD.
                  <>aucun pays identifiable</>
                ) : (
                  <>{groupe.countries.length} pays identifiables</>
                )}
                {confirmees > 0 ? ` · ${confirmees} confirmées` : " · aucune confirmée"}
              </p>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-line-soft pt-2.5 font-mono-label text-10 text-ink-dim">
        <span className="flex items-center gap-1.5">
          <span className="h-[5px] w-4 rounded bg-ok" />
          confirmée par un tiers
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-[5px] w-4 rounded bg-critical" />
          revendiquée seulement
        </span>
      </div>
    </section>
  );
}
