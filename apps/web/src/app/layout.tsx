import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { SiteHeader } from "@/components/layout/site-header";
import { ChatWidget } from "@/features/chatbot/chat-widget";
import { SiteFooter } from "@/components/layout/site-footer";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("brand");
  return {
    title: { default: t("name"), template: `%s · ${t("name")}` },
    description: t("description"),
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [locale, messages] = await Promise.all([getLocale(), getMessages()]);
  const nav = await getTranslations("nav");
  return (
    <html lang={locale} className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
          >
            {nav("skipToContent")}
          </a>
          <SiteHeader />
          <main id="main" className="flex-1">
            {children}
          </main>
          <SiteFooter />
          <ChatWidget />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
