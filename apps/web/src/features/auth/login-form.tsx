"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Database, Loader2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label } from "@/components/ui/input";
import { isSupabaseConfigured } from "@/lib/constants";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

/** Only allow same-site relative redirects (prevents open redirects). */
export function safeNextPath(next: string | undefined | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return "/admin";
  return next;
}

export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations("auth");
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  if (!isSupabaseConfigured) {
    return (
      <Alert variant="warning">
        <Database className="size-4" aria-hidden />
        <AlertTitle>{t("notConfiguredTitle")}</AlertTitle>
        <AlertDescription>
          <p>{t("notConfiguredBody")}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>{t("notConfiguredStep1")}</li>
            <li>
              {t("notConfiguredStep2")} <code>NEXT_PUBLIC_SUPABASE_URL</code>, <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code>
            </li>
            <li>{t("notConfiguredStep3")}</li>
          </ol>
        </AlertDescription>
      </Alert>
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    if (!email.includes("@")) return setError(t("errorEmail"));
    if (password.length < 8) return setError(t("errorPassword"));
    const sb = getSupabaseBrowserClient();
    if (!sb) return;
    setBusy(true);
    try {
      if (mode === "signin") {
        const { error: err } = await sb.auth.signInWithPassword({ email, password });
        if (err) throw err;
        router.push(safeNextPath(next));
        router.refresh();
      } else {
        const { data, error: err } = await sb.auth.signUp({ email, password });
        if (err) throw err;
        if (data.session) {
          router.push("/");
          router.refresh();
        } else {
          setInfo(t("confirmEmail"));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("errorGeneric"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{mode === "signin" ? t("signInTitle") : t("signUpTitle")}</CardTitle>
        <CardDescription>{t("roleNote")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">{t("email")}</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">{t("password")}</Label>
            <Input
              id="password"
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <FieldError>{error}</FieldError>
          {info && <Alert variant="success">{info}</Alert>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy && <Loader2 className="animate-spin" />}
            {mode === "signin" ? t("signIn") : t("signUp")}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {mode === "signin" ? t("noAccount") : t("haveAccount")}{" "}
          <button
            type="button"
            className="font-medium text-primary hover:underline"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setInfo(null);
            }}
          >
            {mode === "signin" ? t("signUp") : t("signIn")}
          </button>
        </p>
      </CardContent>
    </Card>
  );
}
