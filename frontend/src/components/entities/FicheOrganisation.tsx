import { useState } from "react";
import { entitiesApi, type EntityApi, type SectorOption } from "../../api/entities";
import { nomPays } from "../../lib/alertes";
import { Icon } from "../ui/Icon";

const CHAMP =
  "rounded-lg border border-line bg-panel-sunken px-2.5 py-1 text-12 text-ink outline-none transition-colors focus:border-signal/60 disabled:opacity-50";

/** Groupe, pays et secteur DÉCLARÉS d'une organisation (migration 0033).
 *
 * ⚠️ Ce que l'on déclare ici PRIME sur ce qu'en dit le tiers
 * (ransomware.live) : le pays et le secteur d'une alerte passent sur la
 * valeur déclarée, et la gravité est recalculée tout de suite côté serveur.
 * Un seul niveau de groupe : un groupe ne peut pas être lui-même une filiale.
 */
export function FicheOrganisation({
  entite,
  toutes,
  secteurs,
  admin,
  onModifiee,
}: {
  entite: EntityApi;
  toutes: EntityApi[];
  secteurs: SectorOption[];
  admin: boolean;
  onModifiee: (e: EntityApi) => void;
}) {
  const [edition, setEdition] = useState(false);
  const [parent, setParent] = useState(entite.parent_id ?? "");
  const [pays, setPays] = useState(entite.country ?? "");
  const [secteur, setSecteur] = useState(entite.sector ?? "");
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const groupe = toutes.find((e) => e.id === entite.parent_id);
  const aDesFiliales = toutes.some((e) => e.parent_id === entite.id);
  // Un seul niveau : ne proposer comme groupe que des organisations qui ne
  // sont pas elles-mêmes filiales.
  const groupesPossibles = toutes
    .filter((e) => e.id !== entite.id && !e.parent_id)
    .sort((a, b) => a.name.localeCompare(b.name, "fr"));
  const libelleSecteur = secteurs.find((s) => s.value === entite.sector);

  function ouvrir() {
    setParent(entite.parent_id ?? "");
    setPays(entite.country ?? "");
    setSecteur(entite.sector ?? "");
    setErreur(null);
    setEdition(true);
  }

  async function enregistrer() {
    setEnCours(true);
    setErreur(null);
    try {
      onModifiee(
        await entitiesApi.update(entite.id, {
          parent_id: parent || null,
          country: pays.trim() || null,
          sector: secteur || null,
        }),
      );
      setEdition(false);
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Modification impossible");
    } finally {
      setEnCours(false);
    }
  }

  if (edition) {
    return (
      <div className="mt-2.5 flex flex-col gap-2 rounded-xl border border-signal/25 bg-panel-sunken p-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-12 text-ink-dim">
            Groupe
            <select
              value={parent}
              onChange={(e) => setParent(e.target.value)}
              disabled={enCours || aDesFiliales}
              title={aDesFiliales ? "Cette organisation a des filiales : elle ne peut pas devenir filiale" : undefined}
              className={CHAMP}
            >
              <option value="">— aucun (organisation autonome) —</option>
              {groupesPossibles.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-12 text-ink-dim">
            Pays
            <input
              value={pays}
              onChange={(e) => setPays(e.target.value.toUpperCase().slice(0, 2))}
              placeholder="ISO"
              disabled={enCours}
              className={`${CHAMP} w-14 font-mono-data uppercase placeholder:normal-case placeholder:text-ink-faint`}
            />
            {pays.length === 2 && <span className="text-11 text-ink-faint">{nomPays(pays)}</span>}
          </label>
          <label className="flex items-center gap-1.5 text-12 text-ink-dim">
            Secteur
            <select value={secteur} onChange={(e) => setSecteur(e.target.value)} disabled={enCours} className={CHAMP}>
              <option value="">— non déclaré —</option>
              {secteurs.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                  {s.critical ? " (NIS2)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-11 text-ink-faint">
          Le pays et le secteur déclarés remplacent ceux de la source tierce sur les alertes de cette organisation ; la
          gravité est recalculée aussitôt.
        </p>
        {erreur && <p className="text-12 text-critical">{erreur}</p>}
        <div className="flex gap-2">
          <button
            onClick={() => void enregistrer()}
            disabled={enCours || (pays.length > 0 && pays.length !== 2)}
            className="rounded-[10px] bg-signal px-3 py-1 text-12 font-semibold text-on-signal disabled:opacity-50"
          >
            {enCours ? "Enregistrement…" : "Enregistrer"}
          </button>
          <button onClick={() => setEdition(false)} className="rounded-[10px] border border-line px-3 py-1 text-12 text-ink-dim hover:text-ink">
            Annuler
          </button>
        </div>
      </div>
    );
  }

  const rien = !groupe && !entite.country && !entite.sector;
  if (rien && !admin) return null;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-12">
      {groupe && (
        <span className="rounded-md bg-panel-raised px-2 py-0.5 text-ink-dim">
          filiale de <span className="text-ink">{groupe.name}</span>
        </span>
      )}
      {entite.country && (
        <span className="rounded-md bg-panel-raised px-2 py-0.5 text-ink-dim" title={entite.country}>
          {nomPays(entite.country)}
        </span>
      )}
      {entite.sector && (
        <span
          className={`rounded-md px-2 py-0.5 ${libelleSecteur?.critical ? "bg-warn/[0.14] text-warn" : "bg-panel-raised text-ink-dim"}`}
          title={libelleSecteur?.critical ? "Secteur critique (NIS2)" : undefined}
        >
          {libelleSecteur?.label ?? entite.sector}
          {libelleSecteur?.critical ? " · NIS2" : ""}
        </span>
      )}
      {admin && (
        <button
          onClick={ouvrir}
          className="flex items-center gap-1 rounded-md border border-dashed border-line px-2 py-0.5 text-ink-faint transition-colors hover:text-ink"
        >
          <Icon name="edit" className="text-13" />
          {rien ? "groupe, pays, secteur" : "modifier"}
        </button>
      )}
    </div>
  );
}
