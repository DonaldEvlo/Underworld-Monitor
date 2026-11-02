import { useState } from "react";
import { statsApi, type GroupStatApi, type ThreatActorsResponse } from "../../api/stats";
import { useRequete } from "../../hooks/useRequete";
import { nomPays } from "../../lib/alertes";
import { jour } from "../../lib/format";
import { CONTINENT_COLORS } from "../../data/countryCentroids";

const MONDE = "Monde";

// Les libellés de `enrich/geo` sont des clés sans accents : accentués à
// l'affichage seulement (même table que la page Gouvernance).
const CONTINENTS_FR: Record<string, string> = {
  "Amerique du Nord": "Amérique du Nord",
  "Amerique du Sud": "Amérique du Sud",
  Oceanie: "Océanie",
};
const continentFr = (c: string) => CONTINENTS_FR[c] ?? c;

const pourcent = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)} %`);

/**
 * Qui attaque quelle région : le classement des groupes sur un continent ou
 * un pays (2026-10-05).
 *
 * ⚠️ DEUX SOURCES, DEUX QUESTIONS — et la page doit le dire. Le globe montre
 * NOTRE collecte (victimes que nous avons lues, localisées par leur domaine).
 * Ce classement lit les historiques ransomware.live (pays DÉCLARÉ par ce
 * tiers), parce que « qui attaque l'Afrique ? » ne se mesure pas sur les
 * seuls groupes que nous collectons — ce serait se demander qui frappe sous le
 * réverbère. Le drapeau « collecté » relie les deux : la part des victimes
 * portée par des groupes NON collectés est notre trou de couverture.
 *
 * ⚠️ Comptes seulement, aucune victime nommée : le RSSI y a accès.
 */
export function MenaceParRegion({
  groupes,
  onSelectGroupe,
}: {
  groupes: GroupStatApi[];
  onSelectGroupe: (sourceId: string) => void;
}) {
  // `null` = continent par défaut, celui que la plateforme met en avant
  // (Afrique), fixé par le serveur à la première réponse.
  const [continent, setContinent] = useState<string | null>(null);
  const [pays, setPays] = useState("");

  const regionReq = useRequete(
    () => statsApi.threatActors({ continent: continent ?? "Afrique" }),
    [continent],
  );
  const paysReq = useRequete(
    () => statsApi.threatActors({ country: pays }),
    [pays],
    { actif: pays !== "" },
  );
  const region: ThreatActorsResponse | null = regionReq.donnees;
  const vue: ThreatActorsResponse | null = pays ? paysReq.donnees : region;
  const erreur = pays ? paysReq.erreur : regionReq.erreur;
  const continentActif = continent ?? "Afrique";

  const sourceDuGang = (gang: string) =>
    groupes.find((g) => g.gang_slug && g.gang_slug === gang.toLowerCase().replace(/[^a-z0-9]/g, ""));

  const continents = (region?.continents ?? []).filter((c) => c.label !== "non renseigné");
  const max = Math.max(1, ...(vue?.actors ?? []).map((a) => a.victims));
  // ⚠️ Le libellé vient de la RÉPONSE, jamais de la sélection : pendant le
  // rechargement, l'ancienne réponse reste affichée, et un titre « le monde »
  // au-dessus des chiffres de l'Afrique mentirait (constaté au test).
  const libelleRegion = vue?.country
    ? (nomPays(vue.country) ?? vue.country)
    : vue?.continent
      ? continentFr(vue.continent)
      : "le monde";
  const enCours = pays ? paysReq.chargement : regionReq.chargement;

  return (
    <section className="pulse-panel mt-3.5 p-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-display text-15 font-bold tracking-tight text-ink">Qui attaque quelle région</h3>
        <span className="text-body-sm text-ink-dim">
          victimes publiées par les groupes{vue ? ` depuis le ${jour(vue.window_start)}` : ""} · pays déclaré par
          ransomware.live
        </span>
      </div>

      {/* Région : continents (volume sur la fenêtre), puis pays. */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {[{ label: MONDE, count: null as number | null }, ...continents].map((c) => {
          const actif = continentActif === c.label;
          const misEnAvant = region?.highlighted.includes(c.label);
          return (
            <button
              key={c.label}
              onClick={() => {
                setContinent(c.label);
                setPays("");
              }}
              aria-pressed={actif}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-12 transition-colors ${
                actif ? "border-signal/50 bg-signal/[0.12] text-signal" : "border-line text-ink-dim hover:text-ink"
              }`}
            >
              {c.label !== MONDE && (
                <span
                  aria-hidden="true"
                  className="h-2 w-2 rounded-full"
                  style={{ background: CONTINENT_COLORS[c.label] ?? "#9AA5B1" }}
                />
              )}
              {continentFr(c.label)}
              {c.count != null && <span className="font-mono-data text-11 opacity-75">{c.count}</span>}
              {misEnAvant && <span className="font-mono-label text-10 text-warn">surveillé</span>}
            </button>
          );
        })}
        {continentActif !== MONDE && (region?.countries.length ?? 0) > 0 && (
          <select
            value={pays}
            onChange={(e) => setPays(e.target.value)}
            aria-label="Pays"
            className="ml-auto rounded-[10px] border border-line bg-panel px-2.5 py-1.5 text-12 text-ink-dim outline-none focus:border-signal/60"
          >
            <option value="">tout le continent</option>
            {region?.countries.map((c) => (
              <option key={c.code} value={c.code}>
                {nomPays(c.code)} · {c.count}
              </option>
            ))}
          </select>
        )}
      </div>

      {erreur && <p className="mt-3 text-body-sm text-critical">Classement indisponible : {erreur}</p>}
      {!vue && !erreur && <p className="mt-3 text-body-sm text-ink-dim">Chargement du classement…</p>}

      {vue && (
        <div className={`transition-opacity ${enCours ? "opacity-50" : ""}`} aria-busy={enCours}>
          <div className="mt-3.5 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { v: vue.total.toLocaleString("fr-FR"), l: `victimes publiées · ${libelleRegion}` },
              { v: vue.gangs, l: "groupes actifs sur la région" },
              { v: pourcent(vue.critical_sector_share), l: "en secteur critique (NIS2)" },
              {
                v: pourcent(vue.collected_share),
                l: "portées par des groupes que nous collectons",
                ton: (vue.collected_share ?? 1) < 0.5 ? "text-warn" : "text-ok",
              },
            ].map((k) => (
              <div key={k.l} className="rounded-xl border border-line bg-panel-sunken px-3.5 py-2.5">
                <p className={`font-mono-data text-20 tabular-nums ${k.ton ?? "text-ink"}`}>{k.v}</p>
                <p className="text-12 text-ink-dim">{k.l}</p>
              </div>
            ))}
          </div>

          {vue.actors.length === 0 ? (
            <p className="mt-3 text-body-sm text-ink-dim">Aucune victime publiée sur cette région dans la fenêtre.</p>
          ) : (
            <ol className="mt-3.5 flex flex-col gap-1.5">
              {vue.actors.map((a, i) => {
                const source = a.collected ? sourceDuGang(a.gang) : undefined;
                return (
                  <li
                    key={a.gang}
                    className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-xl border border-line bg-panel-sunken px-3 py-2 md:grid-cols-[1.5rem_11rem_minmax(0,1fr)_4.5rem_minmax(0,14rem)_5.5rem_7rem]"
                  >
                    <span className="font-mono-data text-11 text-ink-faint">{i + 1}</span>
                    <span className="truncate font-semibold text-ink" title={a.gang}>
                      {source?.name ?? a.gang}
                    </span>
                    <span className="hidden h-2 overflow-hidden rounded-full bg-panel md:block">
                      <span
                        className="block h-full rounded-full bg-critical/70"
                        style={{ width: `${Math.max(2, (100 * a.victims) / max)}%` }}
                      />
                    </span>
                    <span className="text-right font-mono-data text-12 tabular-nums text-ink" title={`${pourcent(a.share)} des victimes de la région`}>
                      {a.victims} <span className="text-ink-faint">· {pourcent(a.share)}</span>
                    </span>
                    <span className="col-span-3 truncate text-12 text-ink-dim md:col-span-1" title={a.countries.map((c) => `${nomPays(c.code)} ${c.count}`).join(", ")}>
                      {pays
                        ? `dernière le ${jour(a.last_discovered)}`
                        : a.countries.map((c) => `${nomPays(c.code)} ${c.count}`).join(" · ")}
                      {!pays && a.country_count > a.countries.length && ` · +${a.country_count - a.countries.length}`}
                    </span>
                    <span className="hidden font-mono-data text-11 text-ink-dim md:block" title="Part de ses victimes en secteur critique (NIS2)">
                      NIS2 {pourcent(a.critical_sector_share)}
                    </span>
                    <span className="col-span-3 md:col-span-1 md:justify-self-end">
                      {a.collected ? (
                        source ? (
                          <button
                            onClick={() => {
                              onSelectGroupe(source.source_id);
                              window.scrollTo({ top: 0, behavior: "smooth" });
                            }}
                            className="rounded-md bg-signal/[0.12] px-2 py-0.5 font-mono-label text-10 text-signal hover:bg-signal/20"
                            title="Nous lisons son site : afficher nos victimes de ce groupe sur le globe"
                          >
                            collecté · globe
                          </button>
                        ) : (
                          <span className="rounded-md bg-signal/[0.12] px-2 py-0.5 font-mono-label text-10 text-signal">collecté</span>
                        )
                      ) : (
                        <span
                          className="rounded-md border border-warn/40 px-2 py-0.5 font-mono-label text-10 text-warn"
                          title="Nous ne lisons pas le site de ce groupe : ses victimes ne produisent pas d'alerte"
                        >
                          non collecté
                        </span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ol>
          )}

          <p className="mt-3 font-mono-label text-10.5 leading-relaxed text-ink-faint">
            {vue.other_actors > 0 && `${vue.other_actors} autre(s) groupe(s) non affiché(s) · `}
            classement établi sur les {vue.coverage_gangs} groupes dont l&apos;historique est en cache — un groupe absent
            n&apos;est pas un groupe inactif · pays tel que déclaré par le tiers, jamais déduit
            {vue.unknown_country > 0 && ` · ${vue.unknown_country} victime(s) sans pays`}
          </p>
        </div>
      )}
    </section>
  );
}
