"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";

type EntryState = "idle" | "submitting" | "locked" | "success";
type SupportTopic = "Sign-in recovery" | "Role or access review" | "Expired session";

function EyeIcon({ hidden }: { hidden: boolean }) {
  return hidden ? (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="m3 3 18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 4.2A10.9 10.9 0 0 1 12 4c5.5 0 9 5 9 5a15.7 15.7 0 0 1-2.1 2.5M6.6 6.6C4.3 8.1 3 10 3 10s3.5 5 9 5c1 0 2-.2 2.8-.5" />
    </svg>
  ) : (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M3 12s3.5-5 9-5 9 5 9 5-3.5 5-9 5-9-5-9-5Z" />
      <circle cx="12" cy="12" r="2.2" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M5 12h14M14 7l5 5-5 5" />
    </svg>
  );
}

function SupportIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
      <path d="m6.3 6.3 3.6 3.6m4.2 4.2 3.6 3.6m0-11.4-3.6 3.6m-4.2 4.2-3.6 3.6" />
    </svg>
  );
}

export function SecureEntry() {
  const router = useRouter();
  const supportDialog = useRef<HTMLDialogElement>(null);
  const [entryState, setEntryState] = useState<EntryState>("idle");
  const [error, setError] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [retryMinutes, setRetryMinutes] = useState(15);
  const [supportTopic, setSupportTopic] = useState<SupportTopic | null>(null);

  function openSupport(topic?: SupportTopic) {
    if (topic) {
      setSupportTopic(topic);
    }
    supportDialog.current?.showModal();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setEntryState("submitting");

    const formElement = event.currentTarget;
    const form = new FormData(formElement);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: form.get("username"),
          password: form.get("password"),
        }),
      });

      if (response.status === 423) {
        const seconds = Number(response.headers.get("Retry-After") ?? 900);
        setRetryMinutes(Math.max(1, Math.ceil(seconds / 60)));
        setEntryState("locked");
        return;
      }

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        const passwordInput = formElement.elements.namedItem("password");
        if (passwordInput instanceof HTMLInputElement) {
          passwordInput.value = "";
          passwordInput.focus();
        }
        setError(payload?.detail ?? "Sign-in could not be completed.");
        setEntryState("idle");
        return;
      }

      setEntryState("success");
      window.setTimeout(() => {
        router.replace("/");
        router.refresh();
      }, 450);
    } catch {
      setError("The workspace is unavailable. Please try again shortly.");
      setEntryState("idle");
    }
  }

  return (
    <main className="login-page">
      <div className="login-frame">
        <div aria-label="Financial Integrity Platform" className="login-brand-tab">
          <span aria-hidden="true" className="login-monogram">FIP</span>
          <span>Financial Integrity Platform</span>
        </div>

        <section aria-labelledby="entry-title" className="login-card">
          <div className="login-heading">
            <h1 id="entry-title">Enter the investigation register</h1>
            <p>Use your assigned account.</p>
          </div>

          {(entryState === "idle" || entryState === "submitting") && (
            <form className="login-form" onSubmit={submit}>
              {error && (
                <div className="login-alert" role="alert">
                  <span aria-hidden="true">!</span>
                  <p>{error}</p>
                </div>
              )}

              <label htmlFor="account">Account identifier</label>
              <input autoComplete="username" autoFocus id="account" name="username" required />

              <label htmlFor="password">Password</label>
              <div className="password-control">
                <input
                  autoComplete="current-password"
                  id="password"
                  minLength={8}
                  name="password"
                  required
                  type={passwordVisible ? "text" : "password"}
                />
                <button
                  aria-label={passwordVisible ? "Hide password" : "Show password"}
                  className="icon-button"
                  onClick={() => setPasswordVisible((visible) => !visible)}
                  type="button"
                >
                  <EyeIcon hidden={passwordVisible} />
                </button>
              </div>

              <button
                className="recovery-button"
                onClick={() => openSupport("Sign-in recovery")}
                type="button"
              >
                Forgot password?
              </button>

              <button className="entry-button" disabled={entryState === "submitting"} type="submit">
                <span>{entryState === "submitting" ? "Confirming identity…" : "Enter workspace"}</span>
                <ArrowIcon />
              </button>
            </form>
          )}

          {entryState === "locked" && (
            <section aria-live="polite" className="entry-state">
              <span aria-hidden="true" className="state-mark">×</span>
              <h2>Entry temporarily paused</h2>
              <p>Try again in about {retryMinutes} minutes or use access support.</p>
              <button className="state-support" onClick={() => openSupport("Sign-in recovery")} type="button">
                Open access support
              </button>
            </section>
          )}

          {entryState === "success" && (
            <section aria-live="polite" className="entry-state">
              <span aria-hidden="true" className="state-mark state-mark-success">✓</span>
              <h2>Identity confirmed</h2>
              <p>Opening the case register.</p>
            </section>
          )}

          <footer className="login-footer">
            <span>Authorized personnel only</span>
            <button onClick={() => openSupport()} type="button">
              <SupportIcon />
              Access support
            </button>
          </footer>
        </section>
      </div>

      <dialog aria-labelledby="support-title" className="support-dialog" ref={supportDialog}>
        <div className="support-heading">
          <div>
            <p className="eyebrow">Secure entry</p>
            <h2 id="support-title">Access support</h2>
          </div>
          <button
            aria-label="Close access support"
            className="dialog-close"
            onClick={() => supportDialog.current?.close()}
            type="button"
          >
            ×
          </button>
        </div>
        <div className="support-options">
          {(["Sign-in recovery", "Role or access review", "Expired session"] as SupportTopic[]).map(
            (topic) => (
              <button
                aria-pressed={supportTopic === topic}
                key={topic}
                onClick={() => setSupportTopic(topic)}
                type="button"
              >
                {topic === "Sign-in recovery" && "I can’t sign in"}
                {topic === "Role or access review" && "My access or role is wrong"}
                {topic === "Expired session" && "My session expired"}
              </button>
            ),
          )}
        </div>
        <p aria-live="polite" className="support-note">
          {supportTopic
            ? `${supportTopic} selected. The support handoff can continue from here.`
            : "Access help only; case information stays protected."}
        </p>
      </dialog>
    </main>
  );
}
