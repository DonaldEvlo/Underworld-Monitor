import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { Icon } from "../components/ui/Icon";
import { LogoFaille } from "../components/ui/LogoFaille";
import { clearLogoutReason, readLogoutReason, useAuth } from "../context/auth-context";
import { useRequete } from "../hooks/useRequete";

/** Points qui scintillent dans le fond. Positions fixes : un placement
 * aleatoire changerait a chaque rendu et ferait « sauter » le decor. */
const SCINTILLEMENTS = [
  { left: "14%", top: "22%", size: 3, color: "#3ee8b8", delay: "0s" },
  { left: "26%", top: "62%", size: 2, color: "#5ec8f0", delay: "0.8s" },
  { left: "78%", top: "18%", size: 3, color: "#3ee8b8", delay: "1.4s" },
  { left: "86%", top: "54%", size: 2, color: "#dce9e4", delay: "0.3s" },
  { left: "62%", top: "76%", size: 2, color: "#3ee8b8", delay: "2s" },
  { left: "38%", top: "12%", size: 2, color: "#5ec8f0", delay: "1.1s" },
];

type EtatService = "verification" | "en-ligne" | "injoignable";

/** Connexion — le seul ecran accessible sans session.
 *
 * ⚠️ TROIS ELEMENTS DE LA MAQUETTE N'ONT PAS ETE REPRIS, VOLONTAIREMENT :
 *
 * - Le CODE A USAGE UNIQUE : le backend n'a aucune authentification a deux
 *   facteurs. Un champ qui ne verifie rien laisserait croire a une protection
 *   qui n'existe pas — pire que pas de champ.
 * - « Chaque consultation est journalisee et nominative » : aucune
 *   journalisation des acces n'est implementee (la regle 5 du projet l'exige,
 *   mais le code ne la fait pas). L'ecrire serait une fausse promesse de
 *   securite, affichee precisement a l'endroit ou l'on se fie a elle.
 * - Le BANDEAU DEFILANT de detections recentes : cette page est publique.
 *   Y afficher des domaines de victimes les exposerait a quiconque ouvre
 *   l'URL, sans authentification — une fuite de l'outil de detection de
 *   fuites.
 *
 * De meme, le pied de carte ne dit PAS « circuit Tor actif » : `/api/health`
 * ne renvoie que l'etat de l'API, pas celui de Tor. Il dit ce qu'on sait.
 */
