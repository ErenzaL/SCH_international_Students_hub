import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithIntl } from "@/test/utils";
import type { KnowledgeDocumentDetail } from "@/types/api";
import type { PdfDocLike, PdfLoader } from "@/features/knowledge/pdf-viewer";

const get = vi.fn();
vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, get: (...a: unknown[]) => get(...a) } };
});

import { KnowledgeArticle } from "@/features/knowledge/knowledge-article";
import { PdfViewer } from "@/features/knowledge/pdf-viewer";

const API = "http://localhost:8000";
const rendered: number[] = [];

function fakePdf(pages = 3): PdfLoader {
  return vi.fn(async () => ({
    numPages: pages,
    destroy: vi.fn(),
    getPage: async (n: number) => ({
      getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
      render: () => {
        rendered.push(n);
        return { promise: Promise.resolve(), cancel: vi.fn() };
      },
    }),
  }) as PdfDocLike);
}

const pdfDoc: KnowledgeDocumentDetail = {
  id: "g1", title: "한국 유학생 생활 가이드북", category: "visa-immigration", organization: "NIIED", scope: "national",
  authority_type: "official_government", language: "ko", source_url: null, source_published_at: "2021-03-05T00:00:00Z",
  verified_at: "2026-11-01T00:00:00Z", excerpt: "", content: "# 체류 안내\n\n외국인등록은 입국 후 90일 이내에 해야 합니다.",
  version_id: "v1", version_number: 1, verified_languages: [], translation: null,
  original: { kind: "pdf", has_file: true, filename: "guideBook_ko.pdf", size: 9172193, mime_type: "application/pdf",
    file_url: "/api/v1/knowledge/documents/g1/original", download_url: "/api/v1/knowledge/documents/g1/original?download=1",
    preview_url: null, source_url: null },
};

beforeEach(() => {
  get.mockReset();
  rendered.length = 0;
});

describe("original PDF", () => {
  it("shows the original file in a viewer with page navigation, zoom and full screen", async () => {
    get.mockResolvedValue(pdfDoc);
    const loader = fakePdf(3);
    renderWithIntl(<KnowledgeArticle id="g1" pdfLoader={loader} />);
    const viewer = await screen.findByTestId("pdf-viewer");
    expect(loader).toHaveBeenCalledWith(`${API}/api/v1/knowledge/documents/g1/original`);  // the original file, not chunks
    await waitFor(() => expect(within(viewer).getByTestId("pdf-page-count")).toHaveTextContent("/ 3"));
    expect(viewer.querySelectorAll("[data-page]")).toHaveLength(3);
    await waitFor(() => expect(rendered).toContain(1));
    const user = userEvent.setup();
    // page navigation
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByLabelText("Page number")).toHaveValue("2");
    await user.clear(screen.getByLabelText("Page number"));
    await user.type(screen.getByLabelText("Page number"), "3{Enter}");
    expect(screen.getByLabelText("Page number")).toHaveValue("3");
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    // zoom
    const before = screen.getByTestId("pdf-zoom").textContent;
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByTestId("pdf-zoom").textContent).not.toBe(before);
    await user.click(screen.getByRole("button", { name: "Fit width" }));
    // full screen (CSS overlay that also works on phones) and Escape to leave it
    await user.click(screen.getByRole("button", { name: "Full screen" }));
    expect(viewer.className).toContain("fixed");
    await user.keyboard("{Escape}");
    expect(viewer.className).not.toContain("fixed");
    // open / download the original
    expect(screen.getByRole("link", { name: "Open original" })).toHaveAttribute("href", `${API}/api/v1/knowledge/documents/g1/original`);
    expect(screen.getByRole("link", { name: "Download original" }))
      .toHaveAttribute("href", `${API}/api/v1/knowledge/documents/g1/original?download=1`);
    // the extracted text is a collapsed, clearly-labelled text version, not the main view
    const tv = screen.getByTestId("text-version");
    expect(tv.tagName).toBe("DETAILS");
    expect(tv).not.toHaveAttribute("open");
    expect(tv).toHaveTextContent("Text version (extracted for search and translation)");
  });

  it("opens at the cited page", async () => {
    get.mockResolvedValue(pdfDoc);
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(0);
      return 0;
    });
    renderWithIntl(<KnowledgeArticle id="g1" initialPage={2} pdfLoader={fakePdf(3)} />);
    await waitFor(() => expect(screen.getByLabelText("Page number")).toHaveValue("2"));
    raf.mockRestore();
  });

  it("falls back to open/download links when the file cannot be displayed", async () => {
    renderWithIntl(<PdfViewer url={`${API}/x/original`} downloadUrl={`${API}/x/original?download=1`} title="T"
      loader={vi.fn(async () => { throw new Error("404"); })} />);
    const box = await screen.findByTestId("pdf-failed");
    expect(box).toHaveTextContent("could not be displayed");
    expect(within(box).getByRole("link", { name: /Download original/ })).toHaveAttribute("href", `${API}/x/original?download=1`);
  });

  it("is usable at phone width (fit to width, no fixed page size)", async () => {
    renderWithIntl(<PdfViewer url={`${API}/p`} downloadUrl={`${API}/p?download=1`} title="T" loader={fakePdf(1)} />);
    const scroll = await screen.findByTestId("pdf-scroll");
    Object.defineProperty(scroll, "clientWidth", { value: 360, configurable: true });
    await act(async () => {
      window.dispatchEvent(new Event("resize"));
    });
    // default zoom is "fit width": the page is never wider than the phone screen once measured
    expect(screen.getByRole("button", { name: "Fit width" })).toBeDisabled();
  });
});

