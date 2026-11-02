import { Link } from "react-router-dom";
import { AppLayout } from "../components/layout/AppLayout";
import { Icon } from "../components/ui/Icon";
import { useAuth } from "../context/auth-context";
import { libelleRole, routeAccueil, type Perimetre } from "../lib/roles";

/** Ce que le rôle manquant empêche de voir — écrit en termes de métier, pas de
 * nom de route. « Vous n'avez pas accès à /comptes » n'apprend rien ; « la
 * configuration est réservée à l'administrateur » se comprend et se relaie. */
const MOTIF: Record<Perimetre, { quoi: string; qui: string }> = {
  alertes: {
    quoi: "Le traitement des alertes",
    qui: "aux analystes et aux administrateurs",
  },
  corpus: {
    quoi: "Le détail du corpus collecté",
    qui: "aux analystes et aux administrateurs",
  },
  administration: {
    quoi: "La configuration de la plateforme",
    qui: "aux administrateurs",
  },
  agrege: { quoi: "Cette vue", qui: "aux comptes actifs" },
};

/**
 * Refus d'accès, expliqué.
 *
 * ⚠️ UN REFUS SANS MOTIF SE LIT COMME UNE PANNE. C'est la même raison qui fait
 * répondre 403 et non 404 côté serveur : l'utilisateur est authentifié, il
 * appartient à l'organisation, il doit pouvoir diagnostiquer son propre droit
 * manquant et savoir à qui le demander. Cacher l'existence de la page ne
 * protégerait rien — la garde est serveur — et le laisserait conclure à un bug.
 *
 * ⚠️ Le retour proposé mène à l'accueil DE SON RÔLE, pas à `/` : envoyer un
 * RSSI vers le poste de veille le ferait rebondir sur un second refus.
 */
export function AccesRefuse({ perimetre }: { perimetre: Perimetre }) {
  const { user } = useAuth();
  const motif = MOTIF[perimetre];
  const accueil = routeAccueil(user?.role);

  return (
    <AppLayout title="Accès refusé">
      <div className="mx-auto max-w-xl rounded-lg border border-line bg-panel-raised p-8 text-center">
        <Icon name="lock" className="text-40 text-ink-faint" />
        <h2 className="mt-3 font-headline-sm text-headline-sm text-ink">
          Cette page n&apos;est pas dans votre périmètre
        </h2>
        <p className="mt-3 text-body-sm text-ink-dim">
          {motif.quoi} est réservé {motif.qui}. Votre compte est enregistré comme{" "}
          <span className="font-mono-data text-ink">{libelleRole(user?.role)}</span>.
        </p>
        <p className="mt-2 text-body-sm text-ink-faint">
          Un administrateur peut faire évoluer votre rôle depuis la page Comptes.
        </p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <Link
            to={accueil}
            className="rounded-md bg-primary px-4 py-2 font-mono-data text-12 font-bold text-on-primary transition-opacity hover:opacity-90"
          >
            Retour à mon espace
          </Link>
        </div>
      </div>
    </AppLayout>
  );
}
