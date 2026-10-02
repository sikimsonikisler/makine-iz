import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";
import { errorMessage } from "./api";

/** Basit hash yönlendirmesi: #/makine/demo-motor?start=... */
export function useHashRoute(): { parts: string[]; query: URLSearchParams } {
  const read = () => {
    const raw = window.location.hash.replace(/^#/, "") || "/";
    const [path, search = ""] = raw.split("?");
    return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), query: new URLSearchParams(search) };
  };
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onChange = () => {
      setRoute(read());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(to: string) {
  window.location.hash = to;
}

/** Veriyi yükler ve isteğe bağlı olarak belirli aralıklarla yeniler. Son isteğin sonucu geçerlidir. */
export function usePolling<T>(loader: () => Promise<T>, deps: DependencyList, intervalMs: number | null = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const sequence = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++sequence.current;
    try {
      const result = await loaderRef.current();
      if (mine === sequence.current) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (mine === sequence.current) setError(errorMessage(e));
    } finally {
      if (mine === sequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    void reload();
    if (intervalMs === null) return undefined;
    const id = window.setInterval(() => void reload(), intervalMs);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, intervalMs]);

  return { data, error, loading, reload, setData };
}
