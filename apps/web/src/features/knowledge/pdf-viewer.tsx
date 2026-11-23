"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft, ChevronRight, Download, ExternalLink, Maximize2, Minimize2, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The parts of a pdf.js document/page this viewer uses (lets tests supply a fake). */
export interface PdfPageLike {
  getViewport(o: { scale: number }): { width: number; height: number };
  render(o: { canvas: HTMLCanvasElement; viewport: { width: number; height: number }; transform?: number[] }): {
    promise: Promise<unknown>;
    cancel(): void;
  };
}
export interface PdfDocLike {
  numPages: number;
  getPage(n: number): Promise<PdfPageLike>;
  destroy(): Promise<void> | void;
}
export type PdfLoader = (url: string) => Promise<PdfDocLike>;

/** pdf.js, loaded on demand (the library and its worker are only downloaded when a PDF is opened). The PDF is parsed
 * in a Web Worker and only page images are drawn: no annotation, form or scripting layer is loaded. */
export const loadPdf: PdfLoader = async (url) => {
  const pdfjs = await import("pdfjs-dist");
  if (!pdfjs.GlobalWorkerOptions.workerPort) {
    pdfjs.GlobalWorkerOptions.workerPort = new Worker(
      new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url), { type: "module" });
  }
  const task = pdfjs.getDocument({ url, enableXfa: false, withCredentials: false });
  return (await task.promise) as unknown as PdfDocLike;
};

const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];

