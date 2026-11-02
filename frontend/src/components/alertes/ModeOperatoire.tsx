import { useState } from "react";

import {
  alertsApi,
  type AlertModusOperandiResponse,
  type GangModusOperandiApi,
  type GangTechniqueApi,
} from "../../api/alerts";
import { hrefSur } from "../../lib/liens";

/**
 * Mode opératoire HABITUEL des groupes qui revendiquent les victimes de
 * l'alerte : techniques MITRE ATT&CK, outils, CVE citées.
 *
 * ⚠️ Documenté par un tiers SUR LE GANG, à partir d'autres incidents : ce n'est
 * jamais le vecteur de CETTE compromission. La mise en garde vient du serveur
 * et reste affichée en tête — sans elle, « CVE-2023-4966 » sous une alerte se
 * lirait « vous avez été compromis par Citrix Bleed », ce que rien n'établit.
 *
 * Chargé À LA DEMANDE : c'est un appel à un tiers limité à ~1 requête par
 * minute. Une alerte régionale à cinq gangs enchaînerait sinon cinq appels à
 * l'ouverture du dossier, dont quatre heurteraient la limite. Une fois en
 * cache (7 jours côté serveur), la réponse est immédiate.
 */
export function ModeOperatoire({ alertId }: { alertId: string }) {
  const [donnees, setDonnees] = useState<AlertModusOperandiResponse | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  async function charger() {
    setEnCours(true);
    setErreur(null);
    try {
      setDonnees(await alertsApi.modusOperandi(alertId));
    } catch (err) {
      setErreur(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <section className="pulse-panel p-4">
      <h2 className="font-display text-15 font-bold tracking-tight text-ink">
        Mode opératoire du groupe
      </h2>
      <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
        source tierce · techniques MITRE ATT&amp;CK, outils, CVE — sur le groupe, pas sur l&apos;incident
      </p>

      {donnees === null ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void charger()}
            disabled={enCours}
            className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink hover:bg-panel-sunken disabled:opacity-50"
          >
            {enCours ? "Consultation…" : "Consulter le mode opératoire"}
          </button>
          <span className="font-mono-label text-10.5 text-ink-faint">
            appel à ransomware.live — seul le nom du groupe sort de la plateforme
          </span>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          <p className="rounded-xl border border-warn/30 bg-panel-sunken p-2.5 text-body-sm text-ink">
            {donnees.caveat}
          </p>
          {donnees.gangs.length === 0 ? (
            <p className="font-mono-label text-10.5 text-ink-dim">
              aucun groupe identifié pour les victimes de cette alerte
            </p>
          ) : (
            donnees.gangs.map((g) => <ProfilGang key={g.gang} profil={g} />)
          )}
        </div>
      )}

      {erreur ? (
        <p className="mt-2 font-mono-label text-10.5 text-critical">{erreur}</p>
      ) : null}
    </section>
  );
}

