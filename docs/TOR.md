# Running Ratatosk as a Tor onion service

Ratatosk loads no third-party scripts, fonts or other resources, so it works
unchanged as an onion service. This guide covers the bundled docker-compose
profile and a few settings worth changing for Tor users.

## With docker compose

```bash
cp .env.example .env              # set RATATOSK_SECRET_KEY
docker compose --profile tor up -d --build
docker compose exec tor cat /var/lib/tor/ratatosk/hostname
```

The last command prints your `.onion` address. The service's keys live in
the `tor-keys` volume. **Back that volume up: it *is* your address.** If you
lose it, you get a new one.

If the same instance is also reachable on a normal domain, enter the onion
address under **Admin Settings → Tor onion address**. Pages on the normal
domain then send an `Onion-Location` header, and Tor Browser offers to switch
to the onion version.

## Onion-only

To serve *only* over Tor, remove the `ports:` mapping from the `ratatosk`
service in `docker-compose.yml`. The app is then reachable only through the Tor
container on the internal network.

## Recommended settings for Tor users

| Setting | Suggestion | Why |
|---|---|---|
| Chunk size | 1-2 MB | Smaller requests survive Tor's latency and circuit changes better. Interrupted uploads resume either way. |
| IP obfuscation | `none` | Behind Tor every client appears to come from the Tor daemon, so addresses carry no information. |
| Zero-log mode | on | Nothing ties events to anyone. |
| Rate limit per minute | higher than default | All Tor users share one apparent network address, so per-network limits apply to everyone at once. |
| Timestamp fuzzing | `hour` or `day` | Blunts timing correlation in the audit log. |

## Notes

- Onion services provide end-to-end transport encryption, so TLS isn't
  required. The app doesn't send HSTS on plain-HTTP onion requests.
- Tor Browser's "Safest" security level disables JavaScript, and Ratatosk
  can't encrypt or decrypt without it. Users need the "Safer" or "Standard"
  level.
- Streaming large downloads to disk uses a service worker. Tor Browser in
  private-browsing mode may not allow one; downloads then fall back to
  building the file in memory, which works but needs RAM for large files.
