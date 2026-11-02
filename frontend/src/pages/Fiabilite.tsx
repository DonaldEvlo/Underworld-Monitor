import { useState } from "react";
import { linksApi, type LinkHealthApi, type LinkStatus } from "../api/links";
import { passwordsApi, type PasswordBreachApi } from "../api/passwords";
import { statsApi, type GroupStatApi } from "../api/stats";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { useRequete } from "../hooks/useRequete";

/** Nombre de documents analysés par passe. Volontairement modeste : chaque
 * hôte ou mot de passe unique coûte une requête réseau, et l'analyste attend. */
const DOCUMENT_CHOICES = [50, 100, 200, 500];

const LINK_STATUS_LABELS: Record<LinkStatus, string> = {
  alive: "En ligne",
  gone: "Supprimé",
  restricted: "Accès restreint",
  server_error: "Erreur serveur",
  unreachable: "Injoignable",
};

const LINK_STATUS_STYLES: Record<LinkStatus, string> = {
  alive: "bg-ok/15 text-ok",
  gone: "bg-critical/15 text-critical",
  restricted: "bg-warn/15 text-warn",
  server_error: "bg-warn/15 text-warn",
  unreachable: "bg-panel-raised text-ink-dim",
};

/** Tranches d'apparitions HIBP, de la plus massive à la plus rare. */
const BUCKET_LABELS: Record<string, string> = {
  "100k+": "Plus de 100 000 fois (recyclage massif)",
  "1k-100k": "1 000 à 100 000 fois",
  "10-1k": "10 à 1 000 fois",
  "1-10": "Moins de 10 fois (rare, signal fort)",
};
const BUCKET_ORDER = ["100k+", "1k-100k", "10-1k", "1-10"];

const PANNEAU = "rounded-[18px] border border-line bg-panel";
const CHAMP = "rounded-lg border border-line bg-panel-sunken px-3 py-1.5 text-body-sm text-ink outline-none focus:border-signal/60 disabled:opacity-50";

function percent(ratio: number | null): string {
  return ratio === null ? "—" : `${Math.round(ratio * 100)} %`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[14px] border border-line bg-panel-sunken px-4 py-3">
      <p className="font-caption text-caption text-ink-faint">{label}</p>
      <p className="mt-1 font-mono-data text-20 tabular-nums text-ink">{value}</p>
      {hint && <p className="mt-0.5 text-11 text-ink-dim">{hint}</p>}
    </div>
  );
}

function RunButton({ running, onClick, label }: { running: boolean; onClick: () => void; label: string }) {
  return (
    <button onClick={onClick} disabled={running} className="flex items-center gap-2 rounded-[10px] bg-signal px-3.5 py-2 text-13 font-semibold text-on-signal transition-opacity hover:opacity-90 disabled:opacity-50">
      {running && <Icon name="progress_activity" className="animate-spin text-15" />}
      {running ? "Analyse en cours…" : label}
    </button>
  );
}

/**
 * Fiabilité des sources — MESURÉE, pas déclarée.
 *
 * Part des victimes revendiquées par une source qu'un agrégateur tiers
 * (RansomLook, ransomware.live) a aussi indexées. Il lit le MÊME site : c'est
 * de la couverture, pas une vérification indépendante. Calculée sur les données déjà en base, sans appel.
 *
 * ⚠️ La maquette ajoutait que ce taux « fixe le poids de l'annonce dans la
 * gravité ». C'est FAUX : la gravité se décide détection par détection, sur la
 * corroboration de CETTE victime — jamais sur une moyenne de la source. Le
 * dire aurait fait croire à un mécanisme qui n'existe pas.
 */
