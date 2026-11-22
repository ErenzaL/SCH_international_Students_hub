# apps/web — SCH International Student Hub (frontend)

Next.js 16 (App Router) · TypeScript · Tailwind CSS v4 · shadcn-style UI components · next-intl · Supabase Auth (browser, anon key only).

## Run

```bash
npm install
cp ../../.env.example .env.local   # then edit NEXT_PUBLIC_* values (see root .env.example)
npm run dev                         # http://localhost:3000
```

| Script | What it does |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` / `npm start` | Production build / `next start -p ${PORT:-3000}` |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint |
| `npm test` | Vitest + Testing Library |

Only these variables are read by the browser: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Never put a service-role key here.

## Layout

```
src/app/            routes (public pages, /login, /admin/*), proxy.ts gate for /admin
src/components/     ui/ (button, card, dialog …), layout/ (header, nav, language switcher), shared/ (states, badges)
src/features/       announcements, knowledge, assistant, home, auth, admin/{shell,sources,documents,review,announcements,translations,users,settings,overview}
src/lib/            api.ts (typed client + ApiError), use-api.ts, jobs.ts (ingestion polling), i18n/, supabase/, constants.ts
src/messages/       en.json (base) + ko/id/vi/zh-CN (missing keys fall back to English)
src/types/api.ts    TypeScript mirror of ../../docs/api-contract.md
```

## i18n

No locale-prefixed routes. Locale = `NEXT_LOCALE` cookie → `Accept-Language` → `en`. The switcher writes the cookie + `localStorage` and calls `router.refresh()`. Catalogs are deep-merged over English (`src/lib/i18n/merge.ts`). A test (`src/messages/messages.test.ts`) fails if a literal translation key used in code is missing from `en.json` or if a locale has keys English lacks.
UI translations are provisional; they translate the interface only, never knowledge content.

## Auth & authorization

`src/proxy.ts` (Next 16's replacement for middleware) redirects unauthenticated `/admin/*` visits to `/login` when Supabase is configured. That is a UX convenience only — the admin shell loads `GET /api/v1/me` and the FastAPI backend / Postgres RLS enforce every permission.
