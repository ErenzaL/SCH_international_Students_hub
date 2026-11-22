import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { renderMarkdown } from "@/lib/chat-markdown";
import { parseSse } from "@/lib/chat-stream";

describe("chat markdown", () => {
  it("renders lists, bold, links and citations as React nodes", () => {
    render(<div>{renderMarkdown("**Register** at the office [1].\n\n- Passport\n- Photo\n\nSee [HiKorea](https://www.hikorea.go.kr).", {
      renderCitation: (n, key) => <a key={key} href={`#c${n}`}>[{n}]</a>,
    })}</div>);
    expect(screen.getByText("Register").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("link", { name: "HiKorea" })).toHaveAttribute("href", "https://www.hikorea.go.kr/");
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#c1");
  });
  it("never renders HTML or non-http links from model or document text", () => {
    const { container } = render(<div>{renderMarkdown("<script>alert(1)</script> [x](javascript:alert(1)) <img src=x onerror=1>")}</div>);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });
});

describe("sse parsing", () => {
  it("splits complete events and keeps the partial rest", () => {
    const { events, rest } = parseSse(": open\n\nevent: delta\ndata: {\"text\":\"Hi\"}\n\nevent: done\ndata: {\"a\":1}\n\nevent: del");
    expect(events).toEqual([{ event: "delta", data: "{\"text\":\"Hi\"}" }, { event: "done", data: "{\"a\":1}" }]);
    expect(rest).toBe("event: del");
  });
});
