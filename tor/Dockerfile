FROM alpine:3.20

RUN apk add --no-cache tor

ARG TOR_CONTROL_PASSWORD=changeme

COPY torrc /etc/tor/torrc

# Le mot de passe de contrôle n'est jamais stocké en clair : seul son hash finit
# dans torrc (voir app/pipeline/collect/tor.py pour l'authentification côté client).
RUN echo "HashedControlPassword $(tor --hash-password "$TOR_CONTROL_PASSWORD" | tail -1)" >> /etc/tor/torrc

EXPOSE 9050 9051

CMD ["tor", "-f", "/etc/tor/torrc"]
