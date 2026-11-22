"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Menu } from "lucide-react";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { MainNav } from "@/components/layout/main-nav";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { AuthMenu } from "@/components/layout/auth-menu";
import { Logo } from "@/components/layout/logo";

export function SiteHeader() {
  const t = useTranslations("nav");
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4">
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="rounded-md p-2 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden"
              aria-label={t("menu")}
            >
              <Menu className="size-5" />
            </button>
          </DialogTrigger>
          <DialogContent side="left" closeLabel={t("close")}>
            <DialogTitle className="sr-only">{t("menu")}</DialogTitle>
            <div className="pt-6">
              <MainNav orientation="vertical" onNavigate={() => setOpen(false)} />
            </div>
          </DialogContent>
        </Dialog>

        <Link href="/" className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <Logo />
        </Link>
        <div className="ml-4 hidden md:block">
          <MainNav />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <LanguageSwitcher />
          <AuthMenu />
        </div>
      </div>
    </header>
  );
}
