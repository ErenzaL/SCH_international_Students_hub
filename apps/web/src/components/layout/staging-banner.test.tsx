import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("next-intl/server", () => ({ getTranslations: async () => (k: string) => `t:${k}` }));

describe("staging banner", () => {
  it("is shown only when NEXT_PUBLIC_SITE_ENV is staging", async () => {
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_SITE_ENV", "staging");
    const staged = await import("@/components/layout/staging-banner");
    render(await staged.StagingBanner());
    expect(screen.getByTestId("staging-banner")).toHaveTextContent("t:banner");
    vi.resetModules();
    vi.stubEnv("NEXT_PUBLIC_SITE_ENV", "");
    const prod = await import("@/components/layout/staging-banner");
    expect(await prod.StagingBanner()).toBeNull();
    vi.unstubAllEnvs();
  });
});
