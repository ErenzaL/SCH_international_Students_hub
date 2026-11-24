"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Database, GraduationCap, Loader2, ShieldCheck } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, Input, Label } from "@/components/ui/input";
import { LanguageSelect } from "@/features/account/language-select";
import { api } from "@/lib/api";
import { isSupabaseConfigured, LOCALES } from "@/lib/constants";
import { saveLocalePreference } from "@/lib/i18n/preference";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { buildSignupMetadata } from "@/lib/signup";
import type { LanguageCode, Me } from "@/types/api";

/** Only allow same-site relative redirects (prevents open redirects). */
export function safeNextPath(next: string | undefined | null, fallback = "/admin"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return fallback;
  return next;
}

export type Audience = "student" | "staff";

/** Staff sign-in when asked for (?as=staff) or when an admin page sent the visitor here. */
export function initialAudience(as: string | undefined, next: string | undefined): Audience {
  return as === "staff" || (as !== "student" && (next ?? "").startsWith("/admin")) ? "staff" : "student";
}

/**
 * Two ways in: students sign in or create an account (every new account is a student); staff (admins, Global
 * Supporters) only sign in - staff access is granted by a super admin to an existing account, never created here.
 * The split is presentation: roles come from the database and every staff page and API checks them again.
 */
export function LoginForm({ next, as }: { next?: string; as?: string }) {
  const t = useTranslations("auth");
  const router = useRouter();
  const [audience, setAudience] = useState<Audience>(initialAudience(as, next));
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [language, setLanguage] = useState<LanguageCode | "">("");
  const [displayName, setDisplayName] = useState("");
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
    const signup = mode === "signup" && audience === "student";
    const meta = signup ? buildSignupMetadata(language, displayName) : null;
    if (signup && !meta) return setError(t("errorLanguage"));
    const sb = getSupabaseBrowserClient();
    if (!sb) return;
    setBusy(true);
    try {
      if (!signup) {
        const { error: err } = await sb.auth.signInWithPassword({ email, password });
        if (err) throw err;
        // signed in: the profile's preferred language becomes the default on this device too
        let me: Me | null = null;
        try {
          me = await api.get<Me>("/api/v1/me");
          if (me.preferred_language_confirmed && LOCALES.includes(me.preferred_language)) saveLocalePreference(me.preferred_language);
        } catch {
          /* keep the current site language if the profile cannot be read */
        }
        if (audience === "staff" && !me?.is_staff) {
          // no staff role granted to this account: do not leave it signed in on the staff side
          await sb.auth.signOut();
          setError(me ? t("notStaff") : t("errorGeneric"));
          return;
        }
        router.push(safeNextPath(next, audience === "staff" ? "/admin" : "/"));
        router.refresh();
      } else {
        // only the language + optional display name are sent; roles are always assigned server-side
        const { data, error: err } = await sb.auth.signUp({ email, password, options: { data: meta ?? {} } });
        if (err) throw err;
        if (meta) saveLocalePreference(meta.preferred_language);
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

  const switchTo = (a: Audience) => {
    setAudience(a);
    setMode("signin");
    setError(null);
    setInfo(null);
  };
  const signupMode = audience === "student" && mode === "signup";

  return (
    <Card>
      <div role="tablist" aria-label={t("audienceLabel")} className="grid grid-cols-2 gap-1 border-b border-border p-1.5">
        {([["student", GraduationCap], ["staff", ShieldCheck]] as const).map(([id, Icon]) => (
          <button key={id} type="button" role="tab" aria-selected={audience === id} data-testid={`login-${id}`}
            onClick={() => switchTo(id)}
            className={`flex min-h-10 items-center justify-center gap-2 rounded-md text-sm font-semibold transition-colors ${
              audience === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>
            <Icon className="size-4" aria-hidden /> {t(id === "student" ? "studentTab" : "staffTab")}
          </button>
        ))}
      </div>
      <CardHeader>
        <CardTitle className="text-xl">
          {audience === "staff" ? t("staffTitle") : signupMode ? t("signUpTitle") : t("signInTitle")}
        </CardTitle>
        <CardDescription>{audience === "staff" ? t("staffNote") : t("studentNote")}</CardDescription>
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
              autoComplete={signupMode ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {signupMode && (
            <>
              <div className="space-y-1.5">
                <Label htmlFor="signup-language">
                  {t("supportLanguage")} <span aria-hidden className="text-destructive">*</span>
                </Label>
                <LanguageSelect
                  id="signup-language"
                  value={language}
                  onChange={setLanguage}
                  placeholder={t("chooseLanguage")}
                  required
                  aria-describedby="signup-language-help"
                />
                <p id="signup-language-help" className="text-xs text-muted-foreground">
                  {t("supportLanguageHelp")}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="signup-name">{t("displayName")}</Label>
                <Input
                  id="signup-name"
                  autoComplete="nickname"
                  maxLength={80}
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>
            </>
          )}
          <FieldError>{error}</FieldError>
          {info && <Alert variant="success">{info}</Alert>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy && <Loader2 className="animate-spin" />}
            {signupMode ? t("signUp") : t("signIn")}
          </Button>
        </form>
        {audience === "staff" ? (
          <p className="mt-4 rounded-md bg-muted/60 p-3 text-center text-xs text-muted-foreground" data-testid="staff-no-signup">
            {t("staffNoSignup")}
          </p>
        ) : (
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
        )}
      </CardContent>
    </Card>
  );
}
