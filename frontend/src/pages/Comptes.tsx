import { useState } from "react";
import { usersApi, type PasswordAdvice, type UserApi } from "../api/users";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { useAuth } from "../context/auth-context";
import { useRequete } from "../hooks/useRequete";

/**
 * Gestion des comptes et des rôles — réservée à l'administrateur.
 *
 * ⚠️ AVANT CETTE PAGE, créer un compte ou changer un rôle se faisait EN BASE.
 * C'était le dernier maillon manquant pour que les trois profils du dossier de
 * conception existent réellement.
 *
 * ⚠️ LES GARDE-FOUS ANTI-VERROUILLAGE VIVENT CÔTÉ SERVEUR
 * (`services/user_service.py`) : on ne retire pas le rôle du dernier
 * administrateur, on ne désactive ni ne supprime son propre compte. Cette page
 * ne fait que DÉSACTIVER les contrôles correspondants et AFFICHER le refus —
 * la règle n'est jamais appliquée par le navigateur.
 */

const ROLES = [
  { valeur: "analyst", libelle: "Analyste", aide: "Traite les alertes, voit le corpus" },
  { valeur: "admin", libelle: "Administrateur", aide: "Analyste + configuration" },
  { valeur: "viewer", libelle: "Direction", aide: "Vue agrégée seule, sans le détail" },
];

function tonRole(role: string): string {
  if (role === "admin") return "border-warn/40 bg-warn-dim/40 text-warn";
  if (role === "viewer") return "border-info/35 bg-info/10 text-info";
  return "border-signal/35 bg-signal/10 text-signal";
}

function libelleAdmins(n: number): string {
  if (n === 0) return "aucun administrateur actif";
  if (n === 1) return "1 administrateur actif — son rôle ne peut pas être retiré";
  return `${n} administrateurs actifs`;
}

