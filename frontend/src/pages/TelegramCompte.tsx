import { useCallback, useEffect, useState } from "react";
import {
  PHASES_ACTIVES,
  telegramApi,
  type TelegramLogin,
  type TelegramStatus,
} from "../api/telegram";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";

/**
 * Compte de lecture Telegram — réservé à l'administrateur.
 *
 * Remplace la commande `telegram_login` lancée dans un terminal : on affiche un
 * QR, l'administrateur le scanne avec le téléphone du compte dédié, et la
 * collecte passe du simple aperçu web (≈ 20 messages, sans compte) au Client
 * API (100 messages, fichiers joints, canaux sans aperçu).
 *
 * ⚠️ QR CODE, PAS CODE PAR MESSAGE : une application tierce ne reçoit son code
 * que dans l'application Telegram, et il n'arrive souvent jamais (constaté le
 * 2026-09-26). Le QR est la voie officielle pour les applications tierces.
 *
 * ⚠️ AUCUNE IDENTITÉ DU COMPTE N'EST AFFICHÉE (numéro, nom) : la page n'en a
 * pas l'usage, et une capture d'écran de l'interface ne doit pas la révéler.
 *
 * ⚠️ LE QR EST AFFICHÉ EN `<img>`, JAMAIS INJECTÉ COMME HTML : un SVG inséré
 * dans le DOM peut exécuter du script, une image non.
 */

const SONDAGE_MS = 1500;

