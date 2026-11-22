import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { Bot, MessageCircleQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CategoryGrid } from "@/features/home/category-grid";
import { HeroSearch } from "@/features/home/hero-search";
import { HomeAnnouncements } from "@/features/home/home-announcements";

const FAQ_KEYS = ["f1", "f2", "f3", "f4", "f5"] as const;

export default async function HomePage() {
  const t = await getTranslations("home");
  return (
    <>
      <section className="bg-primary text-primary-foreground">
        <div className="mx-auto max-w-6xl px-4 py-14 text-center md:py-20">
          <p className="mb-3 text-sm font-medium uppercase tracking-widest text-blue-200">{t("eyebrow")}</p>
          <h1 className="text-3xl font-bold tracking-tight md:text-5xl">{t("heroTitle")}</h1>
          <p className="mx-auto mt-4 max-w-2xl text-base text-blue-100 md:text-lg">{t("heroSubtitle")}</p>
          <HeroSearch />
        </div>
      </section>

      <section aria-labelledby="cat-h" className="mx-auto max-w-6xl px-4 pt-14">
        <h2 id="cat-h" className="text-xl font-bold md:text-2xl">
          {t("categoriesTitle")}
        </h2>
        <p className="mb-4 mt-1 text-muted-foreground">{t("categoriesSubtitle")}</p>
        <CategoryGrid />
      </section>

      <HomeAnnouncements />

      <section aria-labelledby="faq-h" className="mx-auto max-w-6xl px-4 pt-14">
        <h2 id="faq-h" className="mb-4 flex items-center gap-2 text-xl font-bold md:text-2xl">
          <MessageCircleQuestion className="size-6 text-primary" aria-hidden /> {t("faqTitle")}
        </h2>
        <div className="divide-y divide-border rounded-xl border border-border bg-card">
          {FAQ_KEYS.map((k) => (
            <details key={k} className="group p-4">
              <summary className="cursor-pointer list-none font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {t(`faq.${k}.q`)}
              </summary>
              <p className="mt-2 text-sm text-muted-foreground">{t(`faq.${k}.a`)}</p>
            </details>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">{t("faqNote")}</p>
      </section>

      <section aria-labelledby="ai-h" className="mx-auto max-w-6xl px-4 pt-14">
        <div className="flex flex-col items-start gap-4 rounded-2xl border border-border bg-secondary/60 p-6 md:flex-row md:items-center md:justify-between">
          <div className="flex gap-4">
            <Bot className="size-10 shrink-0 text-primary" aria-hidden />
            <div>
              <h2 id="ai-h" className="text-xl font-bold">
                {t("assistantTitle")}
              </h2>
              <p className="mt-1 max-w-xl text-sm text-muted-foreground">{t("assistantBody")}</p>
            </div>
          </div>
          <Button asChild size="lg">
            <Link href="/assistant">{t("assistantCta")}</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