export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [motDePasseVisible, setMotDePasseVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // État du service affiché avant connexion : un échec se lit « injoignable ».
  const sante = useRequete(() => api.get<{ status: string }>("/api/health"), []);
  const service: EtatService = sante.chargement
    ? "verification"
    : sante.donnees?.status === "ok"
      ? "en-ligne"
      : "injoignable";
  // Lu une seule fois au montage, effacé ensuite par un effet : voir
  // `readLogoutReason` (le mode strict appelle l'initialiseur deux fois).
  const [logoutReason] = useState(() => readLogoutReason());
  useEffect(() => clearLogoutReason(), []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
      void navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Erreur inconnue");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-panel-sunken px-4 py-16 font-body-md">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div
          className="login-drift-a absolute -left-[260px] -top-[380px] h-[1100px] w-[1100px] rounded-full blur-[20px]"
          style={{
            background: "radial-gradient(circle, rgba(62,232,184,.16) 0%, rgba(62,232,184,0) 62%)",
          }}
        />
        <div
          className="login-drift-b absolute -bottom-[420px] -right-[300px] h-[980px] w-[980px] rounded-full blur-[24px]"
          style={{
            background: "radial-gradient(circle, rgba(94,200,240,.13) 0%, rgba(94,200,240,0) 64%)",
          }}
        />
        <div className="login-grid absolute inset-0" />
        <div className="login-scan absolute inset-x-0 top-0 h-[220px]" />

        <svg
          viewBox="0 0 1440 260"
          preserveAspectRatio="none"
          className="absolute inset-x-0 bottom-0 h-[260px] w-full opacity-50"
        >
          <polyline
            className="login-trace"
            points="0,180 200,180 236,180 252,120 268,236 284,180 480,180 700,180 736,180 752,110 768,244 784,180 980,180 1180,180 1216,180 1232,124 1248,232 1264,180 1440,180"
            fill="none"
            stroke="#3ee8b8"
            strokeWidth="1.6"
          />
          <polyline
            points="0,180 1440,180"
            fill="none"
            stroke="#213040"
            strokeWidth="1"
            strokeDasharray="6 10"
          />
        </svg>

        {SCINTILLEMENTS.map((s) => (
          <span
            key={`${s.left}-${s.top}`}
            className="login-twinkle absolute rounded-full"
            style={{
              left: s.left,
              top: s.top,
              width: s.size,
              height: s.size,
              background: s.color,
              animationDelay: s.delay,
            }}
          />
        ))}
      </div>

      <div
        className="login-panel-rise relative w-full max-w-[452px] rounded-[20px] border border-line px-9 pb-7 pt-[34px] shadow-[0_40px_90px_-30px_rgba(0,0,0,0.9)] backdrop-blur-[6px]"
        style={{
          background: "linear-gradient(180deg, rgba(15,21,29,.92) 0%, rgba(7,11,16,.94) 100%)",
        }}
      >
        <div className="login-logo-boot flex items-center gap-3">
          <div className="relative flex h-10 w-10 items-center justify-center">
            {/* Halo tournant : un quart d'arc, le reste transparent. */}
            <span className="login-halo absolute inset-0 rounded-[13px] border border-signal/35 border-l-transparent border-t-transparent" />
            <span className="flex h-8 w-8 items-center justify-center rounded-[11px] border border-line bg-panel">
              <LogoFaille size={20} className="text-signal" title="Underworld Monitor" />
            </span>
          </div>
          <div>
            <p className="font-display text-17 font-bold leading-[19px] tracking-[0.01em] text-ink">
              Underworld Monitor
            </p>
            <p className="mt-[3px] font-mono-label text-9.5 uppercase tracking-[0.2em] text-ink-dim">
              Command Center
            </p>
          </div>
        </div>

        <div className="login-field-in mt-[26px]" style={{ animationDelay: "0.3s" }}>
          <h1 className="font-display text-26 font-bold tracking-[-0.01em] text-ink">
            Connexion
          </h1>
          <p className="mt-[5px] text-13 leading-5 text-ink-dim">
            Accès réservé aux analystes autorisés.
          </p>
        </div>

        {logoutReason && (
          <p
            className="login-field-in mt-5 flex items-start gap-2 rounded-xl border border-warn/40 bg-warn-dim/40 p-3 text-body-sm text-warn"
            style={{ animationDelay: "0.34s" }}
          >
            <Icon name="timer" className="mt-0.5 shrink-0 text-16" />
            {logoutReason}
          </p>
        )}

        <form onSubmit={(e) => void handleSubmit(e)} className="mt-[22px] flex flex-col gap-4">
          <div className="login-field-in" style={{ animationDelay: "0.4s" }}>
            <label
              htmlFor="username"
              className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-dim"
            >
              Identifiant
            </label>
            <input
              id="username"
              autoFocus
              autoComplete="username"
              spellCheck={false}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={submitting}
              className="mt-[7px] h-[46px] w-full rounded-xl border border-line bg-panel-sunken/85 px-3.5 font-mono-data text-13 text-ink outline-none transition-colors hover:border-[#31465c] focus:border-signal focus:ring-4 focus:ring-signal/10 disabled:opacity-50"
            />
          </div>

          <div className="login-field-in" style={{ animationDelay: "0.46s" }}>
            <label
              htmlFor="password"
              className="font-mono-label text-10 uppercase tracking-[0.16em] text-ink-dim"
            >
              Mot de passe
            </label>
            <div className="relative mt-[7px]">
              <input
                id="password"
                type={motDePasseVisible ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={submitting}
                className="h-[46px] w-full rounded-xl border border-line bg-panel-sunken/90 pl-3.5 pr-24 font-mono-data text-13 tracking-[0.06em] text-ink outline-none transition-colors hover:border-[#31465c] focus:border-signal focus:ring-4 focus:ring-signal/10 disabled:opacity-50"
              />
              <button
                type="button"
                onClick={() => setMotDePasseVisible((v) => !v)}
                aria-pressed={motDePasseVisible}
                aria-controls="password"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 font-mono-label text-9.5 uppercase tracking-[0.08em] text-ink-dim transition-colors hover:text-signal focus-visible:text-signal focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-signal/40"
              >
                {motDePasseVisible ? "Masquer" : "Afficher"}
              </button>
            </div>
          </div>

          {error && (
            <p className="rounded-xl border border-critical/40 bg-critical-dim/30 p-3 text-body-sm text-critical">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="login-field-in login-sheen relative mt-2 flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-signal text-14 font-bold tracking-[0.01em] text-on-signal transition-colors hover:bg-[#6ff2cd] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-signal/30 disabled:opacity-50 disabled:hover:bg-signal"
            style={{ animationDelay: "0.52s" }}
          >
            {submitting && <Icon name="progress_activity" className="relative animate-spin text-18" />}
            <span className="relative">{submitting ? "Connexion…" : "Se connecter"}</span>
          </button>
        </form>

        <div
          className="login-field-in mt-[18px] flex items-center gap-3 border-t border-line pt-3.5"
          style={{ animationDelay: "0.58s" }}
        >
          <span className="flex items-center gap-[7px] font-mono-label text-9.5 text-ink-dim">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                service === "en-ligne"
                  ? "status-pulse bg-signal"
                  : service === "injoignable"
                    ? "bg-critical"
                    : "bg-ink-faint"
              }`}
            />
            {service === "en-ligne"
              ? "service en ligne"
              : service === "injoignable"
                ? "service injoignable"
                : "vérification du service…"}
          </span>
        </div>
      </div>
    </div>
  );
}