function imageQr(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function secondesRestantes(iso: string | null, maintenant: number): number | null {
  if (!iso) return null;
  return Math.max(0, Math.round((new Date(iso).getTime() - maintenant) / 1000));
}

function Etat({ ok, oui, non, inconnu }: { ok: boolean | null; oui: string; non: string; inconnu?: string }) {
  const ton =
    ok === null ? "bg-ink-faint" : ok ? "bg-ok" : "bg-warn";
  return (
    <span className="flex items-center gap-2 text-body-sm text-ink">
      <span className={`h-2 w-2 shrink-0 rounded-full ${ton}`} />
      {ok === null ? (inconnu ?? "non vérifié") : ok ? oui : non}
    </span>
  );
}

export function TelegramCompte() {
  const [statut, setStatut] = useState<TelegramStatus | null>(null);
  const [connexion, setConnexion] = useState<TelegramLogin | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [verification, setVerification] = useState(false);
  const [sansTor, setSansTor] = useState(false);
  const [motDePasse, setMotDePasse] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [deconnexionArmee, setDeconnexionArmee] = useState(false);
  const [maintenant, setMaintenant] = useState(() => Date.now());

  const charger = useCallback(async (check = false) => {
    try {
      const s = await telegramApi.status(check);
      setStatut(s);
      setConnexion(s.login);
      setErreur(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur inconnue");
    }
  }, []);

  useEffect(() => {
    telegramApi
      .status()
      .then((s) => {
        setStatut(s);
        setConnexion(s.login);
      })
      .catch((e: unknown) => setErreur(e instanceof Error ? e.message : "Erreur inconnue"));
  }, []);

  const enCours = connexion !== null && PHASES_ACTIVES.includes(connexion.phase);

  // Sondage de l'état de la connexion tant qu'elle est en cours, et horloge
  // du compte à rebours du QR.
  useEffect(() => {
    if (!enCours) return;
    const sondage = window.setInterval(() => {
      telegramApi
        .login()
        .then((l) => {
          setConnexion(l);
          if (l.phase === "connected") void charger();
        })
        .catch((e: unknown) => setErreur(e instanceof Error ? e.message : "Erreur inconnue"));
    }, SONDAGE_MS);
    const horloge = window.setInterval(() => setMaintenant(Date.now()), 1000);
    return () => {
      window.clearInterval(sondage);
      window.clearInterval(horloge);
    };
  }, [enCours, charger]);

  async function verifier() {
    setVerification(true);
    await charger(true);
    setVerification(false);
  }

  async function demarrer() {
    setErreur(null);
    setDeconnexionArmee(false);
    try {
      setConnexion(await telegramApi.startLogin(sansTor));
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Démarrage impossible");
    }
  }

  async function annuler() {
    try {
      setConnexion(await telegramApi.cancel());
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Annulation impossible");
    }
  }

  async function envoyerMotDePasse(e: React.FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    try {
      setConnexion(await telegramApi.password(motDePasse));
    } catch (e2) {
      setErreur(e2 instanceof Error ? e2.message : "Envoi impossible");
    } finally {
      // Le mot de passe ne reste pas dans l'état de la page une fois envoyé.
      setMotDePasse("");
      setEnvoi(false);
    }
  }

  async function deconnecter() {
    setErreur(null);
    try {
      await telegramApi.logout();
      setDeconnexionArmee(false);
      await charger();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Déconnexion impossible");
    }
  }

  const sessionOk = statut?.connected === true && statut.authorized !== false;
  const restantes = secondesRestantes(connexion?.qr_expires_at ?? null, maintenant);

  return (
    <AppLayout title="Compte Telegram">
      <div className="max-w-4xl space-y-5">
        {erreur && (
          <p className="rounded-lg border border-critical/40 bg-critical/10 p-3 text-body-sm text-ink">
            {erreur}
          </p>
        )}

        <section className="pulse-panel p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="font-display text-15 font-bold tracking-tight text-ink">
                État du compte de lecture
              </h2>
              <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
                compte dédié, lecture seule des canaux publics — aucune identité affichée
              </p>
            </div>
            <button
              type="button"
              onClick={() => void verifier()}
              disabled={verification || !statut?.connected || enCours}
              className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim transition-colors hover:border-signal/40 hover:text-signal disabled:opacity-40"
            >
              {verification ? "Vérification…" : "Vérifier auprès de Telegram"}
            </button>
          </div>

          {statut === null ? (
            <p className="mt-3 text-body-sm text-ink-dim">Chargement…</p>
          ) : (
            <dl className="mt-4 grid gap-3 sm:grid-cols-3">
              <div>
                <dt className="font-mono-label text-10 uppercase tracking-wide text-ink-faint">
                  Identifiants API
                </dt>
                <dd className="mt-1">
                  <Etat ok={statut.api_configured} oui="configurés" non="absents du fichier .env" />
                </dd>
              </div>
              <div>
                <dt className="font-mono-label text-10 uppercase tracking-wide text-ink-faint">
                  Compte
                </dt>
                <dd className="mt-1">
                  <Etat ok={statut.connected} oui="connecté" non="non connecté" />
                </dd>
              </div>
              <div>
                <dt className="font-mono-label text-10 uppercase tracking-wide text-ink-faint">
                  Vérifié auprès de Telegram
                </dt>
                <dd className="mt-1">
                  {statut.connected ? (
                    <Etat ok={statut.authorized} oui="session valide" non="session révoquée" />
                  ) : (
                    <span className="text-body-sm text-ink-faint">sans objet</span>
                  )}
                </dd>
              </div>
            </dl>
          )}

          {statut && (
            <p className="mt-4 rounded-lg border border-line bg-panel-sunken p-3 text-body-sm text-ink-dim">
              {sessionOk ? (
                <>
                  Les canaux Telegram sont collectés par le <strong className="text-ink">Client API</strong>{" "}
                  : 100 messages par canal, noms et tailles des fichiers joints (jamais téléchargés),
                  canaux sans aperçu web. Si la session est révoquée, la collecte revient
                  d&apos;elle-même à l&apos;aperçu web.
                </>
              ) : (
                <>
                  Sans session, les canaux sont collectés par l&apos;
                  <strong className="text-ink">aperçu web public</strong> (≈ 20 derniers messages,
                  sans compte). Connecter le compte donne accès à 100 messages, aux fichiers joints
                  et aux canaux sans aperçu.
                </>
              )}
            </p>
          )}
        </section>

        {statut?.api_configured === false && (
          <section className="pulse-panel p-4 text-body-sm text-ink-dim">
            Ajoutez <code className="font-mono-data text-ink">TELEGRAM_API_ID</code> et{" "}
            <code className="font-mono-data text-ink">TELEGRAM_API_HASH</code> (my.telegram.org →
            API development tools) au fichier <code className="font-mono-data text-ink">.env</code>,
            puis redémarrez l&apos;API et le worker.
          </section>
        )}

        {statut?.api_configured && (
          <section className="pulse-panel p-4">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">
              {sessionOk ? "Reconnecter le compte" : "Connecter le compte"}
            </h2>

            {connexion?.phase === "waiting_scan" && connexion.qr_svg ? (
              <div className="mt-4 flex flex-wrap items-start gap-6">
                <img
                  src={imageQr(connexion.qr_svg)}
                  alt="QR code de connexion Telegram"
                  className="h-56 w-56 rounded-lg bg-white p-2"
                />
                <div className="min-w-[240px] flex-1 space-y-3 text-body-sm text-ink">
                  <ol className="list-decimal space-y-1.5 pl-5">
                    <li>Ouvrez Telegram sur le téléphone du compte dédié.</li>
                    <li>
                      <strong>Paramètres → Appareils → Connecter un appareil de bureau</strong>.
                    </li>
                    <li>Scannez ce QR code.</li>
                  </ol>
                  <p className="font-mono-label text-10.5 text-ink-dim">
                    {restantes !== null && restantes > 0
                      ? `QR valable encore ${restantes} s — renouvelé automatiquement`
                      : "renouvellement du QR…"}
                    {" · "}
                    {connexion.via_tor ? "via Tor" : "SANS Tor (exception)"}
                  </p>
                  <button
                    type="button"
                    onClick={() => void annuler()}
                    className="rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim hover:text-ink"
                  >
                    Annuler
                  </button>
                </div>
              </div>
            ) : connexion?.phase === "password_needed" ? (
              <form onSubmit={(e) => void envoyerMotDePasse(e)} className="mt-4 space-y-3">
                <p className="text-body-sm text-ink">
                  QR accepté. Le compte est protégé par la vérification en deux étapes : saisissez
                  son mot de passe.
                </p>
                {connexion.message && (
                  <p className="text-body-sm text-critical">
                    {connexion.message} — {connexion.password_attempts_left} essai(s) restant(s).
                  </p>
                )}
                <div className="flex flex-wrap items-end gap-3">
                  <input
                    type="password"
                    autoComplete="off"
                    value={motDePasse}
                    onChange={(e) => setMotDePasse(e.target.value)}
                    aria-label="Mot de passe de vérification en deux étapes"
                    className="h-10 min-w-[240px] flex-1 rounded-lg border border-line bg-panel-sunken px-3 font-mono-data text-13 text-ink outline-none focus:border-signal"
                  />
                  <button
                    type="submit"
                    disabled={envoi || motDePasse.length === 0}
                    className="h-10 rounded-lg border border-signal/40 bg-signal/10 px-4 text-body-sm font-medium text-signal hover:bg-signal/20 disabled:opacity-40"
                  >
                    {envoi ? "Envoi…" : "Valider"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void annuler()}
                    className="h-10 rounded-lg border border-line px-3 text-body-sm text-ink-dim hover:text-ink"
                  >
                    Annuler
                  </button>
                </div>
                <p className="font-mono-label text-10.5 text-ink-faint">
                  transmis à Telegram puis oublié — jamais journalisé ni conservé
                </p>
              </form>
            ) : connexion?.phase === "starting" ? (
              <p className="mt-4 flex items-center gap-2 text-body-sm text-ink-dim">
                <Icon name="progress_activity" className="animate-spin text-16" />
                Connexion aux serveurs Telegram…
              </p>
            ) : (
              <div className="mt-3 space-y-3">
                {connexion?.phase === "connected" && (
                  <p className="flex items-center gap-2 rounded-lg border border-ok/35 bg-ok/10 p-2.5 text-body-sm text-ink">
                    <Icon name="check_circle" className="text-16 text-ok" />
                    {connexion.message ?? "Compte connecté."}
                  </p>
                )}
                {connexion &&
                  ["expired", "cancelled", "error"].includes(connexion.phase) &&
                  connexion.message && (
                    <p className="flex items-center gap-2 rounded-lg border border-warn/40 bg-warn-dim/40 p-2.5 text-body-sm text-ink">
                      <Icon name="warning" className="text-16 text-warn" />
                      {connexion.message}
                    </p>
                  )}
                <p className="text-body-sm text-ink-dim">
                  Un QR code s&apos;affiche ici ; il se scanne depuis le téléphone du compte dédié.
                  Aucun code par message n&apos;est nécessaire.
                </p>
                <label className="flex items-start gap-2 text-body-sm text-ink-dim">
                  <input
                    type="checkbox"
                    checked={sansTor}
                    onChange={(e) => setSansTor(e.target.checked)}
                    className="mt-1"
                  />
                  <span>
                    Se connecter <strong className="text-ink">sans Tor</strong>, depuis l&apos;IP de
                    ce serveur.
                    <span className="block font-mono-label text-10.5 text-ink-faint">
                      exception à la règle OPSEC, pour la connexion seulement — la collecte reste
                      toujours sous Tor
                    </span>
                  </span>
                </label>
                <button
                  type="button"
                  onClick={() => void demarrer()}
                  className="flex items-center gap-2 rounded-lg border border-signal/40 bg-signal/10 px-4 py-2 text-body-sm font-medium text-signal hover:bg-signal/20"
                >
                  <Icon name="link" className="text-16" />
                  Afficher le QR code
                </button>
              </div>
            )}
          </section>
        )}

        {statut?.connected && !enCours && (
          <section className="pulse-panel p-4">
            <h2 className="font-display text-15 font-bold tracking-tight text-ink">
              Déconnecter le compte
            </h2>
            <p className="mt-1 text-body-sm text-ink-dim">
              Révoque la session chez Telegram puis la supprime du serveur. La collecte revient à
              l&apos;aperçu web, sans compte.
            </p>
            {/* En deux temps (armer puis confirmer), jamais `window.confirm`. */}
            {deconnexionArmee ? (
              <span className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void deconnecter()}
                  className="rounded-lg border border-critical/40 px-3 py-1.5 text-body-sm text-critical"
                >
                  Confirmer la déconnexion
                </button>
                <button
                  type="button"
                  onClick={() => setDeconnexionArmee(false)}
                  className="text-body-sm text-ink-dim"
                >
                  Annuler
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setDeconnexionArmee(true)}
                className="mt-3 flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-body-sm text-ink-dim hover:border-critical/40 hover:text-critical"
              >
                <Icon name="logout" className="text-16" />
                Déconnecter
              </button>
            )}
          </section>
        )}
      </div>
    </AppLayout>
  );
}
