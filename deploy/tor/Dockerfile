# Minimal Tor onion-service sidecar for Ratatosk (FEAT-009).
FROM alpine:3.22
RUN apk add --no-cache tor
COPY torrc /etc/tor/torrc
RUN mkdir -p /var/lib/tor/ratatosk && chown -R tor:root /var/lib/tor && chmod 700 /var/lib/tor/ratatosk
USER tor
CMD ["tor", "-f", "/etc/tor/torrc"]
