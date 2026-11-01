/*
 * Ratatosk service worker: lets the page stream a decrypted download
 * straight to disk instead of holding the whole file in memory (PERF-005).
 *
 * The page posts {type:"open"} with a MessagePort, then navigates a hidden
 * iframe to /__ratatosk_dl/<id>. This worker answers that request with a
 * ReadableStream fed by the port. Backpressure: the stream asks the page for
 * one more chunk ("pull") each time it has room, so the page never decrypts
 * further ahead than the disk is writing. Nothing else is intercepted - every
 * other request goes straight to the network.
 */
const pending = new Map(); // id -> { port, name, mime, size }

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type !== "open" || !event.ports[0]) return;
  const port = event.ports[0];
  pending.set(msg.id, { port, name: msg.name, mime: msg.mime, size: msg.size });
  port.postMessage({ type: "opened" });
  // Forget streams nobody fetched (the page gave up).
  setTimeout(() => pending.delete(msg.id), 5 * 60 * 1000);
});

function contentDisposition(name) {
  const ascii = String(name).replace(/[^\x20-\x7e]/g, "_").replace(/["\\]/g, "_");
  return `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(name)}`;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith("/__ratatosk_dl/")) return;
  const id = url.pathname.slice("/__ratatosk_dl/".length);
  const entry = pending.get(id);
  if (!entry) {
    event.respondWith(new Response("Download expired", { status: 404 }));
    return;
  }
  pending.delete(id);
  const { port } = entry;
  const stream = new ReadableStream({
    start(controller) {
      port.onmessage = (e) => {
        const m = e.data || {};
        if (m.type === "chunk") controller.enqueue(new Uint8Array(m.chunk));
        else if (m.type === "done") controller.close();
        else if (m.type === "abort") controller.error(new Error("aborted"));
      };
    },
    pull() {
      port.postMessage({ type: "pull" });
    },
    cancel() {
      port.postMessage({ type: "cancel" });
    },
  }, { highWaterMark: 4 });
  const headers = {
    "Content-Type": "application/octet-stream",
    "Content-Disposition": contentDisposition(entry.name || "download"),
    "X-Content-Type-Options": "nosniff",
  };
  if (entry.size) headers["Content-Length"] = String(entry.size);
  event.respondWith(new Response(stream, { headers }));
});
