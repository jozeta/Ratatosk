/*
 * Upload engine shared by the upload page and request-link page: streams an
 * encryptor's ciphertext to /api/uploads/{id}/chunk in server-sized,
 * offset-addressed chunks, several in flight at once (PERF-008), retrying
 * failed chunks with backoff (UI-002). Offset addressing makes retries and
 * resumes safe (BUG-008).
 */
(function () {
  const PARALLEL_CHUNKS = 3;
  const MAX_CHUNK_ATTEMPTS = 5;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function putChunk(uploadId, offset, body, signal) {
    for (let attempt = 1; ; attempt++) {
      try {
        await window.SDApi.raw(`/api/uploads/${uploadId}/chunk`, {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream", "Upload-Offset": String(offset) },
          body,
          signal,
        });
        return;
      } catch (e) {
        if (signal && signal.aborted) throw new DOMException("Upload cancelled", "AbortError");
        // Offset-addressed chunks make retries safe (BUG-008). Client errors
        // other than rate limiting won't fix themselves - give up on those.
        const retryable = !e.status || e.status === 429 || e.status >= 500;
        if (!retryable || attempt >= MAX_CHUNK_ATTEMPTS) throw e;
        await sleep(Math.min(16000, 1000 * 2 ** (attempt - 1)));
      }
    }
  }

  /**
   * Pull ciphertext from the encryptor and PUT it in server-sized chunks,
   * up to PARALLEL_CHUNKS in flight, starting at `fromOffset`. Memory use
   * is about PARALLEL_CHUNKS chunks regardless of file size.
   */
  async function streamUpload(uploadId, encryptor, chunkSize, fromOffset, onProgress, signal) {
    if (!(chunkSize > 0)) throw new Error("Server sent an invalid chunk size - check the admin settings.");
    let pending = [], pendingBytes = 0, offset = fromOffset, sent = fromOffset;
    const inFlight = new Set();
    let failure = null;

    function launch(parts, at) {
      const body = new Blob(parts);
      const p = putChunk(uploadId, at, body, signal).then(() => {
        sent += body.size;
        onProgress(Math.min(sent / encryptor.size, 1));
      }).catch((e) => { failure = failure || e; }).finally(() => inFlight.delete(p));
      inFlight.add(p);
    }

    for await (let piece of encryptor.chunks(fromOffset)) {
      while (pendingBytes + piece.byteLength >= chunkSize) {
        const take = chunkSize - pendingBytes;
        pending.push(piece.subarray(0, take));
        while (inFlight.size >= PARALLEL_CHUNKS) await Promise.race(inFlight);
        if (failure) throw failure;
        launch(pending, offset);
        offset += chunkSize;
        pending = [];
        pendingBytes = 0;
        piece = piece.subarray(take);
      }
      if (piece.byteLength) { pending.push(piece); pendingBytes += piece.byteLength; }
      if (signal && signal.aborted) break;
    }
    if (pendingBytes && !(signal && signal.aborted)) launch(pending, offset);
    await Promise.all(inFlight);
    if (signal && signal.aborted) throw new DOMException("Upload cancelled", "AbortError");
    if (failure) throw failure;
  }

  window.SDUploadEngine = { streamUpload, putChunk, PARALLEL_CHUNKS };
})();
