"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";

export function HeroSearch() {
  const t = useTranslations("home");
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      aria-label={t("searchLabel")}
      className="mx-auto mt-8 flex max-w-2xl flex-col gap-2 sm:flex-row"
      onSubmit={(e) => {
        e.preventDefault();
        const query = q.trim();
        router.push(query ? `/knowledge?q=${encodeURIComponent(query)}` : "/knowledge");
      }}
    >
      <div className="relative flex-1">
        <Label htmlFor="hero-q" className="sr-only">
          {t("searchLabel")}
        </Label>
        <Search className="pointer-events-none absolute left-3 top-3.5 size-5 text-muted-foreground" aria-hidden />
        <Input
          id="hero-q"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("searchPlaceholder")}
          className="h-12 bg-white pl-10 text-base text-foreground"
        />
      </div>
      <Button type="submit" size="lg" className="bg-white text-primary hover:bg-white/90">
        {t("searchButton")}
      </Button>
    </form>
  );
}
