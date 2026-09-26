import { useEffect, useState, type ReactNode } from "react";
import http, { mediaUrl } from "../api/client";

// Face-crop endpoints (/api/v1/media/*) require the JWT, but a plain
// <img src> can't send an Authorization header -- every photo 401'd and
// silently showed nothing. This component fetches the image through the
// authenticated axios client and renders it from a blob: URL instead.
//
// Blob URLs are cached per path for the lifetime of the tab, so the
// dashboard's 30s polling doesn't re-download every photo.
const cache = new Map<string, Promise<string>>();

function loadBlobUrl(url: string): Promise<string> {
  let p = cache.get(url);
  if (!p) {
    p = http.get<Blob>(url, { responseType: "blob" }).then((res) => URL.createObjectURL(res.data));
    // A failure (404 / network) must not be cached forever -- allow a retry next render.
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return p;
}

interface AuthImageProps {
  /** API media path as returned by the backend, e.g. "/api/v1/media/crop/<id>". */
  path: string | null | undefined;
  alt: string;
  className?: string;
  /** Rendered when there is no path, while loading, or if loading fails. */
  fallback?: ReactNode;
}

export function AuthImage({ path, alt, className, fallback = null }: AuthImageProps): JSX.Element {
  const url = mediaUrl(path ?? null);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    if (!url) return undefined;
    loadBlobUrl(url)
      .then((blobUrl) => {
        if (!cancelled) setSrc(blobUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (!url || failed || !src) return <>{fallback}</>;
  return <img src={src} alt={alt} className={className} />;
}
