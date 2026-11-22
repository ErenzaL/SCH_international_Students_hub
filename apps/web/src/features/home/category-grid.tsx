"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  Award,
  Briefcase,
  Building2,
  GraduationCap,
  HeartPulse,
  Home,
  Landmark,
  Languages,
  Megaphone,
  ShoppingBasket,
  Stamp,
  type LucideIcon,
} from "lucide-react";
import { CATEGORY_SLUGS, type CategorySlug } from "@/lib/constants";

const ICONS: Record<CategorySlug, LucideIcon> = {
  "visa-immigration": Stamp,
  "part-time-employment": Briefcase,
  "academic-life": GraduationCap,
  scholarships: Award,
  "dormitory-housing": Home,
  "health-insurance": HeartPulse,
  "topik-korean": Languages,
  "employment-internships": Building2,
  "banking-taxes": Landmark,
  "daily-living": ShoppingBasket,
  "university-announcements": Megaphone,
};

export function CategoryGrid() {
  const t = useTranslations("categories");
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {CATEGORY_SLUGS.map((slug) => {
        const Icon = ICONS[slug];
        return (
          <li key={slug}>
            <Link
              href={`/knowledge?category=${slug}`}
              className="flex h-full items-center gap-3 rounded-xl border border-border bg-card p-4 shadow-sm transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary">
                <Icon className="size-5" aria-hidden />
              </span>
              <span className="text-sm font-medium">{t(slug)}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