function ProfilGang({ profil }: { profil: GangModusOperandiApi }) {
  return (
    <div className="rounded-xl border border-line bg-panel-sunken p-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-display text-body-sm font-bold text-ink">{profil.gang}</span>
        {profil.victims.length > 0 ? (
          <span className="font-mono-label text-10.5 text-ink-dim">
            revendique : {profil.victims.join(", ")}
          </span>
        ) : null}
      </div>

      {profil.status === "unavailable" ? (
        // Absence de MESURE : jamais « aucun mode opératoire connu ».
        <p className="mt-1.5 font-mono-label text-10.5 text-ink-dim">
          source tierce injoignable
        </p>
      ) : profil.status === "undocumented" ? (
        <p className="mt-1.5 font-mono-label text-10.5 text-ink-dim">
          aucun mode opératoire publié pour ce groupe
        </p>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          {profil.cves.length > 0 ? (
            <div>
              <p className="font-mono-label text-10.5 text-ink-dim">
                vulnérabilités exploitées par le groupe
              </p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {profil.cves.map((c) =>
                  c.url ? (
                    <a
                      key={c.cve}
                      href={hrefSur(c.url)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="rounded-md bg-warn/[0.12] px-1.5 py-0.5 font-mono-label text-10.5 text-warn hover:underline"
                    >
                      {c.cve}
                    </a>
                  ) : (
                    <span key={c.cve} className="font-mono-label text-10.5 text-ink">
                      {c.cve}
                    </span>
                  ),
                )}
              </div>
            </div>
          ) : null}
          <Tactiques techniques={profil.techniques} />
          {profil.tool_groups.length > 0 ? (
            <div className="flex flex-col gap-0.5">
              <p className="font-mono-label text-10.5 text-ink-dim">
                outils employés par le groupe — à rechercher dans vos journaux
              </p>
              {profil.tool_groups.map((g) => (
                <p key={g.category || "sans-categorie"} className="text-body-sm text-ink">
                  <span className="font-mono-label text-10.5 text-ink-dim">
                    {libelleCategorie(g.category)} :{" "}
                  </span>
                  {g.tools.join(", ")}
                </p>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// Catégories publiées par ransomware.live (relevées le 2026-09-30). Une
// catégorie inconnue s'affiche telle quelle : mieux vaut un libellé brut qu'un
// outil qui disparaît.
const CATEGORIES: Record<string, string> = {
  CredentialTheft: "Vol d'identifiants",
  DefenseEvasion: "Contournement des défenses",
  DiscoveryEnum: "Reconnaissance du réseau",
  Exfiltration: "Exfiltration",
  LOLBAS: "Outils système détournés (LOLBAS)",
  Networking: "Tunnels réseau",
  Offsec: "Cadres offensifs",
  "RMM-Tools": "Prise de main à distance (RMM)",
};

function libelleCategorie(categorie: string): string {
  if (!categorie) return "Divers";
  return CATEGORIES[categorie] ?? categorie;
}

// Les procédures MITRE arrivent en markdown brut : « [INC Ransom](https://…)
// has used … (Citation: SOCRadar INC Ransom January 2024) ». On garde le
// libellé des liens et on retire les citations : la source reste consultable
// par le lien de la technique.
function nettoyerProcedure(texte: string): string {
  return texte
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/\(Citation:[^)]*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function Tactiques({ techniques }: { techniques: GangTechniqueApi[] }) {
  if (techniques.length === 0) return null;
  // Regroupées par tactique, dans l'ordre fourni (celui de la kill chain ATT&CK).
  const parTactique = new Map<string, GangTechniqueApi[]>();
  for (const t of techniques) {
    const cle = t.tactic_name || t.tactic_id || "Tactique non précisée";
    parTactique.set(cle, [...(parTactique.get(cle) ?? []), t]);
  }
  return (
    <div className="flex flex-col gap-1.5">
      {[...parTactique.entries()].map(([tactique, liste]) => (
        <div key={tactique}>
          <p className="font-mono-label text-10.5 text-ink-dim">{tactique}</p>
          <ul className="mt-0.5 flex flex-col gap-0.5">
            {liste.map((t) => (
              <li key={`${tactique}-${t.technique_id}`} className="text-body-sm text-ink">
                {t.url ? (
                  <a
                    href={hrefSur(t.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-mono-label text-10.5 text-signal hover:underline"
                  >
                    {t.technique_id}
                  </a>
                ) : (
                  <span className="font-mono-label text-10.5 text-ink-dim">
                    {t.technique_id}
                  </span>
                )}{" "}
                {t.technique_name}
                {t.details ? (
                  // Repliée : 28 procédures MITRE dépliées font ~5 000 px de
                  // haut dans la colonne du dossier (mesuré le 2026-10-01).
                  <details className="pl-4">
                    <summary className="cursor-pointer font-mono-label text-10 text-ink-faint">
                      procédure documentée
                    </summary>
                    <span className="block text-12 text-ink-dim">
                      {nettoyerProcedure(t.details)}
                    </span>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
