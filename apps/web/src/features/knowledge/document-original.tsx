"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink, FileText, Globe } from "lucide-react";
import { api, buildUrl } from "@/lib/api";
import { PdfViewer, type PdfLoader } from "@/features/knowledge/pdf-viewer";
import type { DocumentOriginal } from "@/types/api";

/**
 * The ORIGINAL document: the uploaded PDF in a viewer, a formatted preview of a Word file (sandboxed, script-free),
 * or the official web page. Text extracted for search is never presented as the original.
 */
export function DocumentOriginalView({ original, title, initialPage, pdfLoader }: {
  original: DocumentOriginal; title: string; initialPage?: number; pdfLoader?: PdfLoader;
}) {
  const t = useTranslations("knowledge.original");
  if (original.kind === "pdf" && original.file_url && original.download_url) {
    return (
      <section aria-labelledby="orig-doc-h" className="space-y-2" data-testid="original-document">
        <h2 id="orig-doc-h" className="flex items-center gap-2 text-lg font-semibold">
          <FileText className="size-5 text-primary" aria-hidden /> {t("heading")}
        </h2>
        <PdfViewer url={buildUrl(original.file_url)} downloadUrl={buildUrl(original.download_url)} title={title}
          initialPage={initialPage} loader={pdfLoader} />
        <p className="text-xs text-muted-foreground">{t("pdfNote", { file: original.filename ?? "PDF" })}</p>
      </section>
    );
  }
  if (original.kind === "docx" && original.file_url && original.download_url) {
    return (
      <section aria-labelledby="orig-doc-h" className="space-y-2" data-testid="original-document">
        <h2 id="orig-doc-h" className="flex items-center gap-2 text-lg font-semibold">
          <FileText className="size-5 text-primary" aria-hidden /> {t("heading")}
        </h2>
        <WordPreview original={original} title={title} />
      </section>
    );
  }
  if (original.kind === "web" && original.source_url) {
    return (
      <section className="rounded-lg border border-border bg-card p-5 text-sm" data-testid="original-document">
        <p className="flex items-center gap-2 font-semibold"><Globe className="size-4 text-primary" aria-hidden /> {t("webTitle")}</p>
        <p className="mt-1 text-muted-foreground">{t("webBody")}</p>
        <a href={original.source_url} target="_blank" rel="noopener noreferrer"
           className="mt-3 inline-flex items-center gap-1 break-all rounded-md border border-border px-3 py-1.5 font-medium text-primary hover:bg-muted">
          <ExternalLink className="size-4 shrink-0" aria-hidden /> {t("openWebPage")}
        </a>
      </section>
    );
  }
  return null;
}

function WordPreview({ original, title }: { original: DocumentOriginal; title: string }) {
  const t = useTranslations("knowledge.original");
  const url = original.preview_url ?? null;
  // results are keyed by URL so a different document never shows the previous preview
  const [result, setResult] = useState<{ url: string; value: { html: string; omitted: number } | "failed" } | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    api.get<{ html: string; omitted_images: number }>(url)
      .then((r) => alive && setResult({ url, value: { html: r.html, omitted: r.omitted_images } }))
      .catch(() => alive && setResult({ url, value: "failed" }));
    return () => {
      alive = false;
    };
  }, [url]);
  const state = !url ? "failed" : result?.url === url ? result.value : "loading";
  if (state === "loading") return <p className="rounded-lg border border-border p-5 text-sm text-muted-foreground" role="status">{t("loading")}</p>;
  if (state === "failed") {
    return (
      <div className="rounded-lg border border-border bg-card p-5 text-sm" data-testid="docx-failed">
        <p className="font-medium">{t("wordNoPreview")}</p>
        <p className="mt-1 text-muted-foreground">{t("wordNoPreviewHint")}</p>
        <DownloadOnly href={buildUrl(original.download_url!)} />
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">{t("wordPreviewNote")}</p>
      {/* no allow-scripts / allow-same-origin: the preview cannot run code or reach the site */}
      <iframe title={t("viewerLabel", { title })} sandbox="" srcDoc={state.html} data-testid="docx-preview"
        className="h-[min(78vh,900px)] w-full rounded-lg border border-border bg-white" />
      {state.omitted > 0 && <p className="text-xs text-muted-foreground">{t("wordImagesOmitted", { n: state.omitted })}</p>}
      <DownloadOnly href={buildUrl(original.download_url!)} />
    </div>
  );
}

function DownloadOnly({ href }: { href: string }) {
  const t = useTranslations("knowledge.original");
  return (
    <a href={href} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-primary hover:bg-muted">
      <FileText className="size-4" aria-hidden /> {t("downloadWord")}
    </a>
  );
}
