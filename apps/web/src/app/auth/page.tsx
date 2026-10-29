"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Loader2, ShieldCheck } from "lucide-react";
import { ApiError, errorMessage, get, post } from "@/lib/api";
import { Button, ErrorNote, Field, Input, Notice } from "@/components/ui";

interface SetupStatus {
  needs_setup: boolean;
  allow_signup: boolean;
  app_name: string;
  environment: string;
}

function AuthCard() {
  const router = useRouter();
  const params = useSearchParams();
  const returnTo = params.get("returnTo") || "/dashboard";
  const initialMode = params.get("mode") === "signup" ? "signup" : "signin";

  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [mode, setMode] = useState<"signin" | "signup">(initialMode);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    get<SetupStatus>("/api/auth/setup-status")
      .then((value) => {
        setStatus(value);
        if (value.needs_setup) setMode("signup");
      })
      .catch(() => setStatus({ needs_setup: false, allow_signup: true, app_name: "Bozii", environment: "" }));
  }, []);

  const needsSetup = status?.needs_setup ?? false;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (needsSetup) {
        await post("/api/auth/setup", { email, name, password });
      } else if (mode === "signup") {
        await post("/api/auth/signup", { email, name, password });
      } else {
        await post("/api/auth/login", { email, password });
      }
      window.location.href = returnTo;
    } catch (caught) {
      setError(errorMessage(caught));
      if (caught instanceof ApiError && caught.code === "signup_disabled") {
        setMode("signin");
      }
    } finally {
      setBusy(false);
    }
  };

  const title = needsSetup
    ? "Create the first account"
    : mode === "signup"
      ? "Create your account"
      : "Sign in to Bozii";
  const submitLabel = needsSetup
    ? "Create account & start"
    : mode === "signup"
      ? "Create account"
      : "Sign in";

  return (
    <div className="flex min-h-screen flex-col bg-canvas">
      <header className="flex h-16 items-center px-5">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-graphite text-sm font-bold text-white">
            B
          </span>
          <span className="text-[15px] font-semibold tracking-tight">Bozii</span>
        </Link>
      </header>

      <main className="flex flex-1 items-center justify-center px-5 pb-16">
        <div className="w-full max-w-md">
          <div className="panel p-6">
            <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            <p className="mt-1 text-sm text-muted">
              {needsSetup
                ? "This instance has no users yet. The first account becomes the administrator."
                : mode === "signup"
                  ? "Accounts are local to this Bozii instance."
                  : "Use the email and password for this instance."}
            </p>

            <form onSubmit={submit} className="mt-5 space-y-4">
              {needsSetup || mode === "signup" ? (
                <Field label="Name">
                  <Input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Ada Lovelace"
                    autoComplete="name"
                  />
                </Field>
              ) : null}

              <Field label="Email" required>
                <Input
                  type="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  autoComplete="email"
                />
              </Field>

              <Field label="Password" required hint={mode === "signup" ? "At least 8 characters." : undefined}>
                <Input
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  autoComplete={mode === "signup" ? "new-password" : "current-password"}
                />
              </Field>

              {error ? <ErrorNote message={error} /> : null}
              {notice ? <Notice message={notice} /> : null}

              <Button type="submit" variant="primary" className="w-full" disabled={busy || !status}>
                {busy ? <Loader2 size={15} className="animate-spin" /> : null}
                {submitLabel}
                {!busy ? <ArrowRight size={15} /> : null}
              </Button>
            </form>

            {!needsSetup ? (
              <div className="mt-4 text-center text-sm text-muted">
                {mode === "signup" ? (
                  <button className="hover:text-ink" onClick={() => setMode("signin")}>
                    Already have an account? Sign in
                  </button>
                ) : status?.allow_signup ? (
                  <button className="hover:text-ink" onClick={() => setMode("signup")}>
                    New here? Create an account
                  </button>
                ) : (
                  <span className="text-xs">Signup is disabled on this instance.</span>
                )}
              </div>
            ) : null}
          </div>

          <div className="mt-4 flex items-center justify-center gap-2 text-xs text-muted">
            <ShieldCheck size={13} className="text-accent" />
            Sessions are cookie-based. Secrets never reach model prompts.
          </div>
        </div>
      </main>
    </div>
  );
}

export default function AuthPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-canvas" />}>
      <AuthCard />
    </Suspense>
  );
}