function SourcesSection() {
  const requete = useRequete(async () => (await statsApi.groups()).groups, []);
  const groupes: GroupStatApi[] | null = requete.donnees;
  const erreur = requete.erreur;

  return (
    <section className={`${PANNEAU} mb-3.5 overflow-hidden`}>
      <div className="border-b border-line px-4 py-3.5">
        <h2 className="font-display text-15 font-bold tracking-tight text-ink">Fiabilité des sources</h2>
        <p className="mt-0.5 font-mono-label text-11 text-ink-dim">
          mesurée, pas déclarée : part des victimes revendiquées qu&apos;un agrégateur tiers a aussi indexées — il lit le même site : couverture, pas indépendance
        </p>
      </div>
      {erreur && <p className="px-4 py-3 text-body-sm text-critical">Impossible de charger les sources : {erreur}</p>}
      {groupes === null && !erreur && <p className="px-4 py-3 text-body-sm text-ink-dim">Chargement…</p>}
      {groupes && groupes.length === 0 && (
        <p className="px-4 py-3 text-body-sm text-ink-dim">Aucune source ne publie de victimes nommées pour l&apos;instant.</p>
      )}
      {groupes && groupes.length > 0 && (
        <div className="overflow-x-auto">
          <div className="min-w-[640px]">
            <div className="grid grid-cols-[minmax(0,1fr)_8rem_8rem_12rem] gap-3.5 border-b border-line px-4 py-2.5 font-mono-label text-10 uppercase tracking-[0.12em] text-ink-faint">
              <span>Source</span>
              <span>Revendiquées</span>
              <span>Confirmées</span>
              <span>Taux</span>
            </div>
            {groupes.map((g) => {
              const taux = g.victim_domains ? Math.min(1, g.corroborated_domains / g.victim_domains) : 0;
              return (
                <div key={g.source_id} className="grid grid-cols-[minmax(0,1fr)_8rem_8rem_12rem] items-center gap-3.5 border-b border-line-soft px-4 py-2.5 last:border-b-0">
                  <div className="min-w-0">
                    <p className="truncate text-13 font-semibold text-ink">{g.name}</p>
                    <p className="font-mono-label text-10 text-ink-faint">site de fuite · {g.active ? "collecté" : "non collecté"}</p>
                  </div>
                  <span className="font-mono-data text-12 text-ink-dim">{g.victim_domains}</span>
                  <span className="font-mono-data text-12 text-ink-dim">{g.corroborated_domains}</span>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 flex-1 rounded-full bg-panel-raised">
                      <div className="h-1.5 rounded-full bg-ok" style={{ width: `${taux * 100}%` }} />
                    </div>
                    <span className="w-10 text-right font-mono-data text-11 text-ok">{Math.round(taux * 100)} %</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      <p className="border-t border-line px-4 py-2.5 font-mono-label text-11 text-ink-faint">
        un taux bas ne disqualifie pas la source : les agrégateurs ne couvrent pas tous les gangs
      </p>
    </section>
  );
}

function LinksSection() {
  const [limit, setLimit] = useState(100);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<LinkHealthApi | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(await linksApi.check(limit));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className={`${PANNEAU} mb-3.5 p-4`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">Vivacité des liens annoncés</h2>
          <p className="mt-1 max-w-2xl text-body-sm text-ink-dim">
            Statut et titre des liens uniquement, jamais leur contenu.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} disabled={running} className={CHAMP}>
            {DOCUMENT_CHOICES.map((n) => (
              <option key={n} value={n}>
                {n} documents
              </option>
            ))}
          </select>
          <RunButton running={running} onClick={() => void run()} label="Vérifier les liens" />
        </div>
      </div>

      {running && (
        <p className="mb-3 font-mono-label text-11 text-ink-dim">
          chaque hôte est interrogé via Tor avec un délai de politesse — comptez une à plusieurs minutes
        </p>
      )}
      {error && <p className="mb-3 text-body-sm text-critical">{error}</p>}
      {!result && !running && <p className="text-body-sm text-ink-dim">Analyse jamais lancée sur cette session.</p>}

      {result && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <Stat label="Documents analysés" value={String(result.documents_scanned)} />
            <Stat label="Contenant des liens" value={String(result.documents_with_links)} />
            <Stat label="Hôtes vérifiés" value={String(result.hosts_checked)} />
            <Stat label="Liens en ligne" value={percent(result.alive_ratio)} />
          </div>
          {result.hosts_checked === 0 ? (
            <p className="text-body-sm text-ink-dim">Aucun lien dans cet échantillon. Essayez un nombre de documents plus élevé.</p>
          ) : (
            <div className="overflow-x-auto rounded-[14px] border border-line">
              <table className="w-full min-w-[720px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-line">
                    {["Hôte", "Statut", "Code", "Titre de la page"].map((h) => (
                      <th key={h} className="px-4 py-2.5 font-mono-label text-10 font-medium uppercase tracking-[0.12em] text-ink-faint">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((item) => (
                    <tr key={item.url} className="border-b border-line-soft last:border-b-0">
                      <td className="max-w-xs px-4 py-2.5">
                        <span className="flex items-center gap-1.5">
                          {item.is_onion && (
                            <span title="Adresse .onion : exige Tor, jamais cliquable" className="rounded bg-info/15 px-1.5 py-0.5 font-mono-label text-10 text-info">
                              TOR
                            </span>
                          )}
                          <span className="truncate font-mono-data text-12 text-ink">{item.host}</span>
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`rounded-md px-2 py-0.5 font-mono-label text-11 ${LINK_STATUS_STYLES[item.status]}`}>{LINK_STATUS_LABELS[item.status]}</span>
                      </td>
                      <td className="px-4 py-2.5 font-mono-data text-12 text-ink-dim">{item.http_status ?? "—"}</td>
                      <td className="max-w-md px-4 py-2.5">
                        <span className="block truncate text-body-sm text-ink-dim">{item.title ?? "—"}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function PasswordsSection() {
  const [limit, setLimit] = useState(100);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PasswordBreachApi | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(await passwordsApi.checkBreaches(limit));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setRunning(false);
    }
  }

  const buckets = result ? BUCKET_ORDER.filter((b) => result.breach_buckets[b]).map((b) => [b, result.breach_buckets[b]] as const) : [];

  return (
    <section className={`${PANNEAU} p-4`}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">Mots de passe déjà compromis</h2>
          <p className="mt-1 max-w-2xl text-body-sm text-ink-dim">
            Le mot de passe ne quitte jamais le serveur (k-anonymity).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} disabled={running} className={CHAMP}>
            {DOCUMENT_CHOICES.map((n) => (
              <option key={n} value={n}>
                {n} documents
              </option>
            ))}
          </select>
          <RunButton running={running} onClick={() => void run()} label="Vérifier les mots de passe" />
        </div>
      </div>

      {running && <p className="mb-3 font-mono-label text-11 text-ink-dim">un appel par mot de passe unique — comptez une à deux minutes</p>}
      {error && <p className="mb-3 text-body-sm text-critical">{error}</p>}
      {!result && !running && <p className="text-body-sm text-ink-dim">Analyse jamais lancée sur cette session.</p>}

      {result && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <Stat label="Identifiants trouvés" value={String(result.credentials_found)} hint={`${result.unique_passwords} mot(s) de passe unique(s)`} />
            <Stat label="Vérifiés" value={String(result.passwords_checked)} />
            <Stat label="Déjà compromis" value={String(result.breached_count)} hint={percent(result.breached_ratio)} />
            <Stat label="Inconnus des fuites" value={String(result.unknown_count)} />
          </div>
          {buckets.length > 0 && (
            <div className="mb-3 rounded-[14px] border border-line bg-panel-sunken p-3.5">
              <p className="mb-2 font-caption text-caption text-ink-faint">Répartition des mots de passe compromis</p>
              {buckets.map(([bucket, count]) => (
                <div key={bucket} className="flex items-center justify-between py-0.5 text-body-sm">
                  <span className="text-ink-dim">{BUCKET_LABELS[bucket] ?? bucket}</span>
                  <span className="font-mono-data tabular-nums text-ink">{count}</span>
                </div>
              ))}
            </div>
          )}
          {result.lookup_errors > 0 && (
            <p className="mb-3 rounded-xl border border-warn/40 bg-warn/10 p-3 text-body-sm text-warn">
              {result.lookup_errors} interrogation(s) en échec (réseau) — non comptabilisées.
            </p>
          )}
          {/* Garde-fou d'interprétation : un taux faible ne signifie pas « corpus
              sain ». Le détecteur capture surtout des faux positifs (numéros,
              champs vides) — sans cette note, le chiffre se lit à l'envers. */}
          {result.passwords_checked > 0 && (result.breached_ratio ?? 0) < 0.2 && (
            <p className="text-body-sm text-ink-dim">
              Taux faible : le détecteur capture souvent autre chose que des mots de passe.
            </p>
          )}
        </>
      )}
    </section>
  );
}

export function Fiabilite() {
  return (
    <AppLayout title="Fiabilité">
      <SourcesSection />
      <LinksSection />
      <PasswordsSection />
    </AppLayout>
  );
}
