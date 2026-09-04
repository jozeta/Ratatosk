/*
 * Client-side metadata stripping. Redrawing an image onto a <canvas> and
 * re-exporting discards EXIF, GPS/geolocation tags, author info, thumbnails,
 * and OS-embedded timestamps in one step - the canvas only ever holds pixel
 * data, never the original metadata segments.
 *
 * Only static raster formats are safe to round-trip this way (animated GIF/
 * WebP would collapse to a single frame, and SVG is text/XML, not raster) -
 * those pass through unmodified.
 */
(function () {
  const STRIPPABLE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

  function stripImageMetadata(file) {
    return new Promise((resolve, reject) => {
      if (!STRIPPABLE_TYPES.has(file.type)) {
        resolve(file);
        return;
      }
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = img.naturalWidth;
          canvas.height = img.naturalHeight;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(img, 0, 0);
          canvas.toBlob(
            (blob) => {
              URL.revokeObjectURL(url);
              if (!blob) {
                resolve(file); // fall back to original rather than fail the upload
                return;
              }
              resolve(new File([blob], file.name, { type: file.type }));
            },
            file.type,
            0.95
          );
        } catch (e) {
          URL.revokeObjectURL(url);
          resolve(file);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(file); // not a decodable image; leave untouched
      };
      img.src = url;
    });
  }

  window.SDExif = { stripImageMetadata, STRIPPABLE_TYPES };
})();
