"""Distinction entre un domaine de VICTIME et un domaine d'INFRASTRUCTURE.

Le pattern `domain` capte tout ce qui ressemble a un domaine, y compris ce qui
sert de support a l'annonce : traqueurs BitTorrent, hebergeurs de fichiers,
messageries, reseaux sociaux, adresses `.onion` des forums que nous collectons.
Rien de tout cela n'est une organisation touchee.

⚠️ Le cas fondateur est AKIRA, et il merite d'etre compris precisement : ce
groupe est fiable et publie de vraies victimes -- mais il joint a chaque
annonce un lien torrent vers les donnees volees. Notre motif ramasse alors
`tracker.opentrackr.org` et `tracker.openbittorrent.com`. Mesure du
2026-09-02 : **69 % des 2016 detections `domain` d'AKIRA sont ces deux
traqueurs**. Faire confiance a la source ne transforme pas un traqueur en
victime -- la fiabilite du groupe et la qualite de notre extraction sont deux
questions distinctes.

Ce module existe parce que la meme liste etait reecrite a trois endroits
(service de severite, requetes d'audit, agregation geographique) avec des
variantes. Une seule definition, testee.

⚠️ Ce que ce module ne fait PAS : juger de la pertinence d'une victime. Un
domaine peut etre parfaitement legitime comme victime sans nous interesser
(hors perimetre geographique). Ici on ne repond qu'a « est-ce une organisation
touchee, ou le tuyau par lequel l'annonce circule ? ».
"""

from __future__ import annotations

# Hebergeurs, messageries, plateformes et traqueurs. Un domaine de cette liste
# apparait dans une annonce comme MOYEN (ou telecharger, comment contacter le
# vendeur), jamais comme cible.
#
# Compare sur le suffixe de labels, pas par sous-chaine : `nottracker.com` ne
# doit pas matcher `tracker.com`, et `gmail.com.evil.net` n'est pas `gmail.com`
# (meme regle que le rattachement d'entite, voir alerting/matching.py).
_INFRASTRUCTURE_DOMAINS: frozenset[str] = frozenset(
    {
        # Traqueurs BitTorrent -- 69 % du bruit d'AKIRA a eux deux.
        "opentrackr.org",
        "openbittorrent.com",
        "torrent.eu.org",
        "tracker.tiny-vps.com",
        "coppersurfer.tk",
        "leechers-paradise.org",
        "explodie.org",
        "publicbt.com",
        "istole.it",
        # Messageries et contacts de vendeur
        "t.me",
        "telegram.me",
        "telegram.org",
        "wa.me",
        "whatsapp.com",
        "signal.me",
        "session.org",
        "tox.chat",
        "discord.com",
        "discord.gg",
        "discordapp.com",
        "icq.com",
        "jabber.org",
        # Fournisseurs de courriel grand public
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "yahoo.com",
        "protonmail.com",
        "proton.me",
        "tutanota.com",
        "mail.ru",
        "yandex.ru",
        "aol.com",
        "gmx.com",
        "cock.li",
        "onionmail.org",
        # Hebergement de fichiers et pastebins -- ou le dump est depose
        "mega.nz",
        "mega.io",
        "anonfiles.com",
        "gofile.io",
        "ufile.io",
        "mediafire.com",
        "dropbox.com",
        "drive.google.com",
        "pastebin.com",
        "rentry.co",
        "justpaste.it",
        "pastr.io",
        "ibb.co",
        "imgur.com",
        "postimg.cc",
        "prnt.sc",
        "files.catbox.moe",
        # Plateformes et grands services cites en passant
        "github.com",
        "gitlab.com",
        "google.com",
        "youtube.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "tiktok.com",
        "reddit.com",
        "linkedin.com",
        "microsoft.com",
        "apple.com",
        "cloudflare.com",
        "archive.org",
        "wikipedia.org",
        "paypal.com",
        "roblox.com",
        "steamcommunity.com",
        # Outils cites dans les annonces de fuite elles-memes
        "virustotal.com",
        "haveibeenpwned.com",
        "intelx.io",
        "dehashed.com",
        "shodan.io",
        "censys.io",
        "crt.sh",
        "ransomlook.io",
        "etherscan.io",
        "blockchain.com",
        "bitcoinabuse.com",
        # Mesure des canaux Telegram (2026-09-26) : domaines cites comme
        # MOYEN par les canaux hacktivistes, jamais comme cible.
        # `check-host.net` = PREUVE de DDoS (« le site ne repond plus ») :
        # cite par 32 canaux sur ~290, loin devant tout autre domaine.
        "check-host.net",
        # Archives de defacement : ou le groupe enregistre sa revendication.
        # La victime est le site defigure, jamais l'archive.
        "zone-h.org",
        "zone-xsec.com",
        "defacer.id",
        "haxor.id",
        # Liens courts de plateformes deja listees, hebergeur, messagerie.
        "youtu.be",
        "fb.me",
        "pixeldrain.com",
        "riseup.net",
    }
)


def _labels(domain: str) -> list[str]:
    return domain.strip().strip(".").lower().split(".")


def is_infrastructure_domain(domain: str | None) -> bool:
    """True si ce domaine est un support d'annonce, pas une organisation cible.

    ⚠️ Tout `.onion` est de l'infrastructure par construction : c'est l'adresse
    d'un forum ou d'un site de fuite que NOUS collectons. Aucune victime n'est
    designee par une adresse `.onion` (verifie : les 10 `.onion` uniques du
    corpus sont tous des sources).

    ⚠️ Une valeur tronquee (`darknet7...wyad.onion`) n'est pas exploitable et
    est traitee comme de l'infrastructure : on ne devine pas ce qu'elle cache.
    """
    if not domain:
        return True

    value = domain.strip().lower()
    if not value or "..." in value:
        return True
    if ".onion" in value:
        return True

    labels = _labels(value)
    # Comparaison par SUFFIXE DE LABELS : `mail.google.com` est bien
    # `google.com`, mais `notgoogle.com` ne l'est pas.
    for size in range(2, min(len(labels), 4) + 1):
        if ".".join(labels[-size:]) in _INFRASTRUCTURE_DOMAINS:
            return True
    return False


def victim_domains(domains: list[str]) -> list[str]:
    """Ne garde que les domaines qui designent une organisation touchee.
    Preserve l'ordre d'entree et les doublons -- le comptage appartient a
    l'appelant."""
    return [d for d in domains if not is_infrastructure_domain(d)]