export function Comptes() {
  const { user } = useAuth();
  const requete = useRequete(() => usersApi.list(), []);
  const comptes: UserApi[] = requete.donnees ?? [];
  const chargement = requete.chargement;
  // Erreur d'une ACTION (création, rôle, suppression), distincte du chargement.
  const [erreurAction, setErreur] = useState<string | null>(null);
  const erreur = requete.erreur ?? erreurAction;
  const modifierComptes = requete.modifier;
  const setComptes = (fn: (precedent: UserApi[]) => UserApi[]) =>
    modifierComptes((precedent) => fn(precedent ?? []));

  const [nom, setNom] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [role, setRole] = useState("analyst");
  const [envoi, setEnvoi] = useState(false);
  const [avis, setAvis] = useState<PasswordAdvice | null>(null);
  const [aSupprimer, setASupprimer] = useState<string | null>(null);

  const adminsActifs = comptes.filter((c) => c.role === "admin" && c.active).length;

  async function verifierMotDePasse() {
    if (motDePasse.length < 12) return;
    try {
      setAvis(await usersApi.passwordAdvice(motDePasse));
    } catch {
      // ⚠️ Un avis indisponible ne bloque pas : HIBP est un tiers, et un
      // administrateur ne doit pas être empêché de créer un compte parce
      // qu'une API externe est en panne.
      setAvis({ breached: false, breach_count: 0, unavailable: true });
    }
  }

  async function creer(e: React.FormEvent) {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      const cree = await usersApi.create({
        username: nom.trim(),
        password: motDePasse,
        role,
      });
      setComptes((p) =>
        [...p, cree].sort((a, b) => a.username.localeCompare(b.username)),
      );
      setNom("");
      setMotDePasse("");
      setAvis(null);
    } catch (e2) {
      setErreur(e2 instanceof Error ? e2.message : "Création impossible");
    } finally {
      setEnvoi(false);
    }
  }

  async function modifier(id: string, champs: { role?: string; active?: boolean }) {
    setErreur(null);
    try {
      const maj = await usersApi.update(id, champs);
      setComptes((p) => p.map((c) => (c.id === id ? maj : c)));
    } catch (e) {
      // ⚠️ Le refus serveur est AFFICHÉ, jamais avalé : « dernier
      // administrateur » est une information, pas une panne. Un clic sans
      // effet ni message ferait conclure à un bug.
      setErreur(e instanceof Error ? e.message : "Modification impossible");
    }
  }

  async function supprimer(id: string) {
    setErreur(null);
    try {
      await usersApi.remove(id);
      setComptes((p) => p.filter((c) => c.id !== id));
      setASupprimer(null);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Suppression impossible");
    }
  }

  return (
    <AppLayout title="Comptes">
      <div className="max-w-4xl space-y-5">
        <section className="pulse-panel p-4">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">
            Créer un compte
          </h2>

          <form onSubmit={(e) => void creer(e)} className="mt-3 flex flex-wrap items-end gap-3">
            <label className="min-w-[180px] flex-1">
              <span className="font-mono-label text-10 uppercase tracking-wide text-ink-dim">
                Identifiant
              </span>
              <input
                value={nom}
                onChange={(e) => setNom(e.target.value)}
                spellCheck={false}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-panel-sunken px-3 font-mono-data text-13 text-ink outline-none focus:border-signal"
              />
            </label>

            <label className="min-w-[200px] flex-1">
              <span className="font-mono-label text-10 uppercase tracking-wide text-ink-dim">
                Mot de passe (12 caractères minimum)
              </span>
              <input
                type="password"
                value={motDePasse}
                onChange={(e) => {
                  setMotDePasse(e.target.value);
                  setAvis(null);
                }}
                onBlur={() => void verifierMotDePasse()}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-panel-sunken px-3 font-mono-data text-13 text-ink outline-none focus:border-signal"
              />
            </label>

            <label className="min-w-[150px]">
              <span className="font-mono-label text-10 uppercase tracking-wide text-ink-dim">
                Rôle
              </span>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="mt-1 h-10 w-full rounded-lg border border-line bg-panel-sunken px-3 text-body-sm text-ink outline-none focus:border-signal"
              >
                {ROLES.map((r) => (
                  <option key={r.valeur} value={r.valeur}>
                    {r.libelle}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="submit"
              disabled={envoi || nom.trim().length < 3 || motDePasse.length < 12}
              className="h-10 rounded-lg border border-signal/40 bg-signal/10 px-4 text-body-sm font-medium text-signal transition-colors hover:bg-signal/20 disabled:opacity-40"
            >
              {envoi ? "Création…" : "Créer"}
            </button>
          </form>

          <p className="mt-2 font-mono-label text-10.5 text-ink-faint">
            {ROLES.find((r) => r.valeur === role)?.aide}
          </p>

          {/* ⚠️ Avis CONSULTATIF, jamais bloquant. Et « indisponible » n'est
              pas « non compromis » : une absence de mesure n'est pas un
              résultat rassurant — même convention que corroboration_status
              null. */}
          {avis && (
            <p
              className={`mt-2 rounded-lg border p-2.5 text-body-sm ${
                avis.unavailable
                  ? "border-line bg-panel-sunken text-ink-dim"
                  : avis.breached
                    ? "border-critical/40 bg-critical/10 text-ink"
                    : "border-ok/35 bg-ok/10 text-ink"
              }`}
            >
              {avis.unavailable
                ? "Vérification des fuites indisponible — impossible de se prononcer."
                : avis.breached
                  ? `Ce mot de passe apparaît dans ${avis.breach_count.toLocaleString("fr-FR")} fuite(s) connue(s). Déconseillé.`
                  : "Ce mot de passe n'apparaît dans aucune fuite connue."}
              <span className="mt-1 block font-mono-label text-10 text-ink-faint">
                contrôle k-anonymity : seuls 5 caractères de l&apos;empreinte sortent, le
                mot de passe n&apos;est jamais transmis en clair ni conservé
              </span>
            </p>
          )}
        </section>

        {erreur && (
          <p className="rounded-lg border border-critical/40 bg-critical/10 p-3 text-body-sm text-ink">
            {erreur}
          </p>
        )}

        <section className="pulse-panel p-4">
          <h2 className="font-display text-15 font-bold tracking-tight text-ink">
            Comptes ({comptes.length})
          </h2>
          <p className="mt-1 font-mono-label text-10.5 text-ink-dim">
            {libelleAdmins(adminsActifs)}
          </p>

          {chargement ? (
            <p className="mt-3 text-body-sm text-ink-dim">Chargement…</p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="font-mono-label text-10 uppercase tracking-wide text-ink-faint">
                    <th className="pb-2">Identifiant</th>
                    <th className="pb-2">Rôle</th>
                    <th className="pb-2">État</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {comptes.map((c) => {
                    const cestMoi = c.id === user?.id;
                    const dernierAdmin =
                      c.role === "admin" && c.active && adminsActifs <= 1;
                    return (
                      <tr key={c.id} className="border-t border-line-soft">
                        <td className="py-2.5">
                          <span className="font-mono-data text-13 text-ink">
                            {c.username}
                          </span>
                          {cestMoi && (
                            <span className="ml-2 font-mono-label text-10 text-ink-faint">
                              vous
                            </span>
                          )}
                        </td>
                        <td className="py-2.5">
                          <select
                            value={c.role}
                            disabled={dernierAdmin}
                            title={
                              dernierAdmin
                                ? "Dernier administrateur actif : son rôle ne peut pas être retiré"
                                : undefined
                            }
                            onChange={(e) => void modifier(c.id, { role: e.target.value })}
                            className={`rounded-full border px-2 py-1 font-mono-label text-10.5 disabled:opacity-50 ${tonRole(c.role)}`}
                          >
                            {ROLES.map((r) => (
                              <option key={r.valeur} value={r.valeur}>
                                {r.libelle}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2.5">
                          <button
                            type="button"
                            disabled={cestMoi || dernierAdmin}
                            title={
                              cestMoi
                                ? "On ne désactive pas son propre compte"
                                : dernierAdmin
                                  ? "Dernier administrateur actif"
                                  : undefined
                            }
                            onClick={() => void modifier(c.id, { active: !c.active })}
                            className="flex items-center gap-1.5 text-body-sm text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
                          >
                            <span
                              className={`h-2 w-2 rounded-full ${c.active ? "bg-ok" : "bg-ink-faint"}`}
                            />
                            {c.active ? "Actif" : "Désactivé"}
                          </button>
                        </td>
                        <td className="py-2.5 text-right">
                          {/* Suppression EN DEUX TEMPS (armer puis confirmer),
                              jamais `window.confirm` : celui-ci bloque le rendu
                              et n'est pas vérifiable au test. */}
                          {aSupprimer === c.id ? (
                            <span className="flex items-center justify-end gap-2">
                              <button
                                type="button"
                                onClick={() => void supprimer(c.id)}
                                className="rounded-md border border-critical/40 px-2 py-1 text-body-sm text-critical"
                              >
                                Confirmer
                              </button>
                              <button
                                type="button"
                                onClick={() => setASupprimer(null)}
                                className="text-body-sm text-ink-dim"
                              >
                                Annuler
                              </button>
                            </span>
                          ) : (
                            <button
                              type="button"
                              disabled={cestMoi || dernierAdmin}
                              title={
                                cestMoi ? "On ne supprime pas son propre compte" : undefined
                              }
                              onClick={() => setASupprimer(c.id)}
                              aria-label={`Supprimer ${c.username}`}
                              className="rounded-md border border-line px-2 py-1 text-body-sm text-ink-dim transition-colors hover:border-critical/40 hover:text-critical disabled:opacity-30"
                            >
                              <Icon name="delete" className="text-15" />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <p className="mt-3 font-mono-label text-10.5 text-ink-faint">
            Supprimer un compte n&apos;efface pas sa trace : le journal des accès aux
            alertes conserve son identifiant et son rôle d&apos;alors.
          </p>
        </section>
      </div>
    </AppLayout>
  );
}