export function PdfViewer({ url, downloadUrl, title, initialPage = 1, loader = loadPdf }: {
  url: string; downloadUrl: string; title: string; initialPage?: number; loader?: PdfLoader;
}) {
  const t = useTranslations("knowledge.original");
  // the loaded document is keyed by URL (a new URL shows "loading" until its own document is ready)
  const [loaded, setLoaded] = useState<{ url: string; doc: PdfDocLike | null; base: { width: number; height: number } | null;
    failed: boolean } | null>(null);
  const active = loaded?.url === url ? loaded : null;
  const doc = active?.doc ?? null;
  const failed = active?.failed ?? false;
  const base = active?.base ?? null;          // page 1 at scale 1
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [width, setWidth] = useState(0);
  const [current, setCurrent] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [expanded, setExpanded] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const jumped = useRef(false);
  // the page the reader is on; kept in view when zoom or full screen changes the page size
  const anchor = useRef(1);
  const restoringUntil = useRef(0);

  useEffect(() => {
    let alive = true;
    let opened: PdfDocLike | null = null;
    loader(url)
      .then(async (d) => {
        opened = d;
        const first = await d.getPage(1);
        if (alive) setLoaded({ url, doc: d, base: first.getViewport({ scale: 1 }), failed: false });
      })
      .catch(() => alive && setLoaded({ url, doc: null, base: null, failed: true }));
    return () => {
      alive = false;
      void opened?.destroy();
    };
  }, [url, loader]);

  // available width for "fit to width" (follows window size and the expanded mode)
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [doc, expanded]);

  const scale = useMemo(() => {
    if (zoom !== "fit") return zoom;
    if (!base || !width) return 1;
    return Math.max(0.3, Math.min(3, (width - 24) / base.width));
  }, [zoom, base, width]);

  const goTo = useCallback((n: number, smooth = true) => {
    if (!doc) return;
    const page = Math.min(Math.max(1, Math.round(n)), doc.numPages);
    const el = scroller.current?.querySelector<HTMLElement>(`[data-page="${page}"]`);
    const box = scroller.current;
    if (el && box) {
      if (typeof box.scrollTo === "function") box.scrollTo({ top: el.offsetTop - 8, behavior: smooth ? "smooth" : "auto" });
      else box.scrollTop = el.offsetTop - 8;
    }
    anchor.current = page;
    setCurrent(page);
    setPageInput(String(page));
  }, [doc]);

  // zoom / fit / full screen re-scale every page: scroll back to the page the reader was on (the old scroll offset
  // would land on another page), and ignore visibility updates until the new layout settles
  const lastLayout = useRef(`${scale}|${expanded}`);
  useLayoutEffect(() => {
    const key = `${scale}|${expanded}`;
    if (lastLayout.current === key) return;
    lastLayout.current = key;
    if (!doc || !jumped.current) return;
    const keep = anchor.current;
    restoringUntil.current = Date.now() + 500;
    requestAnimationFrame(() => goTo(keep, false));
  }, [scale, expanded, doc, goTo]);

  // open at the cited page once the pages are laid out
  useEffect(() => {
    if (doc && base && !jumped.current) {
      jumped.current = true;
      if (initialPage > 1) requestAnimationFrame(() => goTo(initialPage, false));
    }
  }, [doc, base, initialPage, goTo]);

  // the page mostly in view is the current page
  useEffect(() => {
    const root = scroller.current;
    if (!doc || !root || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (top && Date.now() >= restoringUntil.current) {
        const n = Number((top.target as HTMLElement).dataset.page);
        anchor.current = n;
        setCurrent(n);
        setPageInput(String(n));
      }
    }, { root, threshold: [0.3, 0.6] });
    root.querySelectorAll("[data-page]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [doc, scale]);

  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setExpanded(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expanded]);

  const step = (dir: 1 | -1) => {
    const next = dir > 0 ? ZOOM_STEPS.find((z) => z > scale + 0.01) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
      : [...ZOOM_STEPS].reverse().find((z) => z < scale - 0.01) ?? ZOOM_STEPS[0];
    setZoom(next);
  };

  if (failed) {
    return (
      <div className="rounded-lg border border-border bg-card p-5 text-sm" data-testid="pdf-failed" role="status">
        <p className="font-medium">{t("loadFailed")}</p>
        <p className="mt-1 text-muted-foreground">{t("loadFailedHint")}</p>
        <OriginalLinks url={url} downloadUrl={downloadUrl} />
      </div>
    );
  }

  return (
    <div
      className={cn("flex flex-col overflow-hidden border border-border bg-muted/40",
        expanded ? "fixed inset-0 z-[60] h-[100dvh] rounded-none bg-background" : "rounded-lg")}
      role="region" aria-label={t("viewerLabel", { title })} data-testid="pdf-viewer"
    >
      <div className="flex flex-wrap items-center gap-1 border-b border-border bg-card px-2 py-1.5 text-sm">
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("previousPage")}
          disabled={!doc || current <= 1} onClick={() => goTo(current - 1)}><ChevronLeft /></Button>
        <form className="flex items-center gap-1" onSubmit={(e) => { e.preventDefault(); goTo(Number(pageInput) || 1); }}>
          <input aria-label={t("pageNumber")} inputMode="numeric" value={pageInput} disabled={!doc}
            onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ""))}
            className="h-8 w-12 rounded-md border border-input bg-background px-1 text-center text-base sm:text-sm" />
          <span className="text-muted-foreground" data-testid="pdf-page-count">/ {doc?.numPages ?? "…"}</span>
        </form>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("nextPage")}
          disabled={!doc || current >= (doc?.numPages ?? 1)} onClick={() => goTo(current + 1)}><ChevronRight /></Button>
        <span className="mx-1 h-5 w-px bg-border" aria-hidden />
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("zoomOut")} disabled={!doc} onClick={() => step(-1)}><ZoomOut /></Button>
        <span className="w-12 text-center tabular-nums text-muted-foreground" aria-live="polite" data-testid="pdf-zoom">
          {Math.round(scale * 100)}%
        </span>
        <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={t("zoomIn")} disabled={!doc} onClick={() => step(1)}><ZoomIn /></Button>
        <Button size="sm" variant="ghost" className="h-8 px-2" disabled={!doc || zoom === "fit"} onClick={() => setZoom("fit")}>
          {t("fitWidth")}
        </Button>
        <div className="ml-auto flex items-center gap-1">
          <Button size="sm" variant="ghost" className="size-8 p-0" aria-label={expanded ? t("exitFullScreen") : t("fullScreen")}
            aria-pressed={expanded} onClick={() => setExpanded((v) => !v)}>
            {expanded ? <Minimize2 /> : <Maximize2 />}
          </Button>
          <a href={url} target="_blank" rel="noopener noreferrer" aria-label={t("openOriginal")}
             className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"><ExternalLink className="size-4" /></a>
          <a href={downloadUrl} aria-label={t("downloadOriginal")}
             className="inline-flex size-8 items-center justify-center rounded-md hover:bg-muted"><Download className="size-4" /></a>
        </div>
      </div>
      <div ref={scroller} className={cn("relative overflow-auto overscroll-contain", expanded ? "flex-1" : "h-[min(78vh,900px)]")}
           data-testid="pdf-scroll">
        {!doc && <p className="p-6 text-center text-sm text-muted-foreground" role="status">{t("loading")}</p>}
        {doc && base && (
          <div className="flex min-w-fit flex-col items-center gap-3 p-3">
            {Array.from({ length: doc.numPages }, (_, i) => (
              <PdfPageView key={i + 1} doc={doc} n={i + 1} scale={scale} base={base} root={scroller} label={t("pageN", { n: i + 1 })} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** One page: a placeholder of the right size, drawn when it comes near the visible area (long documents stay light). */
function PdfPageView({ doc, n, scale, base, root, label }: {
  doc: PdfDocLike; n: number; scale: number; base: { width: number; height: number };
  root: React.RefObject<HTMLDivElement | null>; label: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [near, setNear] = useState(() => n <= 2 || typeof IntersectionObserver === "undefined");
  // size of the last drawing; until a page is drawn at this zoom its estimate comes from page 1
  const [drawn, setDrawn] = useState<{ scale: number; width: number; height: number } | null>(null);
  const size = drawn && drawn.scale === scale ? drawn : { width: base.width * scale, height: base.height * scale };

  useEffect(() => {
    const el = box.current;
    if (!el || near) return;
    const io = new IntersectionObserver((e) => e.some((x) => x.isIntersecting) && setNear(true),
      { root: root.current, rootMargin: "1200px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [near, root]);

  useEffect(() => {
    if (!near) return;
    let task: { cancel(): void } | null = null;
    let alive = true;
    void doc.getPage(n).then((page) => {
      if (!alive || !canvas.current) return;
      const viewport = page.getViewport({ scale });
      const ratio = typeof window !== "undefined" ? Math.min(window.devicePixelRatio || 1, 2) : 1;
      const c = canvas.current;
      c.width = Math.floor(viewport.width * ratio);
      c.height = Math.floor(viewport.height * ratio);
      setDrawn({ scale, width: viewport.width, height: viewport.height });
      const r = page.render({ canvas: c, viewport, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined });
      task = r;
      r.promise.catch(() => undefined);
    }).catch(() => undefined);
    return () => {
      alive = false;
      task?.cancel();
    };
  }, [near, doc, n, scale, base]);

  return (
    <div ref={box} data-page={n} className="relative shrink-0 bg-white shadow-sm ring-1 ring-black/5"
         style={{ width: size.width, height: size.height }}>
      <canvas ref={canvas} aria-label={label} role="img" style={{ width: size.width, height: size.height, display: "block" }} />
    </div>
  );
}

export function OriginalLinks({ url, downloadUrl }: { url: string; downloadUrl: string }) {
  const t = useTranslations("knowledge.original");
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      <a href={url} target="_blank" rel="noopener noreferrer"
         className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 font-medium text-primary hover:bg-muted">
        <ExternalLink className="size-4" aria-hidden /> {t("openOriginal")}
      </a>
      <a href={downloadUrl}
         className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 font-medium text-primary hover:bg-muted">
        <Download className="size-4" aria-hidden /> {t("downloadOriginal")}
      </a>
    </div>
  );
}
