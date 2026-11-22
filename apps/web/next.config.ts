import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/lib/i18n/request.ts");

// NEXT_PUBLIC_* values are baked into the bundle at build time. On Render (RENDER=true),
// refuse to build a frontend that has no API URL instead of shipping one that points nowhere.
const apiUrl = (process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "").trim();
if (process.env.RENDER && !apiUrl) {
  throw new Error(
    "NEXT_PUBLIC_API_URL is not set for this Render build. Add it to the web service's " +
      "environment (e.g. https://sch-hub-api.onrender.com) and redeploy.",
  );
}
if (apiUrl && process.env.NODE_ENV === "production" && /^https?:\/\/(localhost|127\.0\.0\.1)/i.test(apiUrl)) {
  console.warn(`[next.config] Production build uses a local API URL: ${apiUrl}`);
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default withNextIntl(nextConfig);