describe("Word, web and text originals", () => {
  it("shows a sandboxed formatted preview of a Word file plus the download", async () => {
    const doc = { ...pdfDoc, original: { kind: "docx" as const, has_file: true, filename: "guide.docx",
      file_url: "/api/v1/knowledge/documents/g1/original", download_url: "/api/v1/knowledge/documents/g1/original?download=1",
      preview_url: "/api/v1/knowledge/documents/g1/original/preview" } };
    get.mockImplementation(async (path: string) => path.endsWith("/preview")
      ? { html: "<html><body><h1>장학금</h1><table><tr><td>수수료</td></tr></table></body></html>", omitted_images: 1 }
      : doc);
    renderWithIntl(<KnowledgeArticle id="g1" />);
    const frame = await screen.findByTestId("docx-preview");
    expect(frame).toHaveAttribute("sandbox", "");                  // no scripts, no same-origin access
    expect(frame.getAttribute("srcdoc")).toContain("<table>");
    expect(screen.getByText(/1 image\(s\) are not shown/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download the original Word file/ }))
      .toHaveAttribute("href", `${API}/api/v1/knowledge/documents/g1/original?download=1`);
  });

  it("offers the download when a Word preview is unavailable", async () => {
    const doc = { ...pdfDoc, original: { kind: "docx" as const, has_file: true, file_url: "/f", download_url: "/f?download=1",
      preview_url: "/f/preview" } };
    get.mockImplementation(async (path: string) => {
      if (path.endsWith("/preview")) throw new Error("preview_unavailable");
      return doc;
    });
    renderWithIntl(<KnowledgeArticle id="g1" />);
    const box = await screen.findByTestId("docx-failed");
    expect(within(box).getByRole("link")).toHaveAttribute("href", `${API}/f?download=1`);
  });

  it("links a web source to its official page and labels captured text", async () => {
    get.mockResolvedValue({ ...pdfDoc, original: { kind: "web", has_file: false, source_url: "https://www.hikorea.go.kr/x" } });
    renderWithIntl(<KnowledgeArticle id="g1" />);
    const link = await screen.findByRole("link", { name: "Open the official page" });
    expect(link).toHaveAttribute("href", "https://www.hikorea.go.kr/x");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByTestId("text-version")).toHaveTextContent("Text captured from the official page");
  });

  it("shows pasted text documents as before (the text is the original)", async () => {
    get.mockResolvedValue({ ...pdfDoc, original: { kind: "text", has_file: false, source_url: null } });
    renderWithIntl(<KnowledgeArticle id="g1" />);
    expect(await screen.findByTestId("article-body")).toHaveTextContent("90일 이내");
    expect(screen.queryByTestId("original-document")).toBeNull();
    expect(screen.queryByTestId("text-version")).toBeNull();
  });
});

describe("translation next to the original", () => {
  it("labels an unreviewed machine translation of critical content and a summary-only translation", async () => {
    get.mockImplementation(async (_p: string, q: { lang: string }) => q.lang === "en"
      ? { ...pdfDoc, translation: { status: "machine", language: "en", title: "Guidebook for international students",
        content: "Register within 90 days of entry.", headings: [], reviewed_at: null, generated_at: "2026-11-23T00:00:00Z",
        source_version_number: 1, scope: "summary", high_risk: true } }
      : pdfDoc);
    renderWithIntl(<KnowledgeArticle id="g1" pdfLoader={fakePdf(2)} />);       // site language: English
    expect(await screen.findByTestId("machine-notice")).toHaveTextContent("Unverified machine translation");
    expect(screen.getByTestId("summary-notice")).toHaveTextContent("Summary only, not a full translation");
    expect(screen.getByRole("heading", { name: "Automatic summary (English)" })).toBeInTheDocument();
    expect(screen.getByTestId("original-document")).toBeInTheDocument();      // the original stays available
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /View original/ }));
    expect(screen.getByTestId("text-version")).toBeInTheDocument();
    expect(screen.queryByTestId("machine-notice")).toBeNull();
  });
});
