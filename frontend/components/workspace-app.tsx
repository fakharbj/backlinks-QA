"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Copy,
  Download,
  Eye,
  EyeOff,
  FileSpreadsheet,
  Filter,
  Gauge,
  GitCompare,
  Globe,
  History,
  Info,
  Layers,
  Lightbulb,
  Link2,
  ClipboardCopy,
  Pencil,
  Loader2,
  LogOut,
  Moon,
  Play,
  Plus,
  RefreshCw,
  Settings,
  Sheet,
  ShieldAlert,
  SlidersHorizontal,
  Star,
  Sun,
  Swords,
  Trash2,
  Upload,
  UserPlus,
  Users,
  X,
  XCircle
} from "lucide-react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Fragment, FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  AlertRule,
  AnalyticsResponse,
  api,
  API_BASE,
  ApiError,
  clearTokens,
  getAccessToken,
  loadTokens,
  refreshAccess,
  setTokens,
  AssignmentEvent,
  BacklinkDetail,
  BacklinkRow,
  Batch,
  BatchItem,
  BatchItemsPage,
  BatchLog,
  ImportRowError,
  IssueEvidence,
  SpamMatch,
  CompetitorDomain,
  CompetitorParent,
  CompetitorSheet,
  CompetitorSummary,
  ConflictAction,
  ConflictDetail,
  ConflictFieldMatrixRow,
  ConflictGroup,
  ConflictSummary,
  Dashboard,
  EmployeeOverview,
  LabelSuggestions,
  LabelSuggestionCluster,
  LinkType,
  Page,
  Project,
  ProjectDomain,
  ProjectSettings,
  Report,
  RescoreResult,
  Role,
  ScoringConfig,
  SheetConfig,
  SheetSource,
  SourceDomain,
  SourceDomainDetail,
  SourceDomainList,
  SourceDomainStats,
  SourceDomainRule,
  SourceDomainRuleCondition,
  SourceDomainRuleDefinition,
  SourceDomainSavedFilter,
  SiteMetrics,
  TeamMember,
  TokenPair
} from "@/lib/api";

type Tab = "overview" | "analytics" | "backlinks" | "conflicts" | "domains" | "competitors" | "imports" | "sheets" | "domain-import" | "batches" | "alerts" | "reports" | "performance" | "users" | "tasks" | "team" | "employees" | "scoring" | "settings" | "mywork" | "mydash" | "apiusage" | "myopps" | "guidance" | "myscoring" | "statusguide";

const samplePaste = `source_url,target_url,expected_anchor_text,expected_rel,campaign,vendor,tags
https://example.com/best-tools,https://acme.test/seo,Acme SEO,dofollow,Q3 Outreach,EditorialHub,"guest-post,tier1"
https://publisher.test/review,https://acme.test/pricing,pricing guide,dofollow,Q3 Outreach,LinkDesk,"review,tier2"`;

export function WorkspaceApp() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectIdState] = useState<string>("");
  const [tab, setTabState] = useState<Tab>("overview");
  // Toast stack: every onNotice(text) becomes a stacked, auto-dismissing toast.
  const [toasts, setToasts] = useState<Array<{ id: number; text: string; kind: "info" | "error" }>>([]);
  const setNotice = (text: string) => {
    if (!text) return;
    const id = Date.now() + Math.random();
    const kind = /fail|error|could not|couldn't|denied|invalid|not found/i.test(text)
      ? ("error" as const)
      : ("info" as const);
    setToasts((t) => [...t.slice(-3), { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6500);
  };

  // ── Context persistence ───────────────────────────────────────────────
  // The URL (?project&tab) is the source of truth so refresh, deep links and
  // Back/Forward all keep context; localStorage restores it on bare visits.
  const syncUrl = (project: string, nextTab: Tab, push: boolean) => {
    const q = new URLSearchParams(window.location.search);
    if (project) q.set("project", project);
    else q.delete("project");
    q.set("tab", nextTab);
    const url = `${window.location.pathname}?${q.toString()}`;
    if (push) window.history.pushState(null, "", url);
    else window.history.replaceState(null, "", url);
    try {
      localStorage.setItem("ls_project", project);
      localStorage.setItem("ls_tab", nextTab);
    } catch {
      /* private mode */
    }
  };

  const setTab = (next: Tab) => {
    setTabState(next);
    syncUrl(activeProjectId, next, true);
  };

  // Click-through: open the Backlinks desk pre-filtered (e.g. clicking "Fail"
  // on a dashboard). Filters travel as f_* URL params; Backlinks reads them on
  // mount and then removes them, so refresh/back behave normally.
  const openBacklinks = (filters: Record<string, string>) => {
    const q = new URLSearchParams(window.location.search);
    Object.entries(filters).forEach(([k, v]) => {
      if (v) q.set(`f_${k}`, v);
    });
    window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
    setTab("backlinks");
  };

  // Same pattern for batches: "Open review batch" from Imports/Import Domains
  // jumps straight into that batch's details.
  const openBatch = (batchId: string) => {
    const q = new URLSearchParams(window.location.search);
    q.set("f_batch", batchId);
    window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
    setTab("batches");
  };

  // Open a specific person's dashboard from anywhere (Performance rows, cards).
  const openUserDash = (label: string) => {
    const q = new URLSearchParams(window.location.search);
    q.set("f_user", label);
    window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
    setTab("users");
  };

  const setActiveProjectId = (next: string) => {
    // Entering/leaving project context: keep the tab if the new nav has it,
    // otherwise land on the dashboard.
    const nextTab = navTabs(Boolean(next), role).includes(tab)
      ? tab
      : role === "viewer"
        ? "mywork"
        : "overview";
    setActiveProjectIdState(next);
    setTabState(nextTab);
    syncUrl(next, nextTab, true);
  };

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = q.get("project") ?? localStorage.getItem("ls_project") ?? "";
    const rawTab = q.get("tab") ?? localStorage.getItem("ls_tab");
    const t: Tab = isTab(rawTab) ? rawTab : "overview";
    setActiveProjectIdState(p);
    setTabState(t);
    syncUrl(p, t, false);

    const onPop = () => {
      const qq = new URLSearchParams(window.location.search);
      const pp = qq.get("project") || "";
      const tt = qq.get("tab");
      setActiveProjectIdState(pp);
      setTabState(isTab(tt) ? tt : "overview");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadTokens();
    setToken(getAccessToken());
    setRefreshToken(localStorage.getItem("ls_refresh"));

    // The token manager fires this when the refresh token is dead → real logout.
    const onExpired = () => {
      setToken(null);
      setRefreshToken(null);
      setActiveProjectIdState("");
      queryClient.clear();
      setNotice("Session expired — please sign in again.");
    };
    window.addEventListener("ls-auth-expired", onExpired);

    // Proactively refresh the access token well before its 15-min expiry so the
    // session stays alive for the refresh token's full 7-day life (no surprise logout).
    const timer = setInterval(() => {
      if (localStorage.getItem("ls_refresh")) {
        refreshAccess().then((ok) => {
          if (ok) setToken(getAccessToken());
        });
      }
    }, 10 * 60 * 1000);

    return () => {
      window.removeEventListener("ls-auth-expired", onExpired);
      clearInterval(timer);
    };
  }, [queryClient]);

  const authed = Boolean(token);
  // Who am I → role-safe navigation (viewer = My Work only; manager/qa lose
  // the admin desks they'd only 403 on).
  const me = useQuery({
    queryKey: ["me", token],
    enabled: authed,
    retry: false,
    queryFn: () => api<{ role: string; user: { full_name: string; email: string } }>("/auth/me", { token })
  });
  const role = me.data?.role ?? null;
  useEffect(() => {
    if (!role) return;
    if (!navTabs(Boolean(activeProjectId), role).includes(tab)) {
      const fallback: Tab = role === "viewer" ? "mywork" : "overview";
      setTabState(fallback);
      syncUrl(activeProjectId, fallback, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, tab, activeProjectId]);
  const projects = useQuery({
    queryKey: ["projects", token],
    enabled: authed,
    queryFn: () => api<Project[]>("/projects", { token })
  });

  // Default scope is "All projects" (company dashboard); the user picks a project to
  // drill into a project dashboard. (No auto-select of the first project.)

  function saveTokens(tokens: TokenPair) {
    setTokens(tokens);
    setToken(tokens.access_token);
    setRefreshToken(tokens.refresh_token);
  }

  function logout() {
    clearTokens();
    setToken(null);
    setRefreshToken(null);
    setActiveProjectIdState("");
    setTabState("overview");
    try {
      localStorage.removeItem("ls_project");
      localStorage.removeItem("ls_tab");
    } catch {
      /* ignore */
    }
    window.history.replaceState(null, "", window.location.pathname);
    queryClient.clear();
  }

  if (!authed) {
    return <AuthPanel onToken={saveTokens} />;
  }

  // SECURITY: never flash the full admin UI while the role is still loading —
  // a standard user must only ever see their own surface.
  if (!role) {
    return (
      <main className="grid min-h-screen place-items-center">
        <div className="flex flex-col items-center gap-3 text-muted">
          <Loader2 className="h-6 w-6 animate-spin" />
          <span className="text-sm">Loading your workspace…</span>
          {me.isError ? (
            <button onClick={logout} className="text-xs font-medium text-ocean hover:underline">
              Sign in again
            </button>
          ) : null}
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen">
      <TopBar
        onLogout={logout}
        onRefresh={() => {
          queryClient.invalidateQueries();
          setNotice("Refreshing workspace data");
        }}
      />
      <section className="mx-auto flex w-full gap-5 px-5 py-4">
        <aside className="hidden w-[248px] shrink-0 lg:block">
          <div className="sticky top-[56px]">
            <Sidebar
              activeTab={tab}
              onTab={setTab}
              token={token}
              projects={projects.data || []}
              activeProjectId={activeProjectId}
              onSelect={setActiveProjectId}
              onNotice={setNotice}
              role={role}
            />
          </div>
        </aside>
        <section key={`${tab}-${activeProjectId}`} className="desk-enter min-w-0 flex-1 space-y-5">
          <MobileNav activeTab={tab} onTab={setTab} inProject={Boolean(activeProjectId)} role={role} />
          {role !== "viewer" ? (
            <div className="lg:hidden">
              <ProjectPanel
                token={token}
                projects={projects.data || []}
                activeProjectId={activeProjectId}
                onSelect={setActiveProjectId}
                onNotice={setNotice}
              />
            </div>
          ) : null}
          <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[380px] max-w-[92vw] flex-col gap-2">
            {toasts.map((t) => (
              <div
                key={t.id}
                className={clsx(
                  "pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-panel/95 p-3 text-sm shadow-pop backdrop-blur",
                  t.kind === "error" ? "border-danger/40" : "border-ocean/40"
                )}
              >
                <span
                  className={clsx(
                    "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                    t.kind === "error" ? "bg-danger" : "bg-ocean"
                  )}
                />
                <span className="flex-1 break-words text-ink">{t.text}</span>
                <button
                  onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
                  className="shrink-0 text-muted hover:text-ink"
                  aria-label="Dismiss"
                >
                  <XCircle className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          {tab === "overview" ? (
            <Overview token={token} projectId={activeProjectId} onOpenBacklinks={openBacklinks} />
          ) : null}
          {tab === "analytics" ? <AnalyticsDesk token={token} projectId={activeProjectId} onNotice={setNotice} onOpenBacklinks={openBacklinks} /> : null}
          {tab === "backlinks" ? (
            <Backlinks token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "conflicts" ? <ConflictsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "domains" ? (
            <SourceDomainsDesk
              token={token}
              projectId={activeProjectId}
              onNotice={setNotice}
              onOpenBacklinks={openBacklinks}
              onImportDomains={() => setTab("domain-import")}
            />
          ) : null}
          {tab === "competitors" ? (
            <CompetitorDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "imports" ? (
            <ImportDesk token={token} projectId={activeProjectId} onNotice={setNotice} onOpenBatch={openBatch} />
          ) : null}
          {tab === "sheets" ? <SheetsDesk token={token} projectId={activeProjectId} onNotice={setNotice} /> : null}
          {tab === "domain-import" ? (
            <DomainImportDesk token={token} onNotice={setNotice} onOpenBatch={openBatch} />
          ) : null}
          {tab === "batches" ? (
            <BatchesDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "performance" ? (
            <PerformanceDesk token={token} projectId={activeProjectId} onOpenBacklinks={openBacklinks} onNotice={setNotice} onOpenUser={openUserDash} />
          ) : null}
          {tab === "users" ? (
            <UserDashboardsDesk token={token} projectId={activeProjectId} onOpenBacklinks={openBacklinks} onNotice={setNotice} onPlanWork={() => setTab("tasks")} />
          ) : null}
          {tab === "tasks" ? (
            <TasksDesk token={token} projectId={activeProjectId} projects={projects.data || []} onNotice={setNotice} />
          ) : null}
          {tab === "alerts" ? (
            <AlertsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "reports" ? (
            <ReportsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "team" ? <TeamDesk token={token} onNotice={setNotice} /> : null}
          {tab === "scoring" ? (
            <ScoringDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "settings" ? (
            <SettingsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "mywork" ? <MyWorkDesk token={token} onNotice={setNotice} /> : null}
          {tab === "mydash" ? <MySelfDashboard token={token} onNotice={setNotice} /> : null}
          {tab === "apiusage" ? <ApiUsageDesk token={token} /> : null}
          {tab === "myopps" ? <MyOpportunitiesDesk token={token} /> : null}
          {tab === "guidance" ? <GuidanceDesk token={token} fixed="next" /> : null}
          {tab === "myscoring" ? <GuidanceDesk token={token} fixed="scoring" /> : null}
          {tab === "statusguide" ? <GuidanceDesk token={token} fixed="statuses" /> : null}
        </section>
      </section>
    </main>
  );
}

function AuthPanel({ onToken }: { onToken: (tokens: TokenPair) => void }) {
  const [mode, setMode] = useState<"login" | "register" | "forgot" | "reset">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [fullName, setFullName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  // Public branding (company name/logo/announcement) — no auth on this endpoint.
  const branding = useQuery({
    queryKey: ["branding"],
    queryFn: () =>
      api<{
        company_name: string | null; logo_data_uri: string | null;
        announcement?: string | null; smtp_ready?: boolean;
      }>("/auth/branding"),
    staleTime: 300000
  });

  const submit = useMutation({
    mutationFn: async () => {
      setError("");
      const body =
        mode === "login"
          ? { email, password }
          : { email, password, full_name: fullName, workspace_name: workspaceName };
      return api<TokenPair>(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify(body)
      });
    },
    onSuccess: onToken,
    onError: (err: Error) => setError(err.message)
  });
  const forgot = useMutation({
    mutationFn: () =>
      api<{ message: string }>("/auth/forgot-password", {
        method: "POST", body: JSON.stringify({ email })
      }),
    onSuccess: () => {
      setError("");
      setInfo("If that account exists, a reset code is on its way — check the inbox, then paste the code below.");
      setMode("reset");
    },
    onError: (err: Error) => setError(err.message)
  });
  const reset = useMutation({
    mutationFn: () =>
      api<{ message: string }>("/auth/reset-password", {
        method: "POST", body: JSON.stringify({ token: resetCode.trim(), new_password: password })
      }),
    onSuccess: (d) => {
      setError("");
      setInfo(d.message || "Password updated — sign in with your new password.");
      setPassword("");
      setResetCode("");
      setMode("login");
    },
    onError: (err: Error) => setError(err.message)
  });

  const title =
    mode === "login" ? "Sign in"
    : mode === "register" ? "Create workspace"
    : mode === "forgot" ? "Reset your password"
    : "Enter your reset code";

  const passwordField = (autoComplete: string, label = "Password") => (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase text-muted">{label}</span>
      <span className="relative block">
        <input
          type={showPw ? "text" : "password"}
          name="password"
          autoComplete={autoComplete}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="h-10 w-full rounded-md border border-line bg-panel px-3 pr-10 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
        />
        <button
          type="button"
          onClick={() => setShowPw((v) => !v)}
          title={showPw ? "Hide password" : "Show password"}
          aria-label={showPw ? "Hide password" : "Show password"}
          className="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded text-muted hover:bg-field hover:text-ink"
        >
          {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </span>
    </label>
  );

  return (
    <main className="relative grid min-h-screen place-items-center overflow-hidden px-5">
      {/* Premium-feel backdrop: soft brand-colored glows, no imagery to load. */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute -left-32 -top-32 h-96 w-96 rounded-full bg-ocean/10 blur-3xl" />
        <div className="absolute -bottom-40 -right-24 h-[28rem] w-[28rem] rounded-full bg-plum/10 blur-3xl" />
      </div>
      <section className="relative w-full max-w-[460px] rounded-2xl border border-line bg-panel p-6 shadow-card">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold uppercase text-ocean">Performance by Techsa</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">{title}</h1>
            {branding.data?.company_name ? (
              <p className="mt-1 text-sm text-muted">{branding.data.company_name}</p>
            ) : null}
          </div>
          {branding.data?.logo_data_uri ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={branding.data.logo_data_uri}
              alt=""
              className="h-10 w-10 rounded-lg object-contain"
            />
          ) : (
            <ShieldAlert className="h-7 w-7 text-plum" aria-hidden />
          )}
        </div>
        {branding.data?.announcement ? (
          <p className="mb-4 rounded-lg border border-ocean/30 bg-ocean/5 p-2.5 text-sm text-ink">
            📢 {branding.data.announcement}
          </p>
        ) : null}
        {info ? <p className="mb-3 rounded bg-ocean/10 p-2 text-sm text-ocean">{info}</p> : null}
        {mode === "forgot" ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (email.trim()) forgot.mutate();
            }}
          >
            <p className="text-sm text-muted">
              Enter your account email — we&apos;ll send a one-time reset code.
            </p>
            <Field label="Email" type="email" value={email} onChange={setEmail} name="email" autoComplete="email" />
            {error ? <p className="rounded bg-danger/10 p-2 text-sm text-danger">{error}</p> : null}
            <button
              type="submit"
              disabled={forgot.isPending || !email.trim()}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-ocean px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
            >
              {forgot.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Email me a reset code
            </button>
            <button type="button" onClick={() => { setMode("login"); setError(""); setInfo(""); }}
              className="w-full rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition hover:bg-field">
              Back to sign in
            </button>
          </form>
        ) : mode === "reset" ? (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (resetCode.trim() && password.length >= 8) reset.mutate();
            }}
          >
            <Field label="Reset code (from the email)" value={resetCode} onChange={setResetCode} name="one-time-code" autoComplete="one-time-code" />
            {passwordField("new-password", "New password (min 8 characters)")}
            {error ? <p className="rounded bg-danger/10 p-2 text-sm text-danger">{error}</p> : null}
            <button
              type="submit"
              disabled={reset.isPending || !resetCode.trim() || password.length < 8}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-ocean px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
            >
              {reset.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Set new password
            </button>
            <button type="button" onClick={() => { setMode("login"); setError(""); setInfo(""); }}
              className="w-full rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition hover:bg-field">
              Back to sign in
            </button>
          </form>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              submit.mutate();
            }}
          >
            {mode === "register" ? (
              <>
                <Field label="Full name" value={fullName} onChange={setFullName} name="name" autoComplete="name" />
                <Field label="Workspace" value={workspaceName} onChange={setWorkspaceName} name="organization" autoComplete="organization" />
              </>
            ) : null}
            <Field label="Email" type="email" value={email} onChange={setEmail} name="email" autoComplete="email" />
            {passwordField(mode === "login" ? "current-password" : "new-password")}
            {error ? <p className="rounded bg-danger/10 p-2 text-sm text-danger">{error}</p> : null}
            <button
              type="submit"
              disabled={submit.isPending || !email.trim() || !password}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-ocean px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
            >
              {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              {mode === "login" ? "Sign in" : "Create account"}
            </button>
            {mode === "login" && branding.data?.smtp_ready ? (
              <button
                type="button"
                onClick={() => { setMode("forgot"); setError(""); setInfo(""); }}
                className="w-full text-center text-sm font-medium text-ocean hover:underline"
              >
                Forgot password?
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setMode(mode === "login" ? "register" : "login")}
              className="w-full rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition hover:bg-field"
            >
              {mode === "login" ? "Create a new workspace" : "Use existing account"}
            </button>
          </form>
        )}
        <p className="mt-4 text-center text-[11px] font-medium tracking-wide text-muted">
          Powered by <span className="font-semibold text-ink">Techsa</span>
        </p>
      </section>
    </main>
  );
}

type NavIcon = typeof Gauge;
type NavGroup = { label: string; items: Array<[Tab, string, NavIcon]> };

// ── Context-aware navigation (enterprise SaaS pattern) ─────────────────────
// Company context = the full workspace/admin surface. Selecting a project
// switches the ENTIRE nav to project-scoped items only — workspace admin
// (Team, Employees, Sheets config) disappears until you exit the project.
const WORKSPACE_NAV: NavGroup[] = [
  {
    label: "Monitor",
    items: [
      ["overview", "Dashboard", Gauge],
      ["analytics", "Analytics", BarChart3],
      ["performance", "Performance", Activity],
      ["users", "User Dashboards", Users],
      ["apiusage", "API Usage", Activity]
    ]
  },
  {
    label: "Backlinks",
    items: [
      ["backlinks", "Backlinks", Link2],
      ["conflicts", "Duplicates", Layers],
      ["domains", "Source Domains", Globe],
      ["competitors", "Competitors", Swords]
    ]
  },
  {
    label: "Ingest",
    items: [
      ["imports", "Import Backlinks", Upload],
      ["sheets", "Sheets", Sheet],
      ["domain-import", "Import Domains", Globe],
      ["batches", "Batches", History]
    ]
  },
  { label: "Output", items: [["alerts", "Alerts", Bell], ["reports", "Reports", FileSpreadsheet]] },
  {
    label: "Workspace",
    items: [
      ["tasks", "Tasks & Calendar", CalendarDays],
      ["team", "Team", Users],
      ["scoring", "Scoring", SlidersHorizontal],
      ["settings", "Settings", Settings]
    ]
  }
];

const PROJECT_NAV: NavGroup[] = [
  {
    label: "Project",
    items: [
      ["overview", "Dashboard", Gauge],
      ["backlinks", "Backlinks", Link2],
      ["conflicts", "Duplicates", Layers],
      ["domains", "Source Domains", Globe],
      ["competitors", "Competitors", Swords]
    ]
  },
  {
    label: "Monitor",
    items: [
      ["analytics", "Analytics", BarChart3],
      ["performance", "Performance", Activity],
      ["users", "User Dashboards", Users],
      ["tasks", "Tasks", CalendarDays],
      ["reports", "Reports", FileSpreadsheet],
      ["alerts", "Alerts", Bell]
    ]
  },
  { label: "Ingest", items: [["imports", "Import Backlinks", Upload], ["sheets", "Sheets", Sheet], ["batches", "Batches", History]] },
  {
    label: "Configure",
    items: [["scoring", "Scoring", SlidersHorizontal], ["settings", "Settings", Settings]]
  }
];

// Standard users (Viewer role) get their OWN focused surface — tasks, targets,
// completion and leave — never the team-wide/admin desks.
const MY_NAV: NavGroup[] = [
  {
    label: "My Work",
    items: [
      ["mywork", "My Work", CalendarDays],
      ["mydash", "My Dashboard", Gauge]
    ]
  },
  {
    label: "Grow",
    items: [
      ["myopps", "Opportunities", Globe],
      ["guidance", "Guidance", Lightbulb],
      ["myscoring", "Scoring", Gauge],
      ["statusguide", "Status Guide", Info]
    ]
  }
];

// Role-safe navigation: hide what a role cannot use so nobody clicks into 403s.
const roleFilterNav = (groups: NavGroup[], role: string | null): NavGroup[] => {
  if (!role || role === "admin") return groups;
  const hidden = new Set<Tab>(
    role === "manager"
      ? ["team", "settings"]
      : ["team", "settings", "sheets", "scoring", "apiusage"] // qa
  );
  return groups
    .map((g) => ({ ...g, items: g.items.filter(([id]) => !hidden.has(id)) }))
    .filter((g) => g.items.length);
};

const navGroups = (inProject: boolean, role: string | null): NavGroup[] => {
  if (role === "viewer") return MY_NAV;
  return roleFilterNav(inProject ? PROJECT_NAV : WORKSPACE_NAV, role);
};
const navTabs = (inProject: boolean, role: string | null): Tab[] =>
  navGroups(inProject, role).flatMap((g) => g.items.map(([id]) => id));
const ALL_TAB_IDS = new Set<string>([
  ...navTabs(false, "admin"),
  ...navTabs(true, "admin"),
  "mywork"
]);
const isTab = (v: string | null): v is Tab => Boolean(v) && ALL_TAB_IDS.has(v as string);

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("ls-theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
  };
  return (
    <button
      onClick={toggle}
      title={dark ? "Switch to light" : "Switch to dark"}
      aria-label="Toggle theme"
      className="grid h-8 w-8 place-items-center rounded-lg border border-line bg-panel shadow-card text-muted transition hover:bg-field hover:text-ink"
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function TopBar({ onLogout, onRefresh }: { onLogout: () => void; onRefresh: () => void }) {
  // Public branding (company name + logo) — set by an admin in Settings.
  const branding = useQuery({
    queryKey: ["branding"],
    queryFn: () =>
      api<{ company_name: string | null; logo_data_uri: string | null }>("/auth/branding"),
    staleTime: 300000
  });
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-panel/70 backdrop-blur-xl">
      <div className="mx-auto flex w-full items-center justify-between px-5 py-1.5">
        <div className="flex items-center gap-2.5">
          {branding.data?.logo_data_uri ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={branding.data.logo_data_uri}
              alt=""
              className="h-7 w-7 rounded-lg object-contain"
            />
          ) : (
            <div className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-ocean to-plum text-white shadow-soft">
              <Activity className="h-4 w-4" />
            </div>
          )}
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-bold tracking-tight text-ink">Performance</span>
            <span className="hidden text-[10px] font-medium uppercase tracking-wide text-muted sm:inline">
              by Techsa · {branding.data?.company_name || "SEO operations"}
            </span>
          </div>
        </div>
        <div className="flex gap-1.5">
          <ThemeToggle />
          <IconButton label="Refresh" onClick={onRefresh} icon={RefreshCw} />
          <IconButton label="Log out" onClick={onLogout} icon={LogOut} />
        </div>
      </div>
    </header>
  );
}

function Sidebar({
  activeTab,
  onTab,
  token,
  projects,
  activeProjectId,
  onSelect,
  onNotice,
  role
}: {
  activeTab: Tab;
  onTab: (tab: Tab) => void;
  token: string | null;
  projects: Project[];
  activeProjectId: string;
  onSelect: (id: string) => void;
  onNotice: (text: string) => void;
  role: string | null;
}) {
  return (
    <div className="space-y-4">
      {role !== "viewer" ? (
        <ProjectPanel
          token={token}
          projects={projects}
          activeProjectId={activeProjectId}
          onSelect={onSelect}
          onNotice={onNotice}
        />
      ) : null}
      {activeProjectId && role !== "viewer" ? (
        <div className="flex items-center justify-between rounded-xl border border-ocean/30 bg-ocean/10 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-ocean">
            Project context
          </span>
          <button
            onClick={() => onSelect("")}
            className="text-xs font-medium text-ocean hover:underline"
          >
            Exit
          </button>
        </div>
      ) : null}
      <nav className="rounded-xl border border-line bg-panel p-2 shadow-card">
        {navGroups(Boolean(activeProjectId), role).map((group) => (
          <div key={group.label} className="mb-1 last:mb-0">
            <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
              {group.label}
            </div>
            <div className="space-y-0.5">
              {group.items.map(([id, label, Icon]) => {
                const active = activeTab === id;
                return (
                  <button
                    key={id}
                    onClick={() => onTab(id)}
                    className={clsx(
                      "group relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition",
                      active
                        ? "bg-ocean/10 font-semibold text-ocean"
                        : "font-medium text-muted hover:bg-field hover:text-ink"
                    )}
                  >
                    {active ? (
                      <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-ocean" />
                    ) : null}
                    <Icon className="h-4 w-4 shrink-0" />
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
    </div>
  );
}

function MobileNav({
  activeTab,
  onTab,
  inProject,
  role
}: {
  activeTab: Tab;
  onTab: (tab: Tab) => void;
  inProject: boolean;
  role: string | null;
}) {
  return (
    <nav className="flex gap-1 overflow-x-auto rounded-xl border border-line bg-panel p-1 shadow-card scrollbar-thin lg:hidden">
      {navGroups(inProject, role).flatMap((g) => g.items).map(([id, label, Icon]) => (
        <button
          key={id}
          onClick={() => onTab(id)}
          title={label}
          className={clsx(
            "flex h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-sm font-medium transition",
            activeTab === id ? "bg-ocean/10 font-semibold text-ocean" : "text-muted hover:bg-field hover:text-ink"
          )}
        >
          <Icon className="h-4 w-4" />
          {label}
        </button>
      ))}
    </nav>
  );
}

function ProjectPanel({
  token,
  projects,
  activeProjectId,
  onSelect,
  onNotice
}: {
  token: string | null;
  projects: Project[];
  activeProjectId: string;
  onSelect: (id: string) => void;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const [domain, setDomain] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const createProject = useMutation({
    mutationFn: () =>
      api<Project>("/projects", {
        token,
        method: "POST",
        body: JSON.stringify({
          name,
          client_name: client,
          target_domain: domain,
          target_urls: [`https://${domain}`],
          tags: []
        })
      }),
    onSuccess: (project) => {
      onNotice("Project created");
      setName("");
      setClient("");
      setDomain("");
      setShowCreate(false);
      // Seed the cache so the new project appears instantly, then refetch.
      queryClient.setQueryData<Project[]>(["projects", token], (old) =>
        old ? [project, ...old] : [project]
      );
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onSelect(project.id);
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Per-project logos live in the workspace setting "project_logos" ({projectId: dataURI}).
  const workspaceSettings = useQuery({
    queryKey: ["workspace-settings", token],
    enabled: Boolean(token),
    retry: false,
    staleTime: 300000,
    queryFn: () =>
      api<Array<{ key: string; value: Record<string, unknown> }>>("/settings", { token })
  });
  const projectLogos: Record<string, string> =
    (workspaceSettings.data?.find((s) => s.key === "project_logos")?.value as
      Record<string, string>) || {};

  const active = projects.find((p) => p.id === activeProjectId) || null;
  const shown = projects.filter((p) =>
    `${p.name} ${p.client_name || ""}`.toLowerCase().includes(q.trim().toLowerCase())
  );
  const initials = (n: string) =>
    n.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || "").join("") || "P";
  const pick = (id: string) => {
    onSelect(id);
    setOpen(false);
    setQ("");
    setShowCreate(false);
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          "flex w-full items-center gap-2.5 rounded-xl border p-2.5 text-left shadow-card transition",
          active
            ? "border-plum/40 bg-gradient-to-r from-plum/10 to-ocean/5 hover:border-plum/60"
            : "border-line bg-panel hover:border-ocean/40"
        )}
      >
        {active && projectLogos[active.id] ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={projectLogos[active.id]}
            alt=""
            className="h-9 w-9 shrink-0 rounded-lg object-cover"
          />
        ) : (
          <span
            className={clsx(
              "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xs font-bold text-white dark:text-slate-900",
              active ? "bg-gradient-to-br from-plum to-ocean" : "bg-gradient-to-br from-ocean to-teal-500"
            )}
          >
            {active ? initials(active.name) : <Globe className="h-4 w-4" />}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-ink">
            {active ? active.name : "Dashboard"}
          </span>
          <span className="block truncate text-[11px] text-muted">
            {active ? (active.client_name || "Project workspace") : "Company view — everything combined"}
          </span>
        </span>
        <ChevronDown className={clsx("h-4 w-4 shrink-0 text-muted transition", open && "rotate-180")} />
      </button>

      {open ? (
        <div className="absolute left-0 right-0 top-full z-40 mt-1.5 rounded-xl border border-line bg-panel p-2 shadow-pop">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search projects…"
            autoFocus
            className="mb-1.5 h-9 w-full rounded-lg border border-line bg-panel px-2.5 text-sm focus:border-ocean focus:outline-none"
          />
          <div className="max-h-72 overflow-y-auto">
            <button
              onClick={() => pick("")}
              className={clsx(
                "flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition hover:bg-field",
                !activeProjectId && "bg-ocean/10"
              )}
            >
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-ocean to-teal-500 text-white dark:text-slate-900">
                <Globe className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-ink">Dashboard</span>
                <span className="block text-[11px] text-muted">Company dashboard & totals</span>
              </span>
              {!activeProjectId ? <CheckCircle2 className="h-4 w-4 shrink-0 text-ocean" /> : null}
            </button>
            {shown.map((p) => (
              <button
                key={p.id}
                onClick={() => pick(p.id)}
                className={clsx(
                  "flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition hover:bg-field",
                  activeProjectId === p.id && "bg-plum/10"
                )}
              >
                {projectLogos[p.id] ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={projectLogos[p.id]}
                    alt=""
                    className="h-8 w-8 shrink-0 rounded-lg object-cover"
                  />
                ) : (
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-plum to-ocean text-xs font-bold text-white dark:text-slate-900">
                    {initials(p.name)}
                  </span>
                )}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{p.name}</span>
                  <span className="block truncate text-[11px] text-muted">{p.client_name || "—"}</span>
                </span>
                {activeProjectId === p.id ? <CheckCircle2 className="h-4 w-4 shrink-0 text-plum" /> : null}
              </button>
            ))}
            {!shown.length ? (
              <div className="p-3 text-center text-xs text-muted">No projects match “{q}”.</div>
            ) : null}
          </div>
          <div className="mt-1.5 border-t border-line pt-1.5">
            {showCreate ? (
              <form
                className="space-y-2 p-1"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!name.trim() || !domain.trim()) {
                    onNotice("Project name and target domain are required");
                    return;
                  }
                  createProject.mutate();
                }}
              >
                <Field label="Name" value={name} onChange={setName} />
                <Field label="Client" value={client} onChange={setClient} />
                <Field label="Target domain (required)" value={domain} onChange={setDomain} />
                <div className="flex gap-2">
                  <button className="flex h-9 flex-1 items-center justify-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
                    {createProject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                    Create
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="flex h-9 w-full items-center justify-center gap-2 rounded-lg text-sm font-medium text-ocean transition hover:bg-ocean/10"
              >
                <Plus className="h-4 w-4" /> New project
              </button>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Overview({
  token,
  projectId,
  onOpenBacklinks
}: {
  token: string | null;
  projectId: string;
  onOpenBacklinks: (filters: Record<string, string>) => void;
}) {
  // No project selected → company-wide main dashboard; a project → project dashboard.
  const dashboard = useQuery({
    queryKey: ["dashboard", token, projectId],
    enabled: Boolean(token),
    queryFn: () =>
      api<Dashboard>(projectId ? `/dashboard?project_id=${projectId}` : "/dashboard", { token })
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const activeProject = (projectsQ.data || []).find((p) => p.id === projectId) || null;
  const [trendDays, setTrendDays] = useState("3650"); // default: All time
  const [trendGran, setTrendGran] = useState("week"); // chart bucket: day | week | month
  const trends = useQuery({
    queryKey: ["dashboard-trends", token, projectId, trendDays, trendGran],
    enabled: Boolean(token),
    queryFn: () =>
      api<{
        new_links: number; new_domains: number; new_indexed: number;
        prev_links: number; prev_domains: number; granularity?: string;
        weekly: Array<{
          week: string; links: number; new_domains: number;
          qualified?: number; not_qualified?: number; needs_improvement?: number; indexed?: number;
        }>;
      }>(
        `/dashboard/trends?days=${trendDays}&granularity=${trendGran}${projectId ? `&project_id=${projectId}` : ""}`,
        { token }
      )
  });

  const stats = dashboard.data;
  // Defensive: never plot a bucket dated in the future (a bad sheet date can't
  // stretch the axis). The backend already caps at today; this guards the UI too.
  const _todayStr = new Date().toISOString().slice(0, 10);
  const weekly = (trends.data?.weekly || []).filter((w) => w.week <= _todayStr);
  // Clicking a chart point drills into the Backlinks grid for that exact bucket's
  // window (placement axis) so the chart total reconciles with the grid's row count.
  // The window matches the active granularity: a single day, a Mon–Sun week, or a
  // whole calendar month. w.week is the bucket start ("YYYY-MM-DD").
  const openBucket = (i: number) => {
    const wk = weekly[i]?.week;
    if (!wk) return;
    const r = bucketRange(wk, trendGran);
    onOpenBacklinks({ placement_from: r.from, placement_to: r.to });
  };
  const granNoun = trendGran === "day" ? "day" : trendGran === "month" ? "month" : "week";
  return (
    <section className="space-y-5">
      {projectId ? (
        // ── Project hero: unmistakably a single project's home ───────────
        <div className="relative overflow-hidden rounded-2xl border border-plum/30 bg-gradient-to-r from-plum/15 via-panel to-ocean/10 p-5 shadow-soft">
          <div className="flex flex-wrap items-center gap-4">
            <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-plum to-ocean text-lg font-bold text-white shadow-soft dark:text-slate-900">
              {(activeProject?.name || "P").split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("")}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-bold uppercase tracking-widest text-plum">Project dashboard</div>
              <h2 className="truncate text-xl font-bold tracking-tight text-ink">
                {activeProject?.name || "Project"}
              </h2>
              <p className="truncate text-sm text-muted">
                {activeProject?.client_name ? `Client: ${activeProject.client_name} · ` : ""}
                Everything on this page is about this project only.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
                <span className="block text-lg font-bold leading-tight text-ink">{stats?.totals.total ?? 0}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Links</span>
              </span>
              <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
                <span className="block text-lg font-bold leading-tight text-ocean">{stats?.totals.pass_count ?? 0}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Pass</span>
              </span>
              <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
                <span className="block text-lg font-bold leading-tight text-ink">{stats?.totals.avg_score ?? "—"}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Avg score</span>
              </span>
            </div>
          </div>
        </div>
      ) : (
        // ── Company header: the whole-workspace view ─────────────────────
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-ocean to-teal-500 text-white shadow-soft dark:text-slate-900">
            <Globe className="h-5 w-5" />
          </span>
          <div>
            <h2 className="flex items-center gap-1.5 text-lg font-bold tracking-tight text-ink">
              Company dashboard
              <HelpTip text="The combined picture across ALL projects. Pick a project (top-left selector) to switch to that project's own dashboard — it looks different on purpose, so you always know where you are." />
            </h2>
            <p className="text-sm text-muted">All projects together — totals, activity and health.</p>
          </div>
        </div>
      )}
      {!projectId && stats?.counts && Object.keys(stats.counts).length ? (
        <div className="flex flex-wrap gap-2">
          {(
            [
              ["projects", "Projects"],
              ["source_domains", "Source domains"],
              ["competitor_domains", "Competitor domains"],
              ["users", "Users"],
              ["batches", "Runs"],
              ["open_duplicates", "Open duplicates"],
              ["indexed_links", "Indexed links"]
            ] as Array<[string, string]>
          ).map(([k, label]) => (
            <span
              key={k}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-3 py-1.5 text-xs shadow-card"
            >
              <span className="font-bold text-ink">{stats.counts?.[k] ?? 0}</span>
              <span className="text-muted">{label}</span>
            </span>
          ))}
        </div>
      ) : null}

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Total" value={stats?.totals.total ?? 0} icon={Link2} tone="ink"
          help="All backlinks being monitored in this view. Click to open the full list."
          onClick={() => onOpenBacklinks({})} />
        <Metric label="Qualified" value={stats?.totals.pass_count ?? 0} icon={CheckCircle2} tone="ocean"
          help="Links that are live and passed every check — nothing to do. Click to see them."
          onClick={() => onOpenBacklinks({ status: "PASS" })} />
        <Metric label="Needs review" value={stats?.totals.review_count ?? 0} icon={ShieldAlert} tone="plum"
          help="We couldn't decide automatically (usually bot protection on the site). Click to check them yourself."
          onClick={() => onOpenBacklinks({ status: "NEEDS_MANUAL_REVIEW" })} />
        <Metric label="Not qualified" value={stats?.totals.fail_count ?? 0} icon={XCircle} tone="danger"
          help="Serious problems — the link is missing, the page is dead, or it can't be indexed. Click to fix them."
          onClick={() => onOpenBacklinks({ status: "FAIL" })} />
        <Metric label="Needs improvement" value={stats?.totals.warning_count ?? 0} icon={AlertTriangle} tone="ember"
          help="Links that work but lost some value (e.g. nofollow, weak page, redirects). Click to review them."
          onClick={() => onOpenBacklinks({ status: "WARNING" })} />
        <Metric label="Avg score" value={stats?.totals.avg_score ?? "-"} icon={Gauge} tone="ink"
          help="Average quality score (0–100) across these links. Hover any score in the Backlinks list to see how it's calculated." />
      </div>

      {/* Health mix — modern at-a-glance QA-outcome split; click a segment to drill. */}
      {stats?.totals && (stats.totals.total ?? 0) > 0 ? (
        <section className="rounded-xl border border-line bg-panel shadow-card p-4">
          <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-ink">
            Health mix
            <HelpTip text="How this view's links split across QA outcomes. Click any segment or legend chip to open that slice in the Backlinks list." />
          </div>
          <StackedBar
            segments={[
              { name: "Qualified", cssVar: "--ocean", value: stats.totals.pass_count ?? 0 },
              { name: "Needs improvement", cssVar: "--ember", value: stats.totals.warning_count ?? 0 },
              { name: "Needs review", cssVar: "--plum", value: stats.totals.review_count ?? 0 },
              { name: "Not qualified", cssVar: "--danger", value: stats.totals.fail_count ?? 0 },
              // Each bucket uses its OWN count — never a remainder (that wrongly
              // folded UNKNOWN links into "QA pending"). Zero buckets are hidden.
              { name: "Unknown", cssVar: "--ink", value: stats.totals.unknown_count ?? 0 },
              { name: "QA pending", cssVar: "--muted", value: stats.totals.pending_count ?? 0 }
            ]}
            onSegmentClick={(name) => {
              const map: Record<string, string> = {
                Qualified: "PASS", "Needs improvement": "WARNING",
                "Needs review": "NEEDS_MANUAL_REVIEW", "Not qualified": "FAIL",
                Unknown: "UNKNOWN", "QA pending": "PENDING"
              };
              onOpenBacklinks(map[name] ? { status: map[name] } : {});
            }}
          />
        </section>
      ) : null}

      {/* KPI stat boxes — HTTP / index / quality / spam / duplicate / orphaned.
          Each drills into the Backlinks list via the matching filter. */}
      {stats?.kpi && Object.keys(stats.kpi).length ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 xl:grid-cols-12">
          <StatBox label="200 OK" value={Number(stats.kpi.http_200 || 0)} tone="ocean"
            help="Source pages returning HTTP 200. Click to see them."
            onClick={() => onOpenBacklinks({ http_status: "200" })} />
          <StatBox label="301" value={Number(stats.kpi.http_301 || 0)} tone="ember"
            help="Permanent redirects (301). Click to see them."
            onClick={() => onOpenBacklinks({ http_status: "301" })} />
          <StatBox label="302" value={Number(stats.kpi.http_302 || 0)} tone="ember"
            help="Temporary redirects (302). Click to see them."
            onClick={() => onOpenBacklinks({ http_status: "302" })} />
          <StatBox label="404" value={Number(stats.kpi.http_404 || 0)} tone="danger"
            help="Source page not found (404). Click to see them."
            onClick={() => onOpenBacklinks({ http_status: "404" })} />
          <StatBox label="Broken" value={Number(stats.kpi.broken || 0)} tone="danger"
            help="Any 4xx/5xx source page. Click to see them."
            onClick={() => onOpenBacklinks({ broken: "1" })} />
          <StatBox label="Indexed" value={Number(stats.kpi.indexed || 0)} tone="ocean"
            help="Pages Google shows in its index. Click to see them."
            onClick={() => onOpenBacklinks({ index_status: "indexed" })} />
          <StatBox label="Not indexed" value={Number(stats.kpi.not_indexed || 0)} tone="danger"
            help="Pages Google does not show. Click to see them."
            onClick={() => onOpenBacklinks({ index_status: "not_indexed" })} />
          <StatBox label="Qualified" value={Number(stats.kpi.qualified || 0)} tone="ocean"
            help="Links that passed every check. Click to see them."
            onClick={() => onOpenBacklinks({ status: "PASS" })} />
          <StatBox label="Not qualified" value={Number(stats.kpi.non_qualified || 0)} tone="danger"
            help="Links with a serious problem. Click to see them."
            onClick={() => onOpenBacklinks({ status: "FAIL" })} />
          <StatBox label="Spam" value={Number(stats.kpi.spam || 0)} tone="danger"
            help="Links on a high-spam source domain. Click to see them."
            onClick={() => onOpenBacklinks({ spam_min: String(ANALYTICS_SPAM_THRESHOLD) })} />
          <StatBox label="Duplicate" value={Number(stats.kpi.duplicate || 0)} tone="ember"
            help="Links pointing at an already-used page. Click to see them."
            onClick={() => onOpenBacklinks({ duplicate_status: "duplicate" })} />
          <StatBox label="Orphaned" value={Number(stats.kpi.orphaned || 0)} tone="plum"
            help="Links whose source domain has no catalog/metrics row. Click to see them."
            onClick={() => onOpenBacklinks({ orphaned: "1" })} />
        </div>
      ) : null}

      {/* Timeframe activity + previous-period comparison */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Activity</h3>
          <div className="flex flex-wrap items-center gap-2">
            {/* Bucket size — Day/Week/Month. Smaller buckets = more detail and an
                exact click-through window; the tooltip + drill follow the choice. */}
            <div className="inline-flex overflow-hidden rounded-lg border border-line" role="group" aria-label="Chart detail">
              {(
                [["day", "Day"], ["week", "Week"], ["month", "Month"]] as Array<[string, string]>
              ).map(([v, l]) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setTrendGran(v)}
                  className={`h-9 px-2.5 text-sm font-medium transition-colors ${
                    trendGran === v
                      ? "bg-ocean text-white dark:text-slate-900"
                      : "bg-panel text-muted hover:bg-field"
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
            <select
              value={trendDays}
              onChange={(e) => setTrendDays(e.target.value)}
              className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
            >
              {TIMEFRAMES.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid gap-3 p-4 sm:grid-cols-3">
          <div className="rounded-lg border border-line bg-field/50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">New links</div>
            <div className="mt-1 text-2xl font-bold text-ink">
              {trends.data?.new_links ?? 0}
              <DeltaPill now={trends.data?.new_links ?? 0} prev={trends.data?.prev_links} />
            </div>
            <div className="text-[11px] text-muted">previous period: {trends.data?.prev_links ?? 0}</div>
          </div>
          <div className="rounded-lg border border-line bg-field/50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">
              New source domains {projectId ? "(for this project)" : ""}
            </div>
            <div className="mt-1 text-2xl font-bold text-ink">
              {trends.data?.new_domains ?? 0}
              <DeltaPill now={trends.data?.new_domains ?? 0} prev={trends.data?.prev_domains} />
            </div>
            <div className="text-[11px] text-muted">previous period: {trends.data?.prev_domains ?? 0}</div>
          </div>
          <div className="rounded-lg border border-line bg-field/50 p-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">Indexed (new links)</div>
            <div className="mt-1 text-2xl font-bold text-ink">{trends.data?.new_indexed ?? 0}</div>
            <div className="text-[11px] text-muted">
              {pct(trends.data?.new_indexed ?? 0, trends.data?.new_links ?? 0)} of new links
            </div>
          </div>
        </div>
        {weekly.length ? (
          <div className="space-y-5 border-t border-line p-4">
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Links &amp; new source domains over time
              </div>
              <TrendChart
                labels={weekly.map((w) => w.week)}
                labelFmt={(w) => bucketLabel(w, trendGran)}
                tickFmt={(w) => bucketTick(w, trendGran)}
                onPointClick={openBucket}
                series={[
                  { name: "Links added", cssVar: "--ocean", values: weekly.map((w) => w.links) },
                  { name: "New source domains", cssVar: "--plum", values: weekly.map((w) => w.new_domains) }
                ]}
              />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Quality over time <span className="normal-case text-[10px]">(by link&apos;s placement {granNoun})</span>
              </div>
              <TrendChart
                labels={weekly.map((w) => w.week)}
                labelFmt={(w) => bucketLabel(w, trendGran)}
                tickFmt={(w) => bucketTick(w, trendGran)}
                onPointClick={openBucket}
                series={[
                  { name: "Qualified", cssVar: "--ocean", values: weekly.map((w) => w.qualified ?? 0) },
                  { name: "Not qualified", cssVar: "--danger", values: weekly.map((w) => w.not_qualified ?? 0) },
                  { name: "Needs improvement", cssVar: "--ember", values: weekly.map((w) => w.needs_improvement ?? 0) }
                ]}
              />
            </div>
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Indexed links over time
              </div>
              <TrendChart
                labels={weekly.map((w) => w.week)}
                labelFmt={(w) => bucketLabel(w, trendGran)}
                tickFmt={(w) => bucketTick(w, trendGran)}
                onPointClick={openBucket}
                series={[
                  { name: "Indexed", cssVar: "--plum", values: weekly.map((w) => w.indexed ?? 0) }
                ]}
              />
            </div>
          </div>
        ) : (
          <div className="border-t border-line p-4">
            <Empty label="No activity in this range yet." />
          </div>
        )}
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Issue Mix" />
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <Issue label="Nofollow" value={stats?.issues.nofollow_count ?? 0}
              help="Links marked rel=nofollow — they pass less SEO value. Click to see them."
              onClick={() => onOpenBacklinks({ rel: "nofollow" })} />
            <Issue label="Not indexable" value={stats?.issues.noindex_count ?? 0}
              help="Pages that tell Google not to index them — the link there helps very little. Click to see them."
              onClick={() => onOpenBacklinks({ indexability: "not_indexable" })} />
            <Issue label="Robots blocked" value={stats?.issues.robots_blocked_count ?? 0}
              help="Pages blocked by robots.txt — search engines can't even visit them. Click to see them."
              onClick={() => onOpenBacklinks({ robots_status: "blocked" })} />
            <Issue label="Canonical" value={stats?.issues.canonical_issue_count ?? 0}
              help="Pages that declare a different page as the 'real' one, weakening the link. Click to see them."
              onClick={() => onOpenBacklinks({ canonical_status: "mismatch,cross_domain" })} />
            <Issue label="Broken page" value={stats?.issues.broken_count ?? 0}
              help="Pages returning an error (404, 500…) — the link is effectively gone. Click to see them."
              onClick={() => onOpenBacklinks({ broken: "1" })} />
            <Issue label="Link missing" value={stats?.issues.link_missing_count ?? 0}
              help="The page loads fine, but your link is no longer on it. Click to see them."
              onClick={() => onOpenBacklinks({ link_missing: "1" })} />
          </div>
        </section>
        <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Recent Changes" />
          <div className="divide-y divide-line">
            {(stats?.recent_changes || []).slice(0, 8).map((item) => (
              <div key={`${item.backlink_id}-${item.created_at}`} className="p-3">
                <div className="truncate text-sm font-medium text-ink">{item.source_page_url}</div>
                <div className="mt-1 flex items-center justify-between text-xs text-muted">
                  <span>{item.event_type}</span>
                  <Severity value={item.severity || "INFO"} />
                </div>
              </div>
            ))}
            {!dashboard.isLoading && !stats?.recent_changes.length ? (
              <Empty label="No changes yet" />
            ) : null}
          </div>
        </section>
      </div>

      {stats?.is_project ? (
        <div className="space-y-5">
          <ProjectEffort token={token} projectId={projectId} onOpenBacklinks={onOpenBacklinks} />
          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="By link type" />
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-field text-xs uppercase text-muted">
                    <tr><Th>Link type</Th><Th>Total</Th><Th>Qualified</Th><Th>Not qualified</Th><Th>Avg</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.link_type_breakdown || []).map((r) => (
                      <tr
                        key={r.link_type}
                        title="Click to open these links"
                        onClick={() => onOpenBacklinks({ link_type: r.link_type === "(none)" ? "(blanks)" : r.link_type })}
                        className="cursor-pointer hover:bg-field/60"
                      >
                        <Td><span className="font-medium text-ocean hover:underline">{linkTypeLabel(r.link_type)}</span></Td>
                        <Td>{r.total}</Td>
                        <Td><span className="text-ocean">{r.pass_count}</span></Td>
                        <Td><span className="text-danger">{r.fail_count}</span></Td>
                        <Td>{r.avg_score ?? "-"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!(stats.link_type_breakdown || []).length ? <Empty label="No link types" /> : null}
              </div>
            </section>
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="Team performance" />
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-field text-xs uppercase text-muted">
                    <tr><Th>User</Th><Th>Total</Th><Th>Qualified %</Th><Th>Not qualified</Th><Th>Avg</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.assigned_user_stats || []).map((r) => (
                      <tr
                        key={r.assigned_user_label}
                        title="Click to open this person's links"
                        onClick={() =>
                          onOpenBacklinks({
                            user: r.assigned_user_label === "(unassigned)" ? "(blanks)" : r.assigned_user_label
                          })
                        }
                        className="cursor-pointer hover:bg-field/60"
                      >
                        <Td><span className="font-medium text-ocean hover:underline">{r.assigned_user_label}</span></Td>
                        <Td>{r.total}</Td>
                        <Td>{pct(r.pass_count, r.total)}</Td>
                        <Td><span className="text-danger">{r.fail_count}</span></Td>
                        <Td>{r.avg_score ?? "-"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!(stats.assigned_user_stats || []).length ? <Empty label="No assignments" /> : null}
              </div>
            </section>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="Activity (14 days)" />
              <div className="space-y-2 p-4">
                {(() => {
                  const trends = stats.trends || [];
                  const max = Math.max(1, ...trends.map((t) => t.added + t.removed + t.score_changed));
                  return trends.map((t) => {
                    const total = t.added + t.removed + t.score_changed;
                    return (
                      <div key={t.date} className="flex items-center gap-3 text-xs">
                        <span className="w-12 shrink-0 text-muted">{t.date.slice(5)}</span>
                        <span className="flex h-2.5 flex-1 overflow-hidden rounded-full bg-field">
                          <span className="h-full bg-ocean" style={{ width: `${(t.added / max) * 100}%` }} />
                          <span className="h-full bg-danger" style={{ width: `${(t.removed / max) * 100}%` }} />
                          <span className="h-full bg-ember/60" style={{ width: `${(t.score_changed / max) * 100}%` }} />
                        </span>
                        <span
                          className="w-32 shrink-0 text-right text-muted"
                          title={`${t.added} added · ${t.removed} lost · ${t.score_changed} score changes`}
                        >
                          +{t.added} / −{t.removed} / Δ{t.score_changed}
                        </span>
                      </div>
                    );
                  });
                })()}
                {(stats.trends || []).length ? (
                  <div className="flex gap-3 pt-1 text-[10px] uppercase tracking-wide text-muted">
                    <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-ocean" /> Added</span>
                    <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-danger" /> Lost</span>
                    <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-ember/60" /> Score Δ</span>
                  </div>
                ) : (
                  <Empty label="No recent activity" />
                )}
              </div>
            </section>
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="Top source domains" />
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-field text-xs uppercase text-muted">
                    <tr><Th>Domain</Th><Th>Links</Th><Th>Qualified</Th><Th>Not qualified</Th><Th>Indexed %</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.top_source_domains || []).map((r) => (
                      <tr
                        key={r.source_domain}
                        title="Click to open links from this website"
                        onClick={() => onOpenBacklinks({ source_domain: r.source_domain })}
                        className="cursor-pointer hover:bg-field/60"
                      >
                        <Td><span className="break-all text-ocean hover:underline">{r.source_domain}</span></Td>
                        <Td>{r.total}</Td>
                        <Td><span className="text-ocean">{r.pass_count}</span></Td>
                        <Td><span className="text-danger">{r.fail_count}</span></Td>
                        <Td>{r.indexed_pct != null ? `${r.indexed_pct}%` : "-"}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!(stats.top_source_domains || []).length ? <Empty label="No source domains" /> : null}
              </div>
            </section>
          </div>

          <section className="min-w-0 overflow-hidden rounded-xl border border-line bg-panel shadow-card">
            <SectionTitle title="Recent regressions (high severity)" />
            <div className="divide-y divide-line">
              {(stats.recent_regressions || []).map((r) => (
                <div
                  key={`${r.backlink_id}-${r.created_at}`}
                  title="Click to open this link in the Backlinks list"
                  onClick={() => onOpenBacklinks({ search: r.source_page_url })}
                  className="cursor-pointer p-3 transition hover:bg-field/60"
                >
                  <div className="truncate text-sm font-medium text-ocean hover:underline">{r.source_page_url}</div>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted">
                    <span>
                      {r.event_type}
                      {r.field ? ` · ${r.field}` : ""}
                      {r.old_value != null ? `: ${r.old_value} → ${r.new_value}` : ""}
                    </span>
                    <Severity value={r.severity || "INFO"} />
                  </div>
                </div>
              ))}
              {!(stats.recent_regressions || []).length ? <Empty label="No regressions" /> : null}
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function Backlinks({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  // Deep-link filters: dashboards open this desk pre-filtered via f_* URL params
  // (read once on mount, then removed so refresh/back behave normally).
  const fParam = (k: string) => {
    try {
      return new URLSearchParams(window.location.search).get(`f_${k}`) || "";
    } catch {
      return "";
    }
  };
  const [status, setStatus] = useState(() => fParam("status"));
  const [dupFilter, setDupFilter] = useState(() => fParam("duplicate_status"));
  const [indexFilter, setIndexFilter] = useState(() => fParam("index_status"));
  const [rel, setRel] = useState(() => fParam("rel"));
  const [linkType, setLinkType] = useState(() => fParam("link_type"));
  const [userF, setUserF] = useState(() => fParam("user"));
  const [domainF, setDomainF] = useState(() => fParam("source_domain"));
  const [issueLabel, setIssueLabel] = useState(() => fParam("issue_label"));
  // KPI drill-through filters (from Analytics/Overview stat boxes): exact HTTP
  // status (comma list), broken (4xx/5xx), min source-domain spam, orphaned.
  const [httpStatusF, setHttpStatusF] = useState(() => fParam("http_status"));
  // HTTP error class as an individually-selectable multi-select ("4xx"/"5xx").
  // Legacy "broken" deep-links (any 4xx/5xx) seed both classes.
  const [httpClassF, setHttpClassF] = useState(
    () => fParam("http_class") || (fParam("broken") === "1" ? "4xx,5xx" : "")
  );
  // Verdict-column deep-link filters (from dashboard "Issue Mix" cards) so a card
  // drills into EXACTLY the rows it counted. No standalone UI control — they show
  // in the active-filter count and clear with "Clear all".
  const [indexabilityF, setIndexabilityF] = useState(() => fParam("indexability"));
  const [robotsStatusF, setRobotsStatusF] = useState(() => fParam("robots_status"));
  const [canonicalStatusF, setCanonicalStatusF] = useState(() => fParam("canonical_status"));
  const [linkMissingF, setLinkMissingF] = useState(() => fParam("link_missing") === "1");
  const [spamMinF, setSpamMinF] = useState(() => fParam("spam_min"));
  const [orphanedF, setOrphanedF] = useState(() => fParam("orphaned") === "1");
  const [noPlacementF, setNoPlacementF] = useState(() => fParam("no_placement") === "1");
  const [noUserF, setNoUserF] = useState(() => fParam("no_user") === "1");
  const [qaWaitF, setQaWaitF] = useState(() => fParam("qa_wait"));
  // Project filter for the ALL-PROJECTS view (inside a project the scope is fixed
  // by the top-left picker, so this select hides there).
  const [projF, setProjF] = useState("");
  const [showScoreGuide, setShowScoreGuide] = useState(false);
  const [liveBatch, setLiveBatch] = useState<string | null>(null);
  const [sort, setSort] = useState("score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState(() => fParam("search"));
  const [debouncedSearch, setDebouncedSearch] = useState(() => fParam("search"));
  const [targetInput, setTargetInput] = useState(() => fParam("target"));
  const [targetF, setTargetF] = useState(() => fParam("target"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Row selection for scoped "check these exact links" / bulk-edit actions.
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulkUser, setBulkUser] = useState("");
  const [bulkDate, setBulkDate] = useState("");
  // Which date type the "Link date" column shows / sorts on, plus its range filter.
  // Date-range deep link: a dashboard drill (e.g. clicking a weekly chart point)
  // arrives as f_<axis.from>/f_<axis.to> — e.g. f_placement_from/f_placement_to.
  // Seed the date-axis picker + range from whichever axis' params are present so
  // the grid opens filtered to that window; absent → placement/empty as before.
  const _seedDateAxis = BACKLINK_DATE_AXES.find(
    (a) => (a.from && fParam(a.from)) || (a.to && fParam(a.to))
  );
  const [dateAxis, setDateAxis] = useState(() => _seedDateAxis?.key || "placement");
  const [dateFrom, setDateFrom] = useState(() => (_seedDateAxis?.from ? fParam(_seedDateAxis.from) : ""));
  const [dateTo, setDateTo] = useState(() => (_seedDateAxis?.to ? fParam(_seedDateAxis.to) : ""));
  const axis = BACKLINK_DATE_AXES.find((a) => a.key === dateAxis) || BACKLINK_DATE_AXES[0];

  useEffect(() => {
    // Consume the f_* params so they don't stick around in the address bar.
    try {
      const q = new URLSearchParams(window.location.search);
      let dirty = false;
      Array.from(q.keys()).forEach((k) => {
        if (k.startsWith("f_")) {
          q.delete(k);
          dirty = true;
        }
      });
      if (dirty) {
        window.history.replaceState(null, "", `${window.location.pathname}?${q.toString()}`);
      }
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => {
    const t = setTimeout(() => setTargetF(targetInput.trim()), 350);
    return () => clearTimeout(t);
  }, [targetInput]);

  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  // Shared cache with the sidebar's projects query (same key → no extra request).
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const projectName = (id: string) =>
    (projectsQ.data || []).find((p) => p.id === id)?.name || "—";
  // User + source-domain options with live counts (same engine as Analytics).
  const facetsQ = useQuery({
    queryKey: ["bl-facets", token, projectId],
    enabled: Boolean(token),
    queryFn: () =>
      api<AnalyticsResponse>("/analytics/query", {
        token,
        method: "POST",
        body: JSON.stringify({
          filters: projectId ? { project_id: projectId } : {},
          facets: ["user", "source_domain"]
        })
      })
  });
  const facetOpts = (dim: string) =>
    (facetsQ.data?.facets?.[dim] || [])
      // "(unassigned)"/"(none)" buckets are covered by the "(Blanks)" option.
      .filter((o) => !String(o.value).startsWith("("))
      .map((o) => ({
        value: String(o.value),
        label: String(o.label || o.value),
        count: Number(o.count) || 0
      }));

  const clearFilters = () => {
    setStatus("");
    setDupFilter("");
    setIndexFilter("");
    setRel("");
    setLinkType("");
    setUserF("");
    setDomainF("");
    setIssueLabel("");
    setSearch("");
    setTargetInput("");
    setTargetF("");
    setDateFrom("");
    setDateTo("");
    setHttpStatusF("");
    setHttpClassF("");
    setIndexabilityF("");
    setRobotsStatusF("");
    setCanonicalStatusF("");
    setLinkMissingF(false);
    setSpamMinF("");
    setOrphanedF(false);
    setNoPlacementF(false);
    setNoUserF(false);
    setQaWaitF("");
    setProjF("");
  };
  const activeFilterCount = [status, dupFilter, indexFilter, rel, linkType, userF, domainF, issueLabel, debouncedSearch, targetF, dateFrom, dateTo, httpStatusF, httpClassF, indexabilityF, robotsStatusF, canonicalStatusF, spamMinF, qaWaitF, projF]
    .filter(Boolean).length + (orphanedF ? 1 : 0) + (linkMissingF ? 1 : 0) + (noPlacementF ? 1 : 0) + (noUserF ? 1 : 0);

  // Filter values are comma-joined multi-select lists ("FAIL,WARNING").
  const toks = (v: string) => (v ? v.split(",") : []);
  const toggleTok = (v: string, setter: (s: string) => void, tok: string) => {
    const list = toks(v);
    setter(
      (list.includes(tok) ? list.filter((x) => x !== tok) : [...list, tok]).join(",")
    );
  };

  // One-click QA presets — each toggles the underlying filter, so they compose.
  const chips: Array<[string, boolean, () => void]> = [
    ["QA pending", toks(status).includes("PENDING"), () => toggleTok(status, setStatus, "PENDING")],
    ["Not qualified", toks(status).includes("FAIL"), () => toggleTok(status, setStatus, "FAIL")],
    ["Needs review", toks(status).includes("NEEDS_MANUAL_REVIEW"), () => toggleTok(status, setStatus, "NEEDS_MANUAL_REVIEW")],
    ["Link missing", issueLabel === "LINK_MISSING", () => setIssueLabel(issueLabel === "LINK_MISSING" ? "" : "LINK_MISSING")],
    ["Nofollow", toks(rel).includes("nofollow"), () => toggleTok(rel, setRel, "nofollow")],
    ["Not indexed", toks(indexFilter).includes("not_indexed"), () => toggleTok(indexFilter, setIndexFilter, "not_indexed")],
    ["Duplicates", toks(dupFilter).includes("duplicate"), () => toggleTok(dupFilter, setDupFilter, "duplicate")],
    ["4xx errors", toks(httpClassF).includes("4xx"), () => toggleTok(httpClassF, setHttpClassF, "4xx")],
    ["5xx errors", toks(httpClassF).includes("5xx"), () => toggleTok(httpClassF, setHttpClassF, "5xx")],
    ["Spam", Boolean(spamMinF), () => setSpamMinF((s) => (s ? "" : String(ANALYTICS_SPAM_THRESHOLD)))],
    ["Orphaned", orphanedF, () => setOrphanedF((o) => !o)],
    ["No date", noPlacementF, () => setNoPlacementF((v) => !v)],
    ["No user", noUserF, () => setNoUserF((v) => !v)],
    ["Waiting for API", toks(qaWaitF).includes("waiting_api"), () => toggleTok(qaWaitF, setQaWaitF, "waiting_api")],
    ["QA failed (API)", toks(qaWaitF).includes("api_failed"), () => toggleTok(qaWaitF, setQaWaitF, "api_failed")]
  ];

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "50", with_total: "true" });
    if (projectId) params.set("project_id", projectId);  // omit → all projects
    else if (projF) params.set("project_id", projF);     // filter-panel pick
    if (status) params.set("status", status);
    if (dupFilter) params.set("duplicate_status", dupFilter);
    if (indexFilter) params.set("index_status", indexFilter);
    if (rel) params.set("rel", rel);
    if (linkType) params.set("link_type", linkType);
    if (userF) params.set("assigned_user_label", userF);
    if (domainF) params.set("source_domain", domainF);
    if (issueLabel) params.set("issue_label", issueLabel);
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (targetF) params.set("target", targetF);
    if (httpStatusF) params.set("http_status", httpStatusF);
    if (httpClassF) params.set("http_class", httpClassF);
    if (indexabilityF) params.set("indexability", indexabilityF);
    if (robotsStatusF) params.set("robots_status", robotsStatusF);
    if (canonicalStatusF) params.set("canonical_status", canonicalStatusF);
    if (linkMissingF) params.set("link_missing", "true");
    if (spamMinF) params.set("spam_min", spamMinF);
    if (orphanedF) params.set("orphaned", "true");
    if (noPlacementF) params.set("no_placement", "true");
    if (noUserF) params.set("no_user", "true");
    if (qaWaitF) params.set("qa_wait", qaWaitF);
    if (axis.from && dateFrom) params.set(axis.from, dateFrom);
    if (axis.to && dateTo) params.set(axis.to, dateTo);
    if (sort) params.set("sort", sort);
    params.set("direction", sortDir);
    return params.toString();
  }, [projectId, projF, status, dupFilter, indexFilter, rel, linkType, userF, domainF, issueLabel, debouncedSearch, targetF, httpStatusF, httpClassF, indexabilityF, robotsStatusF, canonicalStatusF, linkMissingF, spamMinF, orphanedF, noPlacementF, noUserF, qaWaitF, axis.from, axis.to, dateFrom, dateTo, sort, sortDir]);
  const backlinks = useInfiniteQuery({
    queryKey: ["backlinks", token, query],
    enabled: Boolean(token),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<Page<BacklinkRow>>(
        `/backlinks?${query}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
        { token }
      ),
    getNextPageParam: (last) => (last.has_more ? last.next_cursor : null)
  });
  const rows = useMemo(
    () => (backlinks.data?.pages || []).flatMap((p) => p.items),
    [backlinks.data]
  );
  const totalCount = backlinks.data?.pages[0]?.total ?? 0;
  // New filters/sort → old row selection no longer matches what's on screen.
  useEffect(() => {
    setPicked(new Set());
  }, [query]);

  const onSortCol = (key: string) => {
    if (sort === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      setSortDir(key === "source_domain" || key === "link_type" ? "asc" : "desc");
    }
  };

  // The current grid filters, exactly as the recheck endpoint expects them —
  // "check what I'm looking at" uses the same whitelist as the list itself.
  const filterBody = () => ({
    project_id: projectId || projF || null,
    status: status || null,
    duplicate_status: dupFilter || null,
    index_status: indexFilter || null,
    rel: rel || null,
    link_type: linkType || null,
    assigned_user_label: userF || null,
    source_domain: domainF || null,
    issue_label: issueLabel || null,
    search: debouncedSearch || null,
    target: targetF || null,
    http_status: httpStatusF || null,
    http_class: httpClassF || null,
    indexability: indexabilityF || null,
    robots_status: robotsStatusF || null,
    canonical_status: canonicalStatusF || null,
    link_missing: linkMissingF ? true : null,
    spam_min: spamMinF ? Number(spamMinF) : null,
    orphaned: orphanedF ? true : null,
    no_placement: noPlacementF ? true : null,
    no_user: noUserF ? true : null,
    qa_wait: qaWaitF || null,
    ...(axis.from && dateFrom ? { [axis.from]: dateFrom } : {}),
    ...(axis.to && dateTo ? { [axis.to]: dateTo } : {})
  });

  // Bulk edit (assign user / set placement date) on the ticked rows.
  const bulkLabelsQ = useQuery({
    queryKey: ["workforce-labels", token],
    enabled: Boolean(token),
    queryFn: () => api<string[]>("/workforce/labels", { token })
  });
  const bulkEdit = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ updated: number }>("/backlinks/bulk-edit", { token, method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => {
      onNotice(`Updated ${r.updated} link${r.updated === 1 ? "" : "s"}.`);
      setPicked(new Set());
      setBulkUser("");
      setBulkDate("");
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["performance"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });
  const fillPlacement = useMutation({
    mutationFn: () =>
      api<{ updated: number }>("/backlinks/fill-missing-placement", {
        token, method: "POST", body: JSON.stringify({ filters: filterBody() })
      }),
    onSuccess: (r) => {
      onNotice(`Back-filled ${r.updated} link(s) with their import date.`);
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const [staleDays, setStaleDays] = useState("30");
  const recheck = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ job_id: string; queued: number; batch_id?: string | null }>("/backlinks/recheck", {
        token,
        method: "POST",
        body: JSON.stringify(body)
      }),
    onSuccess: (data) => {
      onNotice(
        data.queued
          ? `QA check started — ${data.queued} link${data.queued === 1 ? "" : "s"} queued.`
          : "Nothing to check in this scope — everything is already covered."
      );
      if (data.queued && data.batch_id) setLiveBatch(data.batch_id);
      setPicked(new Set());
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });
  const checkPending = () => {
    if (
      window.confirm(
        `Start QA checks for every "QA pending" link ${projectId ? "in this project" : "across ALL projects"}?\n\nOnly links that were never checked are queued — fresh data is not rechecked, but crawling uses server capacity.`
      )
    )
      recheck.mutate({ project_id: projectId || null, only_pending: true, priority: true });
  };
  const checkFiltered = () => {
    const scope = activeFilterCount
      ? `the ${totalCount} link${totalCount === 1 ? "" : "s"} matching your current filters`
      : null;
    const ok = window.confirm(
      scope
        ? `Start QA checks for ${scope}?\n\nAlready-fresh domain metrics are reused from cache; page checks will crawl each link.`
        : `No filter is applied. This may check ALL ${totalCount} links ${projectId ? "in this project" : "in the workspace"} and use many API credits. Continue?`
    );
    if (ok) recheck.mutate({ project_id: projectId || null, filters: filterBody(), priority: true });
  };
  const checkStale = () => {
    if (
      window.confirm(
        `Recheck links whose last check is older than ${staleDays} days ${projectId ? "in this project" : "across ALL projects"}?\n\nRecently-checked links are skipped automatically.`
      )
    )
      recheck.mutate({
        project_id: projectId || null,
        priority: true,
        older_than_days: Number(staleDays)
      });
  };
  const checkPicked = () => {
    if (
      window.confirm(
        `Force recheck the ${picked.size} selected link${picked.size === 1 ? "" : "s"}?\n\nThis re-crawls them now even if they were checked recently.`
      )
    )
      recheck.mutate({ backlink_ids: Array.from(picked), priority: true });
  };
  const indexCheck = useMutation({
    mutationFn: () =>
      api<{ message: string }>("/index/check", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: projectId || null })
      }),
    onSuccess: (r) => onNotice(r.message || "Index check started"),
    onError: (err: Error) => onNotice(err.message)
  });
  const runIndexCheck = () => {
    if (
      window.confirm(
        `Check Google index status for links ${projectId ? "in this project" : "across ALL projects"}?\n\nThis uses the SERP API (credits) — already-checked URLs are deduplicated.`
      )
    )
      indexCheck.mutate();
  };
  const checkMetrics = useMutation({
    mutationFn: () => api<unknown>("/source-domains/fetch-metrics", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Domain metrics check started — DA/PA via Moz, AS via Semrush (Semrush needs its API endpoint configured)");
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="border-b border-line p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Backlinks</h2>
            <p className="text-sm text-muted">
              {totalCount} records
              {activeFilterCount ? ` · ${activeFilterCount} filter${activeFilterCount > 1 ? "s" : ""}` : ""}
              {picked.size ? ` · ${picked.size} selected` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {(() => {
              // Server-side export of the FULL filtered set (not the 200-row page), CSV or Excel.
              const doExport = async (fmt: "csv" | "xlsx") => {
                try {
                  const p2 = new URLSearchParams(query);
                  p2.delete("limit");
                  p2.delete("with_total");
                  p2.set("format", fmt);
                  const res = await fetch(`${API_BASE}/backlinks/export?${p2.toString()}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {}
                  });
                  if (!res.ok) throw new Error(`Export failed (${res.status})`);
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `backlinks.${fmt === "xlsx" ? "xlsx" : "csv"}`;
                  document.body.appendChild(link);
                  link.click();
                  link.remove();
                  URL.revokeObjectURL(url);
                  const cap = res.headers.get("X-Export-Truncated");
                  onNotice(cap ? `Exported the first ${cap} links (limit reached).` : "Exported all matching links.");
                } catch (e) {
                  onNotice(e instanceof Error ? e.message : "Export failed");
                }
              };
              return (
                <>
                  <ExportButton onClick={() => doExport("csv")} />
                  <button
                    onClick={() => doExport("xlsx")}
                    title="Download all matching links (every filter, all pages) as an Excel file"
                    className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field"
                  >
                    <Download className="h-3.5 w-3.5" /> Excel
                  </button>
                </>
              );
            })()}
            <button
              onClick={runIndexCheck}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Check Google indexing for these links (asks before spending API credits)"
            >
              {indexCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
              Check indexing
            </button>
            <button
              onClick={() => checkMetrics.mutate()}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Fetch DA/PA (Moz) and AS (Semrush) for the source domains of your links — batch-refreshes the stalest domains first"
            >
              {checkMetrics.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
              Check DA · PA · AS
            </button>
            {picked.size ? (
              <div className="flex items-center gap-1.5 rounded-lg border border-ocean/40 bg-ocean/5 px-2 py-1">
                <span className="text-xs font-semibold text-ink">{picked.size} sel.</span>
                <SearchSelect
                  value={bulkUser}
                  onChange={setBulkUser}
                  options={(bulkLabelsQ.data || []).map((l) => ({ value: l }))}
                  placeholder="Assign user…"
                  allowCustom
                  width="w-36"
                />
                <button
                  disabled={!bulkUser || bulkEdit.isPending}
                  onClick={() => {
                    if (!window.confirm(`Assign ${picked.size} selected link${picked.size === 1 ? "" : "s"} to “${bulkUser}”?`)) return;
                    bulkEdit.mutate({ ids: Array.from(picked), set_user: true, assigned_user_label: bulkUser });
                  }}
                  className="h-8 rounded-md border border-line px-2 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
                >
                  Assign
                </button>
                <input
                  type="date"
                  value={bulkDate}
                  onChange={(e) => setBulkDate(e.target.value)}
                  title="Placement (go-live) date to set on the selected links"
                  className="h-8 rounded-md border border-line bg-panel px-1.5 text-xs text-ink"
                />
                <button
                  disabled={!bulkDate || bulkEdit.isPending}
                  onClick={() => {
                    if (!window.confirm(`Set placement date ${bulkDate} on ${picked.size} selected link${picked.size === 1 ? "" : "s"}?`)) return;
                    bulkEdit.mutate({ ids: Array.from(picked), set_placement: true, placement_date: bulkDate });
                  }}
                  className="h-8 rounded-md border border-line px-2 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
                >
                  Set date
                </button>
                <button
                  onClick={checkPicked}
                  className="flex h-8 items-center gap-1.5 rounded-md border border-ocean/40 bg-ocean/10 px-2 text-xs font-semibold text-ocean transition hover:bg-ocean/20"
                  title="Re-crawl exactly the rows you ticked, even if they were checked recently"
                >
                  <Play className="h-3.5 w-3.5" />
                  Check ({picked.size})
                </button>
              </div>
            ) : null}
            <button
              onClick={checkPending}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
              title="QA-check links that were never checked (new imports) — the safe everyday action"
            >
              {recheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run QA check
            </button>
            <button
              onClick={checkFiltered}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Check exactly the links matching your current filters (asks first when no filter is set)"
            >
              <Filter className="h-4 w-4" />
              Check filtered
            </button>
            <button
              onClick={() => {
                if (window.confirm("Retry QA for every link parked by an API failure or exhausted quota (\"Waiting for API\" / \"API failed\")? Run this after the quota resets or the outage clears."))
                  recheck.mutate({
                    project_id: projectId || null,
                    filters: { ...filterBody(), qa_wait: "waiting_api,api_failed" },
                    priority: false
                  });
              }}
              className="flex h-9 items-center gap-2 rounded-lg border border-ember/40 px-3 text-sm font-semibold text-ember transition hover:bg-ember/10"
              title="Re-queue links whose QA was paused by an API limit, outage or failure — they never retry on their own"
            >
              <History className="h-4 w-4" />
              Retry failed QA
            </button>
            <button
              onClick={() => setShowScoreGuide(true)}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field hover:text-ink"
              title="Plain-English guide: how the 0-100 score is calculated and how to improve it"
            >
              <Info className="h-4 w-4" />
              Scoring guide
            </button>
            {showScoreGuide ? <ScoringGuideModal onClose={() => setShowScoreGuide(false)} /> : null}
            {liveBatch ? (
              <QaLiveProgress
                token={token}
                batchId={liveBatch}
                onClose={() => setLiveBatch(null)}
                onDone={() => queryClient.invalidateQueries({ queryKey: ["backlinks"] })}
                onViewResults={() => {
                  clearFilters();
                  setSort("last_checked_at");
                  setSortDir("desc");
                }}
                onViewFailures={() => {
                  clearFilters();
                  setStatus("FAIL,NEEDS_MANUAL_REVIEW,UNKNOWN");
                  setSort("last_checked_at");
                  setSortDir("desc");
                }}
              />
            ) : null}
            <button
              onClick={() => {
                if (window.confirm(`Give every link in this ${activeFilterCount ? "filtered set" : projectId ? "project" : "workspace"} that has NO placement date a date, spread naturally across the existing placement window (so they don't all land on one day)? Links that already have a date are left untouched.`))
                  fillPlacement.mutate();
              }}
              disabled={fillPlacement.isPending}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field disabled:opacity-40"
              title="Give links with no placement date a sensible date (their import date) so they appear on the activity chart"
            >
              {fillPlacement.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarDays className="h-4 w-4" />}
              Fill missing dates
            </button>
            <span className="flex items-center gap-1">
              <select
                value={staleDays}
                onChange={(e) => setStaleDays(e.target.value)}
                title="Only recheck links whose last check is older than this — fresh links are skipped"
                className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
              >
                <option value="10">Older than 10 days</option>
                <option value="20">Older than 20 days</option>
                <option value="30">Older than 30 days</option>
              </select>
              <button
                onClick={checkStale}
                className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
                title="Recheck old data only — anything checked recently is skipped"
              >
                <RefreshCw className="h-4 w-4" />
                Recheck stale
              </button>
            </span>
          </div>
        </div>

        {/* One-click QA presets */}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {chips.map(([label, active, toggle]) => (
            <button
              key={label}
              onClick={toggle}
              className={clsx(
                "h-7 rounded-full border px-3 text-xs font-medium transition",
                active
                  ? "border-ocean bg-ocean/10 text-ocean"
                  : "border-line text-muted hover:border-ocean/40 hover:text-ink"
              )}
            >
              {label}
            </button>
          ))}
          {activeFilterCount ? (
            <button onClick={clearFilters} className="ml-1 text-xs font-medium text-ocean hover:underline">
              Clear all
            </button>
          ) : null}
        </div>

        {/* Full filter row */}
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search URL or anchor…"
            className="h-9 w-56 rounded-xl border border-line bg-panel shadow-card px-3 text-sm focus:border-ocean focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <input
            value={targetInput}
            onChange={(e) => setTargetInput(e.target.value)}
            placeholder="Target URL or page…"
            title="Find backlinks by where they POINT — e.g. type /pricing to see every link to that page"
            className="h-9 w-48 rounded-xl border border-line bg-panel shadow-card px-3 text-sm focus:border-ocean focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <FilterMultiSelect
            label="Status"
            options={[
              { value: "PASS", label: "Pass" },
              { value: "WARNING", label: "Warning" },
              { value: "FAIL", label: "Not qualified" },
              { value: "UNKNOWN", label: "Couldn't check" },
              { value: "NEEDS_MANUAL_REVIEW", label: "Needs review" },
              { value: "PENDING", label: "Pending" }
            ]}
            selected={toks(status)}
            onChange={(v) => setStatus(v.join(","))}
          />
          {!projectId ? (
            <SearchSelect
              value={projF}
              onChange={setProjF}
              options={(projectsQ.data || []).map((p) => ({ value: p.id, label: p.name }))}
              placeholder="Project: all"
              width="w-44"
            />
          ) : null}
          <FilterMultiSelect
            label="Rel"
            options={[
              { value: "dofollow", label: "Dofollow" },
              { value: "nofollow", label: "Nofollow" },
              { value: "sponsored", label: "Sponsored" },
              { value: "ugc", label: "UGC" }
            ]}
            selected={toks(rel)}
            onChange={(v) => setRel(v.join(","))}
          />
          <FilterMultiSelect
            label="Link type"
            withBlanks
            options={(linkTypes.data || []).map((lt) => ({ value: lt.name }))}
            selected={toks(linkType)}
            onChange={(v) => setLinkType(v.join(","))}
          />
          <FilterMultiSelect
            label="Duplicates"
            options={[
              { value: "duplicate", label: "Any duplicate" },
              { value: "dup_same_project", label: "Same project" },
              { value: "dup_cross_project", label: "Used by another project" },
              { value: "dup_cross_user", label: "Added by another user" },
              { value: "unique", label: "Unique only" }
            ]}
            selected={toks(dupFilter)}
            onChange={(v) => setDupFilter(v.join(","))}
          />
          <FilterMultiSelect
            label="Index"
            options={[
              { value: "indexed", label: "Indexed" },
              { value: "not_indexed", label: "Not indexed" },
              { value: "uncertain", label: "Index unclear" },
              { value: "unchecked", label: "Not checked yet" }
            ]}
            selected={toks(indexFilter)}
            onChange={(v) => setIndexFilter(v.join(","))}
          />
          <FilterMultiSelect
            label="User"
            withBlanks
            options={facetOpts("user")}
            selected={toks(userF)}
            onChange={(v) => setUserF(v.join(","))}
          />
          <FilterMultiSelect
            label="Source domain"
            withBlanks
            options={facetOpts("source_domain")}
            selected={toks(domainF)}
            onChange={(v) => setDomainF(v.join(","))}
          />
          {/* Date-type axis + range: picks which date the grid shows/sorts and filters. */}
          <label className="flex items-center gap-1 rounded-xl border border-line bg-panel shadow-card px-2 text-xs text-muted">
            <select
              value={dateAxis}
              onChange={(e) => setDateAxis(e.target.value)}
              title="Which date type the Link date column shows, sorts, and filters on"
              className="h-9 rounded-lg bg-transparent px-1 text-sm text-ink focus:outline-none"
            >
              {BACKLINK_DATE_AXES.map((a) => (
                <option key={a.key} value={a.key}>{a.label}</option>
              ))}
            </select>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              title={`${axis.label} from`}
              className="h-9 rounded-lg border border-line bg-panel px-1.5 text-sm text-ink"
            />
            –
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              title={`${axis.label} to`}
              className="h-9 rounded-lg border border-line bg-panel px-1.5 text-sm text-ink"
            />
          </label>
        </div>
      </div>
      <div className="max-h-[70vh] overflow-auto scrollbar-thin">
        {/* Dense grid: slim one-line rows ([&_td] overrides the shared cell padding). */}
        <table className="min-w-[1240px] w-full border-collapse text-left text-sm [&_td]:px-2 [&_td]:py-1 [&_td]:align-middle [&_th]:px-2">
          <thead className="sticky top-0 z-10 bg-field text-xs uppercase text-muted">
            <tr>
              <Th>
                <input
                  type="checkbox"
                  aria-label="Select all loaded rows"
                  checked={rows.length > 0 && picked.size === rows.length}
                  onChange={(e) =>
                    setPicked(e.target.checked ? new Set(rows.map((r) => r.id)) : new Set())
                  }
                />
              </Th>
              <Th>Status</Th>
              <SortTh label="Score" sortKey="score" sort={sort} dir={sortDir} onSort={onSortCol}
                help="How scoring works: every link starts at 100 and each problem subtracts points by how serious it is (link missing/dead page cost the most; nofollow, weak pages cost less). Below the warn line = Needs improvement; below the fail line = Not qualified. Hover any score to see its exact breakdown. Thresholds are set per link type/project in Scoring." />
              <SortTh label="Source" sortKey="source_domain" sort={sort} dir={sortDir} onSort={onSortCol}
                help="Sort by source domain A→Z" />
              <Th>Target</Th>
              <SortTh label="Type" sortKey="link_type" sort={sort} dir={sortDir} onSort={onSortCol} />
              <Th>User</Th>
              {!projectId ? <Th>Project</Th> : null}
              <Th>Index</Th>
              <SortTh label="HTTP" sortKey="http_status" sort={sort} dir={sortDir} onSort={onSortCol} />
              <Th>Rel</Th>
              <Th><span title="DA/PA/AS of the source domain, or rank/visits from the metrics provider">Metrics</span></Th>
              <Th>Issue</Th>
              {axis.sort ? (
                <SortTh label={axis.label} sortKey={axis.sort} sort={sort} dir={sortDir} onSort={onSortCol}
                  help={`Showing each link's ${axis.label} date (change the date type in the toolbar). Hover a cell for its other dates.`} />
              ) : (
                <Th><span title={`Showing each link's ${axis.label} date — this date type isn't sortable`}>{axis.label}</span></Th>
              )}
              <SortTh label="Checked" sortKey="last_checked_at" sort={sort} dir={sortDir} onSort={onSortCol} />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row) => (
              <tr
                key={row.id}
                onClick={() => setSelectedId(row.id)}
                className={clsx("cursor-pointer hover:bg-field/70", picked.has(row.id) && "bg-ocean/5")}
              >
                <Td>
                  <input
                    type="checkbox"
                    aria-label="Select row"
                    checked={picked.has(row.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      setPicked((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(row.id);
                        else next.delete(row.id);
                        return next;
                      });
                    }}
                  />
                </Td>
                <Td>
                  <span className="inline-flex items-center gap-1">
                    <Status value={row.override_status || row.status} reason={row.top_issue_label} compact />
                    {row.qa_wait_reason ? <QaWaitBadge reason={row.qa_wait_reason} /> : null}
                  </span>
                </Td>
                <Td>
                  <span onClick={(e) => e.stopPropagation()}>
                    <ScoreTip token={token} backlinkId={row.id} score={row.score} />
                  </span>
                </Td>
                <Td>
                  <span className="flex items-center gap-1.5">
                    <Url value={row.source_page_url} />
                    {row.is_duplicate ? (
                      <span
                        className="shrink-0 rounded bg-ember/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ember"
                        title={`Duplicate: ${(row.duplicate_status || "duplicate").replace("dup_", "").replace(/_/g, " ")}`}
                      >
                        dup
                      </span>
                    ) : null}
                  </span>
                </Td>
                <Td>
                  <span className="flex items-center gap-1.5">
                    <Url value={row.target_url} />
                    {(row.targets_on_source ?? 1) > 1 ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSearch(row.source_page_url);
                        }}
                        className="shrink-0 rounded bg-plum/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-plum hover:bg-plum/20"
                        title={`This source page links to ${row.targets_on_source} different targets — click to see all of them`}
                      >
                        ×{row.targets_on_source}
                      </button>
                    ) : null}
                  </span>
                </Td>
                <Td><span className="whitespace-nowrap text-xs" title={row.link_type || undefined}>{linkTypeLabel(row.link_type) || "—"}</span></Td>
                <Td>
                  {row.assigned_user_label ? (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setUserF(row.assigned_user_label || "");
                      }}
                      title={`Show all links by ${row.assigned_user_label}`}
                      className="whitespace-nowrap text-xs font-medium text-ocean hover:underline"
                    >
                      {row.assigned_user_label}
                    </button>
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </Td>
                {!projectId ? (
                  <Td>
                    <span className="whitespace-nowrap text-xs text-muted">
                      {projectName(row.project_id)}
                    </span>
                  </Td>
                ) : null}
                <Td>{row.index_status ? <IndexBadge value={row.index_status} /> : <span className="text-xs text-muted">—</span>}</Td>
                <Td>{row.http_status ?? "-"}</Td>
                <Td>{row.current_rel ?? "-"}</Td>
                <Td>
                  {row.domain_da != null || row.domain_as != null || row.domain_spam != null ? (
                    <span className="flex flex-wrap gap-1">
                      <MetricTag label="DA" value={row.domain_da} />
                      <MetricTag label="AS" value={row.domain_as} />
                      {row.domain_spam != null ? <SpamTag value={row.domain_spam} /> : null}
                    </span>
                  ) : (
                    <span title={metricAgeTitle(row.extra?.metrics)}>{formatSiteMetric(row.extra?.metrics)}</span>
                  )}
                </Td>
                <Td><IssueWord label={row.top_issue_label} count={row.issue_count} /></Td>
                <Td>
                  <span
                    className="whitespace-nowrap text-xs text-muted"
                    title={dateAxisTooltip(row)}
                  >
                    {formatDay((row[axis.field] as string | null | undefined) ?? null)}
                  </span>
                </Td>
                <Td><span className="whitespace-nowrap">{formatDate(row.last_checked_at)}</span></Td>
              </tr>
            ))}
          </tbody>
        </table>
        {!backlinks.isLoading && !rows.length ? <Empty label="No backlinks match these filters" /> : null}
        {backlinks.isLoading ? (
          <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
        ) : null}
      </div>
      {backlinks.hasNextPage ? (
        <div className="border-t border-line p-2 text-center">
          <button
            onClick={() => backlinks.fetchNextPage()}
            disabled={backlinks.isFetchingNextPage}
            className="h-9 rounded-lg border border-line px-4 text-sm font-medium text-ink transition hover:bg-field disabled:opacity-50"
          >
            {backlinks.isFetchingNextPage ? "Loading…" : `Load more (${rows.length} of ${totalCount})`}
          </button>
        </div>
      ) : null}
      {selectedId ? (
        <BacklinkDetailDrawer
          token={token}
          backlinkId={selectedId}
          onClose={() => setSelectedId(null)}
          onNotice={onNotice}
        />
      ) : null}
    </section>
  );
}

function BacklinkDetailDrawer({
  token,
  backlinkId,
  onClose,
  onNotice
}: {
  token: string | null;
  backlinkId: string;
  onClose: () => void;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["backlink", token, backlinkId],
    enabled: Boolean(token),
    queryFn: () => api<BacklinkDetail>(`/backlinks/${backlinkId}`, { token })
  });
  const duplicates = useQuery({
    queryKey: ["backlink-dupes", token, backlinkId],
    enabled: Boolean(token),
    queryFn: () => api<BacklinkRow[]>(`/backlinks/${backlinkId}/duplicates`, { token })
  });
  // The duplicate group this backlink belongs to (if any) — powers the inline
  // Duplicates panel + the "compare all records" view without leaving the drawer.
  const [showCompare, setShowCompare] = useState(false);
  const conflictGroup = useQuery({
    queryKey: ["backlink-conflict", token, backlinkId],
    enabled: Boolean(token),
    queryFn: () => api<ConflictDetail | Record<string, never>>(`/conflicts/for-backlink/${backlinkId}`, { token })
  });
  const assignments = useQuery({
    queryKey: ["backlink-assign", token, backlinkId],
    enabled: Boolean(token),
    queryFn: () => api<AssignmentEvent[]>(`/backlinks/${backlinkId}/assignment-history`, { token })
  });

  const recheck = useMutation({
    mutationFn: () =>
      api<{ job_id: string; queued: number }>(`/backlinks/${backlinkId}/recheck`, {
        token,
        method: "POST"
      }),
    onSuccess: () => onNotice("Recheck queued — refresh in a moment"),
    onError: (err: Error) => onNotice(err.message)
  });

  const deleteLink = useMutation({
    mutationFn: () =>
      api<{ message: string }>(`/backlinks/${backlinkId}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Backlink deleted");
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      onClose();
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const override = useMutation({
    mutationFn: (payload: { status: string; note: string }) =>
      api<BacklinkRow>(`/backlinks/${backlinkId}/override`, {
        token,
        method: "POST",
        body: JSON.stringify(payload)
      }),
    onSuccess: () => {
      onNotice("Verdict overridden");
      queryClient.invalidateQueries({ queryKey: ["backlink", token, backlinkId] });
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  // Edit an editable link field (currently the placement date). PATCH sends only
  // the changed key; sending placement_date:null clears it, a "YYYY-MM-DD" sets it.
  // Invalidate the dashboard too — placement_date moves the link on the time chart.
  const editField = useMutation({
    mutationFn: (payload: { placement_date: string | null }) =>
      api<BacklinkRow>(`/backlinks/${backlinkId}`, {
        token,
        method: "PATCH",
        body: JSON.stringify(payload)
      }),
    onSuccess: () => {
      onNotice("Placement date saved");
      queryClient.invalidateQueries({ queryKey: ["backlink", token, backlinkId] });
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const data = detail.data;
  const grp =
    conflictGroup.data && (conflictGroup.data as ConflictDetail).id
      ? (conflictGroup.data as ConflictDetail)
      : null;
  return (
    <>
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        className="h-full w-full max-w-[680px] overflow-y-auto bg-panel shadow-xl scrollbar-thin"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-panel px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink">Backlink detail</h2>
            <p className="flex items-center gap-1 text-xs text-muted">
              <span className="min-w-0 truncate">{data?.source_page_url}</span>
              {data?.source_page_url ? <CopyButton text={data.source_page_url} title="Copy source URL" /> : null}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (window.confirm("Delete this backlink? Its history stays in past runs, but the link disappears from every list and count.")) {
                  deleteLink.mutate();
                }
              }}
              title="Delete this backlink (admins/editors only)"
              className="grid h-9 w-9 place-items-center rounded-md border border-danger/40 text-danger transition hover:bg-danger/10"
              aria-label="Delete backlink"
            >
              {deleteLink.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            </button>
            <button
              onClick={() => recheck.mutate()}
              className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              {recheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Recheck
            </button>
            <IconButton label="Close" onClick={onClose} icon={XCircle} />
          </div>
        </div>

        {detail.isLoading || !data ? (
          <div className="grid place-items-center p-12 text-muted">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : (
          <div className="space-y-5 p-5">
            {data.qa_wait_reason ? (
              <div className={clsx(
                "flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm",
                data.qa_wait_reason === "api_failed" ? "border-danger/40 bg-danger/5" : "border-ember/40 bg-ember/5"
              )}>
                <QaWaitBadge reason={data.qa_wait_reason} />
                <span className="min-w-0 flex-1 text-muted">
                  {STATUS_HELP[data.qa_wait_reason]?.what}{" "}
                  <span className="text-ink">{STATUS_HELP[data.qa_wait_reason]?.next}</span>
                </span>
                <button
                  onClick={() => recheck.mutate()}
                  disabled={recheck.isPending}
                  className="flex h-8 items-center gap-1.5 rounded-lg bg-ocean px-3 text-xs font-semibold text-white disabled:opacity-60 dark:text-slate-900"
                >
                  {recheck.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  Retry QA now
                </button>
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KeyStat label="Status" node={<Status value={data.override_status || data.status} />} />
              <KeyStat label="Score" node={<span className="text-2xl font-semibold text-ink">{data.score ?? "-"}</span>} />
              <KeyStat
                label="HTTP"
                node={
                  data.latest_result?.found_in_browser && data.http_status && data.http_status >= 400 ? (
                    <span
                      className="font-semibold"
                      title={`Automated requests get HTTP ${data.http_status} (bot protection), but the page opens normally in a real browser${data.latest_result?.browser_http_status ? ` (browser saw HTTP ${data.latest_result.browser_http_status})` : ""} — we verified the link in a rendered browser session.`}
                    >
                      <span className="text-muted line-through">{data.http_status}</span>{" "}
                      <span className="text-ocean">✓ browser OK</span>
                    </span>
                  ) : (
                    <span className="font-semibold">{data.http_status ?? "-"}</span>
                  )
                }
              />
              <KeyStat label="Indexable" node={<span className="font-medium">{data.indexability ?? "-"}</span>} />
            </div>

            {/* The full story of the last check — plain words, no bare codes. */}
            <QaEvidencePanel data={data} />

            <DetailBlock title="Link facts">
              <FactRow k="Target" v={data.target_url} />
              <FactRow k="Expected target" v={data.expected_target_url} />
              <FactRow k="Final URL" v={data.final_url} />
              <FactRow
                k="Link on page"
                v={(() => {
                  if (!data.link_found)
                    return data.link_found === false ? "NOT found on the page" : "Not checked yet";
                  const href = data.latest_result?.matched_href;
                  if (!href) return "Found";
                  try {
                    const linkHost = new URL(href).hostname.replace(/^www\./, "");
                    const targetHost = new URL(data.target_url).hostname.replace(/^www\./, "");
                    if (linkHost !== targetHost) {
                      return `${href} — a redirect link that forwards to your target (counted as found)`;
                    }
                  } catch {
                    /* fall through */
                  }
                  return href;
                })()}
              />
              <FactRow k="Rel (observed / expected)" v={`${data.current_rel ?? "-"} / ${data.expected_rel}`} />
              <FactRow
                k="Anchor (observed)"
                v={
                  data.current_anchor_text ||
                  (data.link_found
                    ? "Image/icon link — no text on the link itself"
                    : data.link_found === false
                      ? "— (the link wasn't found, so there's no anchor to read)"
                      : "— (not checked yet)")
                }
              />
              <FactRow k="Expected anchor" v={data.expected_anchor_text} />
              <FactRow k="Canonical / Robots" v={`${data.canonical_status ?? "-"} / ${data.robots_status ?? "-"}`} />
              <FactRow
                k="Posted / published date"
                v={
                  data.latest_result?.published_date
                    ? `${data.latest_result.published_date}${data.latest_result.date_source ? ` (from ${data.latest_result.date_source})` : ""}`
                    : "Not detected on page"
                }
              />
              <FactRow
                k="Authority"
                v={
                  <span className="flex flex-wrap gap-1">
                    <MetricTag label="DA" value={data.domain_da} title="Domain Authority — Moz, for the whole source domain" />
                    <MetricTag label="PA" value={data.domain_pa} title="Page/domain authority — Moz" />
                    <MetricTag label="AS" value={data.domain_as} title="Authority Score — Semrush" />
                    {data.domain_spam != null ? <SpamTag value={data.domain_spam} /> : null}
                  </span>
                }
              />
              <FactRow
                k="Source site metrics"
                v={
                  data.extra?.metrics
                    ? formatSiteMetricLong(data.extra.metrics)
                    : "Not fetched (metrics API not configured)"
                }
              />
              <FactRow k="Assigned user / employee" v={`${data.assigned_user_label ?? "-"}${data.employee_code ? ` (${data.employee_code})` : ""}`} />
              <FactRow k="Link type" v={data.link_type || "-"} />
              <FactRow
                k="Duplicate status"
                v={data.is_duplicate ? (data.duplicate_status || "duplicate").replace(/_/g, " ") : "unique"}
              />
              <FactRow
                k="Google index"
                v={data.index_status ? <IndexBadge value={data.index_status} /> : "not checked yet"}
              />
            </DetailBlock>

            <DetailBlock title="Dates">
              <PlacementDateEditor
                value={data.placement_date ?? null}
                pending={editField.isPending}
                onSave={(v) => editField.mutate({ placement_date: v })}
              />
              {/* Placement is edited above; the rest of the date types are read-only. */}
              {BACKLINK_DATE_FIELDS.filter((d) => d.field !== "placement_date").map((d) => {
                const v = (data[d.field] as string | null | undefined) ?? null;
                return (
                  <FactRow
                    key={d.field as string}
                    k={d.label}
                    v={v ? (d.time ? formatDate(v) : formatDay(v)) : "—"}
                  />
                );
              })}
              <FactRow k="Next check due" v={data.next_check_at ? formatDate(data.next_check_at) : "—"} />
            </DetailBlock>

            {(() => {
              const occ = duplicates.data || [];
              if (!grp && occ.length === 0) return null;
              // Prefer the conflict group's own members (has similarity, scope,
              // field diffs); fall back to the plain occurrences list.
              const siblings = grp
                ? (grp.members || []).filter((m) => m.backlink_id !== backlinkId)
                : occ.map((d) => ({
                    backlink_id: d.id, source_page_url: d.source_page_url, target_url: d.target_url,
                    assigned_user_label: d.assigned_user_label, project_name: null,
                    duplicate_status: d.duplicate_status, link_type: d.link_type, status: d.status
                  }));
              const diffFields = grp
                ? (grp.field_matrix || []).filter((r) => !r.all_same).map((r) => compareFieldLabel(r.field))
                : [];
              return (
                <DetailBlock title={`Duplicates (${siblings.length} other record${siblings.length === 1 ? "" : "s"})`}>
                  {grp ? (
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <ScopeChip scope={grp.scope} />
                      <SimilarityMeter value={grp.similarity} />
                      {grp.resolution_status ? <Status value={grp.resolution_status} compact /> : null}
                      <button
                        onClick={() => setShowCompare(true)}
                        className="ml-auto flex items-center gap-1 rounded-md border border-ocean/40 bg-ocean/10 px-2 py-1 text-[11px] font-semibold text-ocean transition hover:bg-ocean/20"
                      >
                        <GitCompare className="h-3 w-3" /> Compare all records
                      </button>
                    </div>
                  ) : null}
                  {diffFields.length ? (
                    <div className="mb-2 text-xs text-muted">
                      Differs on: <span className="font-medium text-ember">{diffFields.join(", ")}</span>
                    </div>
                  ) : null}
                  <div className="space-y-1.5">
                    {siblings.map((d) => (
                      <div key={d.backlink_id} className="rounded-md border border-line p-2 text-xs">
                        <div className="truncate font-medium text-ink" title={d.source_page_url}>{d.source_page_url}</div>
                        <div className="text-muted">
                          → {d.target_url || "—"} · {d.assigned_user_label || "no user"}
                          {d.project_name ? ` · ${d.project_name}` : ""}
                          {d.duplicate_status ? ` · ${(d.duplicate_status || "").replace(/_/g, " ")}` : ""}
                        </div>
                      </div>
                    ))}
                  </div>
                </DetailBlock>
              );
            })()}

            {assignments.data && assignments.data.length > 0 ? (
              <DetailBlock title="Assignment history">
                <div className="space-y-1.5">
                  {assignments.data.map((a, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="text-ink">{a.old_user_label || "—"} → {a.new_user_label || "—"}</span>
                      <span className="text-xs text-muted">{formatDate(a.changed_at)} · {a.source}</span>
                    </div>
                  ))}
                </div>
              </DetailBlock>
            ) : null}

            {data.score_breakdown.length ? (
              <DetailBlock title="Why this score">
                {(() => {
                  // Rule-set version, if the payload exposes it. We only have the
                  // id (a uuid) — show that it exists without inventing a number.
                  const rv = data.scoring_rule_version_id ?? data.latest_result?.scoring_rule_version_id;
                  return rv ? (
                    <div className="mb-2 text-xs text-muted">Scored by rule set v{rv.slice(0, 8)}</div>
                  ) : null;
                })()}
                <div className="space-y-1.5">
                  {/* Server orders the steps: baseline, biggest deduction first, gains, cap.
                      Each losing step carries a plain "How to improve" line. */}
                  {data.score_breakdown.map((step, i) => {
                    // Human line: prefer parameter/outcome labels; else code + note.
                    const label = step.code === "START" ? "Baseline" : step.code;
                    const human =
                      step.parameter_label && step.outcome_label
                        ? `${step.parameter_label} - ${step.outcome_label}`
                        : step.parameter_label || null;
                    const srcTag = SCORE_SOURCE_LABEL[step.source ?? ""] ?? null;
                    return (
                      <div key={`${step.code}-${i}`}>
                        <div className="flex items-start justify-between gap-3 text-sm">
                          <span className="min-w-0 text-muted">
                            {human ? (
                              <span className="text-ink">{human}</span>
                            ) : (
                              <>
                                {label}
                                {step.note ? <span className="ml-2 text-xs">{step.note}</span> : null}
                              </>
                            )}
                            {srcTag ? (
                              <span className="ml-2 rounded bg-field px-1 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                                {srcTag}
                              </span>
                            ) : null}
                            {step.configured_points !== null && step.configured_points !== undefined ? (
                              <span className="ml-2 text-[11px] text-muted">
                                ({step.configured_points > 0 ? "+" : ""}
                                {step.configured_points} pts)
                              </span>
                            ) : null}
                          </span>
                          <span className={clsx("shrink-0 font-semibold", step.delta < 0 ? "text-danger" : "text-ink")}>
                            {step.cap_applied !== null && step.cap_applied !== undefined
                              ? `cap → ${step.cap_applied}`
                              : step.delta === 0
                              ? "100"
                              : step.delta > 0
                              ? `+${step.delta}`
                              : step.delta}
                          </span>
                        </div>
                        {step.recommendation ? (
                          <p className="mt-0.5 flex items-start gap-1 pl-3 text-xs text-muted">
                            <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-ember" />
                            <span>{step.recommendation}</span>
                          </p>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </DetailBlock>
            ) : null}

            <QaAttemptsBlock token={token} backlinkId={backlinkId} />
            <LinkTimelineBlock token={token} backlinkId={backlinkId} />

            <DetailBlock title={`Issues (${data.issues.length})`}>
              {data.issues.length === 0 ? (
                <p className="text-sm text-muted">No issues detected.</p>
              ) : (
                <div className="space-y-2">
                  {data.issues.map((issue, i) => (
                    <div key={`${issue.code}-${i}`} className="rounded-md border border-line p-3">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs text-muted">{issue.code}</span>
                        <Severity value={issue.severity} />
                      </div>
                      <div className="mt-1 text-sm font-medium text-ink">{issue.message}</div>
                      <SpamEvidence evidence={issue.evidence} />
                      {issue.recommendation ? (
                        <div className="mt-1 text-xs text-muted">→ {issue.recommendation}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </DetailBlock>

            {data.latest_result?.redirect_chain?.length ? (
              <DetailBlock title="Redirect chain">
                <ol className="space-y-1 text-sm">
                  {data.latest_result.redirect_chain.map((hop, i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span className="rounded bg-field px-1.5 py-0.5 text-xs font-semibold">{hop.status}</span>
                      <span className="truncate text-muted" title={hop.url}>{hop.url}</span>
                    </li>
                  ))}
                </ol>
              </DetailBlock>
            ) : null}

            <DetailBlock title="History timeline">
              {data.history.length === 0 ? (
                <p className="text-sm text-muted">No change events yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {data.history.map((ev, i) => (
                    <div key={i} className="flex items-center justify-between text-sm">
                      <span className="text-ink">
                        {ev.event_type.replaceAll("_", " ")}
                        {ev.field ? <span className="text-muted"> · {ev.old_value ?? "—"} → {ev.new_value ?? "—"}</span> : null}
                      </span>
                      <span className="text-xs text-muted">{formatDate(ev.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </DetailBlock>

            <DetailBlock title="Manual override">
              <OverrideForm
                pending={override.isPending}
                onSubmit={(status, note) => override.mutate({ status, note })}
              />
              {data.override_note ? (
                <p className="mt-2 text-xs text-muted">Current note: {data.override_note}</p>
              ) : null}
            </DetailBlock>
          </div>
        )}
      </aside>
    </div>
    {showCompare && grp ? (
      <ConflictComparisonModal
        conflictId={grp.id}
        token={token}
        onClose={() => setShowCompare(false)}
        onNotice={onNotice}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: ["backlink-conflict", token, backlinkId] });
          queryClient.invalidateQueries({ queryKey: ["backlink-dupes", token, backlinkId] });
        }}
      />
    ) : null}
    </>
  );
}

function OverrideForm({
  pending,
  onSubmit
}: {
  pending: boolean;
  onSubmit: (status: string, note: string) => void;
}) {
  const [status, setStatus] = useState("PASS");
  const [note, setNote] = useState("");
  return (
    <form
      className="flex flex-col gap-2 sm:flex-row"
      onSubmit={(event) => {
        event.preventDefault();
        if (note.trim()) onSubmit(status, note.trim());
      }}
    >
      <select
        className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
        value={status}
        onChange={(event) => setStatus(event.target.value)}
      >
        <option value="PASS">Pass</option>
        <option value="WARNING">Warning</option>
        <option value="FAIL">Not qualified</option>
        <option value="NEEDS_MANUAL_REVIEW">Review</option>
      </select>
      <input
        className="h-9 flex-1 rounded-md border border-line bg-panel px-3 text-sm"
        placeholder="Reason (required)"
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <button
        disabled={pending || !note.trim()}
        className="flex h-9 items-center gap-2 rounded-md bg-plum px-3 text-sm font-semibold text-white disabled:opacity-50"
      >
        {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
        Override
      </button>
    </form>
  );
}

// Add/edit a link's placement (go-live) date — the only user-editable date. An
// empty value is called out in amber so links missing a date (and therefore off
// the time chart) are easy to spot and fix. Save sends "YYYY-MM-DD"; clearing the
// box and saving sends null (backend clears the column).
function PlacementDateEditor({
  value,
  pending,
  onSave
}: {
  value: string | null;
  pending: boolean;
  onSave: (value: string | null) => void;
}) {
  // The Date column serializes as "YYYY-MM-DD" (may carry a time) — <input type=
  // "date"> wants exactly the 10-char day form.
  const initial = (value || "").slice(0, 10);
  const [draft, setDraft] = useState(initial);
  // Re-sync the box when the record changes (after a save, or a reopened drawer).
  useEffect(() => setDraft(initial), [initial]);
  const missing = !value;
  const dirty = draft !== initial;
  return (
    <div className="mb-3 border-b border-line pb-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-muted">Placement date</span>
        {missing ? (
          <span className="rounded bg-ember/10 px-1.5 py-0.5 text-[11px] font-semibold text-ember">
            No date — add one to place it on the timeline
          </span>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <div className="relative">
          <CalendarDays className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            type="date"
            className="h-9 rounded-md border border-line bg-panel pl-8 pr-3 text-sm text-ink"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
        </div>
        <button
          disabled={pending || !dirty}
          onClick={() => onSave(draft ? draft : null)}
          className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
        >
          {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          Save
        </button>
        {value && dirty && !draft ? (
          <span className="text-[11px] text-muted">Saving with an empty box clears the date</span>
        ) : null}
      </div>
    </div>
  );
}

function KeyStat({ label, node }: { label: string; node: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-field p-3">
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className="mt-1">{node}</div>
    </div>
  );
}

// ── QA Evidence panel (Enterprise §1): the full story of one check ───────────
// Answers, in order and in plain words: what we requested, how it redirected,
// what came back, what a real browser saw, and WHY the verdict is what it is —
// with the recommended next action. No raw codes without explanations.
const HTTP_WORDS: Record<number, string> = {
  200: "page loaded normally",
  301: "moved permanently",
  302: "temporary redirect",
  403: "access refused (bot protection)",
  404: "page not found",
  410: "page permanently removed",
  429: "too many requests (rate limit)",
  500: "server error",
  503: "service temporarily unavailable"
};
const httpWord = (s: number | null | undefined) =>
  s == null ? "no response" : `${s} — ${HTTP_WORDS[s] || (s < 300 ? "OK" : s < 400 ? "redirect" : s < 500 ? "request refused" : "server problem")}`;

function QaEvidencePanel({ data }: { data: BacklinkDetail }) {
  const lr = data.latest_result;
  if (!lr) return null;
  const hops = lr.redirect_chain || [];
  const rawStatus = data.http_status;
  const browserTried = lr.found_in_browser != null || lr.browser_http_status != null;
  const browserOk = Boolean(lr.found_in_browser);
  const browserBlocked = browserTried && !browserOk && (lr.browser_http_status ?? 0) >= 400;
  const eff = data.override_status || data.status;
  const topIssue = (data.issues || [])[0];
  // One-line conclusion chip — the classification in human words.
  const conclusion =
    browserOk && (rawStatus ?? 0) >= 400
      ? { label: "Verified in a real browser", cls: "bg-ocean/10 text-ocean border-ocean/40",
          text: "The site refuses automated requests, but the page loads fine in a real browser — the link is genuinely live." }
      : browserBlocked
      ? { label: "Blocked for automated tools", cls: "bg-plum/10 text-plum border-plum/40",
          text: "Both our automated request AND a real browser from our servers were refused — the site blocks our network (IP-level bot protection). The page most likely opens fine for real visitors; confirm once in your own browser." }
      : eff === "PASS"
      ? { label: "Confirmed working", cls: "bg-ocean/10 text-ocean border-ocean/40",
          text: "The page loaded, the link is present, and no serious problems were found." }
      : eff === "FAIL"
      ? { label: "Confirmed problem", cls: "bg-danger/10 text-danger border-danger/40",
          text: "We could read the page normally — the problem shown below is real, not a checking error." }
      : eff === "UNKNOWN"
      ? { label: "Temporary — will need a retry", cls: "bg-ember/10 text-ember border-ember/40",
          text: "The website or a service didn't respond properly this time (timeout / rate limit / outage). This says nothing about the link itself yet." }
      : eff === "NEEDS_MANUAL_REVIEW"
      ? { label: "Needs your eyes", cls: "bg-plum/10 text-plum border-plum/40",
          text: "We couldn't verify this automatically with confidence — a quick human look settles it." }
      : { label: "Waiting for its first check", cls: "bg-field text-muted border-line",
          text: "This link hasn't been QA-checked yet — run a QA check to get its first verdict." };
  const nextAction = STATUS_HELP[eff]?.next;
  const step = (n: number, title: string, body: React.ReactNode) => (
    <li className="relative pl-7">
      <span className="absolute left-0 top-0.5 grid h-5 w-5 place-items-center rounded-full bg-field text-[10px] font-bold text-muted">{n}</span>
      <span className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</span>
      <div className="mt-0.5 text-sm text-ink">{body}</div>
    </li>
  );
  let n = 0;
  return (
    <section className="rounded-xl border border-line bg-field/30 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-bold text-ink">What happened during this check</h3>
        <span className={clsx("rounded-full border px-2.5 py-0.5 text-xs font-bold", conclusion.cls)}>
          {conclusion.label}
        </span>
        <span className="ml-auto text-xs text-muted">{formatDate(lr.crawled_at)}</span>
      </div>
      <ol className="space-y-3">
        {step(++n, "We requested the page", (
          <span className="break-all text-sm">
            {data.source_page_url}
            {hops.length ? null : (
              <span className={clsx("ml-2 rounded px-1.5 py-0.5 text-xs font-semibold",
                (rawStatus ?? 0) < 400 ? "bg-ocean/10 text-ocean" : "bg-danger/10 text-danger")}>
                {httpWord(rawStatus)}
              </span>
            )}
          </span>
        ))}
        {hops.length ? step(++n, `It redirected (${hops.length} hop${hops.length === 1 ? "" : "s"})`, (
          <div className="space-y-0.5">
            {hops.map((hop, i) => (
              <div key={i} className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className="rounded bg-field px-1 py-0.5 font-semibold text-muted">{(hop as { status?: number }).status ?? "→"}</span>
                <span className="min-w-0 break-all text-muted">{(hop as { url?: string }).url}</span>
              </div>
            ))}
            <div className="text-xs text-muted">
              Landed on <span className="break-all text-ink">{lr.final_url || data.source_page_url}</span>{" "}
              <span className={clsx("rounded px-1.5 py-0.5 font-semibold",
                (rawStatus ?? 0) < 400 ? "bg-ocean/10 text-ocean" : "bg-danger/10 text-danger")}>
                {httpWord(rawStatus)}
              </span>
            </div>
          </div>
        )) : null}
        {browserTried ? step(++n, "We also opened it in a real browser", (
          browserOk ? (
            <span>
              <span className="rounded bg-ocean/10 px-1.5 py-0.5 text-xs font-semibold text-ocean">
                Loaded successfully{lr.browser_http_status ? ` (${httpWord(lr.browser_http_status)})` : ""}
              </span>{" "}
              <span className="text-sm text-muted">— and the backlink was found on the rendered page.</span>
            </span>
          ) : (
            <span>
              <span className="rounded bg-danger/10 px-1.5 py-0.5 text-xs font-semibold text-danger">
                Also blocked ({httpWord(lr.browser_http_status)})
              </span>{" "}
              <span className="text-sm text-muted">— the protection covers our whole network, not just the automated request.</span>
            </span>
          )
        )) : null}
        {step(++n, "Conclusion", (
          <div>
            <p className="text-sm text-muted">{conclusion.text}</p>
            {topIssue && eff !== "PASS" ? (
              <p className="mt-1 text-sm"><span className="font-semibold text-ink">Main finding:</span> <span className="text-muted">{topIssue.message}</span></p>
            ) : null}
            {nextAction ? (
              <p className="mt-1 flex items-start gap-1 text-sm">
                <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ember" />
                <span><span className="font-semibold text-ink">Next step:</span> <span className="text-muted">{nextAction}</span></span>
              </p>
            ) : null}
          </div>
        ))}
      </ol>
    </section>
  );
}

// Full chronological timeline (Enterprise §10): every recorded event for a link —
// manual edits, QA verdict changes, overrides, reassignments, dedup/index flips —
// from the merged /history endpoint, with colored markers per event family.
function LinkTimelineBlock({ token, backlinkId }: { token: string | null; backlinkId: string }) {
  type Ev = {
    at: string; event_type: string; field: string | null; old_value: string | null;
    new_value: string | null; actor_role: string | null; source: string | null; note: string | null;
  };
  const [open, setOpen] = useState(false);
  const tl = useQuery({
    queryKey: ["link-timeline", token, backlinkId],
    enabled: Boolean(token && backlinkId) && open,
    retry: false,
    queryFn: () => api<{ items: Ev[] }>(`/backlinks/${backlinkId}/history?limit=50`, { token })
  });
  const dot = (t: string) =>
    t.includes("override") || t === "deleted" ? "bg-danger"
    : t === "created" || t.includes("recover") ? "bg-ocean"
    : t.includes("assign") || t === "edited" ? "bg-plum"
    : t.includes("index") || t.includes("dedup") || t === "rescored" ? "bg-ember"
    : "bg-slate-400";
  const wording = (e: Ev) => {
    const t = e.event_type.replaceAll("_", " ");
    if (e.field && (e.old_value || e.new_value))
      return `${t}: ${e.field} ${e.old_value ? `"${e.old_value}" → ` : "→ "}"${e.new_value ?? ""}"`;
    if (e.old_value || e.new_value)
      return `${t}${e.old_value ? ` from "${e.old_value}"` : ""}${e.new_value ? ` to "${e.new_value}"` : ""}`;
    return t;
  };
  return (
    <DetailBlock title="Timeline">
      {!open ? (
        <button onClick={() => setOpen(true)} className="text-sm font-medium text-ocean hover:underline">
          Load the full activity timeline…
        </button>
      ) : tl.isLoading ? (
        <div className="flex justify-center p-3"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : !(tl.data?.items || []).length ? (
        <Empty label="No recorded events yet." />
      ) : (
        <ol className="relative ml-2 space-y-2 border-l border-line pl-4">
          {(tl.data?.items || []).map((e, i) => (
            <li key={i} className="relative text-sm">
              <span className={clsx("absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-panel", dot(e.event_type))} />
              <span className="text-ink">{wording(e)}</span>
              <span className="ml-2 text-xs text-muted">
                {formatDate(e.at)}
                {e.source ? ` · ${e.source}` : ""}
                {e.actor_role ? ` · ${e.actor_role}` : ""}
              </span>
              {e.note ? <p className="text-xs text-muted">“{e.note}”</p> : null}
            </li>
          ))}
        </ol>
      )}
    </DetailBlock>
  );
}

// Every QA execution TRY (Enterprise §2) — including tries that died on an API
// failure before producing a verdict. Answers "why is this still pending?".
function QaAttemptsBlock({ token, backlinkId }: { token: string | null; backlinkId: string }) {
  type Attempt = {
    id: string; attempt_number: number; at: string | null; trigger_source: string;
    queue: string | null; apis_used: string[]; request_count: number;
    duration_ms: number | null; status: string; verdict: string | null;
    failure_kind: string | null; failure_api: string | null; error: string | null;
  };
  const attempts = useQuery({
    queryKey: ["qa-attempts", token, backlinkId],
    enabled: Boolean(token && backlinkId),
    retry: false,
    queryFn: () => api<Attempt[]>(`/backlinks/${backlinkId}/qa-attempts?limit=20`, { token })
  });
  const rows = attempts.data || [];
  if (!rows.length) return null;
  return (
    <DetailBlock title="QA attempts">
      <div className="space-y-1.5">
        {rows.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-2 text-xs">
            <span className="w-8 shrink-0 font-semibold text-muted">#{a.attempt_number}</span>
            <span className="w-32 shrink-0 text-muted">{formatDate(a.at)}</span>
            <span className={clsx(
              "rounded px-1.5 py-0.5 font-semibold",
              a.status === "success" ? "bg-ocean/10 text-ocean" : "bg-danger/10 text-danger"
            )}>
              {a.status === "success" ? (STATUS_HELP[a.verdict || ""]?.label || a.verdict) : `failed — ${a.failure_kind || "error"}`}
            </span>
            <span className="rounded bg-field px-1.5 py-0.5 text-[10px] uppercase text-muted">{a.trigger_source}</span>
            {a.apis_used.length ? (
              <span className="text-muted">via {a.apis_used.join(" + ")}</span>
            ) : null}
            {a.duration_ms != null ? <span className="text-muted">{(a.duration_ms / 1000).toFixed(1)}s</span> : null}
            {a.error ? <span className="min-w-0 flex-1 truncate text-danger" title={a.error}>{a.error}</span> : null}
          </div>
        ))}
      </div>
    </DetailBlock>
  );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line">
      <div className="border-b border-line px-4 py-2.5">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function FactRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1 text-sm">
      <span className="shrink-0 text-muted">{k}</span>
      <span className="min-w-0 break-words text-right font-medium text-ink">{v || "-"}</span>
    </div>
  );
}

// Human tag for a ScoreStep.source. Old rows lack source → no tag rendered.
const SCORE_SOURCE_LABEL: Record<string, string> = {
  ruleset: "configured",
  severity: "severity",
  metric_signal: "metric",
  cap: "cap",
};

// Renders spam-keyword evidence under an issue message. Tolerates BOTH the new
// object shape (evidence.matches: [{keyword,category,region,snippet}]) and the
// legacy shape (evidence.keywords: string[]).
function SpamEvidence({ evidence }: { evidence?: IssueEvidence | null }) {
  if (!evidence) return null;
  const rawMatches = Array.isArray(evidence.matches) ? evidence.matches : [];
  const legacy = Array.isArray(evidence.keywords)
    ? (evidence.keywords as unknown[]).filter((k): k is string => typeof k === "string")
    : [];
  // Normalize legacy string[] into the same {keyword} shape.
  const matches: SpamMatch[] = rawMatches.length
    ? rawMatches
    : legacy.map((k) => ({ keyword: k }));
  if (!matches.length) return null;
  // First non-empty snippet (new shape only) shown as a muted one-liner.
  const snippet = rawMatches.map((m) => m?.snippet).find((s) => typeof s === "string" && s.trim());
  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-1">
        {matches.map((m, i) => {
          const kw = m?.keyword || "match";
          return (
            <span
              key={`${kw}-${i}`}
              className="inline-flex items-center rounded border border-line bg-danger/5 px-1.5 py-0.5 text-[11px] text-ink"
            >
              <span className="font-medium">{kw}</span>
              {m?.category ? <span className="ml-1 text-muted">({m.category})</span> : null}
              {m?.region ? <span className="ml-1 text-muted">- {m.region}</span> : null}
            </span>
          );
        })}
      </div>
      {snippet ? (
        <div className="mt-1 truncate text-[11px] italic text-muted" title={snippet}>
          &ldquo;{snippet}&rdquo;
        </div>
      ) : null}
    </div>
  );
}

// What /imports/paste and /imports/file return since 0029: a review batch.
type StagedImportResult = {
  batch_id: string;
  seq: number;
  total: number;
  new: number;
  existing: number;
  duplicate: number;
  invalid: number;
  message: string;
  default_target?: string | null;
};

function ImportDesk({
  token,
  projectId,
  onNotice,
  onOpenBatch
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
  onOpenBatch: (batchId: string) => void;
}) {
  const queryClient = useQueryClient();
  // In project context the project is fixed; in the global desk the user picks one.
  const [localProject, setLocalProject] = useState("");
  const effectiveProject = projectId || localProject;
  const [text, setText] = useState(
    projectId
      ? `https://example-publisher.com/post-linking-to-you\nhttps://another-blog.net/article`
      : samplePaste
  );
  const [staged, setStaged] = useState<StagedImportResult | null>(null);
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const afterStage = (data: StagedImportResult) => {
    setStaged(data);
    onNotice(data.message);
    queryClient.invalidateQueries({ queryKey: ["batches"] });
  };
  const submit = useMutation({
    mutationFn: () =>
      api<StagedImportResult>("/imports/paste", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: effectiveProject, text })
      }),
    onSuccess: afterStage,
    onError: (err: Error) => onNotice(err.message)
  });
  const uploadFile = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("project_id", effectiveProject);
      fd.append("file", file);
      return api<StagedImportResult>("/imports/file", { token, method: "POST", body: fd });
    },
    onSuccess: afterStage,
    onError: (err: Error) => onNotice(err.message)
  });

  // This project's target — rows pasted without their own target default to it.
  const activeProj = (projectsQ.data || []).find((p) => p.id === effectiveProject);
  const defaultTarget = activeProj?.target_domain ? `https://${activeProj.target_domain}` : null;

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">Import Backlinks</h2>
        <p className="text-sm text-muted">
          Paste links or upload a CSV/XLSX. Everything lands in a <span className="font-semibold text-ink">review batch</span> first —
          QA-test the links in isolation and approve the ones you keep. Nothing touches this project until you approve.
        </p>
      </div>

      {!projectId ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel p-3 shadow-card">
          <span className="text-sm font-medium text-ink">Import into:</span>
          <SearchSelect
            value={localProject}
            onChange={setLocalProject}
            options={(projectsQ.data || []).map((p) => ({ value: p.id, label: p.name }))}
            placeholder="Choose a project…"
            width="w-64"
          />
          <span className="text-xs text-muted">Pick the project these links belong to before staging.</span>
        </div>
      ) : null}

      {staged ? (
        <div className="rounded-xl border border-ocean/40 bg-ocean/5 p-4 shadow-card">
          <p className="text-sm font-semibold text-ink">
            Review batch <span className="text-ocean">#B-{staged.seq}</span> created — {staged.total} links staged
          </p>
          <p className="mt-1 text-sm text-muted">
            {staged.new} new · {staged.existing} already in this project · {staged.duplicate} repeated in the paste
            {staged.invalid ? ` · ${staged.invalid} invalid` : ""}
          </p>
          {staged.default_target ? (
            <p className="mt-1 text-xs text-muted">Targets defaulted to {staged.default_target}</p>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => onOpenBatch(staged.batch_id)}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              <Play className="h-4 w-4" /> Open review batch
            </button>
            <button
              onClick={() => setStaged(null)}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field"
            >
              Import another list
            </button>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Paste links" />
          <div className="space-y-3 p-4">
            <textarea
              className="min-h-[260px] w-full rounded-md border border-line bg-panel p-3 font-mono text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-ocean/20"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => submit.mutate()}
                disabled={submit.isPending || !effectiveProject}
                className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
              >
                {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                Stage for review
              </button>
              <label className="flex h-10 cursor-pointer items-center gap-2 rounded-md border border-line px-4 text-sm font-medium text-ink transition hover:bg-field">
                {uploadFile.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
                Upload CSV / XLSX
                <input
                  type="file"
                  accept=".csv,.xlsx"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (!effectiveProject) {
                      onNotice("Choose a project first");
                      e.target.value = "";
                      return;
                    }
                    if (f) uploadFile.mutate(f);
                    e.target.value = "";
                  }}
                />
              </label>
              <span className="text-xs text-muted">
                First line = headers (auto-mapped). Existing links are flagged, never duplicated.
              </span>
            </div>
            {defaultTarget ? (
              <p className="text-xs text-muted">
                Target URL is optional here — rows without one default to{" "}
                <span className="font-medium text-ink">{defaultTarget}</span> (this project&apos;s target).
              </p>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

// Plain-words color guide for the planner (completion, excusals, priority).
function ColorLegend() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);
  const Row = ({ swatch, label }: { swatch: string; label: string }) => (
    <span className="flex items-center gap-2">
      <span className={clsx("h-3.5 w-6 shrink-0 rounded", swatch)} />
      <span className="text-ink">{label}</span>
    </span>
  );
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="h-8 rounded-full border border-line px-3 text-xs font-medium text-muted transition hover:bg-field hover:text-ink"
      >
        🎨 What do the colors mean?
      </button>
      {open ? (
        <div className="absolute right-0 top-full z-30 mt-1 w-72 space-y-1.5 rounded-lg border border-line bg-panel p-3 text-xs shadow-pop">
          <p className="font-semibold uppercase tracking-wide text-muted">Completion</p>
          <Row swatch="border border-ocean/50 bg-ocean/20" label="Green — target reached (100%+)" />
          <Row swatch="border border-ember/50 bg-ember/20" label="Amber — getting there (60–99%)" />
          <Row swatch="border border-danger/50 bg-danger/20" label="Red — behind (below 60%)" />
          <Row swatch="border border-line bg-field" label="Gray — excused (day off / leave), doesn't count" />
          <Row swatch="border border-plum/50 bg-plum/20" label="Purple — on approved leave" />
          <p className="pt-1 font-semibold uppercase tracking-wide text-muted">Priority dot</p>
          <span className="flex items-center gap-3">
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-danger" /> High</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-ember" /> Medium</span>
            <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-line" /> Low</span>
          </span>
          <p className="pt-1 text-muted">The thin bar inside each plan shows progress toward its target.</p>
        </div>
      ) : null}
    </div>
  );
}

// The standard-user home: their OWN tasks, targets, completion and leave —
// nothing team-wide, nothing admin.
// ── API Usage desk (Enterprise §3): where did our quota go? ──────────────────
const API_LABELS: Record<string, string> = {
  iproyal: "IPRoyal (crawl proxy)",
  render: "Render pool (headless browser)",
  serper: "serper.dev (index checks)",
  moz: "Moz DA/PA (RapidAPI)",
  semrush: "Semrush AS (RapidAPI)",
  rdap: "RDAP (domain age — free)",
  google_sheets: "Google Sheets reads",
  google_cse: "Google CSE (index fallback)"
};

function ApiUsageDesk({ token }: { token: string | null }) {
  type ApiRow = {
    api: string; daily_limit: number | null; hourly_limit: number | null;
    used_today: number; remaining_today: number | null; used_this_hour: number;
    ok_today: number; failed_today: number; success_rate: number | null;
    avg_response_ms: number | null; status: string;
    last_success_at: string | null; last_error: string | null; last_error_at: string | null;
  };
  const [selected, setSelected] = useState("iproyal");
  const [gran, setGran] = useState<"hour" | "day">("hour");
  const snap = useQuery({
    queryKey: ["api-usage", token],
    enabled: Boolean(token),
    refetchInterval: 30000,
    retry: false,
    queryFn: () => api<{ apis: ApiRow[] }>("/api-usage", { token })
  });
  const series = useQuery({
    queryKey: ["api-usage-series", token, selected, gran],
    enabled: Boolean(token && selected),
    retry: false,
    queryFn: () =>
      api<{ points: Array<{ bucket: string; ok: number; fail: number; avg_ms: number | null }> }>(
        `/api-usage/series?api=${selected}&granularity=${gran}&periods=${gran === "hour" ? 48 : 30}`,
        { token }
      )
  });
  const rows = snap.data?.apis || [];
  const points = series.data?.points || [];
  const [showLimits, setShowLimits] = useState(false);
  const [limitDrafts, setLimitDrafts] = useState<Record<string, { d: string; h: string }>>({});
  useEffect(() => {
    if (!snap.data) return;
    const next: Record<string, { d: string; h: string }> = {};
    for (const r of snap.data.apis) {
      next[r.api] = { d: r.daily_limit ? String(r.daily_limit) : "", h: r.hourly_limit ? String(r.hourly_limit) : "" };
    }
    setLimitDrafts(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap.data?.apis?.length]);
  const saveLimits = useMutation({
    mutationFn: () => {
      const daily: Record<string, number> = {};
      const hourly: Record<string, number> = {};
      for (const [apiName, v] of Object.entries(limitDrafts)) {
        if (Number(v.d) > 0) daily[apiName] = Number(v.d);
        if (Number(v.h) > 0) hourly[apiName] = Number(v.h);
      }
      return api<{ daily_limits: Record<string, number> }>("/api-usage/limits", {
        token, method: "PUT", body: JSON.stringify({ daily, hourly })
      });
    },
    onSuccess: () => {
      setShowLimits(false);
      snap.refetch();
    }
  });
  const statusMeta = (s: string) =>
    s === "limit_reached"
      ? { label: "Limit reached", cls: "bg-danger/10 text-danger border-danger/30" }
      : s === "erroring"
      ? { label: "Erroring", cls: "bg-ember/10 text-ember border-ember/30" }
      : s === "idle"
      ? { label: "Idle today", cls: "bg-field text-muted border-line" }
      : { label: "Healthy", cls: "bg-ocean/10 text-ocean border-ocean/30" };
  if (snap.isError) {
    return (
      <section className="rounded-xl border border-line bg-panel p-8 text-center shadow-card">
        <p className="text-sm text-muted">API usage is visible to managers and admins.</p>
      </section>
    );
  }
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
            API Usage
            <HelpTip text="Every external API the platform calls, with today's consumption, success rate and health. Set daily/hourly limits in the server settings (API_DAILY_LIMITS) — when a limit is reached, QA pauses gracefully ('Waiting for API') instead of burning failed requests." />
          </h2>
          <p className="text-sm text-muted">Live consumption across every connected service — refreshes every 30s.</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowLimits((v) => !v)}
            className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field"
            title="Set daily/hourly request limits per API — when a limit is reached, dependent QA pauses instead of burning failed requests (admins only)"
          >
            <Gauge className="h-4 w-4" />
            Configure limits
          </button>
          <ExportButton
            onClick={() =>
              downloadCsv(
                "api-usage.csv",
                ["API", "Used today", "Daily limit", "Remaining", "This hour", "OK", "Failed", "Success %", "Avg ms", "Status", "Last error"],
                rows.map((r) => [r.api, r.used_today, r.daily_limit, r.remaining_today, r.used_this_hour, r.ok_today, r.failed_today, r.success_rate, r.avg_response_ms, r.status, r.last_error])
              )
            }
          />
        </div>
      </div>

      {showLimits ? (
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <div className="border-b border-line p-3">
            <h3 className="text-sm font-semibold text-ink">Request limits</h3>
            <p className="text-xs text-muted">
              Set the maximum requests per API. Empty = unlimited (never throttled). When a limit is
              reached, work needing that API pauses gracefully as “Waiting for API” and resumes after
              the reset (daily limits reset at midnight UTC, hourly on the hour) — nothing fails, nothing retries blindly.
              Saving is admin-only and audited.
            </p>
          </div>
          <div className="grid gap-2 p-3 sm:grid-cols-2">
            {rows.map((r) => (
              <div key={`lim-${r.api}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-field/40 p-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{API_LABELS[r.api] || r.api}</span>
                <label className="flex items-center gap-1 text-xs text-muted">
                  Daily
                  <input
                    type="number" min={0} placeholder="∞"
                    value={limitDrafts[r.api]?.d ?? ""}
                    onChange={(e) => setLimitDrafts((x) => ({ ...x, [r.api]: { d: e.target.value, h: x[r.api]?.h ?? "" } }))}
                    className="h-8 w-24 rounded-md border border-line bg-panel px-2 text-right text-sm"
                  />
                </label>
                <label className="flex items-center gap-1 text-xs text-muted">
                  Hourly
                  <input
                    type="number" min={0} placeholder="∞"
                    value={limitDrafts[r.api]?.h ?? ""}
                    onChange={(e) => setLimitDrafts((x) => ({ ...x, [r.api]: { d: x[r.api]?.d ?? "", h: e.target.value } }))}
                    className="h-8 w-20 rounded-md border border-line bg-panel px-2 text-right text-sm"
                  />
                </label>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-line p-3">
            <span className="text-xs text-muted">
              Tip: set IPRoyal to your plan&apos;s daily request allowance and serper to ~2,400/day per active key.
            </span>
            <button
              onClick={() => saveLimits.mutate()}
              disabled={saveLimits.isPending}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-4 text-sm font-semibold text-white disabled:opacity-60 dark:text-slate-900"
            >
              {saveLimits.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Save limits
            </button>
          </div>
          {saveLimits.isError ? (
            <p className="border-t border-line p-3 text-sm text-danger">
              Couldn&apos;t save — limit configuration is restricted to workspace admins.
            </p>
          ) : null}
        </section>
      ) : null}

      {/* Threshold warnings (§8): informational at 80%, strong at 95%, hard stop
          explained at 100% — plain words, no bare codes. */}
      {rows
        .filter((r) => r.daily_limit && r.used_today / r.daily_limit >= 0.8)
        .map((r) => {
          const pct = Math.round((100 * r.used_today) / (r.daily_limit || 1));
          const hard = pct >= 100;
          const strong = pct >= 95;
          return (
            <div
              key={`warn-${r.api}`}
              className={clsx(
                "flex flex-wrap items-center gap-2 rounded-xl border p-3 text-sm",
                hard ? "border-danger/50 bg-danger/5" : strong ? "border-danger/40 bg-danger/5" : "border-ember/40 bg-ember/5"
              )}
            >
              <span className={clsx("rounded px-2 py-0.5 text-xs font-bold uppercase",
                hard ? "bg-danger text-white" : strong ? "bg-danger/10 text-danger" : "bg-ember/10 text-ember")}>
                {hard ? "Limit reached — paused" : strong ? "Critical" : "Warning"}
              </span>
              <span className="min-w-0 flex-1 text-ink">
                <span className="font-semibold">{API_LABELS[r.api] || r.api}</span> is at{" "}
                <span className="font-bold">{pct}%</span> of its daily limit ({r.used_today.toLocaleString()} of {r.daily_limit?.toLocaleString()}).
                {hard
                  ? " New scheduled work needing it is parked as “Waiting for API” — it resumes after the daily reset or a manual retry."
                  : " At 100%, dependent QA runs pause automatically instead of failing — plan remaining checks accordingly."}
              </span>
            </div>
          );
        })}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {rows.map((r) => {
          const meta = statusMeta(r.status);
          const pct = r.daily_limit ? Math.min(100, Math.round((100 * r.used_today) / r.daily_limit)) : null;
          return (
            <button
              key={r.api}
              onClick={() => setSelected(r.api)}
              className={clsx(
                "rounded-xl border p-3 text-left shadow-card transition",
                selected === r.api ? "border-ocean bg-ocean/5" : "border-line bg-panel hover:bg-field/50"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-ink">{API_LABELS[r.api] || r.api}</span>
                <span className={clsx("rounded border px-1.5 py-0.5 text-[10px] font-semibold", meta.cls)}>{meta.label}</span>
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-2xl font-bold text-ink">{r.used_today.toLocaleString()}</span>
                <span className="text-xs text-muted">
                  {r.daily_limit ? `of ${r.daily_limit.toLocaleString()} today` : "requests today"}
                </span>
              </div>
              {pct != null ? (
                <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-field">
                  <div
                    className={clsx("h-full rounded", pct >= 90 ? "bg-danger" : pct >= 70 ? "bg-ember" : "bg-ocean")}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted">
                <span>{r.used_this_hour} this hour</span>
                {r.success_rate != null ? <span>{r.success_rate}% success</span> : null}
                {r.avg_response_ms != null ? <span>~{r.avg_response_ms}ms</span> : null}
              </div>
              {r.last_error ? (
                <p className="mt-1 truncate text-[11px] text-danger" title={`${r.last_error} (${formatDate(r.last_error_at)})`}>
                  Last error: {r.last_error}
                </p>
              ) : null}
            </button>
          );
        })}
        {snap.isLoading ? (
          <div className="col-span-full flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
        ) : null}
      </div>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">
            {API_LABELS[selected] || selected} — {gran === "hour" ? "last 48 hours" : "last 30 days"}
          </h3>
          <div className="inline-flex overflow-hidden rounded-lg border border-line" role="group">
            {(["hour", "day"] as const).map((g) => (
              <button
                key={g}
                onClick={() => setGran(g)}
                className={clsx(
                  "h-8 px-2.5 text-xs font-medium capitalize",
                  gran === g ? "bg-ocean text-white dark:text-slate-900" : "bg-panel text-muted hover:bg-field"
                )}
              >
                {g === "hour" ? "Hourly" : "Daily"}
              </button>
            ))}
          </div>
        </div>
        <div className="p-4">
          {points.length && points.some((p) => p.ok || p.fail) ? (
            <TrendChart
              labels={points.map((p) => p.bucket)}
              series={[
                { name: "Successful", cssVar: "--ocean", values: points.map((p) => p.ok) },
                { name: "Failed", cssVar: "--danger", values: points.map((p) => p.fail) }
              ]}
            />
          ) : (
            <Empty label="No usage recorded in this window yet." />
          )}
        </div>
      </section>
    </section>
  );
}

// ── User "Opportunities" desk (Enterprise): a CURATED, limited list ──────────
// General opportunity domains for the person — deliberately capped at 15 so it
// reads as a shortlist, not a database dump. Task-specific suggestions live on
// each task; this is the browse-anytime view.
function MyOpportunitiesDesk({ token }: { token: string | null }) {
  const list = useQuery({
    queryKey: ["my-opportunities", token],
    enabled: Boolean(token),
    retry: false,
    queryFn: () =>
      api<{ items: SourceDomain[]; total: number }>("/source-domains?opportunity=true&limit=60", { token })
  });
  const rows = useMemo(() => {
    const items = (list.data?.items || []).map((d) => ({ ...d, opp: opportunityScore(d) }));
    items.sort((a, b) => b.opp - a.opp);
    return items.slice(0, 15); // curated shortlist — quality over quantity
  }, [list.data]);
  const why = (d: SourceDomain & { opp: number }) => {
    const bits: string[] = [];
    if ((d.da ?? 0) >= 30) bits.push(`Strong authority (DA ${d.da})`);
    if (d.backlink_count > 0 && d.qualified_pct >= 60) bits.push(`${Math.round(d.qualified_pct)}% of its links qualified before`);
    if (d.backlink_count === 0) bits.push("Fresh domain — never used yet");
    if ((d.spam_score ?? 10) < 5) bits.push("Very low spam risk");
    if ((d.robots_band || "") === "allowed") bits.push("Open to crawlers");
    bits.push("Available — nobody is working on it");
    return bits;
  };
  return (
    <section className="space-y-4">
      <div>
        <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
          Opportunity domains
          <HelpTip text="A curated shortlist of the BEST available websites right now — high quality, low risk, not assigned to anyone. Use them for your link-building work; your task cards also suggest domains matched to each specific task." />
        </h2>
        <p className="text-sm text-muted">The 15 best available websites, ranked — refreshed as domains get used or assigned.</p>
      </div>
      {list.isLoading ? (
        <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
      ) : !rows.length ? (
        <section className="rounded-xl border border-line bg-panel p-8 text-center shadow-card">
          <Globe className="mx-auto mb-3 h-8 w-8 text-muted" />
          <h3 className="text-base font-semibold text-ink">No opportunities right now</h3>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            Every suitable domain is either in use or assigned. Check back later, or ask your
            manager to import more source domains.
          </p>
        </section>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((d, i) => (
            <div key={d.id} className={clsx(
              "rounded-xl border p-4 shadow-card",
              i === 0 ? "border-ocean/50 bg-ocean/5" : "border-line bg-panel"
            )}>
              <div className="flex items-start justify-between gap-2">
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-semibold text-ink">{d.domain_key}</span>
                    <CopyButton text={d.domain_key} title="Copy domain" />
                  </span>
                  {i === 0 ? <span className="mt-0.5 inline-block rounded bg-ocean px-1.5 py-0.5 text-[10px] font-bold uppercase text-white dark:text-slate-900">Best available</span> : null}
                </span>
                <span className={clsx(
                  "shrink-0 rounded-lg px-2 py-1 text-sm font-bold",
                  d.opp >= 70 ? "bg-ocean/10 text-ocean" : d.opp >= 45 ? "bg-ember/10 text-ember" : "bg-field text-muted"
                )}>
                  {d.opp}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <MetricTag label="DA" value={d.da} />
                <MetricTag label="PA" value={d.pa} />
                <SpamTag value={d.spam_score} />
                <span className={clsx(
                  "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                  (d.robots_band || "unknown") === "allowed" ? "bg-ocean/10 text-ocean" : "bg-field text-muted"
                )}>
                  robots: {(d.robots_band || "unknown").replaceAll("_", " ")}
                </span>
              </div>
              <ul className="mt-2 space-y-0.5 text-xs text-muted">
                {why(d).slice(0, 3).map((w, wi) => <li key={wi}>• {w}</li>)}
              </ul>
              <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
                <span>{d.backlink_count} links · {d.project_count} project{d.project_count === 1 ? "" : "s"}</span>
                <span>{d.metrics_updated_at ? `checked ${formatDay(d.metrics_updated_at)}` : "not checked yet"}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ── User "Guidance" desk (Enterprise §13): next steps + status + scoring ─────
// Mounted three ways from the sidebar (Guidance / Scoring / Status Guide) — the
// owner wants them as SEPARATE sections, so `fixed` locks one view per tab.
function GuidanceDesk({ token, fixed }: { token: string | null; fixed?: "next" | "statuses" | "scoring" }) {
  const [gTabState, setGTab] = useState<"next" | "statuses" | "scoring">(fixed || "next");
  const gTab = fixed || gTabState;
  const me = useQuery({
    queryKey: ["my-labels", token],
    enabled: Boolean(token),
    queryFn: async () => {
      const today = new Date().toISOString().slice(0, 10);
      return api<{ labels: string[] }>(`/workforce/me?date_from=${today}&date_to=${today}`, { token });
    }
  });
  const label = me.data?.labels?.[0] || "";
  const dash = useQuery({
    queryKey: ["guidance-stats", token, label],
    enabled: Boolean(token && label),
    retry: false,
    queryFn: () =>
      api<{ links: Record<string, number | null>; plan: Record<string, number | null> }>(
        `/performance/user-dashboard?user_label=${encodeURIComponent(label)}&days=30`,
        { token }
      )
  });
  const k = dash.data?.links || {};
  const n = (key: string) => Number(k[key] ?? 0);
  // Personal, prioritized next steps derived from the person's own 30-day stats.
  const tips: Array<{ title: string; body: string; tone: string }> = [];
  if (n("fail") > 0)
    tips.push({
      tone: "danger",
      title: `Fix your ${n("fail")} not-qualified link${n("fail") === 1 ? "" : "s"} first`,
      body: "Open My Work → recent links, click a red one, and read “Why this score” — it lists exactly what went wrong and how to fix it. A missing or dead link caps its score at 25 until repaired."
    });
  if (n("qa_pending") > 0)
    tips.push({
      tone: "ember",
      title: `${n("qa_pending")} link${n("qa_pending") === 1 ? " is" : "s are"} still waiting for QA`,
      body: "Links don't check themselves — ask your manager to run a QA check so your completed work counts toward your numbers."
    });
  if (n("nofollow") > n("dofollow") && n("links") > 5)
    tips.push({
      tone: "ember",
      title: "Most of your links are nofollow",
      body: "Nofollow links pass less value. Where dofollow was agreed with the publisher, ask them to remove rel=\"nofollow\" — each fix adds points back."
    });
  if (n("links") > 0 && n("indexed") / Math.max(1, n("links")) < 0.3)
    tips.push({
      tone: "ember",
      title: "Few of your pages are indexed by Google",
      body: "Unindexed pages carry little SEO value. Share them, add internal links where possible, then run “Check indexing”."
    });
  tips.push({
    tone: "ocean",
    title: "Pick better domains up front",
    body: "The Opportunities tab ranks the best available websites (authority, low spam, open to crawlers). Starting from a strong domain is the easiest score boost there is."
  });
  const toneCls = (t: string) =>
    t === "danger" ? "border-danger/40 bg-danger/5" : t === "ember" ? "border-ember/40 bg-ember/5" : "border-ocean/40 bg-ocean/5";
  const statusKeys = ["PENDING", "PASS", "WARNING", "FAIL", "NEEDS_MANUAL_REVIEW", "UNKNOWN", "waiting_api", "api_failed", "indexed", "not_indexed", "uncertain", "unchecked", "duplicate", "unique"];
  const titles = {
    next: ["Guidance", "Personalized next steps — computed from your own last-30-day numbers."],
    statuses: ["Status Guide", "Every status in plain words: what it means, why it happens, what to do."],
    scoring: ["Scoring", "Your personal scores, what moves them, and how link scoring works."]
  } as const;
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">{titles[gTab][0]}</h2>
        <p className="text-sm text-muted">{titles[gTab][1]}</p>
      </div>
      {!fixed ? (
        <span className="flex w-fit overflow-hidden rounded-lg border border-line text-xs font-medium">
          {([["next", "What to do next"], ["statuses", "Status guide"], ["scoring", "Scoring guide"]] as const).map(([v, l]) => (
            <button
              key={v}
              onClick={() => setGTab(v)}
              className={clsx("px-3 py-1.5 transition", gTab === v ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
            >
              {l}
            </button>
          ))}
        </span>
      ) : null}
      {gTab === "next" ? (
        <div className="space-y-3">
          {tips.map((t, i) => (
            <div key={i} className={clsx("rounded-xl border p-4", toneCls(t.tone))}>
              <h3 className="text-sm font-semibold text-ink">{i + 1}. {t.title}</h3>
              <p className="mt-1 text-sm text-muted">{t.body}</p>
            </div>
          ))}
        </div>
      ) : gTab === "statuses" ? (
        <div className="grid gap-3 md:grid-cols-2">
          {statusKeys.map((key) => {
            const h = STATUS_HELP[key];
            if (!h) return null;
            return (
              <div key={key} className="rounded-xl border border-line bg-panel p-4 shadow-card">
                <div className="flex items-center gap-2">
                  {key === "waiting_api" || key === "api_failed" ? (
                    <QaWaitBadge reason={key} />
                  ) : (
                    <Status value={key} />
                  )}
                </div>
                <p className="mt-2 text-sm text-muted">{h.what}</p>
                <p className="mt-1 text-sm"><span className="font-semibold text-ink">What to do:</span> <span className="text-muted">{h.next}</span></p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="space-y-4">
          {/* Personal scores (§5): the user's own numbers with the factors named. */}
          {(() => {
            const links = n("links");
            if (!links) return null;
            const quality = Math.round((n("pass") / links) * 100);
            const reliability = Math.round(100 - (n("fail") / links) * 100);
            const checked = links - n("qa_pending");
            const qaScore = checked > 0 ? Math.round((n("pass") / checked) * 100) : null;
            const plan = (dash.data?.plan || {}) as Record<string, number | null>;
            const production = plan.completion_pct != null ? Math.round(Number(plan.completion_pct)) : null;
            const parts = [quality, reliability, qaScore, production].filter((v): v is number => v != null);
            const overall = parts.length ? Math.round(parts.reduce((a, b) => a + b, 0) / parts.length) : null;
            const dial = (label: string, v: number | null, why: string) => (
              <div className="rounded-xl border border-line bg-panel p-4 shadow-card">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
                <div className={clsx("mt-1 text-3xl font-bold",
                  v == null ? "text-muted" : v >= 80 ? "text-ocean" : v >= 50 ? "text-ember" : "text-danger")}>
                  {v ?? "—"}{v != null ? <span className="text-base font-semibold text-muted">/100</span> : null}
                </div>
                <p className="mt-1 text-xs leading-snug text-muted">{why}</p>
              </div>
            );
            return (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                {dial("Overall", overall, "The average of your scores below — your one-number summary (last 30 days).")}
                {dial("Quality", quality, `${n("pass")} of your ${links} links fully qualified. Raise it by fixing red links first.`)}
                {dial("Reliability", reliability, `${n("fail")} link${n("fail") === 1 ? "" : "s"} not qualified. Fewer failures = higher reliability.`)}
                {dial("QA pass rate", qaScore, checked > 0 ? `Of your ${checked} checked links, ${n("pass")} passed QA.` : "No checked links yet — runs after your first QA.")}
                {dial("Production", production, production != null ? "Completed links vs your planned target this period." : "Appears once you have planned targets in the calendar.")}
              </div>
            );
          })()}
          <div className="rounded-xl border border-line bg-panel p-5 shadow-card">
            <h3 className="mb-3 text-sm font-bold text-ink">How link scoring works</h3>
            <ScoringGuideContent />
          </div>
        </div>
      )}
    </section>
  );
}

// ── My task calendar (Phase 10 P6) ──────────────────────────────────────────
// The signed-in person's assigned work on a real calendar: month / week / day
// views with free prev/next navigation (covers "one month back, current, one
// ahead" and beyond). Read-only — statuses derive client-side so FUTURE tasks
// read as "upcoming", never "behind". Click a task → full details.
type MyCalRow = {
  id: string; day: string; project_id: string; hours: number;
  link_type_names: string[]; expected_links: number; actual_links: number;
  completion_pct: number | null; excused: boolean; excuse_reason: string | null;
  priority: string | null; note: string | null;
};

function myCalStatus(r: MyCalRow, today: string): { key: string; label: string; cls: string } {
  if (r.excused) return { key: "excused", label: r.excuse_reason || "Excused", cls: "border-line bg-field text-muted" };
  if ((r.completion_pct ?? 0) >= 100) return { key: "done", label: "Done", cls: "border-ocean/40 bg-ocean/10 text-ocean" };
  if (r.day > today) return { key: "upcoming", label: "Upcoming", cls: "border-line bg-panel text-ink" };
  if (r.day === today) return { key: "today", label: "In progress", cls: "border-ember/40 bg-ember/10 text-ember" };
  return { key: "missed", label: "Behind", cls: "border-danger/40 bg-danger/10 text-danger" };
}

function MyTaskCalendar({ token }: { token: string | null }) {
  const fmtIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const today = fmtIso(new Date());
  const [mode, setMode] = useState<"month" | "week" | "day">("month");
  const [anchor, setAnchor] = useState(() => new Date());
  const [openTask, setOpenTask] = useState<MyCalRow | null>(null);

  // Visible window per mode (month view fetches the whole month; ≤ 31 days/call).
  const range = useMemo(() => {
    const a = new Date(anchor);
    if (mode === "month") {
      const from = new Date(a.getFullYear(), a.getMonth(), 1);
      const to = new Date(a.getFullYear(), a.getMonth() + 1, 0);
      return { from: fmtIso(from), to: fmtIso(to) };
    }
    if (mode === "week") {
      const mon = new Date(a);
      mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
      const sun = new Date(mon);
      sun.setDate(sun.getDate() + 6);
      return { from: fmtIso(mon), to: fmtIso(sun) };
    }
    return { from: fmtIso(a), to: fmtIso(a) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor, mode]);

  const me = useQuery({
    queryKey: ["my-cal", token, range.from, range.to],
    enabled: Boolean(token),
    queryFn: () =>
      api<{ labels: string[]; rows: MyCalRow[]; leaves: Array<{ start_date: string; end_date: string; status: string }> }>(
        `/workforce/me?date_from=${range.from}&date_to=${range.to}`,
        { token }
      )
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const projectName = (id: string) => (projectsQ.data || []).find((p) => p.id === id)?.name || "—";
  const rows = me.data?.rows || [];
  const byDay = useMemo(() => {
    const m: Record<string, MyCalRow[]> = {};
    for (const r of rows) (m[r.day] ||= []).push(r);
    return m;
  }, [rows]);
  const onLeave = (day: string) =>
    (me.data?.leaves || []).some((l) => l.status === "approved" && l.start_date <= day && day <= l.end_date);

  const step = (dir: number) => {
    const a = new Date(anchor);
    if (mode === "month") a.setMonth(a.getMonth() + dir);
    else a.setDate(a.getDate() + dir * (mode === "week" ? 7 : 1));
    setAnchor(a);
  };
  const title =
    mode === "month"
      ? anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" })
      : mode === "week"
      ? `Week of ${formatDay(range.from)}`
      : formatDay(range.from);

  // Month grid: Monday-first with leading offset padding.
  const monthCells = useMemo(() => {
    if (mode !== "month") return [];
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const daysIn = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0).getDate();
    const offset = (first.getDay() + 6) % 7;
    const cells: Array<string | null> = Array(offset).fill(null);
    for (let d = 1; d <= daysIn; d++)
      cells.push(fmtIso(new Date(anchor.getFullYear(), anchor.getMonth(), d)));
    return cells;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor, mode]);

  const chip = (r: MyCalRow, full = false) => {
    const st = myCalStatus(r, today);
    return (
      <button
        key={r.id}
        onClick={() => setOpenTask(r)}
        title={`${projectName(r.project_id)} — ${st.label}. Click for details.`}
        className={clsx(
          "block w-full truncate rounded border px-1 py-0.5 text-left font-medium leading-tight",
          full ? "text-xs" : "text-[9px]",
          st.cls
        )}
      >
        {r.priority === "high" ? "⬤ " : ""}
        {projectName(r.project_id)}
        {full ? ` · ${r.link_type_names.map(linkTypeLabel).join(", ") || "any type"} · ${r.actual_links}/${r.expected_links}` : ""}
      </button>
    );
  };

  const weekDays = useMemo(() => {
    if (mode !== "week") return [];
    const out: string[] = [];
    const d = new Date(`${range.from}T00:00:00`);
    for (let i = 0; i < 7; i++) {
      out.push(fmtIso(d));
      d.setDate(d.getDate() + 1);
    }
    return out;
  }, [mode, range.from]);

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">My calendar</h3>
          <HelpTip text="All your assigned work — past, current and upcoming. Colors: green = done, orange = today, red = behind (past target not reached), plain = upcoming, grey = excused/leave. Click any task for full details." />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex overflow-hidden rounded-lg border border-line" role="group">
            {(["day", "week", "month"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={clsx(
                  "h-8 px-2.5 text-xs font-medium capitalize transition-colors",
                  mode === m ? "bg-ocean text-white dark:text-slate-900" : "bg-panel text-muted hover:bg-field"
                )}
              >
                {m}
              </button>
            ))}
          </div>
          <button onClick={() => step(-1)} className="h-8 rounded-lg border border-line px-2 text-sm hover:bg-field">‹</button>
          <span className="min-w-[130px] text-center text-sm font-semibold text-ink">{title}</span>
          <button onClick={() => step(1)} className="h-8 rounded-lg border border-line px-2 text-sm hover:bg-field">›</button>
          <button onClick={() => setAnchor(new Date())} className="h-8 rounded-lg border border-line px-2.5 text-xs font-medium hover:bg-field">
            Today
          </button>
        </div>
      </div>
      <div className="p-3">
        {me.isLoading ? (
          <div className="flex justify-center p-6"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
        ) : mode === "month" ? (
          <>
            <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-semibold uppercase text-muted">
              {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                <span key={d}>{d}</span>
              ))}
            </div>
            <div className="mt-1 grid grid-cols-7 gap-1">
              {monthCells.map((day, i) =>
                day === null ? (
                  <div key={`pad-${i}`} />
                ) : (
                  <div
                    key={day}
                    className={clsx(
                      "min-h-[64px] rounded-lg border p-1",
                      day === today ? "border-ocean bg-ocean/5" : "border-line bg-panel"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <span className={clsx("text-[10px] font-semibold", day === today ? "text-ocean" : "text-muted")}>
                        {Number(day.slice(8))}
                      </span>
                      {onLeave(day) ? (
                        <span className="rounded bg-plum/15 px-1 text-[8px] font-semibold text-plum">Leave</span>
                      ) : null}
                    </div>
                    <div className="mt-0.5 space-y-0.5">
                      {(byDay[day] || []).slice(0, 3).map((r) => chip(r))}
                      {(byDay[day] || []).length > 3 ? (
                        <button
                          onClick={() => { setMode("day"); setAnchor(new Date(`${day}T00:00:00`)); }}
                          className="block w-full rounded px-1 text-left text-[9px] text-muted hover:text-ink"
                        >
                          +{(byDay[day] || []).length - 3} more
                        </button>
                      ) : null}
                    </div>
                  </div>
                )
              )}
            </div>
          </>
        ) : mode === "week" ? (
          <div className="grid gap-1 sm:grid-cols-7">
            {weekDays.map((day) => (
              <div key={day} className={clsx("min-h-[90px] rounded-lg border p-1.5", day === today ? "border-ocean bg-ocean/5" : "border-line bg-panel")}>
                <div className="flex items-center justify-between">
                  <span className={clsx("text-[10px] font-semibold", day === today ? "text-ocean" : "text-muted")}>{formatDay(day)}</span>
                  {onLeave(day) ? <span className="rounded bg-plum/15 px-1 text-[8px] font-semibold text-plum">Leave</span> : null}
                </div>
                <div className="mt-1 space-y-1">{(byDay[day] || []).map((r) => chip(r))}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-2">
            {(byDay[range.from] || []).map((r) => chip(r, true))}
            {!(byDay[range.from] || []).length ? <Empty label="Nothing planned on this day." /> : null}
          </div>
        )}
        {!me.isLoading && mode !== "day" && !rows.length ? (
          <p className="mt-2 text-center text-sm text-muted">No tasks in this {mode}.</p>
        ) : null}
      </div>
      {openTask ? (
        <div className="border-t border-line bg-field/40 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-ink">{projectName(openTask.project_id)}</span>
            <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
              openTask.priority === "high" ? "bg-danger/10 text-danger" : openTask.priority === "low" ? "bg-field text-muted" : "bg-ember/10 text-ember")}>
              {openTask.priority || "medium"} priority
            </span>
            <span className={clsx("rounded px-1.5 py-0.5 text-[10px] font-semibold", myCalStatus(openTask, today).cls)}>
              {myCalStatus(openTask, today).label}
            </span>
            <button onClick={() => setOpenTask(null)} className="ml-auto text-xs text-muted hover:text-ink">Close ×</button>
          </div>
          <div className="mt-1.5 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <span className="text-muted">Date <span className="float-right text-ink">{formatDay(openTask.day)}</span></span>
            <span className="text-muted">Hours <span className="float-right text-ink">{openTask.hours}h</span></span>
            <span className="text-muted">Link types <span className="float-right text-ink">{openTask.link_type_names.map(linkTypeLabel).join(", ") || "Any"}</span></span>
            <span className="text-muted">Target <span className="float-right text-ink">{openTask.actual_links} / {openTask.expected_links} links{openTask.completion_pct != null ? ` (${openTask.completion_pct}%)` : ""}</span></span>
          </div>
          {openTask.note ? <p className="mt-1 text-xs text-muted">📝 {openTask.note}</p> : null}
          {openTask.excused ? <p className="mt-1 text-xs text-muted">Excused: {openTask.excuse_reason}</p> : null}
          <TaskDomainSuggestions token={token} assignmentId={openTask.id} projectId={openTask.project_id} />
        </div>
      ) : null}
    </section>
  );
}

// Recommended source domains for ONE task (Phase 10 P4): filtered to the task's
// project + link types, quality-ranked, robots-blocked/used/spammy excluded.
// Copy the domain, or Accept/Skip — skips never come back.
function TaskDomainSuggestions({
  token,
  assignmentId,
  projectId
}: {
  token: string | null;
  assignmentId: string;
  projectId: string;
}) {
  const queryClient = useQueryClient();
  type Suggestion = {
    domain_key: string; da: number | null; pa: number | null; spam_score: number | null;
    semrush_as: number | null; robots_band: string | null; qualified_pct: number | null;
    link_type_match: boolean; reasons: string[];
  };
  const sugg = useQuery({
    queryKey: ["task-domain-suggestions", token, assignmentId],
    enabled: Boolean(token && assignmentId),
    retry: false,
    queryFn: () =>
      api<{ items: Suggestion[]; link_types: string[] }>(
        `/workforce/assignments/${assignmentId}/domain-suggestions?limit=8`,
        { token }
      )
  });
  const act = useMutation({
    mutationFn: (v: { domain_key: string; status: "accepted" | "skipped" }) =>
      api("/source-domains/recommendations/action", {
        token,
        method: "POST",
        body: JSON.stringify({
          domain_key: v.domain_key, status: v.status,
          project_id: projectId, assignment_id: assignmentId
        })
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["task-domain-suggestions"] })
  });
  if (sugg.isError) return null;
  const items = sugg.data?.items || [];
  return (
    <div className="mt-3 border-t border-line pt-2">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        Suggested domains for this task
        <HelpTip text="Source domains matching this task's link type and project, ranked by quality (DA, qualified %, low spam). Domains that block links (robots.txt), are spammy, or were already used in this project are excluded. Accept = you'll use it; Skip = don't show it again." />
      </div>
      {sugg.isLoading ? (
        <div className="flex justify-center p-2"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : !items.length ? (
        <p className="text-xs text-muted">No suitable unused domains right now — ask your manager for a manual recommendation.</p>
      ) : (
        <div className="space-y-1">
          {items.map((s, i) => (
            <div key={s.domain_key} className={clsx(
              "rounded-lg border px-2 py-1.5",
              i === 0 ? "border-ocean/40 bg-ocean/5" : "border-line bg-panel"
            )}>
              <div className="flex flex-wrap items-center gap-2">
                {i < 3 ? (
                  <span className={clsx(
                    "rounded px-1.5 py-0.5 text-[10px] font-bold uppercase",
                    i === 0 ? "bg-ocean text-white dark:text-slate-900" : "bg-ocean/10 text-ocean"
                  )}>
                    {i === 0 ? "Top pick" : `#${i + 1}`}
                  </span>
                ) : null}
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">
                  {s.domain_key}
                </span>
                {s.da != null ? <MetricTag label="DA" value={s.da} /> : null}
                {s.pa != null ? <MetricTag label="PA" value={s.pa} /> : null}
                {s.spam_score != null ? <SpamTag value={s.spam_score} /> : null}
                {s.link_type_match ? (
                  <span className="rounded bg-ocean/10 px-1.5 py-0.5 text-[10px] font-semibold text-ocean">type match</span>
                ) : null}
                <CopyButton text={s.domain_key} title="Copy domain" />
                <button
                  onClick={() => act.mutate({ domain_key: s.domain_key, status: "accepted" })}
                  className="rounded border border-ocean/40 px-1.5 py-0.5 text-[11px] font-medium text-ocean hover:bg-ocean/10"
                >
                  Accept
                </button>
                <button
                  onClick={() => act.mutate({ domain_key: s.domain_key, status: "skipped" })}
                  className="rounded border border-line px-1.5 py-0.5 text-[11px] font-medium text-muted hover:bg-field"
                >
                  Skip
                </button>
              </div>
              {/* WHY this domain — the recommendation explains itself. */}
              <p className="mt-0.5 text-[11px] leading-snug text-muted">{s.reasons.join(" · ")}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Viewer "My Dashboard": the admin person-dashboard scoped to the signed-in
// person (backend self-scopes via visible_labels; UI hides admin mutations).
function MySelfDashboard({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const [label, setLabel] = useState("");
  const me = useQuery({
    queryKey: ["my-labels", token],
    enabled: Boolean(token),
    queryFn: async () => {
      const today = new Date().toISOString().slice(0, 10);
      return api<{ labels: string[] }>(`/workforce/me?date_from=${today}&date_to=${today}`, { token });
    }
  });
  const labels = me.data?.labels || [];
  const active = label || labels[0] || "";
  if (me.isLoading) {
    return <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>;
  }
  if (!labels.length) {
    return (
      <section className="rounded-xl border border-line bg-panel p-8 text-center shadow-card">
        <Gauge className="mx-auto mb-3 h-8 w-8 text-muted" />
        <h2 className="text-base font-semibold text-ink">No dashboard yet</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted">
          Your account isn&apos;t linked to a team member name, so there are no stats to show.
          Ask your admin to link you on the Employees desk.
        </p>
      </section>
    );
  }
  return (
    <div className="space-y-3">
      {labels.length > 1 ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted">Working as:</span>
          {labels.map((l) => (
            <button
              key={l}
              onClick={() => setLabel(l)}
              className={clsx(
                "rounded-full border px-3 py-1 text-xs font-medium",
                l === active ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
              )}
            >
              {l}
            </button>
          ))}
        </div>
      ) : null}
      <UserDashboard
        token={token}
        userLabel={active}
        selfView
        onClose={() => undefined}
        onOpenBacklinks={() => onNotice("Ask a manager to open the full Backlinks list for you.")}
        onNotice={onNotice}
      />
    </div>
  );
}

// The person's own QA picture (Enterprise: data-rich user dashboard): links built,
// quality split, average score — self-scoped via the same endpoint admins use.
function MyQaSummary({ token, userLabel }: { token: string | null; userLabel: string }) {
  const dash = useQuery({
    queryKey: ["my-qa-summary", token, userLabel],
    enabled: Boolean(token && userLabel),
    retry: false,
    queryFn: () =>
      api<{ links: Record<string, number | null> }>(
        `/performance/user-dashboard?user_label=${encodeURIComponent(userLabel)}&days=3650`,
        { token }
      )
  });
  const k = dash.data?.links || {};
  const n = (key: string) => Number(k[key] ?? 0);
  const total = n("total") || n("links") || 0;
  if (dash.isError || (!dash.isLoading && !total)) return null;
  const pct = (v: number) => (total ? Math.round((100 * v) / total) : 0);
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center gap-1.5 border-b border-line p-3">
        <h3 className="text-sm font-semibold text-ink">My links &amp; quality</h3>
        <HelpTip text="Everything you've built, all time: how many links, how they split across QA outcomes, and your average quality score. Click a card in My Dashboard for the full breakdown." />
      </div>
      <div className="grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-lg border border-line bg-field/40 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Links built</div>
          <div className="text-xl font-bold text-ink">{total.toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-ocean/30 bg-ocean/5 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Qualified</div>
          <div className="text-xl font-bold text-ocean">{n("pass").toLocaleString()}</div>
          <div className="text-[10px] text-muted">{pct(n("pass"))}% of your links</div>
        </div>
        <div className="rounded-lg border border-ember/30 bg-ember/5 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Needs improvement</div>
          <div className="text-xl font-bold text-ember">{n("warning").toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-danger/30 bg-danger/5 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Not qualified</div>
          <div className="text-xl font-bold text-danger">{n("fail").toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-line bg-field/40 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Indexed</div>
          <div className="text-xl font-bold text-ink">{n("indexed").toLocaleString()}</div>
          <div className="text-[10px] text-muted">{pct(n("indexed"))}% indexed</div>
        </div>
        <div className="rounded-lg border border-line bg-field/40 p-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-muted">Avg score</div>
          <div className="text-xl font-bold text-ink">{k["avg_score"] ?? "—"}</div>
        </div>
      </div>
    </section>
  );
}

// The person's own performance, visual (Enterprise: LARGE data-rich dashboard):
// 90-day activity/quality trend + per-project and per-link-type breakdowns —
// the same analytics an admin sees, self-scoped.
function MyPerformancePanel({ token, userLabel }: { token: string | null; userLabel: string }) {
  type Payload = {
    weekly: Array<{ week: string; links: number; indexed: number; pass: number; fail: number; new_domains?: number }>;
    by_type: Array<{ link_type: string; links: number; pass: number; indexed: number }>;
    projects: Array<{ project_id: string; links: number; indexed: number; fail: number; hours: number; target: number }>;
  };
  const dash = useQuery({
    queryKey: ["my-performance", token, userLabel],
    enabled: Boolean(token && userLabel),
    retry: false,
    queryFn: () =>
      api<Payload>(
        `/performance/user-dashboard?user_label=${encodeURIComponent(userLabel)}&days=90&granularity=week`,
        { token }
      )
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const projectName = (id: string) => (projectsQ.data || []).find((p) => p.id === id)?.name || "—";
  const d = dash.data;
  const weekly = (d?.weekly || []).filter((w) => w.links > 0 || w.pass > 0);
  const types = (d?.by_type || []).slice(0, 6);
  const projects = (d?.projects || []).filter((p) => p.links > 0).slice(0, 6);
  const maxType = Math.max(1, ...types.map((t) => t.links));
  if (dash.isError || (!dash.isLoading && !weekly.length && !projects.length)) return null;
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center gap-1.5 border-b border-line p-3">
        <h3 className="text-sm font-semibold text-ink">My performance — last 90 days</h3>
        <HelpTip text="Your weekly output and quality, plus how your work splits across projects and link types. The full filterable version (any date range, comparisons, exports) lives in My Dashboard." />
      </div>
      {dash.isLoading ? (
        <div className="flex justify-center p-6"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : (
        <div className="grid gap-4 p-4 xl:grid-cols-[1.3fr_1fr]">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
              Links built &amp; qualified per week
            </div>
            {weekly.length >= 2 ? (
              <TrendChart
                labels={weekly.map((w) => w.week)}
                labelFmt={weekRangeLabel}
                series={[
                  { name: "Links built", cssVar: "--ocean", values: weekly.map((w) => w.links) },
                  { name: "Qualified", cssVar: "--plum", values: weekly.map((w) => w.pass) }
                ]}
              />
            ) : (
              <Empty label="Your trend appears after two weeks of activity." />
            )}
          </div>
          <div className="space-y-4">
            {projects.length ? (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">By project</div>
                <div className="space-y-1">
                  {projects.map((p) => (
                    <div key={p.project_id} className="flex items-center justify-between gap-2 rounded-lg border border-line bg-field/40 px-2.5 py-1.5 text-sm">
                      <span className="min-w-0 truncate font-medium text-ink">{projectName(p.project_id)}</span>
                      <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                        <span><span className="font-bold text-ink">{p.links}</span> links</span>
                        <span className="text-ocean">{p.links ? Math.round((100 * p.indexed) / p.links) : 0}% indexed</span>
                        {p.fail ? <span className="text-danger">{p.fail} failed</span> : null}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {types.length ? (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">By link type</div>
                <div className="space-y-1.5">
                  {types.map((t) => (
                    <div key={t.link_type} className="text-xs">
                      <div className="flex items-center justify-between">
                        <span className="min-w-0 truncate font-medium text-ink">{linkTypeLabel(t.link_type) || "(none)"}</span>
                        <span className="shrink-0 text-muted">{t.links} · {t.links ? Math.round((100 * t.pass) / t.links) : 0}% qualified</span>
                      </div>
                      <div className="mt-0.5 h-1.5 w-full overflow-hidden rounded bg-field">
                        <div className="h-full rounded bg-ocean" style={{ width: `${(100 * t.links) / maxType}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

// The person's latest links with live QA state — "what happened to what I built".
function MyRecentLinks({ token, userLabel }: { token: string | null; userLabel: string }) {
  const links = useQuery({
    queryKey: ["my-recent-links", token, userLabel],
    enabled: Boolean(token && userLabel),
    retry: false,
    queryFn: () =>
      api<Page<BacklinkRow>>(
        `/backlinks?assigned_user_label=${encodeURIComponent(userLabel)}&sort=updated_at&direction=desc&limit=8`,
        { token }
      )
  });
  const rows = links.data?.items || [];
  if (links.isError || (!links.isLoading && !rows.length)) return null;
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center gap-1.5 border-b border-line p-3">
        <h3 className="text-sm font-semibold text-ink">My recent links</h3>
        <HelpTip text="Your latest links with their current QA verdict and score — hover a status to see what it means and what to do." />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-field text-xs uppercase text-muted">
            <tr><Th>Source page</Th><Th>Type</Th><Th>Status</Th><Th>Score</Th><Th>Updated</Th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.id}>
                <Td>
                  <span className="inline-flex max-w-[320px] items-center gap-1">
                    <span className="min-w-0 truncate text-ink" title={r.source_page_url}>{r.source_page_url}</span>
                    <CopyButton text={r.source_page_url} title="Copy URL" />
                  </span>
                </Td>
                <Td><span className="whitespace-nowrap text-xs text-muted">{linkTypeLabel(r.link_type || "") || "—"}</span></Td>
                <Td>
                  <span className="inline-flex items-center gap-1">
                    <Status value={r.override_status || r.status} compact />
                    {r.qa_wait_reason ? <QaWaitBadge reason={r.qa_wait_reason} /> : null}
                  </span>
                </Td>
                <Td>{r.score ?? "—"}</Td>
                <Td><span className="whitespace-nowrap">{formatDate(r.updated_at ?? null)}</span></Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// Recommendations addressed to THIS person (manual admin picks + engine rows the
// person hasn't decided on yet), with metrics context + copy + accept/skip.
function MyRecommendationsPanel({ token, userLabel }: { token: string | null; userLabel: string }) {
  const queryClient = useQueryClient();
  type Reco = {
    id: string; domain_key: string; project_id: string | null; link_type_name: string | null;
    source: string; status: string; reason: string | null; priority: string | null;
    due_date: string | null; note: string | null;
  };
  const recos = useQuery({
    queryKey: ["my-recos", token, userLabel],
    enabled: Boolean(token && userLabel),
    retry: false,
    queryFn: () =>
      api<Reco[]>(
        `/source-domains/recommendations?user_label=${encodeURIComponent(userLabel)}&status_filter=suggested,viewed&limit=20`,
        { token }
      )
  });
  const act = useMutation({
    mutationFn: (v: { r: Reco; status: "accepted" | "skipped" }) =>
      api("/source-domains/recommendations/action", {
        token, method: "POST",
        body: JSON.stringify({
          domain_key: v.r.domain_key, status: v.status,
          project_id: v.r.project_id, recommended_to: userLabel
        })
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-recos"] })
  });
  const rows = recos.data || [];
  if (!rows.length) return null;
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center gap-1.5 border-b border-line p-3">
        <h3 className="text-sm font-semibold text-ink">Recommended for you</h3>
        <HelpTip text="Source domains your manager picked for you (or the system queued) — use them for your link-building tasks. Accept when you'll use one, Skip to dismiss it." />
        <span className="ml-auto rounded-full bg-ocean/10 px-2 py-0.5 text-xs font-semibold text-ocean">{rows.length}</span>
      </div>
      <div className="divide-y divide-line">
        {rows.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            {r.source === "manual" ? (
              <span className="rounded bg-plum/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-plum" title="Hand-picked by your manager">Manager pick</span>
            ) : null}
            {r.priority === "high" ? (
              <span className="rounded bg-danger/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-danger">High priority</span>
            ) : null}
            <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{r.domain_key}</span>
            {r.link_type_name ? <span className="text-xs text-muted">{linkTypeLabel(r.link_type_name)}</span> : null}
            {r.due_date ? <span className="text-xs text-muted">due {formatDay(r.due_date)}</span> : null}
            <CopyButton text={r.domain_key} title="Copy domain" />
            <button
              onClick={() => act.mutate({ r, status: "accepted" })}
              className="rounded border border-ocean/40 px-1.5 py-0.5 text-[11px] font-medium text-ocean hover:bg-ocean/10"
            >
              Accept
            </button>
            <button
              onClick={() => act.mutate({ r, status: "skipped" })}
              className="rounded border border-line px-1.5 py-0.5 text-[11px] font-medium text-muted hover:bg-field"
            >
              Skip
            </button>
            {(r.reason || r.note) ? (
              <p className="w-full text-[11px] text-muted">{r.reason || r.note}</p>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function MyWorkDesk({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  const fmtIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const today = fmtIso(new Date());
  const monday = (() => {
    const x = new Date();
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return fmtIso(x);
  })();
  const sunday = (() => {
    const x = new Date(`${monday}T00:00:00`);
    x.setDate(x.getDate() + 6);
    return fmtIso(x);
  })();

  type MyRow = {
    id: string; day: string; project_id: string; user_label: string; hours: number;
    link_type_names: string[]; expected_links: number; actual_links: number;
    completion_pct: number | null; excused: boolean; excuse_reason: string | null;
    priority: string | null; note: string | null;
  };
  const me = useQuery({
    queryKey: ["my-work", token, monday, sunday],
    enabled: Boolean(token),
    queryFn: () =>
      api<{
        labels: string[];
        rows: MyRow[];
        leaves: Array<{ id: string; start_date: string; end_date: string; reason: string | null; status: string }>;
      }>(`/workforce/me?date_from=${monday}&date_to=${sunday}`, { token })
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const projectName = (id: string) => (projectsQ.data || []).find((p) => p.id === id)?.name || "—";

  const [lvFrom, setLvFrom] = useState(today);
  const [lvTo, setLvTo] = useState(today);
  const [lvReason, setLvReason] = useState("");
  const requestLeave = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/workforce/leaves", {
        token,
        method: "POST",
        body: JSON.stringify({
          user_label: me.data?.labels[0] || "",
          start_date: lvFrom,
          end_date: lvTo,
          reason: lvReason.trim() || null
        })
      }),
    onSuccess: () => {
      onNotice("Leave request sent — your admin will approve or reject it.");
      setLvReason("");
      queryClient.invalidateQueries({ queryKey: ["my-work"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const rows = me.data?.rows || [];
  const todayRows = rows.filter((r) => r.day === today);
  const weekTarget = rows.reduce((a, r) => a + (r.excused ? 0 : r.expected_links), 0);
  const weekDone = rows.reduce((a, r) => a + (r.excused ? 0 : r.actual_links), 0);
  const weekPct = weekTarget > 0 ? Math.round((100 * weekDone) / weekTarget) : null;

  const taskCard = (r: MyRow) => (
    <div key={r.id} className="rounded-lg border border-line bg-field/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{projectName(r.project_id)}</span>
        <span
          className={clsx(
            "rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase",
            r.priority === "high" ? "bg-danger/10 text-danger" : r.priority === "low" ? "bg-field text-muted" : "bg-ember/10 text-ember"
          )}
        >
          {r.priority || "medium"}
        </span>
        <span className="text-xs text-muted">{r.hours}h · {r.link_type_names.map(linkTypeLabel).join(", ") || "any type"}</span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-ink">
          <span className="font-bold">{r.actual_links}</span>
          <span className="text-muted"> / {r.expected_links} links</span>
        </span>
        {r.excused ? (
          <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-muted">{r.excuse_reason}</span>
        ) : r.completion_pct != null ? (
          <span
            className={clsx(
              "rounded px-2 py-0.5 text-xs font-semibold",
              r.completion_pct >= 100 ? "bg-ocean/10 text-ocean" : r.completion_pct >= 60 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger"
            )}
          >
            {r.completion_pct}% done
          </span>
        ) : null}
      </div>
      {r.note ? <p className="mt-1 text-xs text-muted">📝 {r.note}</p> : null}
    </div>
  );

  if (!me.isLoading && me.data && !me.data.labels.length) {
    return (
      <section className="rounded-xl border border-line bg-panel p-8 text-center shadow-card">
        <CalendarDays className="mx-auto mb-3 h-8 w-8 text-muted" />
        <h2 className="text-base font-semibold text-ink">Welcome!</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted">
          Your account isn&apos;t linked to a team member name yet, so there are no tasks to show.
          Ask your admin to link you on the Employees desk — your plans and targets will appear here.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      {/* Premium hero: who you are, where you stand, at a glance (Techsa accent). */}
      <div className="relative overflow-hidden rounded-2xl border border-ocean/30 bg-gradient-to-r from-ocean/15 via-panel to-plum/10 p-5 shadow-soft">
        <div className="flex flex-wrap items-center gap-4">
          <span className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-ocean to-plum text-lg font-bold text-white shadow-soft dark:text-slate-900">
            {(me.data?.labels[0] || "Me").split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join("")}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-bold uppercase tracking-widest text-ocean">My workspace</div>
            <h2 className="truncate text-xl font-bold tracking-tight text-ink">
              {me.data?.labels.length ? me.data.labels.join(", ") : "My Work"}
            </h2>
            <p className="text-sm text-muted">
              {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })} · week of {formatDay(monday)}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
              <span className="block text-lg font-bold leading-tight text-ink">{todayRows.length}</span>
              <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Today&apos;s tasks</span>
            </span>
            <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
              <span className="block text-lg font-bold leading-tight text-ocean">{weekDone}<span className="text-xs text-muted"> / {weekTarget}</span></span>
              <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Week links</span>
            </span>
            <span className="rounded-xl border border-line bg-panel/80 px-3 py-2 text-center shadow-card">
              <span className={clsx("block text-lg font-bold leading-tight", weekPct != null && weekPct >= 100 ? "text-ocean" : "text-ember")}>
                {weekPct != null ? `${weekPct}%` : "—"}
              </span>
              <span className="block text-[10px] font-semibold uppercase tracking-wide text-muted">Completion</span>
            </span>
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <Metric label="Today's tasks" value={todayRows.length} icon={CalendarDays} tone="ink"
          sub={todayRows.length ? `${todayRows.reduce((a, r) => a + r.hours, 0)}h planned` : "Nothing planned today"} />
        <Metric label="This week's target" value={weekTarget} icon={Gauge} tone="ocean"
          sub={`${weekDone} done so far`} help="Total links you're expected to build this week, from your assigned hours and rates." />
        <Metric label="Completion" value={weekPct != null ? `${weekPct}%` : "—"} icon={CheckCircle2}
          tone={weekPct != null && weekPct >= 100 ? "ocean" : "ember"}
          sub="Excused days (leave / days off) don't count against you" />
      </div>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Today" />
        <div className="space-y-2 p-3">
          {todayRows.map(taskCard)}
          {!todayRows.length ? <p className="p-2 text-sm text-muted">No tasks planned for today.</p> : null}
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="This week" />
        <div className="space-y-2 p-3">
          {rows.filter((r) => r.day !== today).map((r) => (
            <div key={r.id} className="flex items-start gap-3">
              <span className="mt-3 w-20 shrink-0 whitespace-nowrap text-xs font-semibold text-muted">{formatDay(r.day)}</span>
              <div className="min-w-0 flex-1">{taskCard(r)}</div>
            </div>
          ))}
          {me.isLoading ? (
            <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
          ) : null}
          {!me.isLoading && !rows.length ? <p className="p-2 text-sm text-muted">Nothing planned this week yet.</p> : null}
        </div>
      </section>

      {/* The person's own QA picture: links, quality split, avg score. */}
      {me.data?.labels.length ? (
        <MyQaSummary token={token} userLabel={me.data.labels[0]} />
      ) : null}

      {/* Visual performance: 90-day trend + project/link-type breakdowns. */}
      {me.data?.labels.length ? (
        <MyPerformancePanel token={token} userLabel={me.data.labels[0]} />
      ) : null}

      {/* Domains a manager hand-picked (or the engine queued) for this person. */}
      {me.data?.labels.length ? (
        <MyRecommendationsPanel token={token} userLabel={me.data.labels[0]} />
      ) : null}

      {/* Full task calendar: past, current and upcoming months (day/week/month). */}
      <MyTaskCalendar token={token} />

      {/* Latest links with live QA verdicts — what happened to what I built. */}
      {me.data?.labels.length ? (
        <MyRecentLinks token={token} userLabel={me.data.labels[0]} />
      ) : null}

      {/* Week at a glance + the company working-days calendar */}
      <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
        <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
          {me.data?.labels.length ? (
            <UserWeekStrip token={token} userLabel={me.data.labels[0]} />
          ) : (
            <div />
          )}
          <MiniWorkCalendar token={token} />
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="My leave" />
        <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
          <input type="date" value={lvFrom} onChange={(e) => setLvFrom(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <input type="date" value={lvTo} onChange={(e) => setLvTo(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <input value={lvReason} onChange={(e) => setLvReason(e.target.value)} placeholder="Reason (optional)…" className="h-9 w-56 rounded-lg border border-line bg-panel px-2 text-sm" />
          <button
            onClick={() => requestLeave.mutate()}
            disabled={requestLeave.isPending}
            className="h-9 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
          >
            Request leave
          </button>
          <span className="text-xs text-muted">Approved leave excuses your targets for those days.</span>
        </div>
        <div className="divide-y divide-line">
          {(me.data?.leaves || []).map((l) => (
            <div key={l.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <span className="text-ink">
                {formatDay(l.start_date)} → {formatDay(l.end_date)}
                {l.reason ? <span className="text-muted"> · {l.reason}</span> : null}
              </span>
              <Status value={l.status === "approved" ? "completed" : l.status === "rejected" ? "failed" : "pending"} />
            </div>
          ))}
          {!(me.data?.leaves || []).length ? <p className="p-3 text-sm text-muted">No leave requests yet.</p> : null}
        </div>
      </section>
    </section>
  );
}

function TasksDesk({
  token,
  projectId,
  projects,
  onNotice
}: {
  token: string | null;
  projectId: string;
  projects: Project[];
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  // Local-safe date helpers (no UTC off-by-one).
  const fmtIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const mondayOf = (d: Date) => {
    const x = new Date(d);
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return x;
  };
  const todayIso = fmtIso(new Date());
  const weekAgoIso = fmtIso(new Date(Date.now() - 6 * 86400000));
  const [from, setFrom] = useState(weekAgoIso);
  const [to, setTo] = useState(todayIso);
  const [view, setView] = useState<"planner" | "project" | "list">("planner");
  // The planner works week-by-week (day-wise, like the old Google Sheet).
  const [weekStart, setWeekStart] = useState(() => fmtIso(mondayOf(new Date())));
  const weekDays = useMemo(() => {
    const base = new Date(`${weekStart}T00:00:00`);
    return [...Array(7)].map((_, i) => {
      const d = new Date(base);
      d.setDate(d.getDate() + i);
      return fmtIso(d);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weekStart]);
  const shiftWeek = (delta: number) => {
    const d = new Date(`${weekStart}T00:00:00`);
    d.setDate(d.getDate() + delta * 7);
    setWeekStart(fmtIso(d));
  };
  const rangeFrom = view === "list" ? from : weekDays[0];
  const rangeTo = view === "list" ? to : weekDays[6];
  // Week-view filters: narrow every view to one person and/or one project.
  const [filterUser, setFilterUser] = useState("");
  const [filterProject, setFilterProject] = useState("");

  type DayRow = {
    id: string; day: string; project_id: string; user_label: string; hours: number;
    link_type_names: string[]; expected_links: number; actual_links: number;
    completion_pct: number | null; excused: boolean; excuse_reason: string | null;
    priority: string | null; rate_source: string | null; lph_used: number | null;
    note: string | null;
  };
  const report = useQuery({
    queryKey: ["day-report", token, rangeFrom, rangeTo, projectId],
    enabled: Boolean(token),
    queryFn: () =>
      api<DayRow[]>(
        `/workforce/day-report?date_from=${rangeFrom}&date_to=${rangeTo}${projectId ? `&project_id=${projectId}` : ""}`,
        { token }
      )
  });
  const visibleRows = useMemo(
    () =>
      (report.data || []).filter(
        (r) =>
          (!filterUser || r.user_label === filterUser) &&
          (!filterProject || r.project_id === filterProject)
      ),
    [report.data, filterUser, filterProject]
  );
  // Everyone plannable (employee catalog + past assignments), TeamLead-scoped.
  const knownLabels = useQuery({
    queryKey: ["workforce-labels", token],
    enabled: Boolean(token),
    queryFn: () => api<string[]>("/workforce/labels", { token })
  });
  // Weekly template: set the week up ONCE — next weeks fill automatically
  // (a daily job materializes the coming week without overwriting manual edits).
  const templates = useQuery({
    queryKey: ["task-templates", token],
    enabled: Boolean(token),
    queryFn: () =>
      api<{ users: Array<{ user_label: string; entries: number; week_hours: number }>; total_entries: number }>(
        "/workforce/templates",
        { token }
      )
  });
  const saveTemplateMut = useMutation({
    mutationFn: () =>
      api<{ saved: number; message: string }>("/workforce/templates/save-week", {
        token,
        method: "POST",
        body: JSON.stringify({ week_start: weekDays[0] })
      }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["task-templates"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const applyTemplateMut = useMutation({
    mutationFn: (mode: "week" | "month") =>
      api<{ applied: number; cleared: number; skipped_inactive: number; range: string; warnings: string[] }>(
        "/workforce/templates/apply",
        { token, method: "POST", body: JSON.stringify({ week_start: weekDays[0], mode, clear: true }) }
      ),
    onSuccess: (r) => {
      onNotice(`Template applied to ${r.range} — ${r.applied} plan${r.applied === 1 ? "" : "s"} set, ${r.cleared} existing cleared.`);
      (r.warnings || []).forEach((w) => onNotice(`⚠ ${w}`));
      queryClient.invalidateQueries({ queryKey: ["day-report"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  // Working-day shading for the planner week (may span two months).
  const wm1 = { y: Number(weekDays[0].slice(0, 4)), m: Number(weekDays[0].slice(5, 7)) };
  const wm2 = { y: Number(weekDays[6].slice(0, 4)), m: Number(weekDays[6].slice(5, 7)) };
  const weekCal1 = useQuery({
    queryKey: ["work-calendar", token, wm1.y, wm1.m],
    enabled: Boolean(token),
    queryFn: () =>
      api<Array<{ day: string; is_working: boolean; is_override: boolean }>>(
        `/workforce/calendar?year=${wm1.y}&month=${wm1.m}`,
        { token }
      )
  });
  const weekCal2 = useQuery({
    queryKey: ["work-calendar", token, wm2.y, wm2.m],
    enabled: Boolean(token) && (wm1.m !== wm2.m || wm1.y !== wm2.y),
    queryFn: () =>
      api<Array<{ day: string; is_working: boolean; is_override: boolean }>>(
        `/workforce/calendar?year=${wm2.y}&month=${wm2.m}`,
        { token }
      )
  });
  const workingMap = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const d of [...(weekCal1.data || []), ...(weekCal2.data || [])]) m.set(d.day, d.is_working);
    return m;
  }, [weekCal1.data, weekCal2.data]);
  const productivity = useQuery({
    queryKey: ["productivity", token],
    enabled: Boolean(token),
    queryFn: () =>
      api<{
        global: Array<{ link_type_name: string; links_per_hour: number }>;
        overrides: Array<{ user_label: string; link_type_name: string; links_per_hour: number }>;
      }>("/workforce/productivity", { token })
  });
  const leaves = useQuery({
    queryKey: ["leaves", token],
    enabled: Boolean(token),
    queryFn: () =>
      api<Array<{ id: string; user_label: string; start_date: string; end_date: string; reason: string | null; status: string }>>(
        "/workforce/leaves",
        { token }
      )
  });
  const [calCursor, setCalCursor] = useState(() => {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  });
  const calendar = useQuery({
    queryKey: ["work-calendar", token, calCursor.year, calCursor.month],
    enabled: Boolean(token),
    queryFn: () =>
      api<Array<{ day: string; is_working: boolean; is_override: boolean }>>(
        `/workforce/calendar?year=${calCursor.year}&month=${calCursor.month}`,
        { token }
      )
  });

  // ── Add-assignment form ──────────────────────────────────────────────
  const formRef = useRef<HTMLElement | null>(null);
  const [fDay, setFDay] = useState(todayIso);
  const [fUser, setFUser] = useState("");
  const [fProject, setFProject] = useState(projectId || "");
  // Project context is a hard scope: entering a project locks planning to it.
  useEffect(() => {
    if (projectId) setFProject(projectId);
  }, [projectId]);
  const [fHours, setFHours] = useState("4");
  const [fTypes, setFTypes] = useState("");
  const [fPriority, setFPriority] = useState("medium");
  const [fNote, setFNote] = useState("");
  const [fTarget, setFTarget] = useState(""); // manual target override (optional)
  const [fRepeat, setFRepeat] = useState(false); // also save as a standing weekly-template entry
  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  // The assign form stays hidden until needed — the desk opens clean.
  const [showAssign, setShowAssign] = useState(false);
  // Planner cells prefill the form ("+ Add" or clicking a chip to edit).
  const prefillForm = (p: { user?: string; day?: string; row?: DayRow }) => {
    setShowAssign(true);
    if (p.row) {
      setFDay(p.row.day);
      setFUser(p.row.user_label);
      setFProject(p.row.project_id);
      setFHours(String(p.row.hours));
      setFTypes(p.row.link_type_names.join(","));
      setFPriority(p.row.priority || "medium");
      setFNote(p.row.note || "");
      setFTarget(p.row.rate_source === "manual" ? String(p.row.expected_links) : "");
    } else {
      if (p.user) setFUser(p.user);
      if (p.day) setFDay(p.day);
    }
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const rateWording = (src: string | null, lph: number | null) => {
    if (src === "manual") return "manual target set by hand";
    if (src === "override") return `${lph ?? "?"} links/hr — this person's own rate`;
    if (src === "global") return `${lph ?? "?"} links/hr — global rate`;
    return "";
  };
  // Standing weekly plan: mirror the assignment into the weekly template so
  // this week's entry also auto-fills the same weekday on future weeks.
  const saveTemplateEntry = useMutation({
    mutationFn: () =>
      api<{ message: string }>("/workforce/templates/entry", {
        token,
        method: "PUT",
        body: JSON.stringify({
          user_label: fUser.trim(),
          weekday: (new Date(`${fDay}T00:00:00`).getDay() + 6) % 7, // 0=Mon..6=Sun
          project_id: fProject || projectId,
          hours: Number(fHours) || 0,
          link_type_names: fTypes ? fTypes.split(",") : [],
          priority: fPriority || null,
          note: fNote.trim() || null,
          expected_links: fTarget.trim() ? Number(fTarget) : null
        })
      }),
    onSuccess: () => {
      onNotice("Standing weekly plan saved — future weeks will auto-fill.");
      setFRepeat(false);
      queryClient.invalidateQueries({ queryKey: ["task-templates"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const addAssignment = useMutation({
    mutationFn: () =>
      api<{ id: string; expected_links: number; rate_source: string | null; lph_used: number | null; warnings: string[] }>(
        "/workforce/assignments",
        {
          token,
          method: "POST",
          body: JSON.stringify({
            project_id: fProject || projectId, user_label: fUser.trim(), day: fDay,
            hours: Number(fHours) || 0,
            link_type_names: fTypes ? fTypes.split(",") : [],
            priority: fPriority || null,
            note: fNote.trim() || null,
            expected_links: fTarget.trim() ? Number(fTarget) : null
          })
        }
      ),
    onSuccess: (r) => {
      onNotice(
        `Assigned — target ${r.expected_links} links (${rateWording(r.rate_source, r.lph_used)}).`
      );
      (r.warnings || []).forEach((w) => onNotice(`⚠ ${w}`));
      if (fRepeat) saveTemplateEntry.mutate(); // before the resets — the template reads the form
      setFNote("");
      setFTarget("");
      queryClient.invalidateQueries({ queryKey: ["day-report"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const removeAssignment = useMutation({
    mutationFn: (id: string) =>
      api<{ message: string }>(`/workforce/assignments/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Assignment removed");
      queryClient.invalidateQueries({ queryKey: ["day-report"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const saveProductivity = useMutation({
    mutationFn: (p: { link_type_name: string; links_per_hour: number; user_label?: string }) =>
      api<{ message: string }>("/workforce/productivity", {
        token,
        method: "PUT",
        body: JSON.stringify(p)
      }),
    onSuccess: () => {
      onNotice("Productivity saved");
      queryClient.invalidateQueries({ queryKey: ["productivity"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const removeOverride = useMutation({
    mutationFn: (p: { user_label: string; link_type_name: string }) =>
      api<{ message: string }>(
        `/workforce/productivity?user_label=${encodeURIComponent(p.user_label)}&link_type_name=${encodeURIComponent(p.link_type_name)}`,
        { token, method: "DELETE" }
      ),
    onSuccess: () => {
      onNotice("Override removed — global rate applies again");
      queryClient.invalidateQueries({ queryKey: ["productivity"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const [ovUser, setOvUser] = useState("");
  const [ovType, setOvType] = useState("");
  const [ovLph, setOvLph] = useState("");
  const toggleDay = useMutation({
    mutationFn: (p: { day: string; is_working: boolean }) =>
      api<{ message: string }>("/workforce/calendar", { token, method: "PUT", body: JSON.stringify(p) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["work-calendar"] }),
    onError: (e: Error) => onNotice(e.message)
  });
  const [lvUser, setLvUser] = useState("");
  const [lvFrom, setLvFrom] = useState(todayIso);
  const [lvTo, setLvTo] = useState(todayIso);
  const requestLeave = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/workforce/leaves", {
        token,
        method: "POST",
        body: JSON.stringify({ user_label: lvUser.trim(), start_date: lvFrom, end_date: lvTo })
      }),
    onSuccess: () => {
      onNotice("Leave request submitted");
      queryClient.invalidateQueries({ queryKey: ["leaves"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const decideLeave = useMutation({
    mutationFn: (p: { id: string; approve: boolean }) =>
      api<{ status: string }>(`/workforce/leaves/${p.id}?approve=${p.approve}`, { token, method: "PATCH" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leaves"] });
      queryClient.invalidateQueries({ queryKey: ["day-report"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const projectName = (id: string) => projects.find((p) => p.id === id)?.name || "—";

  // "Where the time goes" aggregation (hours / target / done by person & project).
  const statGroups: Array<[string, (r: DayRow) => string, (k: string) => string]> = [
    ["By person", (r) => r.user_label, (k) => k],
    ["By project", (r) => r.project_id, (k) => projectName(k)]
  ];
  const statRangeLabel =
    rangeFrom === rangeTo ? formatDay(rangeFrom) : `${formatDay(rangeFrom)} – ${formatDay(rangeTo)}`;

  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-ink">Tasks & calendar</h2>
        <p className="text-sm text-muted">
          Plan each person&apos;s day (hours × link types → expected links), then track completion
          against that day&apos;s plan. Approved leave and non-working days don&apos;t count against anyone.
        </p>
      </div>

      {/* Where the time goes — hours & completion by person and by project */}
      {visibleRows.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {statGroups.map(([title, keyOf, labelOf]) => {
            const agg = new Map<string, { hours: number; target: number; done: number }>();
            for (const r of visibleRows) {
              const k = keyOf(r);
              const a = agg.get(k) || { hours: 0, target: 0, done: 0 };
              a.hours += r.hours;
              if (!r.excused) {
                a.target += r.expected_links;
                a.done += r.actual_links;
              }
              agg.set(k, a);
            }
            const entries = [...agg.entries()].sort((x, y) => y[1].hours - x[1].hours);
            return (
              <section key={title} className="rounded-xl border border-line bg-panel shadow-card">
                <SectionTitle title={`${title} — ${statRangeLabel}`} />
                <div className="divide-y divide-line">
                  {entries.map(([k, a]) => {
                    const pctDone = a.target > 0 ? Math.round((100 * a.done) / a.target) : null;
                    return (
                      <div key={k} className="flex items-center gap-3 px-3 py-2 text-sm">
                        <span className="w-40 truncate font-medium text-ink" title={labelOf(k)}>{labelOf(k)}</span>
                        <span className="w-14 whitespace-nowrap text-xs text-muted">{Math.round(a.hours * 10) / 10}h</span>
                        <span className="w-20 whitespace-nowrap text-xs text-muted">{a.done}/{a.target}</span>
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-field">
                          <span
                            className={clsx(
                              "block h-full rounded-full",
                              pctDone == null ? "bg-line" : pctDone >= 100 ? "bg-ocean" : pctDone >= 60 ? "bg-ember" : "bg-danger"
                            )}
                            style={{ width: `${Math.min(100, pctDone ?? 0)}%` }}
                          />
                        </span>
                        <span className="w-12 text-right text-xs font-semibold text-ink">{pctDone == null ? "—" : `${pctDone}%`}</span>
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      ) : null}

      {/* Plan vs done — weekly planner (day-wise, like the old sheet), project view, list */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
            Plan vs done
            <span className="flex overflow-hidden rounded-lg border border-line text-xs font-medium">
              <button
                onClick={() => setView("planner")}
                title="Weekly planner — people down the side, weekdays across the top; click any cell to plan"
                className={clsx("px-2.5 py-1 transition", view === "planner" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                Week planner
              </button>
              <button
                onClick={() => setView("project")}
                title="By project — who works on each project, day by day"
                className={clsx("px-2.5 py-1 transition", view === "project" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                By project
              </button>
              <button
                onClick={() => setView("list")}
                className={clsx("px-2.5 py-1 transition", view === "list" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                List
              </button>
            </span>
          </h3>
          {view === "list" ? (
            <div className="flex items-center gap-2 text-xs text-muted">
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm text-ink" />
              –
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm text-ink" />
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm">
              <button onClick={() => shiftWeek(-1)} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">← Prev week</button>
              <span className="font-medium text-ink">
                {formatDay(weekDays[0])} – {formatDay(weekDays[6])}
              </span>
              <button onClick={() => shiftWeek(1)} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">Next week →</button>
              <button onClick={() => setWeekStart(fmtIso(mondayOf(new Date())))} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">Today</button>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <SearchSelect
            value={filterUser}
            onChange={setFilterUser}
            options={(knownLabels.data || []).map((l) => ({ value: l }))}
            placeholder="Filter: everyone"
            width="w-44"
          />
          {!projectId ? (
            <SearchSelect
              value={filterProject}
              onChange={setFilterProject}
              options={projects.map((pr) => ({ value: pr.id, label: pr.name }))}
              placeholder="Filter: all projects"
              width="w-48"
            />
          ) : null}
          <span className="mx-1 h-5 w-px bg-line" />
          <button
            onClick={() => {
              if (window.confirm(`Apply the weekly template to the week of ${formatDay(weekDays[0])}?\n\n⚠ This OVERRIDES every assignment in that week (from today onward) — existing plans are wiped and replaced by the template. Past days are kept.`))
                applyTemplateMut.mutate("week");
            }}
            disabled={applyTemplateMut.isPending || !(templates.data?.total_entries || 0)}
            title={!(templates.data?.total_entries || 0) ? "No template yet — set one week up, then Save week as template" : "Wipe this week's assignments (today onward) and replace with the template"}
            className="flex h-8 items-center gap-1.5 rounded-lg bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
          >
            {applyTemplateMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            Apply to this week
          </button>
          <button
            onClick={() => {
              if (window.confirm(`Apply the weekly template to ALL of next month?\n\n⚠ This OVERRIDES every assignment across next calendar month — existing plans are wiped and replaced by the template on each matching weekday. This cannot be undone.`))
                applyTemplateMut.mutate("month");
            }}
            disabled={applyTemplateMut.isPending || !(templates.data?.total_entries || 0)}
            title={!(templates.data?.total_entries || 0) ? "No template yet — set one week up, then Save week as template" : "Wipe next calendar month's assignments and replace with the template"}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-ocean/50 px-3 text-xs font-semibold text-ocean transition hover:bg-ocean/10 disabled:opacity-40"
          >
            <CalendarDays className="h-3.5 w-3.5" />
            Apply to next month
          </button>
          <button
            onClick={() => {
              if (window.confirm("Save THIS week's plans as the standing weekly template?\n\nThis replaces the previous template. Coming weeks are filled from it automatically (manual changes are never overwritten)."))
                saveTemplateMut.mutate();
            }}
            disabled={saveTemplateMut.isPending}
            className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-3 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
          >
            Save week as template
          </button>
          <span className="text-xs text-muted" title="The standing weekly plan — applied to coming weeks automatically every evening">
            {(templates.data?.total_entries || 0)
              ? `Template: ${templates.data?.total_entries} entr${(templates.data?.total_entries || 0) === 1 ? "y" : "ies"} · ${templates.data?.users.length} people · auto-fills next weeks`
              : "No weekly template yet"}
          </span>
          <span className="ml-auto" />
          <ColorLegend />
        </div>
        {view !== "list" ? (
          <div className="overflow-x-auto">
            {(() => {
              const rows = visibleRows;
              const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
              const approvedLeaves = (leaves.data || []).filter((l) => l.status === "approved");
              const onLeave = (label: string, d: string) =>
                approvedLeaves.some((l) => l.user_label === label && l.start_date <= d && l.end_date >= d);
              const isWorking = (d: string) => {
                const w = workingMap.get(d);
                if (w !== undefined) return w;
                return new Date(`${d}T00:00:00`).getDay() !== 0; // default: Sunday off
              };
              const chip = (r: DayRow) => (
                <span
                  key={r.id}
                  onClick={() => prefillForm({ row: r })}
                  title={
                    `${projectName(r.project_id)} — ${r.hours}h · ${r.link_type_names.map(linkTypeLabel).join(", ") || "any type"}\n` +
                    `Target ${r.expected_links} (${rateWording(r.rate_source, r.lph_used) || "rate unknown"}) · done ${r.actual_links}` +
                    `${r.priority ? ` · ${r.priority} priority` : ""}${r.note ? `\nNote: ${r.note}` : ""}` +
                    `${r.excused ? `\n${r.excuse_reason}` : ""}\nClick to edit this plan.`
                  }
                  className={clsx(
                    "block cursor-pointer rounded-md border px-1.5 py-1 text-[11px] leading-tight transition hover:ring-1 hover:ring-ocean/40",
                    r.excused
                      ? "border-line bg-field text-muted"
                      : (r.completion_pct ?? 0) >= 100
                        ? "border-ocean/40 bg-ocean/15 text-ocean"
                        : (r.completion_pct ?? 0) >= 60
                          ? "border-ember/40 bg-ember/15 text-ember"
                          : "border-danger/40 bg-danger/15 text-danger"
                  )}
                >
                  <span className="flex items-center gap-1">
                    <span
                      className={clsx(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        r.priority === "high" ? "bg-danger" : r.priority === "low" ? "bg-line" : "bg-ember"
                      )}
                      title={`${r.priority || "medium"} priority`}
                    />
                    <span className="truncate font-semibold">{projectName(r.project_id)}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`Remove ${r.user_label}'s ${projectName(r.project_id)} plan on ${r.day}?`))
                          removeAssignment.mutate(r.id);
                      }}
                      className="ml-auto shrink-0 text-muted hover:text-danger"
                      aria-label="Remove assignment"
                    >
                      ×
                    </button>
                  </span>
                  <span className="block">
                    {r.hours}h · {r.actual_links}/{r.expected_links}
                    {r.excused ? " · excused" : ""}
                    {r.rate_source === "manual" ? (
                      <span className="text-[10px] opacity-80"> · manual target</span>
                    ) : r.lph_used ? (
                      <span className="text-[10px] opacity-80"> · @{r.lph_used}/h{r.rate_source === "override" ? " (own rate)" : ""}</span>
                    ) : null}
                  </span>
                  {!r.excused && r.expected_links > 0 ? (
                    <span className="mt-1 block h-1 overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
                      <span
                        className="block h-full rounded-full bg-current"
                        style={{ width: `${Math.min(100, r.completion_pct ?? 0)}%` }}
                      />
                    </span>
                  ) : null}
                </span>
              );
              const dayHeader = (d: string, i: number) => (
                <th key={d} className={clsx("whitespace-nowrap px-3 py-2 text-left font-semibold uppercase", d === todayIso && "bg-ocean/10")}>
                  <span
                    className={clsx(!isWorking(d) && "opacity-50", d === todayIso && "font-bold text-ocean")}
                    title={d === todayIso ? "Today" : isWorking(d) ? d : `${d} — non-working day`}
                  >
                    {dayNames[i]} {d.slice(8)}/{d.slice(5, 7)}
                    {d === todayIso ? " · today" : !isWorking(d) ? " · off" : ""}
                  </span>
                </th>
              );
              if (view === "project") {
                const gridProjects = Array.from(new Set(rows.map((r) => r.project_id)));
                if (!gridProjects.length)
                  return report.isLoading ? (
                    <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
                  ) : (
                    <Empty label="No plans this week — use the Week planner or the form above." />
                  );
                return (
                  <table className="w-full text-left text-sm">
                    <thead className="bg-field text-xs uppercase text-muted">
                      <tr>
                        <Th>Project</Th>
                        {weekDays.map(dayHeader)}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {gridProjects.map((pid) => (
                        <tr key={pid} className="align-top">
                          <Td><span className="font-medium text-ink">{projectName(pid)}</span></Td>
                          {weekDays.map((d) => {
                            const cell = rows.filter((r) => r.project_id === pid && r.day === d);
                            const hours = cell.reduce((a, r) => a + r.hours, 0);
                            const target = cell.reduce((a, r) => a + r.expected_links, 0);
                            const done = cell.reduce((a, r) => a + r.actual_links, 0);
                            return (
                              <td key={d} className={clsx("px-3 py-2 align-top", d === todayIso && "bg-ocean/5")}>
                                {cell.length ? (
                                  <span className={clsx("block min-w-[110px] space-y-1", !isWorking(d) && "opacity-60")}>
                                    {cell.map((r) => (
                                      <span
                                        key={r.id}
                                        onClick={() => prefillForm({ row: r })}
                                        title={`${r.user_label} — ${r.hours}h · target ${r.expected_links}, done ${r.actual_links}${r.excused ? ` · ${r.excuse_reason}` : `${r.completion_pct != null ? ` · ${r.completion_pct}% done` : ""}`}. Click to edit.`}
                                        className={clsx(
                                          "block cursor-pointer rounded-md border px-1.5 py-1 text-[11px] leading-tight transition hover:ring-1 hover:ring-ocean/40",
                                          r.excused
                                            ? "border-line bg-field text-muted"
                                            : (r.completion_pct ?? 0) >= 100
                                              ? "border-ocean/40 bg-ocean/15 text-ocean"
                                              : (r.completion_pct ?? 0) >= 60
                                                ? "border-ember/40 bg-ember/15 text-ember"
                                                : "border-danger/40 bg-danger/15 text-danger"
                                        )}
                                      >
                                        {r.user_label} · {r.hours}h · {r.actual_links}/{r.expected_links}
                                        {!r.excused && r.expected_links > 0 ? (
                                          <span className="mt-1 block h-1 overflow-hidden rounded-full bg-black/10 dark:bg-white/10">
                                            <span
                                              className="block h-full rounded-full bg-current"
                                              style={{ width: `${Math.min(100, r.completion_pct ?? 0)}%` }}
                                            />
                                          </span>
                                        ) : null}
                                      </span>
                                    ))}
                                    <span className="block text-[10px] font-semibold text-muted">
                                      Σ {hours}h · {done}/{target}
                                    </span>
                                  </span>
                                ) : (
                                  <span className="text-xs text-muted">—</span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                );
              }
              const gridUsers = Array.from(
                new Set([...(knownLabels.data || []), ...rows.map((r) => r.user_label)])
              ).sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
              if (!gridUsers.length)
                return (
                  <Empty label="No people yet — sync a sheet (users are created automatically) or type a name in the form above." />
                );
              return (
                <table className="w-full text-left text-sm">
                  <thead className="bg-field text-xs uppercase text-muted">
                    <tr>
                      <Th>Person</Th>
                      {weekDays.map(dayHeader)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {gridUsers.map((u) => (
                      <tr key={u} className="align-top">
                        <Td><span className="whitespace-nowrap font-medium text-ink">{u}</span></Td>
                        {weekDays.map((d) => {
                          const cell = rows.filter((r) => r.user_label === u && r.day === d);
                          const leave = onLeave(u, d);
                          return (
                            <td key={d} className={clsx("px-3 py-2 align-top", d === todayIso && "bg-ocean/5")}>
                              <span className={clsx("block min-w-[116px] space-y-1", !isWorking(d) && "opacity-60")}>
                                {leave ? (
                                  <span className="block rounded-md bg-plum/10 px-1.5 py-1 text-[11px] font-medium text-plum" title="Approved leave — plans on this day are excused">
                                    On leave
                                  </span>
                                ) : null}
                                {cell.map(chip)}
                                <button
                                  onClick={() => prefillForm({ user: u, day: d })}
                                  title={`Plan work for ${u} on ${d}`}
                                  className="block w-full rounded-md border border-dashed border-line px-1.5 py-0.5 text-center text-[11px] text-muted transition hover:border-ocean/50 hover:text-ocean"
                                >
                                  + Add
                                </button>
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              );
            })()}
          </div>
        ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Date</Th><Th>User</Th><Th>Project</Th><Th>Hours</Th><Th>Link types</Th>
                <Th>Priority</Th><Th>Target</Th><Th>Done</Th><Th>Completion</Th><Th>Note</Th><Th>{" "}</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {visibleRows.map((r) => (
                <tr key={r.id} className="cursor-pointer hover:bg-field/60" onClick={() => prefillForm({ row: r })}>
                  <Td><span className="whitespace-nowrap">{r.day}</span></Td>
                  <Td><span className="font-medium text-ink">{r.user_label}</span></Td>
                  <Td>{projectName(r.project_id)}</Td>
                  <Td>{r.hours}h</Td>
                  <Td><span className="text-xs text-muted">{r.link_type_names.map(linkTypeLabel).join(", ") || "—"}</span></Td>
                  <Td>
                    <span
                      className={clsx(
                        "rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase",
                        r.priority === "high"
                          ? "bg-danger/10 text-danger"
                          : r.priority === "low"
                            ? "bg-field text-muted"
                            : "bg-ember/10 text-ember"
                      )}
                    >
                      {r.priority || "medium"}
                    </span>
                  </Td>
                  <Td>
                    <span title={rateWording(r.rate_source, r.lph_used) || undefined}>
                      {r.expected_links}
                      {r.rate_source === "manual" ? <span className="ml-0.5 text-[10px] text-muted">(manual)</span> : null}
                      {r.rate_source === "override" ? <span className="ml-0.5 text-[10px] text-plum">(own rate)</span> : null}
                    </span>
                  </Td>
                  <Td>{r.actual_links}</Td>
                  <Td>
                    {r.excused ? (
                      <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-muted" title={r.excuse_reason || ""}>
                        Excused — {r.excuse_reason}
                      </span>
                    ) : r.completion_pct == null ? (
                      "—"
                    ) : (
                      <span
                        className={clsx(
                          "rounded px-2 py-0.5 text-xs font-semibold",
                          r.completion_pct >= 100 ? "bg-ocean/10 text-ocean"
                            : r.completion_pct >= 60 ? "bg-ember/10 text-ember"
                              : "bg-danger/10 text-danger"
                        )}
                      >
                        {r.completion_pct}%
                      </span>
                    )}
                  </Td>
                  <Td>
                    <span className="block max-w-[180px] truncate text-xs text-muted" title={r.note || undefined}>
                      {r.note || "—"}
                    </span>
                  </Td>
                  <Td>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        removeAssignment.mutate(r.id);
                      }}
                      className="text-xs text-muted hover:text-danger hover:underline"
                    >
                      Remove
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {report.isLoading ? (
            <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
          ) : null}
          {!report.isLoading && !visibleRows.length ? (
            <Empty label="No assignments match this period/filters — add one above." />
          ) : null}
        </div>
        )}
      </section>

      {/* Assign — hidden by default; "+ Add" in the planner opens it prefilled */}
      {!showAssign ? (
        <div>
          <button
            onClick={() => setShowAssign(true)}
            className="flex h-10 items-center gap-2 rounded-lg bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
          >
            <Plus className="h-4 w-4" />
            Assign work
          </button>
        </div>
      ) : (
      <section ref={formRef} className="rounded-xl border border-line bg-panel p-4 shadow-card">
        <div className="flex items-center justify-between">
          <SectionTitle title="Assign work" flush />
          <button onClick={() => setShowAssign(false)} className="text-xs font-medium text-muted hover:text-ink hover:underline">
            Hide
          </button>
        </div>
        <div className="flex flex-wrap items-end gap-2 pt-3">
          <input type="date" value={fDay} onChange={(e) => setFDay(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <SearchSelect
            value={fUser}
            onChange={setFUser}
            options={(knownLabels.data || []).map((l) => ({ value: l }))}
            placeholder="Person…"
            allowCustom
            width="w-44"
          />
          {projectId ? (
            <span
              className="flex h-9 items-center rounded-lg border border-ocean/40 bg-ocean/10 px-2.5 text-sm font-medium text-ocean"
              title="You're inside this project — plans here always belong to it"
            >
              {projects.find((p) => p.id === projectId)?.name || "This project"}
            </span>
          ) : (
            <SearchSelect
              value={fProject}
              onChange={setFProject}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              placeholder="Project…"
              width="w-48"
            />
          )}
          <input type="number" min={0} max={24} step={0.5} value={fHours} onChange={(e) => setFHours(e.target.value)} className="h-9 w-20 rounded-lg border border-line bg-panel px-2 text-sm" title="Hours" />
          <FilterMultiSelect
            label="Link types"
            options={(linkTypes.data || []).map((lt) => ({ value: lt.name, label: linkTypeLabel(lt.name) }))}
            selected={fTypes ? fTypes.split(",") : []}
            onChange={(v) => setFTypes(v.join(","))}
          />
          <select
            value={fPriority}
            onChange={(e) => setFPriority(e.target.value)}
            title="Priority for this assignment"
            className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
          >
            <option value="high">High priority</option>
            <option value="medium">Medium priority</option>
            <option value="low">Low priority</option>
          </select>
          <input
            type="number"
            min={0}
            value={fTarget}
            onChange={(e) => setFTarget(e.target.value)}
            placeholder="Target (auto)"
            title="Leave blank to calculate the target from productivity rates (personal rate beats global). Type a number to set it by hand — highest priority."
            className="h-9 w-28 rounded-lg border border-line bg-panel px-2 text-sm"
          />
          <input
            value={fNote}
            onChange={(e) => setFNote(e.target.value)}
            placeholder="Note (e.g. Only niche relevant)…"
            className="h-9 w-56 rounded-lg border border-line bg-panel px-2 text-sm"
          />
          <label className="flex w-full items-center gap-2 text-sm text-ink">
            <input type="checkbox" checked={fRepeat} onChange={(e) => setFRepeat(e.target.checked)} className="h-4 w-4 rounded border-line" />
            Repeat every week on this weekday (standing plan — applies to this week and auto-fills future weeks)
          </label>
          <button
            onClick={() => addAssignment.mutate()}
            disabled={addAssignment.isPending || !fUser.trim() || !(fProject || projectId)}
            className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
          >
            {addAssignment.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Assign
          </button>
          <span className="text-xs text-muted">
            Target priority: manual number → person&apos;s own rate → global rate. Assigning the same person+project+day again updates that plan.
          </span>
        </div>
      </section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Productivity settings */}
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Productivity (links per hour) — personal rates first" />
          <div className="border-b border-line">
            <p className="flex items-center gap-1.5 px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-muted">
              Per-person rates (highest priority)
              <HelpTip text="A personal rate for one link type, e.g. a fast profile-link builder. It beats the global rate above when calculating that person's expected links. Remove it to fall back to the global rate." />
            </p>
            <div className="divide-y divide-line">
              {(productivity.data?.overrides || []).map((o) => (
                <div key={`${o.user_label}|${o.link_type_name}`} className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="text-sm text-ink">
                    <span className="font-medium">{o.user_label}</span>
                    <span className="text-muted"> · {o.link_type_name}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{o.links_per_hour}/h</span>
                    <button
                      onClick={() => removeOverride.mutate({ user_label: o.user_label, link_type_name: o.link_type_name })}
                      className="text-xs text-muted hover:text-danger hover:underline"
                    >
                      Remove
                    </button>
                  </span>
                </div>
              ))}
              {!(productivity.data?.overrides || []).length ? (
                <p className="px-3 py-2 text-xs text-muted">No personal rates yet — everyone uses the global rates above.</p>
              ) : null}
            </div>
            <div className="flex flex-wrap items-end gap-2 p-3">
              <input value={ovUser} onChange={(e) => setOvUser(e.target.value)} placeholder="User (sheet name)…" className="h-9 w-36 rounded-lg border border-line bg-panel px-2 text-sm" />
              <select value={ovType} onChange={(e) => setOvType(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
                <option value="">Link type…</option>
                {Array.from(
                  new Set([
                    ...(linkTypes.data || []).filter((t) => t.is_active).map((t) => t.name),
                    ...(productivity.data?.global || []).map((g) => g.link_type_name)
                  ])
                )
                  .sort((a, b) => a.localeCompare(b))
                  .map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
              </select>
              <input type="number" min={0.1} step={0.5} value={ovLph} onChange={(e) => setOvLph(e.target.value)} placeholder="links/h" className="h-9 w-24 rounded-lg border border-line bg-panel px-2 text-sm" />
              <button
                onClick={() => {
                  saveProductivity.mutate({ link_type_name: ovType, links_per_hour: Number(ovLph), user_label: ovUser.trim() });
                  setOvUser(""); setOvType(""); setOvLph("");
                }}
                disabled={saveProductivity.isPending || !ovUser.trim() || !ovType || !(Number(ovLph) > 0)}
                className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field disabled:opacity-50"
              >
                Add override
              </button>
            </div>
          </div>
          <p className="px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-muted">
            Global default rates (used when no personal rate exists)
          </p>
          <div className="divide-y divide-line">
            {(productivity.data?.global || []).map((g) => (
              <div key={g.link_type_name} className="flex items-center justify-between gap-3 p-3">
                <span className="text-sm font-medium text-ink">{g.link_type_name}</span>
                <input
                  type="number"
                  min={0.1}
                  step={0.5}
                  defaultValue={g.links_per_hour}
                  onBlur={(e) => {
                    const v = Number(e.target.value);
                    if (v > 0 && v !== g.links_per_hour)
                      saveProductivity.mutate({ link_type_name: g.link_type_name, links_per_hour: v });
                  }}
                  className="h-8 w-24 rounded-lg border border-line bg-panel px-2 text-right text-sm"
                />
              </div>
            ))}
            {!(productivity.data?.global || []).length ? <Empty label="No link types yet." /> : null}
          </div>
        </section>

        {/* Working-days calendar */}
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <div className="flex items-center justify-between border-b border-line p-3">
            <h3 className="text-sm font-semibold text-ink">Working days</h3>
            <div className="flex items-center gap-2 text-sm">
              <button onClick={() => setCalCursor((c) => (c.month === 1 ? { year: c.year - 1, month: 12 } : { ...c, month: c.month - 1 }))} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">←</button>
              <span className="font-medium text-ink">{calCursor.year}-{String(calCursor.month).padStart(2, "0")}</span>
              <button onClick={() => setCalCursor((c) => (c.month === 12 ? { year: c.year + 1, month: 1 } : { ...c, month: c.month + 1 }))} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">→</button>
            </div>
          </div>
          <div className="grid grid-cols-7 gap-1 p-3">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => (
              <div key={w} className="pb-1 text-center text-[10px] font-semibold uppercase tracking-wide text-muted">{w}</div>
            ))}
            {(() => {
              // Google-calendar alignment: pad so the 1st lands under its weekday.
              const first = calendar.data?.[0]?.day;
              const offset = first ? (new Date(first + "T00:00:00").getDay() + 6) % 7 : 0;
              return Array.from({ length: offset }).map((_, i) => <div key={"sp" + i} />);
            })()}
            {(calendar.data || []).map((d) => (
              <button
                key={d.day}
                onClick={() => toggleDay.mutate({ day: d.day, is_working: !d.is_working })}
                title={`${d.day} — ${d.is_working ? "working day" : "day off"} (click to change)`}
                className={clsx(
                  "h-9 rounded-lg border text-xs font-medium transition",
                  d.is_working
                    ? "border-ocean/30 bg-ocean/10 text-ocean"
                    : "border-line bg-field text-muted"
                )}
              >
                {Number(d.day.slice(8))}
              </button>
            ))}
          </div>
          <p className="border-t border-line p-2.5 text-[11px] text-muted">
            Default: Monday–Saturday working, Sunday off. Click any date to override. Off days don&apos;t
            count against anyone&apos;s completion.
          </p>
        </section>
      </div>

      {/* Leave */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Leave requests" />
        <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
          <input value={lvUser} onChange={(e) => setLvUser(e.target.value)} placeholder="User…" className="h-9 w-36 rounded-lg border border-line bg-panel px-2 text-sm" />
          <input type="date" value={lvFrom} onChange={(e) => setLvFrom(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <input type="date" value={lvTo} onChange={(e) => setLvTo(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <button
            onClick={() => requestLeave.mutate()}
            disabled={requestLeave.isPending || !lvUser.trim()}
            className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field disabled:opacity-50"
          >
            Request leave
          </button>
        </div>
        <div className="divide-y divide-line">
          {(leaves.data || []).map((l) => (
            <div key={l.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <div>
                <span className="font-medium text-ink">{l.user_label}</span>{" "}
                <span className="text-muted">{l.start_date} → {l.end_date}{l.reason ? ` · ${l.reason}` : ""}</span>
              </div>
              <div className="flex items-center gap-2">
                <Status value={l.status === "approved" ? "completed" : l.status === "rejected" ? "failed" : "pending"} />
                {l.status === "pending" ? (
                  <>
                    <button onClick={() => decideLeave.mutate({ id: l.id, approve: true })} className="text-xs font-medium text-ocean hover:underline">Approve</button>
                    <button onClick={() => decideLeave.mutate({ id: l.id, approve: false })} className="text-xs font-medium text-danger hover:underline">Reject</button>
                  </>
                ) : null}
              </div>
            </div>
          ))}
          {!leaves.isLoading && !(leaves.data || []).length ? <Empty label="No leave requests." /> : null}
        </div>
      </section>
    </section>
  );
}

// ── Shared: GSC-style chart, CSV export, help tips ──────────────────────────
// Interactive team benchmark: the FULL per-person distribution (not just an
// average) on a metric you pick, ranked, with this person highlighted and the
// team-average marker drawn in. Switch metric = flexible analysis; hover a row
// for its exact value. Shows the active metric + the timeframe it covers.
type BenchMember = { user_label: string; links: number; indexed: number; avg_score: number | null; qualified_rate: number; is_current: boolean };
const _BENCH_METRICS: Array<{ key: string; label: string; suffix?: string; integer?: boolean; get: (m: BenchMember) => number }> = [
  { key: "links", label: "Links built", integer: true, get: (m) => m.links },
  { key: "qualified_rate", label: "Qualified %", suffix: "%", get: (m) => m.qualified_rate },
  { key: "avg_score", label: "Avg QA score", get: (m) => m.avg_score ?? 0 },
  { key: "indexed", label: "Indexed links", integer: true, get: (m) => m.indexed }
];
function TeamDistribution({ members, caption }: { members: BenchMember[]; caption: string }) {
  const [metricKey, setMetricKey] = useState("links");
  const [hover, setHover] = useState<string | null>(null);
  const metric = _BENCH_METRICS.find((m) => m.key === metricKey) || _BENCH_METRICS[0];
  const fmt = (v: number) =>
    metric.integer ? `${Math.round(v).toLocaleString()}${metric.suffix || ""}` : `${Math.round(v * 10) / 10}${metric.suffix || ""}`;
  const rows = [...members].sort((a, b) => metric.get(b) - metric.get(a));
  const max = Math.max(1, ...rows.map((m) => metric.get(m)));
  const avg = rows.length ? rows.reduce((s, m) => s + metric.get(m), 0) / rows.length : 0;
  const curIdx = rows.findIndex((m) => m.is_current);
  return (
    <div className="pt-2">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        {_BENCH_METRICS.map((m) => (
          <button
            key={m.key}
            onClick={() => setMetricKey(m.key)}
            className={clsx(
              "h-7 rounded-full border px-2.5 text-xs font-medium transition",
              metricKey === m.key ? "border-ocean bg-ocean/10 text-ocean" : "border-line bg-panel text-muted hover:bg-field"
            )}
          >
            {m.label}
          </button>
        ))}
        <span className="ml-auto text-[11px] text-muted">
          {caption}{curIdx >= 0 ? ` · you rank #${curIdx + 1} of ${rows.length}` : ""}
        </span>
      </div>
      {/* A "Team average" reference row on top, then every member ranked. */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 rounded px-1 py-0.5">
          <span className="w-24 shrink-0 truncate text-[11px] font-medium text-ember">Team average</span>
          <div className="h-3 flex-1 overflow-hidden rounded-full bg-field">
            <div className="h-3 rounded-full border border-dashed border-ember bg-ember/20" style={{ width: `${Math.max(2, (avg / max) * 100)}%` }} />
          </div>
          <span className="w-14 shrink-0 text-right text-[11px] font-semibold tabular-nums text-ember">{fmt(avg)}</span>
        </div>
        {rows.map((m) => {
          const v = metric.get(m);
          return (
            <div
              key={m.user_label}
              className={clsx("flex items-center gap-2 rounded px-1 py-0.5", hover === m.user_label && "bg-field")}
              onMouseEnter={() => setHover(m.user_label)}
              onMouseLeave={() => setHover(null)}
              title={`${m.user_label} — ${metric.label}: ${fmt(v)}`}
            >
              <span className={clsx("w-24 shrink-0 truncate text-[11px]", m.is_current ? "font-semibold text-ocean" : "text-muted")}>
                {m.is_current ? `${m.user_label} (you)` : m.user_label}
              </span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-field">
                <div
                  className={clsx("h-3 rounded-full", m.is_current ? "bg-ocean" : "bg-muted/40")}
                  style={{ width: `${Math.max(2, (v / max) * 100)}%` }}
                />
              </div>
              <span className={clsx("w-14 shrink-0 text-right text-[11px] tabular-nums", m.is_current ? "font-semibold text-ink" : "text-muted")}>
                {fmt(v)}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-ocean" /> You</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-muted/40" /> Teammate</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm border border-dashed border-ember bg-ember/20" /> Team average</span>
      </div>
    </div>
  );
}

const _MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Human-friendly label for a chart bucket key. "2026-07-04" → "Jul 4"
// (axis) or "Jul 4, 2026" (tooltip); "2026-07" → "Jul 2026". Falls back to raw.
function fmtChartLabel(raw: string, withYear = false): string {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (d) {
    const mon = _MONTHS[parseInt(d[2], 10) - 1] || d[2];
    return withYear ? `${mon} ${parseInt(d[3], 10)}, ${d[1]}` : `${mon} ${parseInt(d[3], 10)}`;
  }
  const m = /^(\d{4})-(\d{2})$/.exec(raw);
  if (m) return `${_MONTHS[parseInt(m[2], 10) - 1] || m[2]} ${m[1]}`;
  return raw;
}

// Weekly dashboard buckets are date_trunc('week') → the bucket's Monday. Given
// that Monday ISO ("YYYY-MM-DD"), return the Sunday that closes its 7-day span.
// UTC math so the result never drifts by a day across timezones.
function weekEndIso(mondayIso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(mondayIso);
  if (!m) return mondayIso;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  d.setUTCDate(d.getUTCDate() + 6);
  return d.toISOString().slice(0, 10);
}
// Human label for a weekly bucket so a point reads as a WEEK, never a single day:
// "Week of May 18 – 24, 2026" (same month), "Week of May 30 – Jun 5, 2026"
// (month crossing), "Week of Dec 28, 2026 – Jan 3, 2027" (year crossing).
function weekRangeLabel(mondayIso: string): string {
  const a = /^(\d{4})-(\d{2})-(\d{2})$/.exec(mondayIso);
  const b = /^(\d{4})-(\d{2})-(\d{2})$/.exec(weekEndIso(mondayIso));
  if (!a || !b) return `Week of ${fmtChartLabel(mondayIso, true)}`;
  const mon1 = _MONTHS[+a[2] - 1] || a[2];
  const mon2 = _MONTHS[+b[2] - 1] || b[2];
  const d1 = +a[3];
  const d2 = +b[3];
  if (a[1] !== b[1]) return `Week of ${mon1} ${d1}, ${a[1]} – ${mon2} ${d2}, ${b[1]}`;
  if (mon1 !== mon2) return `Week of ${mon1} ${d1} – ${mon2} ${d2}, ${b[1]}`;
  return `Week of ${mon1} ${d1} – ${d2}, ${b[1]}`;
}
// "May 2026" for a monthly bucket (bucket start "YYYY-MM-01").
function monthLabel(firstIso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(firstIso);
  if (!m) return fmtChartLabel(firstIso, true);
  return `${_MONTHS[+m[2] - 1] || m[2]} ${m[1]}`;
}
// Tooltip/title label for a bucket start, per the active granularity.
function bucketLabel(iso: string, gran: string): string {
  if (gran === "day") return fmtChartLabel(iso, true);
  if (gran === "month") return monthLabel(iso);
  return weekRangeLabel(iso);
}
// Compact x-axis tick per granularity (month → "May '26", else the short date).
function bucketTick(iso: string, gran: string): string {
  if (gran === "month") {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (m) return `${_MONTHS[+m[2] - 1] || m[2]} '${m[1].slice(2)}`;
  }
  return fmtChartLabel(iso);
}
// The inclusive [from,to] date window a bucket covers, for drilling the grid so the
// chart total reconciles exactly with the grid's row count.
function bucketRange(iso: string, gran: string): { from: string; to: string } {
  if (gran === "day") return { from: iso, to: iso };
  if (gran === "month") {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!m) return { from: iso, to: iso };
    // day 0 of the next month = the last day of this month.
    const end = new Date(Date.UTC(+m[1], +m[2], 0));
    return { from: iso, to: end.toISOString().slice(0, 10) };
  }
  return { from: iso, to: weekEndIso(iso) };
}

// Modern 100%-stacked horizontal bar for a categorical mix (status, index state).
// Pure inline SVG-free (flex rects); each segment carries an exact count + share
// in its tooltip and is click-through to the matching Backlinks filter.
function StackedBar({
  segments,
  onSegmentClick
}: {
  segments: Array<{ name: string; value: number; cssVar: string }>;
  onSegmentClick?: (name: string) => void;
}) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((a, s) => a + s.value, 0);
  if (!total) return <Empty label="No data yet." />;
  return (
    <div>
      <div className="flex h-7 w-full overflow-hidden rounded-lg border border-line bg-field">
        {shown.map((s) => {
          const wPct = (s.value / total) * 100;
          return (
            <div
              key={s.name}
              title={`${s.name}: ${s.value.toLocaleString()} (${wPct.toFixed(1)}%)`}
              onClick={onSegmentClick ? () => onSegmentClick(s.name) : undefined}
              style={{ width: `${wPct}%`, background: `rgb(var(${s.cssVar}))` }}
              className={clsx(
                "h-full transition-all duration-500",
                onSegmentClick && "cursor-pointer hover:brightness-110"
              )}
            />
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {shown.map((s) => (
          <button
            key={s.name}
            onClick={onSegmentClick ? () => onSegmentClick(s.name) : undefined}
            className={clsx(
              "flex items-center gap-1.5 text-[11px] text-muted",
              onSegmentClick && "hover:text-ink"
            )}
          >
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: `rgb(var(${s.cssVar}))` }} />
            {s.name} <span className="font-semibold text-ink">{s.value.toLocaleString()}</span>
            <span>({total ? Math.round((s.value / total) * 100) : 0}%)</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// Interactive multi-series area/line chart used across every desk. Hover shows a
// crosshair + a floating card with the human date and each series' exact value;
// points are clickable; the latest point is emphasised; a subtle mount fade
// respects prefers-reduced-motion. Upgrading this lifts all charts at once.
// Reusable Day/Week/Month segmented control for every trend chart. `allowDay=false`
// disables Day so a long window (e.g. all-time) can't render thousands of daily dots;
// callers compute an effective granularity that falls back to week when Day is off.
function GranularityToggle({
  value,
  onChange,
  allowDay = true
}: {
  value: string;
  onChange: (g: string) => void;
  allowDay?: boolean;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-lg border border-line" role="group" aria-label="Chart detail">
      {(
        [["day", "Day"], ["week", "Week"], ["month", "Month"]] as Array<[string, string]>
      ).map(([v, l]) => {
        const disabled = v === "day" && !allowDay;
        return (
          <button
            key={v}
            type="button"
            disabled={disabled}
            onClick={() => onChange(v)}
            title={disabled ? "Pick a shorter timeframe to see day-by-day detail" : undefined}
            className={`h-8 px-2.5 text-xs font-medium transition-colors ${
              value === v
                ? "bg-ocean text-white dark:text-slate-900"
                : disabled
                ? "cursor-not-allowed bg-panel text-muted/40"
                : "bg-panel text-muted hover:bg-field"
            }`}
          >
            {l}
          </button>
        );
      })}
    </div>
  );
}

function TrendChart({
  labels,
  series,
  height = 170,
  onPointClick,
  valueFmt,
  labelFmt,
  tickFmt
}: {
  labels: string[];
  series: Array<{ name: string; cssVar: string; values: number[] }>;
  height?: number;
  onPointClick?: (index: number) => void;
  valueFmt?: (v: number) => string;
  // Overrides the tooltip's bucket label (title + floating card). Axis ticks keep
  // the short fmtChartLabel form unless tickFmt is given. Weekly charts pass
  // weekRangeLabel so a point reads as "Week of May 18 – 24" not a single "May 18".
  labelFmt?: (raw: string) => string;
  // Overrides the compact x-axis tick (e.g. "May '26" for monthly buckets).
  tickFmt?: (raw: string) => string;
}) {
  const W = 640;
  const H = height;
  const PADX = 34;
  const PADY = 22;
  const [hover, setHover] = useState<number | null>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 20);
    return () => clearTimeout(t);
  }, []);
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const n = labels.length;
  const x = (i: number) => (n <= 1 ? W / 2 : PADX + (i * (W - PADX * 2)) / (n - 1));
  const y = (v: number) => H - PADY - (v / max) * (H - PADY * 2);
  const fmtV = valueFmt || ((v: number) => String(v));
  const fmtLabel = labelFmt || ((raw: string) => fmtChartLabel(raw, true));
  if (!labels.length) return <Empty label="Not enough data for a chart yet." />;

  const pickIndex = (clientX: number, rect: DOMRect) => {
    const px = ((clientX - rect.left) / Math.max(1, rect.width)) * W; // → viewBox units
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(x(i) - px);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  };
  const hoverLeftPct = hover != null ? (x(hover) / W) * 100 : 0;

  return (
    <div className="relative">
      <div className="mb-1.5 flex flex-wrap gap-3 px-1">
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
            <span className="h-2 w-2 rounded-full" style={{ background: `rgb(var(${s.cssVar}))` }} />
            {s.name}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={`w-full touch-none${onPointClick ? " cursor-pointer" : ""}`}
        role="img"
        style={{ opacity: mounted ? 1 : 0, transition: "opacity .5s ease" }}
        onMouseMove={(e) => setHover(pickIndex(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => onPointClick?.(pickIndex(e.clientX, e.currentTarget.getBoundingClientRect()))}
      >
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={PADX} x2={W - PADX} y1={y(max * f)} y2={y(max * f)}
              stroke="rgb(var(--line))" strokeWidth="1" strokeDasharray={f === 0 ? "" : "3 4"}
            />
            <text x={PADX - 6} y={y(max * f) + 3} textAnchor="end" fontSize="9" fill="rgb(var(--muted))">
              {Math.round(max * f)}
            </text>
          </g>
        ))}
        {/* Crosshair at the hovered bucket. */}
        {hover != null ? (
          <line
            x1={x(hover)} x2={x(hover)} y1={PADY - 8} y2={H - PADY}
            stroke="rgb(var(--muted))" strokeWidth="1" strokeDasharray="2 3" opacity="0.5"
          />
        ) : null}
        {series.map((s) => {
          const pts = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
          const area = `M ${x(0)},${y(s.values[0] ?? 0)} ${s.values
            .map((v, i) => `L ${x(i)},${y(v)}`)
            .join(" ")} L ${x(s.values.length - 1)},${H - PADY} L ${x(0)},${H - PADY} Z`;
          return (
            <g key={s.name}>
              <path d={area} fill={`rgb(var(${s.cssVar}) / 0.10)`} />
              <polyline
                points={pts} fill="none" stroke={`rgb(var(${s.cssVar}))`}
                strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
              />
              {s.values.map((v, i) => {
                const isHover = hover === i;
                const isLast = i === n - 1;
                return (
                  <circle
                    key={i} cx={x(i)} cy={y(v)}
                    r={isHover ? 5 : isLast ? 3.5 : 2.5}
                    fill={`rgb(var(${s.cssVar}))`}
                    stroke="rgb(var(--panel))" strokeWidth={isHover || isLast ? 1.5 : 0}
                  >
                    <title>{`${fmtLabel(labels[i])} — ${s.name}: ${fmtV(v)}`}</title>
                  </circle>
                );
              })}
            </g>
          );
        })}
        {labels.map((l, i) =>
          n <= 8 || i === 0 || i === n - 1 || i % Math.ceil(n / 6) === 0 ? (
            <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="9" fill="rgb(var(--muted))">
              {tickFmt ? tickFmt(l) : fmtChartLabel(l)}
            </text>
          ) : null
        )}
      </svg>
      {/* Floating tooltip — follows the hovered bucket, clamped to the panel. */}
      {hover != null ? (
        <div
          className="pointer-events-none absolute top-6 z-10 -translate-x-1/2 rounded-lg border border-line bg-panel px-2.5 py-1.5 text-xs shadow-pop"
          style={{ left: `clamp(64px, ${hoverLeftPct}%, calc(100% - 64px))` }}
        >
          <div className="mb-0.5 font-semibold text-ink">{fmtLabel(labels[hover])}</div>
          {series.map((s) => (
            <div key={s.name} className="flex items-center gap-1.5 whitespace-nowrap text-muted">
              <span className="h-2 w-2 rounded-full" style={{ background: `rgb(var(${s.cssVar}))` }} />
              <span>{s.name}</span>
              <span className="ml-auto pl-2 font-semibold text-ink tabular-nums">{fmtV(s.values[hover] ?? 0)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// Grouped two-series bar chart (e.g. Target vs Done per week/person) with
// hover tooltips — same visual language as TrendChart.
function BarCompare({
  labels,
  a,
  b,
  aName,
  bName,
  aVar = "--line",
  bVar = "--ocean",
  height = 170,
  onClickIndex,
  labelFmt,
  tickFmt
}: {
  labels: string[];
  a: number[];
  b: number[];
  aName: string;
  bName: string;
  aVar?: string;
  bVar?: string;
  height?: number;
  onClickIndex?: (i: number) => void;
  labelFmt?: (raw: string) => string;
  tickFmt?: (raw: string) => string;
}) {
  const W = 640;
  const H = height;
  const PADX = 34;
  const PADY = 22;
  const max = Math.max(1, ...a, ...b);
  const n = Math.max(labels.length, 1);
  const slot = (W - PADX * 2) / n;
  const bw = Math.max(3, Math.min(22, slot * 0.32));
  const y = (v: number) => H - PADY - (v / max) * (H - PADY * 2);
  const fmtL = labelFmt || ((s: string) => s);
  const fmtT = tickFmt || ((s: string) => (s.length > 10 ? `${s.slice(0, 9)}…` : s));
  if (!labels.length) return <Empty label="Not enough data for a chart yet." />;
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap gap-3 px-1">
        {[[aName, aVar], [bName, bVar]].map(([name, cssVar]) => (
          <span key={name} className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
            <span className="h-2 w-2 rounded-sm" style={{ background: `rgb(var(${cssVar}))` }} />
            {name}
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1={PADX} x2={W - PADX} y1={y(max * f)} y2={y(max * f)}
              stroke="rgb(var(--line))" strokeWidth="1" strokeDasharray={f === 0 ? "" : "3 4"}
            />
            <text x={PADX - 6} y={y(max * f) + 3} textAnchor="end" fontSize="9" fill="rgb(var(--muted))">
              {Math.round(max * f)}
            </text>
          </g>
        ))}
        {labels.map((l, i) => {
          const cx = PADX + slot * i + slot / 2;
          const av = a[i] ?? 0;
          const bv = b[i] ?? 0;
          return (
            <g
              key={i}
              onClick={onClickIndex ? () => onClickIndex(i) : undefined}
              style={onClickIndex ? { cursor: "pointer" } : undefined}
            >
              <rect x={cx - bw - 1} y={y(av)} width={bw} height={Math.max(0, H - PADY - y(av))}
                rx="2" fill={`rgb(var(${aVar}) / 0.55)`}>
                <title>{`${fmtL(l)} — ${aName}: ${av}`}</title>
              </rect>
              <rect x={cx + 1} y={y(bv)} width={bw} height={Math.max(0, H - PADY - y(bv))}
                rx="2" fill={`rgb(var(${bVar}))`}>
                <title>{`${fmtL(l)} — ${bName}: ${bv}`}</title>
              </rect>
              {labels.length <= 10 || i === 0 || i === labels.length - 1 || i % Math.ceil(labels.length / 6) === 0 ? (
                <text x={cx} y={H - 6} textAnchor="middle" fontSize="9" fill="rgb(var(--muted))">
                  {fmtT(l)}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function downloadCsv(
  filename: string,
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>
) {
  const esc = (v: string | number | null | undefined) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const body = [headers.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([`﻿${body}`], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Copy text to the clipboard with an execCommand fallback (older browsers /
// non-secure contexts). Used by every CopyButton across the app.
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  }
}

// One-click copy with inline check feedback. Wrap any value users need to paste
// elsewhere (URLs, domains, task/recommendation details).
function CopyButton({ text, title = "Copy" }: { text: string; title?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async (e) => {
        e.stopPropagation();
        if (await copyToClipboard(text)) {
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        }
      }}
      title={title}
      aria-label={title}
      className="inline-flex shrink-0 items-center text-muted transition hover:text-ink"
    >
      {done ? <CheckCircle2 className="h-3.5 w-3.5 text-ocean" /> : <ClipboardCopy className="h-3.5 w-3.5" />}
    </button>
  );
}

function ExportButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title="Download what you see as a CSV file"
      className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
    >
      <Download className="h-3.5 w-3.5" /> Export
    </button>
  );
}

function HelpTip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex align-middle">
      <Info className="h-3.5 w-3.5 cursor-help text-muted transition group-hover:text-ocean" />
      <span className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-1.5 hidden w-72 -translate-x-1/2 rounded-lg border border-line bg-panel p-2.5 text-left text-xs font-normal normal-case leading-snug text-ink shadow-pop group-hover:block">
        {text}
      </span>
    </span>
  );
}

function DeltaPill({ now, prev }: { now: number; prev?: number | null }) {
  if (prev == null) return null;
  const d = now - prev;
  if (d === 0) return <span className="ml-1 text-[10px] text-muted">±0</span>;
  return (
    <span className={clsx("ml-1 text-[10px] font-semibold", d > 0 ? "text-ocean" : "text-danger")}>
      {d > 0 ? "+" : ""}{d}
    </span>
  );
}

// Read-only company working-days calendar (for user dashboards).
function MiniWorkCalendar({ token }: { token: string | null }) {
  const [cursor, setCursor] = useState(() => {
    const d = new Date();
    return { year: d.getFullYear(), month: d.getMonth() + 1 };
  });
  const cal = useQuery({
    queryKey: ["work-calendar", token, cursor.year, cursor.month],
    enabled: Boolean(token),
    queryFn: () =>
      api<Array<{ day: string; is_working: boolean; is_override: boolean }>>(
        `/workforce/calendar?year=${cursor.year}&month=${cursor.month}`,
        { token }
      )
  });
  return (
    <div>
      <div className="flex items-center justify-between pb-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Working days</span>
        <span className="flex items-center gap-1.5 text-xs">
          <button onClick={() => setCursor((c) => (c.month === 1 ? { year: c.year - 1, month: 12 } : { ...c, month: c.month - 1 }))} className="rounded border border-line px-1.5 py-0.5 hover:bg-field">←</button>
          <span className="font-medium text-ink">{cursor.year}-{String(cursor.month).padStart(2, "0")}</span>
          <button onClick={() => setCursor((c) => (c.month === 12 ? { year: c.year + 1, month: 1 } : { ...c, month: c.month + 1 }))} className="rounded border border-line px-1.5 py-0.5 hover:bg-field">→</button>
        </span>
      </div>
      <div className="grid grid-cols-7 gap-1">
        {(cal.data || []).map((d) => (
          <span
            key={d.day}
            title={`${d.day} — ${d.is_working ? "working day" : "day off"}`}
            className={clsx(
              "grid h-7 place-items-center rounded text-[11px] font-medium",
              d.is_working ? "bg-ocean/10 text-ocean" : "bg-field text-muted"
            )}
          >
            {Number(d.day.slice(8))}
          </span>
        ))}
      </div>
    </div>
  );
}

// One person's current week at a glance — plans, targets, completion, leave.
// Used by the admin per-user dashboard AND the user's own My Work page.
function UserWeekStrip({
  token,
  userLabel,
  projectId
}: {
  token: string | null;
  userLabel: string;
  projectId?: string;
}) {
  const fmtIso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const monday = (() => {
    const x = new Date();
    x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
    return fmtIso(x);
  })();
  const days = [...Array(7)].map((_, i) => {
    const d = new Date(`${monday}T00:00:00`);
    d.setDate(d.getDate() + i);
    return fmtIso(d);
  });
  type Row = {
    id: string; day: string; project_id: string; hours: number; expected_links: number;
    actual_links: number; completion_pct: number | null; excused: boolean;
    excuse_reason: string | null; priority: string | null; note: string | null;
    link_type_names: string[];
  };
  const rep = useQuery({
    queryKey: ["user-week", token, userLabel, monday, projectId || ""],
    enabled: Boolean(token) && Boolean(userLabel),
    queryFn: () =>
      api<Row[]>(
        `/workforce/day-report?date_from=${days[0]}&date_to=${days[6]}&user_label=${encodeURIComponent(userLabel)}${projectId ? `&project_id=${projectId}` : ""}`,
        { token }
      )
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const pName = (id: string) => (projectsQ.data || []).find((p) => p.id === id)?.name || "—";
  const rows = rep.data || [];
  const names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const target = rows.reduce((a, r) => a + (r.excused ? 0 : r.expected_links), 0);
  const done = rows.reduce((a, r) => a + (r.excused ? 0 : r.actual_links), 0);
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">
          This week — {userLabel}
        </span>
        <span className="text-xs text-muted">
          {done}/{target} links{target > 0 ? ` · ${Math.round((100 * done) / target)}%` : ""}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-7">
        {days.map((d, i) => {
          const cell = rows.filter((r) => r.day === d);
          return (
            <div key={d} className="rounded-lg border border-line bg-panel p-1.5">
              <div className="mb-1 text-[10px] font-semibold uppercase text-muted">
                {names[i]} {d.slice(8)}/{d.slice(5, 7)}
              </div>
              {cell.map((r) => (
                <div
                  key={r.id}
                  title={`${pName(r.project_id)} — ${r.hours}h · ${r.actual_links}/${r.expected_links}${r.excused ? ` · ${r.excuse_reason}` : ""}${r.note ? ` · ${r.note}` : ""}`}
                  className={clsx(
                    "mb-1 rounded border px-1 py-0.5 text-[10px] leading-tight",
                    r.excused
                      ? "border-line bg-field text-muted"
                      : (r.completion_pct ?? 0) >= 100
                        ? "border-ocean/40 bg-ocean/15 text-ocean"
                        : (r.completion_pct ?? 0) >= 60
                          ? "border-ember/40 bg-ember/15 text-ember"
                          : "border-danger/40 bg-danger/15 text-danger"
                  )}
                >
                  <span className="block truncate font-semibold">{pName(r.project_id)}</span>
                  {r.hours}h · {r.actual_links}/{r.expected_links}
                </div>
              ))}
              {!cell.length ? <span className="text-[10px] text-muted">—</span> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Admin user dashboard: one page with EVERYTHING about a person ───────────
function UserDashboard({
  token,
  userLabel,
  initialProjectId,
  onClose,
  onOpenBacklinks,
  onNotice,
  onPlanWork,
  selfView = false
}: {
  token: string | null;
  userLabel: string;
  initialProjectId?: string;
  onClose: () => void;
  onOpenBacklinks: (filters: Record<string, string>) => void;
  onNotice: (text: string) => void;
  onPlanWork?: () => void;
  // Viewer "My Dashboard": same KPIs/charts scoped to the signed-in person,
  // with every admin mutation (quick-plan, mark-leave, rate editing) hidden.
  // The backend enforces self-scoping regardless (visible_labels).
  selfView?: boolean;
}) {
  const queryClient = useQueryClient();
  // Default to All time — a person's dashboard should show their whole record,
  // not just the last month, until the viewer narrows the timeframe.
  const [days, setDays] = useState("3650");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [projFilter, setProjFilter] = useState(initialProjectId || "");
  const [ltFilter, setLtFilter] = useState("");
  const [historyStatus, setHistoryStatus] = useState("");
  const [dateType, setDateType] = useState<"created" | "checked" | "sheet">("created");
  const [projSort, setProjSort] = useState("links");
  const [projSortDir, setProjSortDir] = useState<"asc" | "desc">("desc");
  const [dashTab, setDashTab] = useState<"overview" | "projects" | "calendar" | "rates">("overview");
  const [gran, setGran] = useState("week");
  // Disable "Day" on windows long enough to render thousands of dots; fall back to week.
  const windowDays =
    days === "custom"
      ? customFrom && customTo
        ? Math.max(1, Math.round((Date.parse(customTo) - Date.parse(customFrom)) / 86400000))
        : 30
      : Number(days);
  const allowDay = windowDays <= 180;
  const effGran = gran === "day" && !allowDay ? "week" : gran;

  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const projectName = (id: string) => (projectsQ.data || []).find((p) => p.id === id)?.name || "—";
  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });

  const customReady = days !== "custom" || Boolean(customFrom && customTo);
  type DashPayload = {
    from: string; to: string; date_type?: string;
    links: Record<string, number | null>;
    plan: Record<string, number | null>;
    previous: { links: Record<string, number | null>; plan: Record<string, number | null> } | null;
    projects: Array<{ project_id: string; links: number; indexed: number; fail: number; project_new_domains: number; hours: number; target: number }>;
    by_type: Array<{ link_type: string; links: number; pass: number; indexed: number }>;
    team: {
      rank: number | null; of: number; avg_links: number; avg_indexed: number;
      avg_score: number | null; avg_qualified_rate: number | null; top_links: number; this_user_links: number;
      members?: Array<{ user_label: string; links: number; indexed: number; avg_score: number | null; qualified_rate: number; is_current: boolean }>;
    } | null;
    weekly: Array<{ week: string; links: number; indexed: number; pass: number; fail: number; new_domains: number }>;
    plan_weekly: Array<{ week: string; target: number; done: number }>;
    rates: { global: Array<{ link_type_name: string; links_per_hour: number }>; overrides: Array<{ link_type_name: string; links_per_hour: number }> };
    leaves: Array<{ id: string; start_date: string; end_date: string; reason: string | null; status: string }>;
  };
  const dash = useQuery({
    queryKey: ["user-dashboard", token, userLabel, days, customFrom, customTo, projFilter, ltFilter, dateType, effGran],
    enabled: Boolean(token) && customReady,
    queryFn: () => {
      const p = new URLSearchParams({ user_label: userLabel, compare: "true", granularity: effGran });
      if (days === "custom") {
        p.set("date_from", `${customFrom}T00:00:00Z`);
        p.set("date_to", `${customTo}T23:59:59Z`);
      } else p.set("days", days);
      if (projFilter) p.set("project_id", projFilter);
      if (ltFilter) p.set("link_type", ltFilter);
      if (dateType !== "created") p.set("date_type", dateType);
      return api<DashPayload>(`/performance/user-dashboard?${p.toString()}`, { token });
    }
  });

  // Recent task history (day report is capped at 92 days — window clamps).
  const fmtIso = (dt: Date) =>
    `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  const histTo = fmtIso(new Date());
  const histFrom = fmtIso(new Date(Date.now() - 60 * 86400000));
  type DayRow = {
    id: string; day: string; project_id: string; user_label: string; hours: number;
    link_type_names: string[]; expected_links: number; actual_links: number;
    completion_pct: number | null; excused: boolean; excuse_reason: string | null;
    priority: string | null; rate_source: string | null; lph_used: number | null; note: string | null;
  };
  const history = useQuery({
    queryKey: ["user-dash-history", token, userLabel, projFilter],
    enabled: Boolean(token),
    queryFn: () =>
      api<DayRow[]>(
        `/workforce/day-report?date_from=${histFrom}&date_to=${histTo}&user_label=${encodeURIComponent(userLabel)}${projFilter ? `&project_id=${projFilter}` : ""}`,
        { token }
      )
  });
  const weakest = useQuery({
    queryKey: ["user-dash-weakest", token, userLabel, projFilter],
    enabled: Boolean(token),
    queryFn: () => {
      const p = new URLSearchParams({ limit: "8", sort: "score" });
      p.set("assigned_user_label", userLabel);
      if (projFilter) p.set("project_id", projFilter);
      return api<Page<BacklinkRow>>(`/backlinks?${p.toString()}`, { token });
    }
  });

  // ── Calendar month with quick admin actions ─────────────────────────────
  const [calCursor, setCalCursor] = useState(() => {
    const dt = new Date();
    return { year: dt.getFullYear(), month: dt.getMonth() + 1 };
  });
  const monthFrom = `${calCursor.year}-${String(calCursor.month).padStart(2, "0")}-01`;
  const monthEnd = new Date(calCursor.year, calCursor.month, 0).getDate();
  const monthTo = `${calCursor.year}-${String(calCursor.month).padStart(2, "0")}-${String(monthEnd).padStart(2, "0")}`;
  const monthPlan = useQuery({
    queryKey: ["user-dash-month", token, userLabel, monthFrom, projFilter],
    enabled: Boolean(token),
    queryFn: () =>
      api<DayRow[]>(
        `/workforce/day-report?date_from=${monthFrom}&date_to=${monthTo}&user_label=${encodeURIComponent(userLabel)}${projFilter ? `&project_id=${projFilter}` : ""}`,
        { token }
      )
  });
  const monthCal = useQuery({
    queryKey: ["work-calendar", token, calCursor.year, calCursor.month],
    enabled: Boolean(token),
    queryFn: () =>
      api<Array<{ day: string; is_working: boolean; is_override: boolean }>>(
        `/workforce/calendar?year=${calCursor.year}&month=${calCursor.month}`,
        { token }
      )
  });
  const [quick, setQuick] = useState<{ day: string; row?: DayRow } | null>(null);
  const [qProject, setQProject] = useState("");
  const [qHours, setQHours] = useState("2");
  const [qTypes, setQTypes] = useState("");
  const [qPriority, setQPriority] = useState("medium");
  const [qTarget, setQTarget] = useState("");
  const [qNote, setQNote] = useState("");
  const openQuick = (day: string, row?: DayRow) => {
    if (selfView) return; // read-only calendar for the person's own view
    setQuick({ day, row });
    setQProject(row?.project_id || projFilter || "");
    setQHours(row ? String(row.hours) : "2");
    setQTypes(row ? row.link_type_names.join(",") : "");
    setQPriority(row?.priority || "medium");
    setQTarget(row && row.rate_source === "manual" ? String(row.expected_links) : "");
    setQNote(row?.note || "");
  };
  const saveQuick = useMutation({
    mutationFn: () =>
      api<{ expected_links: number; rate_source: string | null; lph_used: number | null; warnings: string[] }>(
        "/workforce/assignments",
        {
          token,
          method: "POST",
          body: JSON.stringify({
            project_id: qProject, user_label: userLabel, day: quick?.day,
            hours: Number(qHours) || 0,
            link_type_names: qTypes ? qTypes.split(",") : [],
            priority: qPriority || null,
            note: qNote.trim() || null,
            expected_links: qTarget.trim() ? Number(qTarget) : null
          })
        }
      ),
    onSuccess: (r) => {
      onNotice(`Saved — target ${r.expected_links} links.`);
      (r.warnings || []).forEach((w) => onNotice(`⚠ ${w}`));
      setQuick(null);
      queryClient.invalidateQueries({ queryKey: ["user-dash-month"] });
      queryClient.invalidateQueries({ queryKey: ["user-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["user-dash-history"] });
      queryClient.invalidateQueries({ queryKey: ["day-report"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const removeQuick = useMutation({
    mutationFn: (id: string) =>
      api<{ message: string }>(`/workforce/assignments/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Assignment removed");
      setQuick(null);
      queryClient.invalidateQueries({ queryKey: ["user-dash-month"] });
      queryClient.invalidateQueries({ queryKey: ["user-dashboard"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const markLeave = useMutation({
    mutationFn: async (day: string) => {
      const lv = await api<{ id: string }>("/workforce/leaves", {
        token,
        method: "POST",
        body: JSON.stringify({ user_label: userLabel, start_date: day, end_date: day, reason: "Marked by admin" })
      });
      return api<{ status: string }>(`/workforce/leaves/${lv.id}?approve=true`, { token, method: "PATCH" });
    },
    onSuccess: () => {
      onNotice("Leave marked (approved) — that day is excused.");
      queryClient.invalidateQueries({ queryKey: ["user-dash-month"] });
      queryClient.invalidateQueries({ queryKey: ["user-dashboard"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // Personal productivity rates — editable right here (mirrors the Tasks desk).
  const [rateDrafts, setRateDrafts] = useState<Record<string, string>>({});
  const saveRate = useMutation({
    mutationFn: (p: { link_type_name: string; links_per_hour: number }) =>
      api<{ message: string }>("/workforce/productivity", {
        token,
        method: "PUT",
        body: JSON.stringify({ user_label: userLabel, ...p })
      }),
    onSuccess: () => {
      onNotice("Personal rate saved");
      setRateDrafts({});
      queryClient.invalidateQueries({ queryKey: ["user-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["productivity"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const removeRate = useMutation({
    mutationFn: (link_type_name: string) =>
      api<{ message: string }>(
        `/workforce/productivity?user_label=${encodeURIComponent(userLabel)}&link_type_name=${encodeURIComponent(link_type_name)}`,
        { token, method: "DELETE" }
      ),
    onSuccess: () => {
      onNotice("Personal rate removed — the global rate applies again");
      queryClient.invalidateQueries({ queryKey: ["user-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["productivity"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const d = dash.data;
  const pv = d?.previous;
  const num = (v: number | null | undefined) => (v == null ? 0 : Number(v));
  const open = (extra: Record<string, string>) => onOpenBacklinks({ user: userLabel, ...extra });
  const onProjSort = (key: string) => {
    if (projSort === key) setProjSortDir((x) => (x === "asc" ? "desc" : "asc"));
    else { setProjSort(key); setProjSortDir(key === "project" ? "asc" : "desc"); }
  };

  const historyRows = (history.data || []).filter((r) => {
    if (historyStatus === "excused") return r.excused;
    if (historyStatus === "reached") return !r.excused && (r.completion_pct ?? 0) >= 100;
    if (historyStatus === "behind") return !r.excused && (r.completion_pct ?? 0) < 100;
    return true;
  });

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {!selfView ? (
          <button
            onClick={onClose}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            ← All people
          </button>
        ) : null}
        <div>
          <h2 className="text-base font-semibold text-ink">{selfView ? "My Dashboard" : userLabel}</h2>
          <p className="text-xs text-muted">
            {selfView ? "Your hours, targets, production and quality" : "User dashboard — hours, targets, production, quality"}
          </p>
        </div>
        {projFilter ? (
          <span className="flex items-center gap-1 rounded-full border border-ocean/40 bg-ocean/10 px-2.5 py-1 text-xs font-medium text-ocean">
            {projectName(projFilter)}
            <button onClick={() => setProjFilter("")} title="Remove the project filter — show all projects" className="hover:text-danger">×</button>
          </span>
        ) : (
          <span className="rounded-full bg-field px-2.5 py-1 text-xs font-medium text-muted">All projects</span>
        )}
        {onPlanWork ? (
          <button
            onClick={onPlanWork}
            title="Open the Tasks desk to plan this person's week"
            className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            <CalendarDays className="h-4 w-4" /> Plan work
          </button>
        ) : null}
        <span className="ml-auto" />
        <SearchSelect
          value={projFilter}
          onChange={setProjFilter}
          options={(projectsQ.data || []).map((p) => ({ value: p.id, label: p.name }))}
          placeholder="Project: all"
          width="w-44"
        />
        <SearchSelect
          value={ltFilter}
          onChange={setLtFilter}
          options={(linkTypes.data || []).map((lt) => ({ value: lt.name, label: linkTypeLabel(lt.name) }))}
          placeholder="Link type: all"
          width="w-40"
        />
        <select
          value={dateType}
          onChange={(e) => setDateType(e.target.value as "created" | "checked" | "sheet")}
          title="Which link date the window and trends measure — when the link was created/imported, last QA-checked, or its sheet-created date"
          className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
        >
          <option value="created">By created date</option>
          <option value="checked">By QA-check date</option>
          <option value="sheet">By sheet date</option>
        </select>
        <select value={days} onChange={(e) => setDays(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
          {TIMEFRAMES.map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
          <option value="custom">Custom range…</option>
        </select>
        {days === "custom" ? (
          <>
            <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
            <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          </>
        ) : null}
      </div>

      <span className="inline-flex rounded-lg border border-line bg-field/40 p-0.5 text-xs font-medium">
        {([
          ["overview", "Overview"],
          ["projects", "Projects"],
          ["calendar", "Plans & calendar"],
          ["rates", "Rates & leave"]
        ] as Array<["overview" | "projects" | "calendar" | "rates", string]>).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setDashTab(id)}
            className={clsx("rounded-md px-2.5 py-1 transition", dashTab === id ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
          >
            {label}
          </button>
        ))}
      </span>

      {dash.isLoading ? (
        <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
      ) : null}
      {dash.isError ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          Could not load this dashboard — {(dash.error as Error)?.message}
        </p>
      ) : null}

      {d && dashTab === "overview" ? (
        <>
          {/* Plan & effort */}
          <div className="grid gap-3 md:grid-cols-4">
            <Metric label="Hours assigned" value={num(d.plan.hours_assigned)} icon={CalendarDays} tone="ink"
              sub={`${num(d.plan.hours_counted)}h counted · ${num(d.plan.excused_days)} excused day${num(d.plan.excused_days) === 1 ? "" : "s"}${pv ? ` · prev: ${num(pv.plan.hours_assigned)}h` : ""}`}
              help="Total planned hours in this period. 'Counted' excludes days off and approved leave — those never count against anyone." />
            <Metric label="Target links" value={num(d.plan.target)} icon={Gauge} tone="ink"
              sub={`from ${num(d.plan.assignments)} assignment${num(d.plan.assignments) === 1 ? "" : "s"}${pv ? ` · prev: ${num(pv.plan.target)}` : ""}`}
              help="What the plans expected for this period (manual targets and personal/global rates all included, as saved at assignment time)." />
            <Metric label="Done vs plan" value={num(d.plan.done)} icon={CheckCircle2} tone="ocean"
              sub={pv ? `prev: ${num(pv.plan.done)}` : "links on planned project-days"}
              help="Links actually created on the planned days, per project." />
            <Metric label="Plan completion" value={d.plan.completion_pct != null ? `${d.plan.completion_pct}%` : "—"} icon={Activity}
              tone={(d.plan.completion_pct ?? 0) >= 100 ? "ocean" : "ember"}
              sub={pv && pv.plan.completion_pct != null ? `prev: ${pv.plan.completion_pct}%` : "excused days don't count"}
              help="Done ÷ target for the period, excusal-aware." />
          </div>

          {dateType === "sheet" && num(d.links.links) === 0 ? (
            <p className="rounded-lg border border-ember/40 bg-ember/10 p-2.5 text-xs text-ember">
              No links have a <b>sheet date</b> in this window — many rows were imported without one. Switch “By sheet date” back to “By created date” to see this person&apos;s production.
            </p>
          ) : null}

          {/* Link production — headline cards, each opens the exact rows */}
          <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-7">
            <Metric label="Links created" value={num(d.links.links)} icon={Link2} tone="ink"
              sub={pv ? `prev: ${num(pv.links.links)}` : undefined}
              onClick={() => open({})} help="All links credited to this person in the period. Click to see them." />
            <Metric label="New domains (project)" value={num(d.links.project_new_domains)} icon={Globe} tone="ocean"
              sub={pv ? `prev: ${num(pv.links.project_new_domains)}` : undefined}
              help="First-ever link from that domain inside its project." />
            <Metric label="New domains (overall)" value={num(d.links.global_new_domains)} icon={Globe} tone="plum"
              sub={pv ? `prev: ${num(pv.links.global_new_domains)}` : undefined}
              help="First time the domain appears anywhere in the workspace." />
            <Metric label="Qualified" value={num(d.links.pass)} icon={CheckCircle2} tone="ocean"
              sub={d.links.qualified_rate != null ? `${d.links.qualified_rate}% of created` : "pass QA"}
              onClick={() => open({ status: "PASS" })} help="Links that passed QA with no blocking issue. Click to see them." />
            <Metric label="Indexed" value={num(d.links.indexed)} icon={Activity} tone="ocean"
              sub={d.links.indexed_rate != null ? `${d.links.indexed_rate}% of checked` : `${pct(num(d.links.indexed), num(d.links.links))} of created`}
              onClick={() => open({ index_status: "indexed" })} help="Links Google shows in its index. Click to see them." />
            <Metric label="Not qualified" value={num(d.links.fail)} icon={XCircle} tone="danger"
              sub={pv ? `prev: ${num(pv.links.fail)}` : undefined}
              onClick={() => open({ status: "FAIL" })} help="Links with a serious problem. Click to see them." />
            <Metric label="Avg score" value={d.links.avg_score != null ? String(d.links.avg_score) : "—"} icon={Gauge}
              tone={d.links.avg_score == null ? "ink" : d.links.avg_score >= 70 ? "ocean" : d.links.avg_score >= 40 ? "ember" : "danger"}
              sub={pv && pv.links.avg_score != null ? `prev: ${pv.links.avg_score}` : "0–100 quality score"}
              help="Average QA score across this person's scored links (blank when nothing is scored yet)." />
          </div>

          {/* Full quality vocabulary — dense KPI row, matches Analytics */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
            <StatBox label="Qualified" value={num(d.links.pass)} tone="ocean" onClick={() => open({ status: "PASS" })} help="Passed QA. Click to see them." />
            <StatBox label="Warning" value={num(d.links.warning)} tone="ember" onClick={() => open({ status: "WARNING" })} help="Passed with a minor issue. Click to see them." />
            <StatBox label="Needs review" value={num(d.links.review)} tone="ember" onClick={() => open({ status: "NEEDS_MANUAL_REVIEW" })} help="A human needs to look (e.g. JS page / CAPTCHA). Click to see them." />
            <StatBox label="Unknown" value={num(d.links.unknown)} tone="ink" onClick={() => open({ status: "UNKNOWN" })} help="QA could not reach a verdict. Click to see them." />
            <StatBox label="QA pending" value={num(d.links.qa_pending)} tone="ember" onClick={() => open({ status: "PENDING" })} help="Never QA-checked yet. Click to see them." />
            <StatBox label="Not indexed" value={num(d.links.not_indexed)} tone="danger" onClick={() => open({ index_status: "not_indexed" })} help="Google does not show these. Click to see them." />
            <StatBox label="Index unchecked" value={num(d.links.index_unchecked)} tone="ink" help="Indexing not checked yet (domain-level count)." />
            <StatBox label="Dofollow" value={num(d.links.dofollow)} tone="ocean" onClick={() => open({ rel: "dofollow" })} help="Links that pass SEO value. Click to see them." />
            <StatBox label="Nofollow" value={num(d.links.nofollow)} tone="plum" onClick={() => open({ rel: "nofollow" })} help="Links marked nofollow. Click to see them." />
            <StatBox label="Link missing" value={num(d.links.link_missing)} tone="danger" help="The backlink was not found on the page." />
            <StatBox label="Duplicates" value={num(d.links.duplicates)} tone="plum" onClick={() => open({ duplicate_status: "duplicate" })} help="Another record already uses the page. Click to see them." />
          </div>

          {/* HTTP status of the source pages */}
          <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
            <SectionTitle title="Source-page HTTP status" flush />
            <div className="grid grid-cols-2 gap-2 pt-2 sm:grid-cols-4">
              <Issue label="2xx OK" value={num(d.links.http_2xx)} help="Source page loaded normally." />
              <Issue label="3xx redirect" value={num(d.links.http_3xx)} help="Source page redirects elsewhere." />
              <Issue label="4xx broken" value={num(d.links.http_4xx)} onClick={() => open({ http_class: "4xx" })} help="Page missing/blocked (404/403…). Click to see 4xx client errors." />
              <Issue label="5xx server" value={num(d.links.http_5xx)} onClick={() => open({ http_class: "5xx" })} help="Server error on the source site. Click to see 5xx server errors." />
            </div>
          </section>

          {/* Team benchmark — how this person compares to the visible team */}
          {d.team && d.team.of > 1 ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <SectionTitle title="Team benchmark" flush />
                <span className="rounded-full bg-ocean/10 px-3 py-1 text-xs font-semibold text-ocean">
                  Rank #{d.team.rank ?? "—"} of {d.team.of} by links
                </span>
              </div>
              <p className="pt-1 text-xs text-muted">
                Where this person sits in the whole team on the metric you pick — the full
                distribution, not just the average (so a high performer above the average is
                actually visible). Switch metric to analyze a different dimension.
              </p>
              {d.team.members && d.team.members.length ? (
                <TeamDistribution
                  members={d.team.members}
                  caption={`${fmtChartLabel(d.from, true)} → ${fmtChartLabel(d.to, true)}`}
                />
              ) : (
                <p className="pt-3 text-sm text-muted">Not enough team data for a comparison yet.</p>
              )}
            </section>
          ) : null}

          {/* Trends */}
          <div className="flex items-center justify-end">
            <GranularityToggle value={gran} onChange={setGran} allowDay={allowDay} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
              <SectionTitle title="Production trend" flush />
              <div className="pt-2">
                <TrendChart
                  labels={d.weekly.map((w) => w.week)}
                  labelFmt={(w) => bucketLabel(w, effGran)}
                  tickFmt={(w) => bucketTick(w, effGran)}
                  onPointClick={(i) => {
                    const w = d.weekly[i]?.week;
                    if (!w) return;
                    const r = bucketRange(w, effGran);
                    open({ placement_from: r.from, placement_to: r.to });
                  }}
                  series={[
                    { name: "Links created", cssVar: "--ocean", values: d.weekly.map((w) => w.links) },
                    { name: "Qualified", cssVar: "--plum", values: d.weekly.map((w) => w.pass) },
                    { name: "Indexed", cssVar: "--ember", values: d.weekly.map((w) => w.indexed) },
                    { name: "Not qualified", cssVar: "--danger", values: d.weekly.map((w) => w.fail) }
                  ]}
                />
              </div>
            </section>
            <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
              <SectionTitle title="Target vs done" flush />
              <div className="pt-2">
                <BarCompare
                  labels={d.plan_weekly.map((w) => w.week)}
                  labelFmt={(w) => bucketLabel(w, effGran)}
                  tickFmt={(w) => bucketTick(w, effGran)}
                  a={d.plan_weekly.map((w) => w.target)}
                  b={d.plan_weekly.map((w) => w.done)}
                  aName="Target"
                  bName="Done"
                />
              </div>
            </section>
          </div>

          {/* Link types built by this person */}
          {d.by_type.length ? (
            <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
              <SectionTitle title="Link types built" flush />
              <div className="space-y-1.5 pt-2">
                {(() => {
                  const maxType = Math.max(1, ...d.by_type.map((t) => t.links));
                  return d.by_type.map((t) => (
                    <button
                      key={t.link_type}
                      onClick={() => open(t.link_type === "(none)" ? { link_type: "(blanks)" } : { link_type: t.link_type })}
                      title="Click to see these links"
                      className="flex w-full items-center gap-2 text-left text-xs hover:opacity-80"
                    >
                      <span className="w-32 truncate font-medium text-ink">{linkTypeLabel(t.link_type)}</span>
                      <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-field">
                        <span className="block h-full rounded-full bg-ocean/70" style={{ width: `${Math.round((100 * t.links) / maxType)}%` }} />
                      </span>
                      <span className="w-24 text-right text-[11px] text-muted">{t.pass} qualified · {t.indexed} indexed</span>
                      <span className="w-10 text-right font-semibold text-ink">{t.links}</span>
                    </button>
                  ));
                })()}
              </div>
            </section>
          ) : null}
        </>
      ) : null}

      {d && dashTab === "projects" ? (
        <>
          {/* Per-project comparison — sortable + exportable */}
          <section className="rounded-xl border border-line bg-panel shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
              <h3 className="text-sm font-semibold text-ink">
                Projects — this person, side by side
                <HelpTip text="Every project this person worked on (or was planned for) in the window. Click a row to focus the whole dashboard on that project; click a header to sort." />
              </h3>
              <ExportButton
                disabled={!d.projects.length}
                onClick={() =>
                  downloadCsv(
                    `${userLabel}-projects.csv`,
                    ["Project", "Hours", "Target", "Links", "Completion %", "Indexed", "Not qualified", "New domains"],
                    d.projects.map((p) => [
                      projectName(p.project_id), p.hours, p.target, p.links,
                      p.target > 0 ? Math.round((100 * p.links) / p.target) : "",
                      p.indexed, p.fail, p.project_new_domains
                    ])
                  )
                }
              />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-field text-xs uppercase text-muted">
                  <tr>
                    <SortTh label="Project" sortKey="project" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Hours" sortKey="hours" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Target" sortKey="target" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Links" sortKey="links" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Completion" sortKey="completion" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Indexed" sortKey="indexed" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="Not qualified" sortKey="fail" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                    <SortTh label="New domains" sortKey="new_domains" sort={projSort} dir={projSortDir} onSort={onProjSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {sortRows(d.projects, projSort, projSortDir, (p, k) => {
                    if (k === "project") return projectName(p.project_id);
                    if (k === "completion") return p.target > 0 ? (100 * p.links) / p.target : null;
                    if (k === "new_domains") return p.project_new_domains;
                    return (p as unknown as Record<string, number>)[k];
                  }).map((p) => {
                    const cpl = p.target > 0 ? Math.round((100 * p.links) / p.target) : null;
                    const maxLinks = Math.max(1, ...d.projects.map((x) => x.links));
                    return (
                      <tr
                        key={p.project_id}
                        onClick={() => setProjFilter(projFilter === p.project_id ? "" : p.project_id)}
                        title="Click to focus the whole dashboard on this project"
                        className={clsx("cursor-pointer hover:bg-field/60", projFilter === p.project_id && "bg-ocean/5")}
                      >
                        <Td><span className="font-medium text-ocean hover:underline">{projectName(p.project_id)}</span></Td>
                        <Td>{p.hours}h</Td>
                        <Td>{p.target}</Td>
                        <Td>
                          <span className="flex items-center gap-2">
                            <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-field sm:block">
                              <span className="block h-full rounded-full bg-ocean/70" style={{ width: `${Math.round((100 * p.links) / maxLinks)}%` }} />
                            </span>
                            {p.links}
                          </span>
                        </Td>
                        <Td>
                          {cpl == null ? "—" : (
                            <span className={clsx("rounded px-2 py-0.5 text-xs font-semibold",
                              cpl >= 100 ? "bg-ocean/10 text-ocean" : cpl >= 60 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger")}>
                              {cpl}%
                            </span>
                          )}
                        </Td>
                        <Td>{p.indexed}</Td>
                        <Td><span className="text-danger">{p.fail}</span></Td>
                        <Td>{p.project_new_domains}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!d.projects.length ? <Empty label="No activity in this period." /> : null}
            </div>
          </section>
        </>
      ) : null}

      {d && dashTab === "rates" ? (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {/* Rates in effect — with an inline personal-override editor */}
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="Productivity (links per hour) — personal rate beats global" />
              <div className="divide-y divide-line">
                {d.rates.global.map((g) => {
                  const ov = d.rates.overrides.find((o) => o.link_type_name.toLowerCase() === g.link_type_name.toLowerCase());
                  const draft = rateDrafts[g.link_type_name] ?? "";
                  return (
                    <div key={g.link_type_name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                      <span className="font-medium text-ink">{linkTypeLabel(g.link_type_name)}</span>
                      <span className="flex items-center gap-2">
                        {ov ? (
                          <>
                            <span className="rounded bg-plum/10 px-2 py-0.5 text-xs font-semibold text-plum" title="This person's own rate — wins over the global default">
                              {ov.links_per_hour}/h personal
                            </span>
                            <span className="text-xs text-muted line-through">{g.links_per_hour}/h global</span>
                            {!selfView ? (
                              <button
                                onClick={() => removeRate.mutate(ov.link_type_name)}
                                disabled={removeRate.isPending}
                                title="Drop the personal rate — the global rate applies again"
                                className="text-xs text-muted hover:text-danger hover:underline disabled:opacity-40"
                              >
                                Remove
                              </button>
                            ) : null}
                          </>
                        ) : (
                          <span className="text-xs text-muted">{g.links_per_hour}/h global</span>
                        )}
                        {!selfView ? (
                          <>
                            <input
                              type="number"
                              min={0.1}
                              step={0.5}
                              value={draft}
                              onChange={(e) => setRateDrafts((x) => ({ ...x, [g.link_type_name]: e.target.value }))}
                              placeholder={ov ? String(ov.links_per_hour) : "own rate"}
                              title={`Personal ${linkTypeLabel(g.link_type_name)} rate for ${userLabel}`}
                              className="h-8 w-24 rounded-lg border border-line bg-panel px-2 text-right text-sm"
                            />
                            <button
                              onClick={() => saveRate.mutate({ link_type_name: g.link_type_name, links_per_hour: Number(draft) })}
                              disabled={saveRate.isPending || !(Number(draft) > 0)}
                              className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:bg-field disabled:opacity-40"
                            >
                              Save
                            </button>
                          </>
                        ) : null}
                      </span>
                    </div>
                  );
                })}
                {!d.rates.global.length ? <Empty label="No productivity rates configured yet." /> : null}
              </div>
            </section>

            {/* Leave & absence history */}
            <section className="rounded-xl border border-line bg-panel shadow-card">
              <SectionTitle title="Leave history" />
              <div className="divide-y divide-line">
                {d.leaves.map((l) => (
                  <div key={l.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                    <span className="text-ink">
                      {formatDay(l.start_date)} → {formatDay(l.end_date)}
                      {l.reason ? <span className="text-muted"> · {l.reason}</span> : null}
                    </span>
                    <Status value={l.status === "approved" ? "completed" : l.status === "rejected" ? "failed" : "pending"} />
                  </div>
                ))}
                {!d.leaves.length ? <Empty label="No leave requests." /> : null}
              </div>
            </section>
          </div>
        </>
      ) : null}

      {dashTab === "calendar" ? (
        <>
      {/* Calendar with admin quick actions */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">
            {userLabel}&apos;s calendar
            <HelpTip text="Every day's plans for this person: project, hours, done/target, plus days off (gray) and approved leave (purple). Click a plan to edit it, '+' to add one, or mark a leave day — history snapshots stay intact (editing a day only changes that day)." />
          </h3>
          <div className="flex items-center gap-2 text-sm">
            <button onClick={() => setCalCursor((c) => (c.month === 1 ? { year: c.year - 1, month: 12 } : { ...c, month: c.month - 1 }))} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">←</button>
            <span className="font-medium text-ink">{calCursor.year}-{String(calCursor.month).padStart(2, "0")}</span>
            <button onClick={() => setCalCursor((c) => (c.month === 12 ? { year: c.year + 1, month: 1 } : { ...c, month: c.month + 1 }))} className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-field">→</button>
          </div>
        </div>
        <div className="grid grid-cols-7 gap-1 p-3">
          {(monthCal.data || []).map((cd) => {
            const rows = (monthPlan.data || []).filter((r) => r.day === cd.day);
            const onLeave = rows.some((r) => r.excused && r.excuse_reason === "On approved leave");
            return (
              <div
                key={cd.day}
                className={clsx(
                  "min-h-[74px] rounded-lg border p-1",
                  cd.is_working ? "border-line bg-panel" : "border-line bg-field/60 opacity-70"
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-semibold text-muted">{Number(cd.day.slice(8))}</span>
                  <span className="flex items-center gap-0.5">
                    {!selfView && !onLeave && cd.is_working ? (
                      <button
                        onClick={() => markLeave.mutate(cd.day)}
                        title={`Mark ${cd.day} as approved leave for ${userLabel}`}
                        className="rounded px-1 text-[10px] text-muted hover:bg-plum/10 hover:text-plum"
                      >
                        lv
                      </button>
                    ) : null}
                    {!selfView ? (
                      <button
                        onClick={() => openQuick(cd.day)}
                        title={`Plan work for ${userLabel} on ${cd.day}`}
                        className="rounded px-1 text-[11px] text-muted hover:bg-ocean/10 hover:text-ocean"
                      >
                        +
                      </button>
                    ) : null}
                  </span>
                </div>
                {onLeave ? (
                  <span className="mt-0.5 block rounded bg-plum/15 px-1 py-0.5 text-[9px] font-semibold text-plum">On leave</span>
                ) : null}
                {rows.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => openQuick(cd.day, r)}
                    title={`${projectName(r.project_id)} — ${r.hours}h · ${r.actual_links}/${r.expected_links}${r.note ? ` · ${r.note}` : ""}. Click to edit.`}
                    className={clsx(
                      "mt-0.5 block w-full truncate rounded border px-1 py-0.5 text-left text-[9px] font-medium leading-tight",
                      r.excused
                        ? "border-line bg-field text-muted"
                        : (r.completion_pct ?? 0) >= 100
                          ? "border-ocean/40 bg-ocean/15 text-ocean"
                          : (r.completion_pct ?? 0) >= 60
                            ? "border-ember/40 bg-ember/15 text-ember"
                            : "border-danger/40 bg-danger/15 text-danger"
                    )}
                  >
                    {projectName(r.project_id)} · {r.hours}h · {r.actual_links}/{r.expected_links}
                  </button>
                ))}
              </div>
            );
          })}
        </div>
        {quick ? (
          <div className="border-t border-line bg-field/40 p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
              {quick.row ? "Edit plan" : "New plan"} — {userLabel} · {formatDay(quick.day)}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <SearchSelect
                value={qProject}
                onChange={setQProject}
                options={(projectsQ.data || []).map((p) => ({ value: p.id, label: p.name }))}
                placeholder="Project…"
                width="w-48"
              />
              <input type="number" min={0} max={24} step={0.5} value={qHours} onChange={(e) => setQHours(e.target.value)} title="Hours" className="h-9 w-20 rounded-lg border border-line bg-panel px-2 text-sm" />
              <FilterMultiSelect
                label="Link types"
                options={(linkTypes.data || []).map((lt) => ({ value: lt.name, label: linkTypeLabel(lt.name) }))}
                selected={qTypes ? qTypes.split(",") : []}
                onChange={(v) => setQTypes(v.join(","))}
              />
              <select value={qPriority} onChange={(e) => setQPriority(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
              <input type="number" min={0} value={qTarget} onChange={(e) => setQTarget(e.target.value)} placeholder="Target (auto)" title="Manual target override — highest priority" className="h-9 w-28 rounded-lg border border-line bg-panel px-2 text-sm" />
              <input value={qNote} onChange={(e) => setQNote(e.target.value)} placeholder="Note…" className="h-9 w-48 rounded-lg border border-line bg-panel px-2 text-sm" />
              <button
                onClick={() => saveQuick.mutate()}
                disabled={saveQuick.isPending || !qProject}
                className="h-9 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
              >
                Save
              </button>
              {quick.row ? (
                <button
                  onClick={() => {
                    if (window.confirm(`Remove this plan (${projectName(quick.row!.project_id)} on ${quick.day})?`))
                      removeQuick.mutate(quick.row!.id);
                  }}
                  className="h-9 rounded-lg border border-danger/40 px-3 text-sm font-medium text-danger transition hover:bg-danger/10"
                >
                  Remove
                </button>
              ) : null}
              <button onClick={() => setQuick(null)} className="text-xs font-medium text-muted hover:text-ink hover:underline">Cancel</button>
            </div>
          </div>
        ) : null}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Task completion history */}
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <div className="flex items-center justify-between border-b border-line p-3">
            <h3 className="text-sm font-semibold text-ink">Task history (last 60 days)</h3>
            <select value={historyStatus} onChange={(e) => setHistoryStatus(e.target.value)} className="h-8 rounded-lg border border-line bg-panel px-2 text-xs">
              <option value="">All days</option>
              <option value="reached">Target reached</option>
              <option value="behind">Behind target</option>
              <option value="excused">Excused (leave/day off)</option>
            </select>
          </div>
          <div className="max-h-72 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-field text-xs uppercase text-muted">
                <tr><Th>Date</Th><Th>Project</Th><Th>Hours</Th><Th>Done / target</Th><Th>Result</Th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {historyRows.map((r) => (
                  <tr key={r.id} className="hover:bg-field/60">
                    <Td><span className="whitespace-nowrap text-xs">{formatDay(r.day)}</span></Td>
                    <Td><span className="text-xs">{projectName(r.project_id)}</span></Td>
                    <Td>{r.hours}h</Td>
                    <Td>{r.actual_links}/{r.expected_links}</Td>
                    <Td>
                      {r.excused ? (
                        <span className="rounded bg-field px-1.5 py-0.5 text-[11px] font-medium text-muted" title={r.excuse_reason || ""}>Excused</span>
                      ) : r.completion_pct == null ? "—" : (
                        <span className={clsx("rounded px-1.5 py-0.5 text-[11px] font-semibold",
                          r.completion_pct >= 100 ? "bg-ocean/10 text-ocean" : r.completion_pct >= 60 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger")}>
                          {r.completion_pct}%
                        </span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!history.isLoading && !historyRows.length ? <Empty label="No task history for this filter." /> : null}
          </div>
        </section>

        {/* Weakest links */}
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Weakest links (lowest score first)" />
          <div className="space-y-1 p-3">
            {(weakest.data?.items || []).map((r) => (
              <div key={r.id} className="flex items-center gap-2 text-xs">
                <Status value={r.override_status || r.status} reason={r.top_issue_label} compact />
                <span className="w-8 text-right font-semibold">{r.score ?? "-"}</span>
                <a href={r.source_page_url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-ocean hover:underline">
                  {r.source_page_url}
                </a>
                <span className="shrink-0 text-muted">{linkTypeLabel(r.link_type) || ""}</span>
              </div>
            ))}
            {!(weakest.data?.items || []).length ? <Empty label="No links in this scope." /> : null}
            <button onClick={() => open({})} className="pt-1 text-xs font-medium text-ocean hover:underline">
              Open all of {userLabel}&apos;s links →
            </button>
          </div>
        </section>
      </div>
        </>
      ) : null}
    </section>
  );
}

// ── Project effort: who works how much on THIS project, target vs done ──────
function ProjectEffort({
  token,
  projectId,
  onOpenBacklinks
}: {
  token: string | null;
  projectId: string;
  onOpenBacklinks: (filters: Record<string, string>) => void;
}) {
  const [days, setDays] = useState("30");
  const [userF, setUserF] = useState("");
  const [ltF, setLtF] = useState("");
  const [gran, setGran] = useState("week");
  const allowDay = Number(days) <= 180;
  const effGran = gran === "day" && !allowDay ? "week" : gran;
  const knownLabels = useQuery({
    queryKey: ["workforce-labels", token],
    enabled: Boolean(token),
    queryFn: () => api<string[]>("/workforce/labels", { token })
  });
  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  type Effort = {
    totals: { hours: number; target: number; links: number; indexed: number; fail: number; qa_pending: number; duplicates: number; users: number; completion_pct: number | null };
    users: Array<{ user_label: string; links: number; indexed: number; fail: number; qa_pending: number; duplicates: number; hours: number; target: number; completion_pct: number | null }>;
    by_type: Array<{ link_type: string; links: number }>;
    weekly: Array<{ week: string; done: number; target: number }>;
  };
  const eff = useQuery({
    queryKey: ["project-effort", token, projectId, days, userF, ltF, effGran],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => {
      const p = new URLSearchParams({ project_id: projectId, days, granularity: effGran });
      if (userF) p.set("user_label", userF);
      if (ltF) p.set("link_type", ltF);
      return api<Effort>(`/performance/project-effort?${p.toString()}`, { token });
    }
  });
  const d = eff.data;
  const maxType = Math.max(1, ...(d?.by_type || []).map((t) => t.links));
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          Project effort
          <HelpTip text="Who is working on this project and what it produces: planned hours, targets, links done, quality — per person, with a weekly trend. Every number is clickable." />
        </h3>
        <div className="flex flex-wrap items-center gap-2">
          <SearchSelect
            value={userF}
            onChange={setUserF}
            options={(knownLabels.data || []).map((l) => ({ value: l }))}
            placeholder="Person: everyone"
            width="w-44"
          />
          <SearchSelect
            value={ltF}
            onChange={setLtF}
            options={(linkTypes.data || []).map((lt) => ({ value: lt.name, label: linkTypeLabel(lt.name) }))}
            placeholder="Link type: all"
            width="w-40"
          />
          <GranularityToggle value={gran} onChange={setGran} allowDay={allowDay} />
          <select value={days} onChange={(e) => setDays(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
            {TIMEFRAMES.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </div>
      </div>

      {d ? (
        <>
          <div className="grid gap-3 p-3 md:grid-cols-3 xl:grid-cols-6">
            <Metric label="People working" value={d.totals.users} icon={Users} tone="ink"
              help="People with links or planned hours on this project in the period." />
            <Metric label="Hours assigned" value={d.totals.hours} icon={CalendarDays} tone="ink"
              help="Planned hours on this project in the period." />
            <Metric label="Target links" value={d.totals.target} icon={Gauge} tone="ink"
              help="What the plans expected for this period." />
            <Metric label="Links created" value={d.totals.links} icon={Link2} tone="ocean"
              sub={d.totals.completion_pct != null ? `${d.totals.completion_pct}% of target` : undefined}
              onClick={() => onOpenBacklinks({})} help="Links created on this project in the period. Click to see them." />
            <Metric label="QA pending" value={d.totals.qa_pending} icon={History} tone="ember"
              onClick={() => onOpenBacklinks({ status: "PENDING" })} help="Created in this period, never checked yet. Click to see them." />
            <Metric label="Not qualified" value={d.totals.fail} icon={XCircle} tone="danger"
              onClick={() => onOpenBacklinks({ status: "FAIL" })} help="Created in this period with a serious problem. Click to see them." />
          </div>

          <div className="grid gap-4 p-3 pt-0 lg:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Target vs done — weekly</p>
              <BarCompare
                labels={d.weekly.map((w) => w.week)}
                labelFmt={(w) => bucketLabel(w, effGran)}
                tickFmt={(w) => bucketTick(w, effGran)}
                a={d.weekly.map((w) => w.target)}
                b={d.weekly.map((w) => w.done)}
                aName="Target"
                bName="Done"
                onClickIndex={(i) => {
                  const w = d.weekly[i]?.week;
                  if (!w) return;
                  const r = bucketRange(w, effGran);
                  onOpenBacklinks({ placement_from: r.from, placement_to: r.to });
                }}
              />
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Link types built in this period</p>
              <div className="space-y-1.5">
                {d.by_type.map((t) => (
                  <button
                    key={t.link_type}
                    onClick={() => onOpenBacklinks(t.link_type === "(none)" ? { link_type: "(blanks)" } : { link_type: t.link_type })}
                    title="Click to see these links"
                    className="flex w-full items-center gap-2 text-left text-xs hover:opacity-80"
                  >
                    <span className="w-32 truncate font-medium text-ink">{linkTypeLabel(t.link_type)}</span>
                    <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-field">
                      <span className="block h-full rounded-full bg-ocean/70" style={{ width: `${Math.round((100 * t.links) / maxType)}%` }} />
                    </span>
                    <span className="w-10 text-right font-semibold text-ink">{t.links}</span>
                  </button>
                ))}
                {!d.by_type.length ? <p className="text-xs text-muted">No links in this period.</p> : null}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto border-t border-line">
            <table className="w-full text-left text-sm">
              <thead className="bg-field text-xs uppercase text-muted">
                <tr>
                  <Th>Person</Th><Th>Hours</Th><Th>Target</Th><Th>Links</Th><Th>Completion</Th>
                  <Th>Indexed</Th><Th>QA pending</Th><Th>Not qualified</Th><Th>Duplicates</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {d.users.map((u) => (
                  <tr key={u.user_label} className="hover:bg-field/60">
                    <Td>
                      <button
                        onClick={() => onOpenBacklinks({ user: u.user_label })}
                        title={`See ${u.user_label}'s links on this project`}
                        className="font-medium text-ocean hover:underline"
                      >
                        {u.user_label}
                      </button>
                    </Td>
                    <Td>{u.hours}h</Td>
                    <Td>{u.target}</Td>
                    <Td>{u.links}</Td>
                    <Td>
                      {u.completion_pct == null ? "—" : (
                        <span className={clsx("rounded px-2 py-0.5 text-xs font-semibold",
                          u.completion_pct >= 100 ? "bg-ocean/10 text-ocean" : u.completion_pct >= 60 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger")}>
                          {u.completion_pct}%
                        </span>
                      )}
                    </Td>
                    <Td>{u.indexed}</Td>
                    <Td>{u.qa_pending}</Td>
                    <Td><span className="text-danger">{u.fail}</span></Td>
                    <Td>{u.duplicates}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!d.users.length ? <Empty label="No effort recorded in this period." /> : null}
          </div>
        </>
      ) : eff.isLoading ? (
        <div className="flex justify-center p-6"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : null}
    </section>
  );
}

const TIMEFRAMES: Array<[string, string]> = [
  ["30", "Last 30 days"],
  ["90", "Last 3 months"],
  ["180", "Last 6 months"],
  ["365", "Last 12 months"],
  ["3650", "All time"]
];

// ── User Dashboards — its own desk. Pick a person (or arrive via ?f_user) and
// the full per-person dashboard takes over; otherwise a browsable people grid. ──
function UserDashboardsDesk({
  token,
  projectId,
  onOpenBacklinks,
  onNotice,
  onPlanWork
}: {
  token: string | null;
  projectId: string;
  onOpenBacklinks: (filters: Record<string, string>) => void;
  onNotice: (text: string) => void;
  onPlanWork?: () => void;
}) {
  const [person, setPerson] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new URLSearchParams(window.location.search).get("f_user") || "";
  });
  // Deep link: "Open dashboard" from Performance rows lands here with ?f_user=<label>
  // (mirrors the Batches f_batch reader) — consume it once, then clean the URL.
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const target = q.get("f_user");
    if (target) {
      setPerson(target);
      q.delete("f_user");
      window.history.replaceState(null, "", `${window.location.pathname}${q.toString() ? `?${q.toString()}` : ""}`);
    }
  }, []);

  // The grid + finder list EVERYONE with history (incl. laid-off) — this is a
  // view, not a planning picker, so a laid-off person's work still shows.
  const people = useQuery({
    queryKey: ["workforce-people", token, projectId],
    enabled: Boolean(token),
    queryFn: () => api<Array<{ user_label: string; active: boolean }>>(
      `/workforce/people${projectId ? `?project_id=${projectId}` : ""}`,
      { token }
    )
  });

  type DeskUser = {
    user_label: string; links: number; indexed: number; pass: number; fail: number;
    duplicates: number; avg_score: number | null;
    project_new_domains: number; global_new_domains: number;
  };
  const team = useQuery({
    queryKey: ["user-dashboards-team", token, projectId],
    enabled: Boolean(token) && !person,
    queryFn: () => {
      // All-time counts for the cards (the grid shows total links per person).
      const p = new URLSearchParams({ days: "3650", compare: "false" });
      if (projectId) p.set("project_id", projectId);
      return api<{ users: DeskUser[] }>(`/performance/users?${p.toString()}`, { token });
    }
  });

  if (person)
    return (
      <UserDashboard
        token={token}
        userLabel={person}
        initialProjectId={projectId || undefined}
        onClose={() => setPerson("")}
        onOpenBacklinks={onOpenBacklinks}
        onNotice={onNotice}
        onPlanWork={onPlanWork}
      />
    );

  // The grid lists EVERY known person (not just those with links in the last 30
  // days) — activity is a stat, not a filter. Merge the full label list with the
  // windowed activity so people with no recent links still get a card (0 links).
  const activity = new Map((team.data?.users || []).map((u) => [u.user_label, u]));
  const activeMap = new Map((people.data || []).map((p) => [p.user_label, p.active]));
  const labelSet = Array.from(
    new Set([...(people.data || []).map((p) => p.user_label), ...(team.data?.users || []).map((u) => u.user_label)])
  );
  const users: DeskUser[] = labelSet
    .map(
      (l) =>
        activity.get(l) || {
          user_label: l, links: 0, indexed: 0, pass: 0, fail: 0,
          duplicates: 0, avg_score: null, project_new_domains: 0, global_new_domains: 0,
        }
    )
    .sort((a, b) => b.links - a.links || a.user_label.localeCompare(b.user_label));
  const loading = team.isLoading || people.isLoading;
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
            User Dashboards
            <HelpTip text="Open any person's full dashboard — hours, targets, production, quality, calendar and trends. Pick a name or click a card." />
          </h2>
          <p className="text-sm text-muted">
            {projectId ? "This project only." : "All people across the workspace."} Choose someone to see their full dashboard.
          </p>
        </div>
        <SearchSelect
          value={person}
          onChange={setPerson}
          options={(people.data || []).map((p) => ({ value: p.user_label, label: p.active ? p.user_label : `${p.user_label} (laid off)` }))}
          placeholder="Find a person…"
          width="w-64"
        />
      </div>

      {loading ? (
        <div className="flex justify-center p-10"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
      ) : null}
      {team.isError ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          Could not load people — {(team.error as Error)?.message}
        </p>
      ) : null}

      {!loading && !team.isError ? (
        users.length ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {users.map((u) => {
              const rate = u.links > 0 ? Math.round((100 * u.indexed) / u.links) : null;
              return (
                <button
                  key={u.user_label}
                  onClick={() => setPerson(u.user_label)}
                  title={`Open ${u.user_label}'s dashboard`}
                  className="flex flex-col gap-2 rounded-xl border border-line bg-panel p-4 text-left shadow-card transition hover:border-ocean/40 hover:bg-field/40"
                >
                  <span className="flex items-center gap-2">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ocean/10 text-ocean">
                      <Users className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1 truncate font-semibold text-ink">{u.user_label}</span>
                    {activeMap.get(u.user_label) === false ? (
                      <span className="shrink-0 rounded-full bg-field px-1.5 py-0.5 text-[10px] font-semibold text-muted" title="Laid off — history kept, hidden from planning pickers">laid off</span>
                    ) : null}
                  </span>
                  <span className="text-xs text-muted">{u.links} links · all time</span>
                  {rate != null ? (
                    <span className={clsx("w-fit rounded px-2 py-0.5 text-[11px] font-semibold",
                      rate >= 80 ? "bg-ocean/10 text-ocean" : rate >= 50 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger")}>
                      {rate}% indexed
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
        ) : (
          <Empty label="No people with activity in the last 30 days." />
        )
      ) : null}
    </section>
  );
}

function PerformanceDesk({
  token,
  projectId,
  onOpenBacklinks,
  onNotice,
  onOpenUser
}: {
  token: string | null;
  projectId: string;
  onOpenBacklinks: (filters: Record<string, string>) => void;
  onNotice: (text: string) => void;
  onOpenUser?: (label: string) => void;
}) {
  const [days, setDays] = useState("30");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [cmpMode, setCmpMode] = useState<"prev" | "custom" | "off">("prev");
  const [cmpFrom, setCmpFrom] = useState("");
  const [cmpTo, setCmpTo] = useState("");
  const [duelA, setDuelA] = useState("");
  const [duelB, setDuelB] = useState("");
  const [openUser, setOpenUser] = useState<string | null>(null);

  type PerfUser = {
    user_label: string; links: number; indexed: number; pass: number; fail: number;
    duplicates: number; avg_score: number | null;
    project_new_domains: number; global_new_domains: number;
    previous: Omit<PerfUser, "previous"> | null;
  };
  // "Custom" choices only fire once both dates are picked (no half-built queries).
  const [gran, setGran] = useState("week");
  const customReady = days !== "custom" || Boolean(customFrom && customTo);
  const cmpReady = cmpMode !== "custom" || Boolean(cmpFrom && cmpTo);
  const windowDays =
    days === "custom"
      ? customFrom && customTo
        ? Math.max(1, Math.round((Date.parse(customTo) - Date.parse(customFrom)) / 86400000))
        : 30
      : Number(days);
  const allowDay = windowDays <= 180;
  const effGran = gran === "day" && !allowDay ? "week" : gran;
  const perf = useQuery({
    queryKey: ["performance", token, days, customFrom, customTo, cmpMode, cmpFrom, cmpTo, projectId, effGran],
    enabled: Boolean(token) && customReady && cmpReady,
    queryFn: () => {
      const p = new URLSearchParams({ granularity: effGran });
      if (days === "custom") {
        p.set("date_from", `${customFrom}T00:00:00Z`);
        p.set("date_to", `${customTo}T23:59:59Z`);
      } else {
        p.set("days", days);
      }
      p.set("compare", cmpMode === "off" ? "false" : "true");
      if (cmpMode === "custom") {
        p.set("compare_from", `${cmpFrom}T00:00:00Z`);
        p.set("compare_to", `${cmpTo}T23:59:59Z`);
      }
      if (projectId) p.set("project_id", projectId);
      return api<{
        from: string; to: string;
        compare_from: string | null; compare_to: string | null;
        users: PerfUser[];
        weekly: Array<{ week: string; links: number; new_domains: number; indexed: number }>;
      }>(`/performance/users?${p.toString()}`, { token });
    }
  });
  // Drill-down: the open user's weakest links (like the Backlinks tab, inline).
  const userLinks = useQuery({
    queryKey: ["perf-user-links", token, openUser, projectId],
    enabled: Boolean(token) && Boolean(openUser),
    queryFn: () => {
      const p = new URLSearchParams({ limit: "8", sort: "score" });
      p.set("assigned_user_label", openUser as string);
      if (projectId) p.set("project_id", projectId);
      return api<Page<BacklinkRow>>(`/backlinks?${p.toString()}`, { token });
    }
  });

  const users = perf.data?.users || [];
  const weekly = perf.data?.weekly || [];
  const [perfSort, setPerfSort] = useState("links");
  const [perfDir, setPerfDir] = useState<"asc" | "desc">("desc");
  const onPerfSort = (key: string) => {
    if (perfSort === key) setPerfDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setPerfSort(key);
      setPerfDir(key === "user_label" ? "asc" : "desc");
    }
  };
  const sortedUsers = sortRows(users, perfSort, perfDir, (u, k) => (u as unknown as Record<string, unknown>)[k]);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
            Team performance
            <HelpTip text="Links created, new source domains and quality per person. 'New (project)' = first-ever link from that domain inside the project; 'New (overall)' = first time the domain appears anywhere. Small green/red numbers compare with the previous equal-length period. Click a row to see that person's weakest links." />
          </h2>
          <p className="text-sm text-muted">
            {projectId ? "This project only." : "All projects."} Click a person for details.
            {perf.data ? (
              <span className="ml-1">
                Showing {perf.data.from.slice(0, 10)} → {perf.data.to.slice(0, 10)}
                {perf.data.compare_from
                  ? `, compared with ${perf.data.compare_from.slice(0, 10)} → ${(perf.data.compare_to || "").slice(0, 10)}`
                  : ""}
                .
              </span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            disabled={!users.length}
            onClick={() =>
              downloadCsv(
                "team-performance.csv",
                ["User", "Links", "New domains (project)", "New domains (overall)", "Indexed", "Pass", "Fail", "Duplicates", "Avg score"],
                users.map((u) => [
                  u.user_label, u.links, u.project_new_domains, u.global_new_domains,
                  u.indexed, u.pass, u.fail, u.duplicates, u.avg_score
                ])
              )
            }
          />
          <select
            value={days}
            onChange={(e) => setDays(e.target.value)}
            className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
            title="Timeframe for every number on this page"
          >
            {TIMEFRAMES.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
            <option value="custom">Custom range…</option>
          </select>
          {days === "custom" ? (
            <>
              <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" title="From" />
              <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" title="To" />
            </>
          ) : null}
          <select
            value={cmpMode}
            onChange={(e) => setCmpMode(e.target.value as "prev" | "custom" | "off")}
            className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
            title="What the small green/red numbers compare against"
          >
            <option value="prev">vs previous period</option>
            <option value="custom">vs custom period…</option>
            <option value="off">no comparison</option>
          </select>
          {cmpMode === "custom" ? (
            <>
              <input type="date" value={cmpFrom} onChange={(e) => setCmpFrom(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" title="Compare from" />
              <input type="date" value={cmpTo} onChange={(e) => setCmpTo(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" title="Compare to" />
            </>
          ) : null}
        </div>
      </div>

      {weekly.length ? (
        <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
          <div className="mb-2 flex items-center justify-end">
            <GranularityToggle value={gran} onChange={setGran} allowDay={allowDay} />
          </div>
          <TrendChart
            labels={weekly.map((w) => w.week)}
            labelFmt={(w) => bucketLabel(w, effGran)}
            tickFmt={(w) => bucketTick(w, effGran)}
            onPointClick={(i) => {
              const w = weekly[i]?.week;
              if (!w) return;
              const r = bucketRange(w, effGran);
              onOpenBacklinks({ placement_from: r.from, placement_to: r.to });
            }}
            series={[
              { name: "Links created", cssVar: "--ocean", values: weekly.map((w) => w.links) },
              { name: "New source domains", cssVar: "--plum", values: weekly.map((w) => w.new_domains) },
              { name: "Indexed", cssVar: "--ember", values: weekly.map((w) => w.indexed) }
            ]}
          />
        </section>
      ) : null}

      {users.length >= 2 ? (
        <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
              Compare two people
              <HelpTip text="Put any two team members side by side for the selected timeframe and scope (this project, or all projects when no project is chosen). Green marks the better number — for Fail and Duplicates, lower is better." />
            </h3>
            <select value={duelA} onChange={(e) => setDuelA(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
              <option value="">Pick a person…</option>
              {users.map((u) => (
                <option key={u.user_label} value={u.user_label}>{u.user_label}</option>
              ))}
            </select>
            <span className="text-xs font-semibold uppercase text-muted">vs</span>
            <select value={duelB} onChange={(e) => setDuelB(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
              <option value="">Pick a person…</option>
              {users.filter((u) => u.user_label !== duelA).map((u) => (
                <option key={u.user_label} value={u.user_label}>{u.user_label}</option>
              ))}
            </select>
            {duelA || duelB ? (
              <button onClick={() => { setDuelA(""); setDuelB(""); }} className="text-xs text-muted hover:text-ink hover:underline">
                Clear
              </button>
            ) : null}
          </div>
          {(() => {
            const a = users.find((u) => u.user_label === duelA);
            const b = users.find((u) => u.user_label === duelB);
            if (!a || !b)
              return (
                <p className="pt-3 text-xs text-muted">
                  Choose two people above — the comparison uses the same timeframe as the rest of the page.
                </p>
              );
            const rows: Array<[string, number | null, number | null, boolean]> = [
              ["Links created", a.links, b.links, false],
              ["New domains (project)", a.project_new_domains, b.project_new_domains, false],
              ["New domains (overall)", a.global_new_domains, b.global_new_domains, false],
              ["Indexed", a.indexed, b.indexed, false],
              ["Pass", a.pass, b.pass, false],
              ["Not qualified", a.fail, b.fail, true],
              ["Duplicates", a.duplicates, b.duplicates, true],
              ["Avg score", a.avg_score, b.avg_score, false]
            ];
            const better = (x: number | null, y: number | null, lower: boolean) => {
              if (x == null || y == null || x === y) return 0;
              return (lower ? x < y : x > y) ? -1 : 1; // -1 → A wins, 1 → B wins
            };
            return (
              <div className="grid gap-1.5 pt-3 sm:grid-cols-2">
                {rows.map(([label, av, bv, lower]) => {
                  const w = better(av, bv, lower);
                  return (
                    <div key={label} className="flex items-center justify-between rounded-lg border border-line bg-field/40 px-3 py-2 text-sm">
                      <span className="text-xs font-medium text-muted">{label}</span>
                      <span className="flex items-center gap-2 font-semibold">
                        <span className={clsx(w === -1 ? "text-ocean" : "text-ink")}>{av ?? "—"}</span>
                        <span className="text-[10px] text-muted">/</span>
                        <span className={clsx(w === 1 ? "text-ocean" : "text-ink")}>{bv ?? "—"}</span>
                      </span>
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </section>
      ) : null}

      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <SortTh label="User" sortKey="user_label" sort={perfSort} dir={perfDir} onSort={onPerfSort} />
                <SortTh label="Links" sortKey="links" sort={perfSort} dir={perfDir} onSort={onPerfSort} />
                <SortTh label="New domains (project)" sortKey="project_new_domains" sort={perfSort} dir={perfDir} onSort={onPerfSort}
                  help="First-ever link from that source domain within the project — even if the domain exists globally. Click to sort." />
                <SortTh label="New domains (overall)" sortKey="global_new_domains" sort={perfSort} dir={perfDir} onSort={onPerfSort}
                  help="First-ever link from that source domain anywhere in the workspace. Click to sort." />
                <SortTh label="Indexed" sortKey="indexed" sort={perfSort} dir={perfDir} onSort={onPerfSort} />
                <SortTh label="Not qualified" sortKey="fail" sort={perfSort} dir={perfDir} onSort={onPerfSort}
                  help="Qualified / Not qualified counts — sorted by the not-qualified number." />
                <SortTh label="Duplicates" sortKey="duplicates" sort={perfSort} dir={perfDir} onSort={onPerfSort} />
                <SortTh label="Avg score" sortKey="avg_score" sort={perfSort} dir={perfDir} onSort={onPerfSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sortedUsers.map((u) => (
                <Fragment key={u.user_label}>
                  <tr
                    onClick={() => setOpenUser(openUser === u.user_label ? null : u.user_label)}
                    className={clsx("cursor-pointer hover:bg-field/60", openUser === u.user_label && "bg-ocean/5")}
                  >
                    <Td>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenUser?.(u.user_label);
                        }}
                        title={`Open ${u.user_label}'s full dashboard (hours, targets, calendar, quality, trends)`}
                        className="font-medium text-ocean hover:underline"
                      >
                        {u.user_label}
                      </button>
                    </Td>
                    <Td>{u.links}<DeltaPill now={u.links} prev={u.previous?.links} /></Td>
                    <Td>{u.project_new_domains}<DeltaPill now={u.project_new_domains} prev={u.previous?.project_new_domains} /></Td>
                    <Td>{u.global_new_domains}<DeltaPill now={u.global_new_domains} prev={u.previous?.global_new_domains} /></Td>
                    <Td><span className="whitespace-nowrap">{u.indexed} <span className="text-xs text-muted">({pct(u.indexed, u.links)})</span></span></Td>
                    <Td>
                      <span className="text-ocean">{u.pass}</span> /{" "}
                      <span className="text-danger">{u.fail}</span>
                    </Td>
                    <Td><span className="text-plum">{u.duplicates}</span></Td>
                    <Td>{u.avg_score ?? "-"}</Td>
                  </tr>
                  {openUser === u.user_label ? (
                    <tr>
                      <td colSpan={8} className="bg-field/40 p-4">
                        <div className="mb-2 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-ocean/10 px-2.5 py-1 font-medium text-ocean">Pass {u.pass}</span>
                          <span className="rounded-full bg-danger/10 px-2.5 py-1 font-medium text-danger">Fail {u.fail}</span>
                          <span className="rounded-full bg-plum/10 px-2.5 py-1 font-medium text-plum">Duplicates {u.duplicates}</span>
                          <span className="rounded-full bg-field px-2.5 py-1 font-medium text-muted">Indexed {pct(u.indexed, u.links)}</span>
                          <span className="rounded-full bg-field px-2.5 py-1 font-medium text-muted">Avg score {u.avg_score ?? "—"}</span>
                        </div>
                        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                          Weakest links (lowest score first)
                        </div>
                        {userLinks.isLoading ? (
                          <div className="p-2 text-xs text-muted">Loading…</div>
                        ) : (
                          <div className="space-y-1">
                            {(userLinks.data?.items || []).map((r) => (
                              <div key={r.id} className="flex items-center gap-2 text-xs">
                                <Status value={r.override_status || r.status} reason={r.top_issue_label} />
                                <span className="w-8 text-right font-semibold">{r.score ?? "-"}</span>
                                <a href={r.source_page_url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-ocean hover:underline">
                                  {r.source_page_url}
                                </a>
                                <span className="shrink-0 text-muted">{linkTypeLabel(r.link_type) || ""}</span>
                              </div>
                            ))}
                            {!(userLinks.data?.items || []).length ? (
                              <div className="text-xs text-muted">No links in this scope.</div>
                            ) : null}
                          </div>
                        )}
                        {/* The admin's per-person dashboard: week plan + company calendar */}
                        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_260px]">
                          <UserWeekStrip token={token} userLabel={u.user_label} projectId={projectId || undefined} />
                          <MiniWorkCalendar token={token} />
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          {perf.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
          ) : null}
          {!perf.isLoading && !users.length ? (
            <Empty label="No links created in this period." />
          ) : null}
        </div>
      </div>
    </section>
  );
}

const BATCH_KIND_LABEL: Record<string, string> = {
  import: "Links import",
  link_review: "Links import — review",
  domain_import: "Domain import — review",
  sheet_sync: "Sheet sync",
  writeback: "Sheet write-back",
  crawl: "Crawl",
  recheck: "QA check",
  index_check: "Index check",
  duplicate_scan: "Duplicate scan",
  rescore: "Re-score",
  competitor_import: "Competitor upload",
  competitor_check: "Competitor metrics",
  report: "Report"
};

// Batch lifecycle wording — "review" batches hold staged items awaiting a
// human decision; everything else is a plain processing run.
const BATCH_STATUS: Record<string, { label: string; cls: string }> = {
  review: { label: "Needs review", cls: "bg-plum/10 text-plum border-plum/30" },
  running: { label: "Running", cls: "bg-ocean/10 text-ocean border-ocean/30" },
  pending: { label: "Queued", cls: "bg-field text-muted border-line" },
  completed: { label: "Completed", cls: "bg-ocean/10 text-ocean border-ocean/30" },
  partial: { label: "Partly failed", cls: "bg-ember/10 text-ember border-ember/30" },
  failed: { label: "Failed", cls: "bg-danger/10 text-danger border-danger/30" }
};

function BatchStatusChip({ value }: { value: string }) {
  const meta = BATCH_STATUS[value] || { label: value, cls: "bg-field text-muted border-line" };
  return (
    <span className={clsx("inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold", meta.cls)}>
      {meta.label}
    </span>
  );
}

const ITEM_PRESENCE: Record<string, { label: string; cls: string; help: string }> = {
  new: { label: "New", cls: "bg-ocean/10 text-ocean", help: "Not in your data yet — approving adds it." },
  existing: { label: "Already there", cls: "bg-plum/10 text-plum", help: "Already in the main data — approving refreshes the existing row instead of duplicating it." },
  duplicate: { label: "Repeated", cls: "bg-ember/10 text-ember", help: "The same link appears more than once inside this import." }
};

const ITEM_STATE: Record<string, { label: string; cls: string }> = {
  pending: { label: "Awaiting review", cls: "bg-field text-muted" },
  checking: { label: "Checking…", cls: "bg-ocean/10 text-ocean animate-pulse" },
  checked: { label: "Checked", cls: "bg-ocean/10 text-ocean" },
  failed: { label: "Failed", cls: "bg-danger/10 text-danger" },
  approved: { label: "Approved", cls: "bg-ocean/15 text-ocean" },
  rejected: { label: "Rejected", cls: "bg-field text-muted line-through" }
};

function ItemBadge({ map, value, title }: { map: Record<string, { label: string; cls: string }>; value: string; title?: string }) {
  const meta = map[value] || { label: value, cls: "bg-field text-muted" };
  return (
    <span title={title} className={clsx("inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", meta.cls)}>
      {meta.label}
    </span>
  );
}

function BatchProgress({ totals }: { totals: Record<string, number> }) {
  const total = Number(totals.total || 0);
  const doneRaw = Number(totals.done ?? totals.ok ?? 0);
  // Never show done>total (e.g. a historical render-double-counted batch).
  const done = total ? Math.min(doneRaw, total) : doneRaw;
  const pct = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-28 overflow-hidden rounded-full bg-field">
        <div className="h-full rounded-full bg-ocean transition-all" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-muted">
        {done}/{total || "?"}
      </span>
    </div>
  );
}

// ── The Batch Details page: header, live counts, actions, staged items, logs ─
function BatchDetails({
  token,
  batchId,
  onNotice,
  onBack,
  onOpenBacklinks
}: {
  token: string | null;
  batchId: string;
  onNotice: (text: string) => void;
  onBack: () => void;
  onOpenBacklinks?: (filters: Record<string, string>) => void;
}) {
  const queryClient = useQueryClient();
  const [stateF, setStateF] = useState<string[]>([]);
  const [presenceF, setPresenceF] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  // DA/PA/Spam/AS thresholds for domain queues (filter the survivors to promote/export).
  const [daMin, setDaMin] = useState("");
  const [paMin, setPaMin] = useState("");
  const [spamMax, setSpamMax] = useState("");
  const [asMin, setAsMin] = useState("");
  const [limit, setLimit] = useState(200);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [errorImportId, setErrorImportId] = useState<string | null>(null);

  const batch = useQuery({
    queryKey: ["batch", token, batchId],
    enabled: Boolean(token),
    queryFn: () => api<Batch>(`/batches/${batchId}`, { token }),
    refetchInterval: (q) =>
      q.state.data && (q.state.data.status === "running" || q.state.data.status === "pending") ? 2500 : false
  });
  const b = batch.data;
  const isReview = b?.kind === "link_review" || b?.kind === "domain_import" || b?.kind === "competitor_import";
  const isLinks = b?.kind === "link_review";
  const isDomains = b?.kind === "domain_import" || b?.kind === "competitor_import";
  // Threshold query params shared by the item list + export (only set ones sent).
  const thrParams = (p: URLSearchParams) => {
    if (daMin.trim()) p.set("da_min", daMin.trim());
    if (paMin.trim()) p.set("pa_min", paMin.trim());
    if (spamMax.trim()) p.set("spam_max", spamMax.trim());
    if (asMin.trim()) p.set("as_min", asMin.trim());
    return p;
  };

  const itemsQ = useQuery({
    queryKey: ["batch-items", token, batchId, stateF.join(","), presenceF.join(","), search, daMin, paMin, spamMax, asMin, limit],
    enabled: Boolean(token) && Boolean(isReview),
    queryFn: () => {
      const p = new URLSearchParams({ limit: String(limit) });
      if (stateF.length) p.set("state", stateF.join(","));
      if (presenceF.length) p.set("presence", presenceF.join(","));
      if (search.trim()) p.set("q", search.trim());
      thrParams(p);
      return api<BatchItemsPage>(`/batches/${batchId}/items?${p.toString()}`, { token });
    },
    refetchInterval: (q) =>
      b?.status === "running" || (q.state.data?.items || []).some((it) => it.state === "checking") ? 2500 : false
  });
  const logs = useQuery({
    queryKey: ["batch-logs", token, batchId],
    enabled: Boolean(token),
    queryFn: () => api<BatchLog[]>(`/batches/${batchId}/logs`, { token }),
    // Live-tail while the run is active OR any item is still being checked.
    refetchInterval: (q) => {
      void q;
      return b?.status === "running" || (itemsQ.data?.items || []).some((it) => it.state === "checking")
        ? 3000
        : false;
    }
  });
  const rowErrors = useQuery({
    queryKey: ["import-errors", token, errorImportId],
    enabled: Boolean(token) && Boolean(errorImportId),
    queryFn: () =>
      api<{ total_errors: number; rows: ImportRowError[] }>(`/imports/${errorImportId}/errors.json`, { token })
  });

  const refreshAll = () => {
    queryClient.invalidateQueries({ queryKey: ["batch", token, batchId] });
    queryClient.invalidateQueries({ queryKey: ["batch-items"] });
    queryClient.invalidateQueries({ queryKey: ["batch-logs"] });
    queryClient.invalidateQueries({ queryKey: ["batches"] });
  };

  // Actions target the ticked rows, or everything matching the filters when
  // nothing is ticked ("act on what I'm looking at").
  const selection = (): Record<string, unknown> =>
    picked.size
      ? { item_ids: Array.from(picked) }
      : {
          state: stateF.length ? stateF.join(",") : undefined,
          presence: presenceF.length ? presenceF.join(",") : undefined,
          q: search.trim() || undefined,
          da_min: daMin.trim() ? Number(daMin) : undefined,
          pa_min: paMin.trim() ? Number(paMin) : undefined,
          spam_max: spamMax.trim() ? Number(spamMax) : undefined,
          as_min: asMin.trim() ? Number(asMin) : undefined
        };

  const runCheck = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ queued?: number; checked?: number; remaining?: number; mode: string }>(
        `/batches/${batchId}/items/check`,
        { token, method: "POST", body: JSON.stringify(body) }
      ),
    onSuccess: (r) => {
      onNotice(
        r.mode === "qa"
          ? `QA check started for ${r.queued} links — verdicts appear below as they finish`
          : `Checked ${r.checked} domains${r.remaining ? ` — ${r.remaining} still waiting, run it again` : ""}`
      );
      setPicked(new Set());
      refreshAll();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const approve = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ approved: number; new_rows?: number; updated_rows?: number; error_rows?: number; domains_added?: number; message?: string }>(
        `/batches/${batchId}/items/approve`,
        { token, method: "POST", body: JSON.stringify(body) }
      ),
    onSuccess: (r) => {
      if (r.message && !r.approved) onNotice(r.message);
      else if (isLinks)
        onNotice(
          `Approved ${r.approved} links — ${r.new_rows || 0} added, ${r.updated_rows || 0} refreshed` +
            ((r.error_rows || 0) ? `, ${r.error_rows} errors (see the logs)` : "")
        );
      else onNotice(`Approved ${r.domains_added || r.approved} domains into the Source Domains catalog`);
      setPicked(new Set());
      refreshAll();
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["source-domains"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const reject = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ rejected: number }>(`/batches/${batchId}/items/reject`, { token, method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => {
      onNotice(`Rejected ${r.rejected} items — they stay listed here but will never be imported`);
      setPicked(new Set());
      refreshAll();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const deleteBatch = useMutation({
    mutationFn: () => api<{ message: string }>(`/batches/${batchId}`, { token, method: "DELETE" }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      onBack();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  // ── Delete & revert (rollback) ──────────────────────────────────────────
  type RollbackPreview = {
    seq: number; kind: string; revertable: boolean;
    created_links: number; refreshed_kept: number;
    domains_removable: number; domains_kept: number;
  };
  const [revertOpen, setRevertOpen] = useState(false);
  const [revertTyped, setRevertTyped] = useState("");
  const [logLevel, setLogLevel] = useState<"all" | "info" | "warn" | "error">("all");
  const rollbackPreview = useQuery({
    queryKey: ["batch-rollback-preview", token, batchId],
    enabled: Boolean(token) && revertOpen,
    queryFn: () => api<RollbackPreview>(`/batches/${batchId}/rollback-preview`, { token })
  });
  const deleteBatchRevert = useMutation({
    mutationFn: () =>
      api<{ message: string; reverted_links: number; reverted_domains: number }>(
        `/batches/${batchId}?revert=true`,
        { token, method: "DELETE" }
      ),
    onSuccess: (r) => {
      onNotice(r.message);
      setRevertOpen(false);
      setRevertTyped("");
      queryClient.invalidateQueries({ queryKey: ["batches"] });
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["source-domains"] });
      onBack();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const revertConfirmWord = `B-${b?.seq ?? ""}`;

  const items = itemsQ.data?.items || [];
  const counts = itemsQ.data?.counts;
  const byState = counts?.by_state || {};
  const byPresence = counts?.by_presence || {};
  const openCount =
    (byState.pending || 0) + (byState.checking || 0) + (byState.checked || 0) + (byState.failed || 0);
  const approvable = (byState.pending || 0) + (byState.checked || 0);
  const scopeNote = picked.size
    ? `${picked.size} selected`
    : stateF.length || presenceF.length || search.trim()
      ? "everything matching the filters"
      : "every open item";

  const toggleAllVisible = () => {
    const visible = items.filter((it) => ["pending", "checked", "failed"].includes(it.state)).map((it) => it.id);
    const all = visible.length > 0 && visible.every((id) => picked.has(id));
    setPicked(all ? new Set() : new Set(visible));
  };

  const chip = (
    active: boolean,
    label: string,
    count: number | undefined,
    onClick: () => void,
    tone?: string
  ) => (
    <button
      key={label}
      onClick={onClick}
      className={clsx(
        "flex h-7 items-center gap-1 rounded-full border px-2.5 text-[11px] font-semibold transition",
        active ? "border-ocean/50 bg-ocean/10 text-ocean" : "border-line bg-panel text-muted hover:bg-field",
        tone
      )}
    >
      {label}
      {count != null ? <span className={clsx("rounded-full px-1", active ? "bg-ocean/15" : "bg-field")}>{count}</span> : null}
    </button>
  );

  const resultCell = (it: BatchItem) => {
    if (it.error) return <span className="break-all text-xs text-danger">{it.error}</span>;
    if (it.kind === "link") {
      const qa = it.payload.qa;
      if (!qa) return <span className="text-xs text-muted">Not checked yet</span>;
      return (
        <span className="flex flex-wrap items-center gap-1.5">
          <Status value={qa.status || ""} compact />
          {qa.score != null ? <span className="text-xs font-semibold text-ink">{qa.score}</span> : null}
          {qa.link_found === false ? <span className="text-[10px] font-semibold text-danger">link missing</span> : null}
          {qa.http_status ? <span className="text-[10px] text-muted">HTTP {qa.http_status}</span> : null}
          {qa.rendered ? (
            <span className="rounded bg-plum/10 px-1 py-0.5 text-[10px] font-semibold text-plum" title="JavaScript page — checked in a real browser">
              JS
            </span>
          ) : null}
          {qa.top_issue ? <span className="max-w-[180px] truncate text-[10px] text-muted">{qa.top_issue.replaceAll("_", " ")}</span> : null}
        </span>
      );
    }
    const m = it.payload.metrics;
    if (!m) return <span className="text-xs text-muted">Not checked yet</span>;
    return (
      <span className="flex flex-wrap items-center gap-1">
        <MetricTag label="DA" value={m.da} title="Domain Authority — Moz" />
        <MetricTag label="PA" value={m.pa} title="Page Authority — Moz" />
        <MetricTag label="AS" value={m.semrush_as} title="Authority Score — Semrush" />
        {m.spam_score != null ? <SpamTag value={m.spam_score} /> : null}
        {m.domain_age_days != null ? (
          <span className="text-[10px] text-muted" title="Domain age (registration date via RDAP)">
            {m.domain_age_days >= 365 ? `${Math.round(m.domain_age_days / 365)}y` : `${m.domain_age_days}d`} old
          </span>
        ) : null}
      </span>
    );
  };

  const detailRow = (it: BatchItem) => {
    const mapped = it.payload.mapped || {};
    const qa = it.payload.qa;
    const m = it.payload.metrics;
    const fact = (k: string, v: React.ReactNode) =>
      v == null || v === "" ? null : (
        <div key={k} className="min-w-[160px]">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{k}</p>
          <p className="break-all text-xs text-ink">{v}</p>
        </div>
      );
    return (
      <div className="space-y-3 p-3">
        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {it.kind === "link" ? (
            <>
              {fact("Source page", (
                <a href={it.label} target="_blank" rel="noreferrer" className="text-ocean hover:underline">{it.label}</a>
              ))}
              {fact("Target", mapped.target_url)}
              {fact("Link type", mapped.link_type)}
              {fact("Person", mapped.assigned_user_label)}
              {fact("Expected anchor", mapped.expected_anchor_text)}
              {fact("Source domain", it.payload.source_domain)}
              {fact("Sheet row", it.payload.row != null ? `#${it.payload.row}` : null)}
            </>
          ) : (
            <>
              {fact("Domain", (
                <a href={`https://${it.label}`} target="_blank" rel="noreferrer" className="text-ocean hover:underline">{it.label}</a>
              ))}
              {fact("Traffic (Semrush)", m?.semrush_traffic != null ? m.semrush_traffic.toLocaleString() : null)}
              {fact("Keywords", m?.semrush_keywords != null ? m.semrush_keywords.toLocaleString() : null)}
              {fact("Registered", m?.domain_created_on ? formatDay(m.domain_created_on) : null)}
              {fact("Metrics checked", m?.metrics_updated_at ? formatDate(m.metrics_updated_at) : null)}
            </>
          )}
          {fact("Staged", it.created_at ? formatDate(it.created_at) : null)}
          {fact("Checked", it.checked_at ? formatDate(it.checked_at) : null)}
          {fact(it.state === "rejected" ? "Rejected" : "Approved", it.approved_at ? formatDate(it.approved_at) : null)}
        </div>
        {qa ? (
          <div className="rounded-lg border border-line bg-panel p-2.5">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Isolated QA result (stored in this batch only)</p>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {fact("Verdict", <Status value={qa.status || ""} compact />)}
              {fact("Score", qa.score)}
              {fact("Link found", qa.link_found == null ? null : qa.link_found ? "Yes" : "No")}
              {fact("Anchor", qa.anchor)}
              {fact("Rel", qa.rel)}
              {fact("Matched href", qa.matched_href)}
              {fact("Final URL", qa.final_url)}
              {fact("Robots", qa.robots_status)}
              {fact("Canonical", qa.canonical_status)}
              {fact("Indexability", qa.indexability)}
              {fact("Words on page", qa.word_count)}
            </div>
            {(qa.issues || []).length ? (
              <div className="mt-2 space-y-0.5">
                {(qa.issues || []).map((iss, i) => (
                  <p key={i} className="text-xs">
                    <span className={clsx("font-semibold", iss.severity === "critical" || iss.severity === "high" ? "text-danger" : "text-ember")}>
                      {(iss.label || iss.code || "issue").replaceAll("_", " ")}:
                    </span>{" "}
                    <span className="text-muted">{iss.message}</span>
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  };

  if (!b) {
    return (
      <section className="rounded-xl border border-line bg-panel p-8 text-center shadow-card">
        {batch.isLoading ? <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted" /> : <p className="text-sm text-muted">Batch not found.</p>}
        <button onClick={onBack} className="mt-3 text-sm font-medium text-ocean hover:underline">← All batches</button>
      </section>
    );
  }

  const dur = b.finished_at
    ? `${Math.max(1, Math.round((new Date(b.finished_at).getTime() - new Date(b.started_at).getTime()) / 1000))}s`
    : "running…";

  return (
    <section className="space-y-4">
      {/* Delete & revert confirmation */}
      {revertOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm" onClick={() => setRevertOpen(false)}>
          <div className="w-full max-w-lg rounded-2xl border border-line bg-panel p-5 shadow-pop" onClick={(e) => e.stopPropagation()}>
            <h3 className="flex items-center gap-2 text-base font-semibold text-danger">
              <Trash2 className="h-4 w-4" /> Delete &amp; revert batch #B-{b.seq}
            </h3>
            {rollbackPreview.isLoading ? (
              <p className="py-6 text-center text-sm text-muted"><Loader2 className="mr-1 inline h-4 w-4 animate-spin" /> Working out what would be removed…</p>
            ) : rollbackPreview.data ? (
              (() => {
                const pv = rollbackPreview.data;
                const nothing = pv.created_links === 0 && pv.domains_removable === 0;
                return (
                  <>
                    <p className="mt-2 text-sm text-muted">
                      This removes the rows this batch <b className="text-ink">created</b> and then deletes the run. Refreshed rows, in-use domains, and all crawl history stay. This cannot be undone.
                    </p>
                    <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                      <div className="rounded-lg border border-danger/30 bg-danger/5 p-2.5">
                        <div className="text-2xl font-bold text-danger">{pv.created_links}</div>
                        <div className="text-[11px] font-semibold uppercase text-muted">Links removed</div>
                      </div>
                      {pv.kind === "domain_import" ? (
                        <div className="rounded-lg border border-danger/30 bg-danger/5 p-2.5">
                          <div className="text-2xl font-bold text-danger">{pv.domains_removable}</div>
                          <div className="text-[11px] font-semibold uppercase text-muted">Catalog domains removed</div>
                        </div>
                      ) : (
                        <div className="rounded-lg border border-line bg-field/60 p-2.5">
                          <div className="text-2xl font-bold text-ink">{pv.refreshed_kept}</div>
                          <div className="text-[11px] font-semibold uppercase text-muted">Refreshed links kept</div>
                        </div>
                      )}
                    </div>
                    {pv.kind === "domain_import" && pv.domains_kept > 0 ? (
                      <p className="mt-2 text-xs text-muted">{pv.domains_kept} domain(s) in use by links will be kept.</p>
                    ) : null}
                    {nothing ? (
                      <p className="mt-3 rounded-lg bg-field/70 p-2 text-xs text-muted">This batch created nothing to revert — deleting it just removes the run from history.</p>
                    ) : (
                      <div className="mt-3">
                        <label className="text-xs font-medium text-muted">Type <b className="text-ink">{revertConfirmWord}</b> to confirm</label>
                        <input
                          value={revertTyped}
                          onChange={(e) => setRevertTyped(e.target.value)}
                          placeholder={revertConfirmWord}
                          className="mt-1 h-9 w-full rounded-lg border border-line bg-panel px-2 text-sm"
                        />
                      </div>
                    )}
                    <div className="mt-4 flex justify-end gap-2">
                      <button onClick={() => setRevertOpen(false)} className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-field">Cancel</button>
                      <button
                        onClick={() => deleteBatchRevert.mutate()}
                        disabled={deleteBatchRevert.isPending || (!nothing && revertTyped.trim().toUpperCase() !== revertConfirmWord.toUpperCase())}
                        className="rounded-lg bg-danger px-3 py-1.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40"
                      >
                        {deleteBatchRevert.isPending ? "Deleting…" : nothing ? "Delete batch" : "Delete & revert"}
                      </button>
                    </div>
                  </>
                );
              })()
            ) : (
              <p className="py-6 text-center text-sm text-danger">Could not load the rollback preview.</p>
            )}
          </div>
        </div>
      ) : null}
      {/* Header */}
      <div className="rounded-xl border border-line bg-panel p-4 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <button onClick={onBack} className="whitespace-nowrap text-sm font-medium text-ocean hover:underline">
              ← All batches
            </button>
            <span className="text-line">/</span>
            <h2 className="text-base font-semibold text-ink">
              Batch #B-{b.seq} — {BATCH_KIND_LABEL[b.kind] || b.kind}
            </h2>
            <BatchStatusChip value={b.status} />
            {isReview && openCount > 0 ? (
              <span className="rounded-full bg-plum/10 px-2 py-0.5 text-[11px] font-semibold text-plum">
                {openCount} awaiting decision
              </span>
            ) : null}
          </div>
          {b.status !== "running" ? (
            <div className="flex items-center gap-3">
              {isReview ? (() => {
                // Server-side export of the FULL filtered set (honors state/presence/
                // search + DA/PA/Spam/AS thresholds) straight from the queue.
                const doExport = async (fmt: "csv" | "xlsx") => {
                  try {
                    const p = new URLSearchParams({ format: fmt });
                    if (stateF.length) p.set("state", stateF.join(","));
                    if (presenceF.length) p.set("presence", presenceF.join(","));
                    if (search.trim()) p.set("q", search.trim());
                    thrParams(p);
                    const res = await fetch(`${API_BASE}/batches/${batchId}/items/export?${p.toString()}`, {
                      headers: token ? { Authorization: `Bearer ${token}` } : {}
                    });
                    if (!res.ok) throw new Error(`Export failed (${res.status})`);
                    const blob = await res.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url; a.download = `batch-B-${b.seq}.${fmt}`;
                    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
                    onNotice("Exported the filtered items.");
                  } catch (e) { onNotice(e instanceof Error ? e.message : "Export failed"); }
                };
                return (
                  <span className="flex items-center gap-2">
                    <button onClick={() => doExport("csv")} title="Download the filtered staged rows as CSV" className="flex items-center gap-1.5 text-xs font-medium text-ink hover:underline">
                      <Download className="h-3.5 w-3.5" /> CSV
                    </button>
                    <button onClick={() => doExport("xlsx")} title="Download the filtered staged rows as Excel" className="text-xs font-medium text-ink hover:underline">
                      Excel
                    </button>
                  </span>
                );
              })() : null}
              <button
                onClick={() => { setRevertTyped(""); setRevertOpen(true); }}
                title="Delete this batch AND remove the rows it created (reversible cleanup)"
                className="flex items-center gap-1.5 text-xs font-medium text-danger hover:underline"
              >
                <Trash2 className="h-3.5 w-3.5" /> Delete &amp; revert
              </button>
              <button
                onClick={() => {
                  if (window.confirm(`Remove batch #B-${b.seq} from history? Approved data stays where it was imported. (Admin only)`))
                    deleteBatch.mutate();
                }}
                title="Remove only the run from history — approved data stays"
                className="text-xs font-medium text-muted hover:text-ink hover:underline"
              >
                Remove from history
              </button>
            </div>
          ) : null}
        </div>
        <p className="mt-1 truncate text-sm text-muted" title={b.label || ""}>{b.label || "—"}</p>
        <p className="mt-1 text-xs text-muted">
          Started {formatDate(b.started_at)} · {b.finished_at ? `finished ${formatDate(b.finished_at)} · took ${dur}` : dur}
          {b.meta?.current_step ? <span className="text-ocean"> · {String(b.meta.current_step)}</span> : null}
        </p>
        {b.error ? (
          <div className="mt-2 rounded-lg border border-danger/30 bg-danger/10 p-2.5 text-sm text-danger">
            Stopped because: {b.error}
          </div>
        ) : null}
        {isReview ? (
          <p className="mt-2 rounded-lg bg-field/70 p-2 text-xs text-muted">
            {isLinks
              ? "This is a review batch: the links below are staged in isolation — QA-test them here, then approve the ones you want. Nothing touches the project until you approve."
              : "This is a review batch: the domains below are staged in isolation — check their metrics here, then approve the ones worth keeping. The Source Domains catalog is untouched until you approve."}
          </p>
        ) : null}
      </div>

      {/* Review summary cards (clickable = set the matching filter) */}
      {isReview && counts ? (
        <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4 xl:grid-cols-8">
          <Metric label="Items" value={counts.total} icon={Layers} tone="ink" onClick={() => { setStateF([]); setPresenceF([]); }} help="Everything staged in this batch. Click to clear filters." />
          <Metric label="New" value={byPresence.new || 0} icon={Star} tone="ocean" onClick={() => { setPresenceF(["new"]); }} help="Not in your data yet — the interesting rows. Click to filter." />
          <Metric label="Already there" value={byPresence.existing || 0} icon={CheckCircle2} tone="plum" onClick={() => { setPresenceF(["existing"]); }} help="Already in the main data — approving refreshes them. Click to filter." />
          <Metric label="Repeated" value={byPresence.duplicate || 0} icon={Layers} tone="ember" onClick={() => { setPresenceF(["duplicate"]); }} help="Repeated inside this import. Click to filter." />
          <Metric label="Checked" value={byState.checked || 0} icon={Gauge} tone="ocean" onClick={() => { setStateF(["checked"]); }} help={isLinks ? "QA-tested in isolation. Click to filter." : "Metrics fetched. Click to filter."} />
          <Metric label="Failed" value={byState.failed || 0} icon={XCircle} tone="danger" onClick={() => { setStateF(["failed"]); }} help="Invalid rows or checks that crashed — re-run or reject them. Click to filter." />
          <Metric label="Approved" value={byState.approved || 0} icon={CheckCircle2} tone="ocean" onClick={() => { setStateF(["approved"]); }} help="Imported into the main data. Click to filter." />
          <Metric label="Rejected" value={byState.rejected || 0} icon={XCircle} tone="ink" onClick={() => { setStateF(["rejected"]); }} help="Kept for the audit trail, never imported. Click to filter." />
        </div>
      ) : null}

      {/* Actions */}
      {isReview ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-panel p-3 shadow-card">
          {isLinks ? (
            <button
              onClick={() => {
                if (window.confirm(`Run the isolated QA check on ${scopeNote}? Real crawls run on the worker; results stay inside this batch.`))
                  runCheck.mutate({ ...selection() });
              }}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
              title="Crawl + QA-test the staged links in isolation — same engine as the main QA, but verdicts stay in this batch"
            >
              {runCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run QA check
            </button>
          ) : (
            <>
              <button
                onClick={() => runCheck.mutate({ ...selection() })}
                className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
                title="Fetch DA/PA/Spam (Moz), AS/traffic (Semrush) and domain age for the staged domains — results stay in this batch"
              >
                {runCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
                Check all metrics
              </button>
              <button
                onClick={() => runCheck.mutate({ ...selection(), providers: "moz" })}
                className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
                title="Moz only: DA / PA / Spam score (+ domain age)"
              >
                <Gauge className="h-4 w-4" /> DA/PA (Moz)
              </button>
              <button
                onClick={() => runCheck.mutate({ ...selection(), providers: "semrush" })}
                className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
                title="Semrush only: Authority Score, traffic, keywords (needs the Semrush API endpoint configured)"
              >
                <Gauge className="h-4 w-4" /> AS (Semrush)
              </button>
            </>
          )}
          <span className="mx-1 h-6 w-px bg-line" />
          <button
            onClick={() => {
              if (!picked.size && !window.confirm(`Approve ${scopeNote} (${picked.size || approvable} items)? Links/domains enter the main data.`)) return;
              approve.mutate(selection());
            }}
            disabled={approve.isPending || (!picked.size && !approvable)}
            className="flex h-9 items-center gap-2 rounded-lg border border-ocean/40 bg-ocean/10 px-3 text-sm font-semibold text-ocean transition hover:bg-ocean/20 disabled:opacity-50"
            title="Approve into the main data — only pending/checked items qualify"
          >
            {approve.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Approve {picked.size ? `selected (${picked.size})` : "all filtered"}
          </button>
          <button
            onClick={() => {
              if (window.confirm(`Reject ${scopeNote}? Rejected items stay in the batch history but are never imported.`))
                reject.mutate(selection());
            }}
            disabled={reject.isPending || (!picked.size && !openCount)}
            className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field disabled:opacity-50"
          >
            <XCircle className="h-4 w-4" />
            Reject {picked.size ? `selected (${picked.size})` : "all filtered"}
          </button>
          {(byState.failed || 0) > 0 ? (
            <button
              onClick={() => runCheck.mutate({ state: "failed" })}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Retry only the items whose check failed"
            >
              <RefreshCw className="h-4 w-4" /> Re-run failed ({byState.failed})
            </button>
          ) : null}
          <span className="ml-auto text-xs text-muted">Actions apply to: <span className="font-semibold text-ink">{scopeNote}</span></span>
        </div>
      ) : null}

      {/* Items */}
      {isReview ? (
        <div className="rounded-xl border border-line bg-panel shadow-card">
          <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {chip(!stateF.length, "All states", counts?.total, () => setStateF([]))}
              {Object.entries(ITEM_STATE).map(([v, meta]) =>
                chip(
                  stateF.includes(v),
                  meta.label,
                  byState[v] || 0,
                  () => setStateF((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]))
                )
              )}
            </div>
            <span className="h-6 w-px bg-line" />
            <div className="flex flex-wrap items-center gap-1.5">
              {Object.entries(ITEM_PRESENCE).map(([v, meta]) =>
                chip(
                  presenceF.includes(v),
                  meta.label,
                  byPresence[v] || 0,
                  () => setPresenceF((cur) => (cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]))
                )
              )}
            </div>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={isLinks ? "Search URL…" : "Search domain…"}
              className="ml-auto h-8 w-56 rounded-lg border border-line bg-panel px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
            />
          </div>
          {isDomains ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-line px-3 py-2 text-xs">
              <span className="font-semibold uppercase tracking-wide text-muted">Filter by metrics</span>
              <label className="flex items-center gap-1">DA ≥
                <input type="number" value={daMin} onChange={(e) => setDaMin(e.target.value)} className="h-7 w-16 rounded-md border border-line bg-panel px-1.5" /></label>
              <label className="flex items-center gap-1">PA ≥
                <input type="number" value={paMin} onChange={(e) => setPaMin(e.target.value)} className="h-7 w-16 rounded-md border border-line bg-panel px-1.5" /></label>
              <label className="flex items-center gap-1">Spam ≤
                <input type="number" value={spamMax} onChange={(e) => setSpamMax(e.target.value)} className="h-7 w-16 rounded-md border border-line bg-panel px-1.5" /></label>
              <label className="flex items-center gap-1">AS ≥
                <input type="number" value={asMin} onChange={(e) => setAsMin(e.target.value)} className="h-7 w-16 rounded-md border border-line bg-panel px-1.5" /></label>
              {(daMin || paMin || spamMax || asMin) ? (
                <button onClick={() => { setDaMin(""); setPaMin(""); setSpamMax(""); setAsMin(""); }} className="text-muted hover:text-ink hover:underline">clear</button>
              ) : null}
              <span className="text-muted">— Check DA/PA, Approve and Export all honor these filters.</span>
            </div>
          ) : null}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-field text-xs uppercase text-muted">
                <tr>
                  <Th>
                    <input
                      type="checkbox"
                      checked={items.length > 0 && items.filter((it) => ["pending", "checked", "failed"].includes(it.state)).every((it) => picked.has(it.id)) && picked.size > 0}
                      onChange={toggleAllVisible}
                      className="h-3.5 w-3.5 rounded border-line"
                      title="Select every open row on this page"
                    />
                  </Th>
                  <Th>{isLinks ? "Link" : "Domain"}</Th>
                  <Th>Presence</Th>
                  <Th>State</Th>
                  <Th>{isLinks ? "QA result" : "Metrics"}</Th>
                  <Th>Checked</Th>
                  <Th> </Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((it) => {
                  const open = expanded === it.id;
                  const selectable = ["pending", "checked", "failed"].includes(it.state);
                  return (
                    <Fragment key={it.id}>
                      <tr className={clsx("hover:bg-field/60", open && "bg-ocean/5")}>
                        <Td>
                          <input
                            type="checkbox"
                            disabled={!selectable}
                            checked={picked.has(it.id)}
                            onChange={() =>
                              setPicked((cur) => {
                                const next = new Set(cur);
                                if (next.has(it.id)) next.delete(it.id);
                                else next.add(it.id);
                                return next;
                              })
                            }
                            className="h-3.5 w-3.5 rounded border-line disabled:opacity-30"
                          />
                        </Td>
                        <Td>
                          <div className="max-w-[380px] truncate font-medium text-ink" title={it.label}>{it.label}</div>
                          {isLinks ? (
                            <div className="max-w-[380px] truncate text-xs text-muted" title={it.payload.mapped?.target_url || ""}>
                              → {it.payload.mapped?.target_url || "no target"}
                              {it.payload.source_domain ? ` · ${it.payload.source_domain}` : ""}
                            </div>
                          ) : null}
                        </Td>
                        <Td><ItemBadge map={ITEM_PRESENCE} value={it.presence} title={ITEM_PRESENCE[it.presence]?.help} /></Td>
                        <Td><ItemBadge map={ITEM_STATE} value={it.state} /></Td>
                        <Td>{resultCell(it)}</Td>
                        <Td><span className="whitespace-nowrap text-xs text-muted">{it.checked_at ? formatDate(it.checked_at) : "—"}</span></Td>
                        <Td>
                          <button onClick={() => setExpanded(open ? null : it.id)} className="text-xs font-medium text-ocean hover:underline">
                            {open ? "Hide" : "Details"}
                          </button>
                        </Td>
                      </tr>
                      {open ? (
                        <tr>
                          <td colSpan={7} className="bg-field/40">{detailRow(it)}</td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {itemsQ.isLoading ? (
              <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
            ) : null}
            {!itemsQ.isLoading && !items.length ? <Empty label="No items match these filters." /> : null}
            {counts && items.length < (stateF.length || presenceF.length || search.trim() ? items.length + 1 : counts.total) && items.length >= limit ? (
              <div className="border-t border-line p-2 text-center">
                <button onClick={() => setLimit((l) => l + 200)} className="text-sm font-medium text-ocean hover:underline">
                  Load more
                </button>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* Logs */}
      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
            Run log
            {(b?.status === "running" || (itemsQ.data?.items || []).some((it) => it.state === "checking")) ? (
              <span className="flex items-center gap-1 rounded-full bg-ocean/10 px-2 py-0.5 text-[10px] font-semibold text-ocean">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ocean" /> LIVE
              </span>
            ) : null}
            <span className="text-[11px] font-normal text-muted">{(logs.data || []).length} entr{(logs.data || []).length === 1 ? "y" : "ies"}</span>
          </h3>
          <span className="inline-flex rounded-lg border border-line bg-field/40 p-0.5 text-[11px] font-medium">
            {(["all", "info", "warn", "error"] as const).map((lv) => (
              <button
                key={lv}
                onClick={() => setLogLevel(lv)}
                className={clsx("rounded-md px-2 py-0.5 capitalize transition", logLevel === lv ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                {lv}
              </button>
            ))}
          </span>
        </div>
        <div className="max-h-[420px] space-y-1 overflow-y-auto p-3">
          {(logs.data || []).filter((l) => logLevel === "all" || l.level === logLevel).map((l, i) => (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className={clsx("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", l.level === "error" ? "bg-danger" : l.level === "warn" ? "bg-ember" : "bg-ocean")} />
              <span className="whitespace-nowrap text-muted">{formatDate(l.created_at)}</span>
              <span className="flex-1 text-ink">{l.message}</span>
              {l.data && (l.data as Record<string, unknown>).import_id ? (
                <button
                  onClick={() => setErrorImportId(String((l.data as Record<string, unknown>).import_id))}
                  className="shrink-0 font-medium text-ocean hover:underline"
                >
                  View row errors
                </button>
              ) : null}
            </div>
          ))}
          {logs.isLoading ? <div className="text-xs text-muted">Loading logs…</div> : null}
          {!logs.isLoading && !(logs.data || []).length ? <div className="text-xs text-muted">No log entries for this run.</div> : null}
          {!logs.isLoading && (logs.data || []).length > 0 && !(logs.data || []).filter((l) => logLevel === "all" || l.level === logLevel).length ? (
            <div className="text-xs text-muted">No {logLevel} entries.</div>
          ) : null}
          {errorImportId ? (
            <div className="mt-3 rounded-lg border border-line bg-panel p-2">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs font-semibold text-ink">
                  Row errors {rowErrors.data ? `(${rowErrors.data.total_errors})` : ""}
                </span>
                <button onClick={() => setErrorImportId(null)} className="text-xs text-ocean hover:underline">Close</button>
              </div>
              <div className="max-h-64 overflow-y-auto">
                {(rowErrors.data?.rows || []).map((r) => (
                  <div key={r.row_number} className="border-b border-line py-1.5 text-xs last:border-0">
                    <span className="font-semibold text-ink">Row {r.row_number}:</span>{" "}
                    <span className="text-danger">{r.error}</span>
                    <div className="mt-0.5 break-all text-muted">
                      {Object.entries(r.raw || {}).filter(([, v]) => v).slice(0, 6).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                    </div>
                  </div>
                ))}
                {rowErrors.isLoading ? <div className="text-xs text-muted">Loading…</div> : null}
                {!rowErrors.isLoading && !(rowErrors.data?.rows || []).length ? (
                  <div className="text-xs text-muted">No row errors recorded.</div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function BatchesDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const [kind, setKind] = useState("");
  const [statusF, setStatusF] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  // Deep link: "Open review batch" from Imports / Import Domains lands here
  // with ?f_batch=<id> (mirrors the Backlinks f_* pattern).
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const target = q.get("f_batch");
    if (target) {
      setOpenId(target);
      q.delete("f_batch");
      window.history.replaceState(null, "", `${window.location.pathname}${q.toString() ? `?${q.toString()}` : ""}`);
    }
  }, []);

  const qs = () => {
    const p = new URLSearchParams();
    if (kind) p.set("kind", kind);
    if (statusF) p.set("status", statusF);
    if (projectId) p.set("project_id", projectId);
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  const batches = useQuery({
    queryKey: ["batches", token, kind, statusF, projectId],
    enabled: Boolean(token) && !openId,
    queryFn: () => api<Batch[]>(`/batches${qs()}`, { token }),
    // Live progress: poll while anything is running.
    refetchInterval: (q) =>
      (q.state.data || []).some((b) => b.status === "running" || b.status === "pending") ? 3000 : false
  });

  if (openId) {
    return <BatchDetails token={token} batchId={openId} onNotice={onNotice} onBack={() => setOpenId(null)} />;
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">Batches</h2>
        <p className="text-sm text-muted">
          Every run in one place — imports awaiting review, sheet syncs, QA checks, duplicate scans,
          re-scores and reports — with live progress, counters and logs. Open a batch for the full detail.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <select value={kind} onChange={(e) => setKind(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
          <option value="">All kinds</option>
          {Object.entries(BATCH_KIND_LABEL).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
          <option value="">All statuses</option>
          {Object.entries(BATCH_STATUS).map(([v, meta]) => (
            <option key={v} value={v}>{meta.label}</option>
          ))}
        </select>
        <ExportButton
          disabled={!(batches.data || []).length}
          onClick={() =>
            downloadCsv(
              "batches.csv",
              ["Batch", "Kind", "Label", "Status", "Total", "Done", "OK", "Failed", "Counters", "Started", "Finished", "Error"],
              (batches.data || []).map((b) => [
                `B-${b.seq}`, BATCH_KIND_LABEL[b.kind] || b.kind, b.label, b.status,
                b.totals?.total, b.totals?.done, b.totals?.ok, b.totals?.failed,
                Object.entries(b.counters || {}).map(([k, v]) => `${k}=${v}`).join("; "),
                b.started_at, b.finished_at, b.error
              ])
            )
          }
        />
      </div>

      {/* What these runs cost & produced — API credits vs cache, new vs refreshed */}
      {(() => {
        const rows = batches.data || [];
        const sum = (k: string) => rows.reduce((acc, x) => acc + Number((x.counters || {})[k] || 0), 0);
        const api_calls = sum("api_calls");
        const api_cached = sum("api_cached");
        const new_links = sum("new_links");
        const already = sum("already_there");
        if (!(api_calls + api_cached + new_links + already)) return null;
        const bar = (aVal: number, bVal: number, aName: string, bName: string, aCls: string, bCls: string, hint: string) => {
          const total = Math.max(1, aVal + bVal);
          return (
            <div title={hint} className="min-w-[220px] flex-1">
              <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-muted">
                <span>{aName}: <span className="text-ink">{aVal}</span></span>
                <span>{bName}: <span className="text-ink">{bVal}</span></span>
              </div>
              <div className="flex h-2.5 overflow-hidden rounded-full bg-field">
                <span className={aCls} style={{ width: `${Math.round((100 * aVal) / total)}%` }} />
                <span className={bCls} style={{ width: `${Math.round((100 * bVal) / total)}%` }} />
              </div>
            </div>
          );
        };
        return (
          <div className="flex flex-wrap items-center gap-5 rounded-xl border border-line bg-panel p-3 shadow-card">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">These runs</span>
            {api_calls + api_cached > 0
              ? bar(api_calls, api_cached, "API credits used", "Reused from cache (free)", "block bg-danger/70", "block bg-ocean/70",
                    "Metric checks: fresh API calls cost credits; cached reuse is free")
              : null}
            {new_links + already > 0
              ? bar(new_links, already, "NEW links", "Already there (refreshed)", "block bg-ocean", "block bg-line",
                    "Imports & syncs: truly new links vs rows that already existed and were refreshed")
              : null}
          </div>
        );
      })()}

      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Batch</Th><Th>What ran</Th><Th>Status</Th><Th>Progress</Th><Th>Counters</Th><Th>Started</Th><Th>Duration</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(batches.data || []).map((b) => {
                const dur =
                  b.finished_at
                    ? `${Math.max(1, Math.round((new Date(b.finished_at).getTime() - new Date(b.started_at).getTime()) / 1000))}s`
                    : "…";
                const counterBits = Object.entries(b.counters || {})
                  .filter(([, v]) => Number(v) > 0)
                  .map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`);
                return (
                  <tr
                    key={b.id}
                    onClick={() => setOpenId(b.id)}
                    className="cursor-pointer hover:bg-field/60"
                    title="Open the batch details"
                  >
                    <Td><span className="whitespace-nowrap font-semibold text-ink">#B-{b.seq}</span></Td>
                    <Td>
                      <div className="font-medium text-ink">{BATCH_KIND_LABEL[b.kind] || b.kind}</div>
                      <div className="max-w-[320px] truncate text-xs text-muted">{b.label || "—"}</div>
                    </Td>
                    <Td>
                      <span className="flex flex-wrap items-center gap-1">
                        <BatchStatusChip value={b.status} />
                        {b.review_pending ? (
                          <span className="whitespace-nowrap rounded-full bg-plum/10 px-2 py-0.5 text-[11px] font-semibold text-plum" title="Items still awaiting your approve/reject decision">
                            {b.review_pending} to review
                          </span>
                        ) : null}
                      </span>
                    </Td>
                    <Td><BatchProgress totals={b.totals || {}} /></Td>
                    <Td>
                      <span className="text-xs text-muted">
                        {counterBits.length ? counterBits.slice(0, 4).join(" · ") : "—"}
                      </span>
                    </Td>
                    <Td><span className="whitespace-nowrap">{formatDate(b.started_at)}</span></Td>
                    <Td>{dur}</Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {batches.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
          ) : null}
          {!batches.isLoading && !(batches.data || []).length ? (
            <Empty label="No runs yet — imports, syncs and checks will appear here." />
          ) : null}
        </div>
      </div>
    </section>
  );
}

// ── Import Source Domains (global Ingest) — staged, reviewed, then approved ──
function DomainImportDesk({
  token,
  onNotice,
  onOpenBatch
}: {
  token: string | null;
  onNotice: (text: string) => void;
  onOpenBatch: (batchId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [staged, setStaged] = useState<{ batch_id: string; seq: number; total: number; new: number; existing: number; duplicate: number } | null>(null);
  const lineCount = text
    .replace(/,/g, "\n")
    .split("\n")
    .map((t) => t.trim())
    .filter((t) => t && !t.startsWith("#")).length;

  const submit = useMutation({
    mutationFn: () =>
      api<{ batch_id: string; seq: number; total: number; new: number; existing: number; duplicate: number; message: string }>(
        "/source-domains/import",
        { token, method: "POST", body: JSON.stringify({ text }) }
      ),
    onSuccess: (r) => {
      setStaged(r);
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });
  const uploadFile = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<{ batch_id: string; seq: number; total: number; new: number; existing: number; duplicate: number; message: string; column_used: string }>(
        "/source-domains/import-file",
        { token, method: "POST", body: form }
      );
    },
    onSuccess: (r) => {
      setStaged(r);
      onNotice(`${r.message} (domain column: ${r.column_used})`);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">Import Source Domains</h2>
        <p className="text-sm text-muted">
          Paste a list of websites — each import becomes a review batch where you can check DA/PA/Spam
          (Moz), Authority Score (Semrush) and domain age per website, then approve only the ones worth
          keeping. The Source Domains catalog is untouched until you approve.
        </p>
      </div>

      {staged ? (
        <div className="rounded-xl border border-ocean/40 bg-ocean/5 p-4 shadow-card">
          <p className="text-sm font-semibold text-ink">
            Review batch <span className="text-ocean">#B-{staged.seq}</span> created — {staged.total} domains staged
          </p>
          <p className="mt-1 text-sm text-muted">
            {staged.new} new · {staged.existing} already in the catalog
            {staged.duplicate ? ` · ${staged.duplicate} repeated lines collapsed` : ""}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => onOpenBatch(staged.batch_id)}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              <Play className="h-4 w-4" /> Open review batch
            </button>
            <button
              onClick={() => { setStaged(null); setText(""); }}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field"
            >
              Import another list
            </button>
          </div>
        </div>
      ) : (
        <div className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Paste domains" />
          <div className="space-y-3 p-4">
            <textarea
              className="min-h-[240px] w-full rounded-md border border-line bg-panel p-3 font-mono text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-ocean/20"
              placeholder={"one website per line, e.g.\nexample.com\nhttps://blog.publisher.net/some-page\nanother-site.org"}
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => submit.mutate()}
                disabled={!lineCount || submit.isPending}
                className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
              >
                {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
                Stage {lineCount || ""} domain{lineCount === 1 ? "" : "s"} for review
              </button>
              <span className="text-xs text-muted">
                URLs are reduced to their main domain (blog.example.com/page → example.com); repeats are collapsed.
              </span>
              <label className="flex h-10 cursor-pointer items-center gap-2 rounded-md border border-line px-3 text-sm font-medium text-ink transition hover:bg-field">
                {uploadFile.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                …or upload CSV / Excel
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.txt"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadFile.mutate(f);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function CompetitorDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [compUrl, setCompUrl] = useState("");
  const [pasted, setPasted] = useState("");
  const [cat, setCat] = useState("");
  const [hideDismissed, setHideDismissed] = useState(true);
  const [hideGuest, setHideGuest] = useState(false);
  const [domSearch, setDomSearch] = useState("");
  const [domSearchDeb, setDomSearchDeb] = useState("");
  const [domSort, setDomSort] = useState("");
  const [domDir, setDomDir] = useState<"asc" | "desc">("desc");
  const [domLimit, setDomLimit] = useState(100);
  const [openDomain, setOpenDomain] = useState<string | null>(null);
  type CompPreview = {
    format: string;
    mapping: Record<string, string>;
    row_count: number;
    sample: Array<{ url: string; anchor: string | null; rel: string | null; link_type: string | null }>;
    warnings: string[];
  };
  const [preview, setPreview] = useState<CompPreview | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setDomSearchDeb(domSearch.trim()), 300);
    return () => clearTimeout(t);
  }, [domSearch]);

  const summary = useQuery({
    queryKey: ["competitor-summary", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => api<CompetitorSummary>(`/competitors/summary?project_id=${projectId}`, { token })
  });
  const domains = useQuery({
    queryKey: ["competitor-domains", token, projectId, cat, hideDismissed, hideGuest, domSearchDeb, domSort, domDir, domLimit],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () =>
      api<CompetitorDomain[]>(
        `/competitors/domains?project_id=${projectId}${cat ? `&category=${cat}` : ""}` +
          `&include_dismissed=${!hideDismissed}&exclude_guest_posts=${hideGuest}` +
          `${domSearchDeb ? `&search=${encodeURIComponent(domSearchDeb)}` : ""}` +
          `${domSort ? `&sort=${domSort}&direction=${domDir}` : ""}&limit=${domLimit}`,
        { token }
      )
  });
  const onDomSort = (key: string) => {
    if (domSort === key) setDomDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setDomSort(key);
      setDomDir(key === "domain" ? "asc" : "desc");
    }
  };
  const domainLinks = useQuery({
    queryKey: ["competitor-domain-links", token, projectId, openDomain],
    enabled: Boolean(token) && Boolean(projectId) && Boolean(openDomain),
    queryFn: () =>
      api<Array<{ url: string; anchor: string | null; rel: string | null; link_type: string | null; upload_name: string; competitor_url: string | null }>>(
        `/competitors/domain-backlinks?project_id=${projectId}&domain=${encodeURIComponent(openDomain || "")}`,
        { token }
      )
  });
  // Uploads rolled up to their parent competitor (one row per competitor).
  const [openCompetitor, setOpenCompetitor] = useState<string | null>(null);
  const [compQ, setCompQ] = useState("");
  const [parentSearch, setParentSearch] = useState("");
  const parents = useQuery({
    queryKey: ["competitor-parents", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => api<CompetitorParent[]>(`/competitors/parents?project_id=${projectId}`, { token })
  });
  const parentLinks = useQuery({
    queryKey: ["competitor-parent-links", token, projectId, openCompetitor, compQ],
    enabled: Boolean(token) && Boolean(projectId) && Boolean(openCompetitor),
    queryFn: () =>
      api<Array<{ url: string; source_domain: string | null; anchor: string | null; rel: string | null; link_type: string | null; da?: number | null; pa?: number | null; semrush_as?: number | null; domain_category?: string | null; decision?: string | null; upload_name: string | null; uploaded_at: string | null }>>(
        `/competitors/parents/backlinks?project_id=${projectId}&competitor=${encodeURIComponent(openCompetitor || "")}${compQ.trim() ? `&q=${encodeURIComponent(compQ.trim())}` : ""}&limit=500`,
        { token }
      )
  });
  const previewMut = useMutation({
    mutationFn: () =>
      api<CompPreview>("/competitors/preview", {
        token,
        method: "POST",
        body: JSON.stringify({ text: pasted })
      }),
    onSuccess: (r) => setPreview(r),
    onError: (e: Error) => onNotice(e.message)
  });
  const decide = useMutation({
    mutationFn: (p: { domain_key: string; status: string }) =>
      api<CompetitorSummary>("/competitors/domains/decision", {
        token,
        method: "PATCH",
        body: JSON.stringify({ project_id: projectId, ...p })
      }),
    onSuccess: (_r, p) => {
      onNotice(p.status === "dismissed" ? `${p.domain_key} dismissed.` : `${p.domain_key} re-opened.`);
      queryClient.invalidateQueries({ queryKey: ["competitor-domains"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-summary"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const sheets = useQuery({
    queryKey: ["competitor-sheets", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => api<CompetitorSheet[]>(`/competitors/sheets?project_id=${projectId}`, { token })
  });
  const deleteSheet = useMutation({
    mutationFn: (id: string) =>
      api<{ message: string }>(`/competitors/sheets/${id}`, { token, method: "DELETE" }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["competitor-sheets"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-parents"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-parent-links"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-domains"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-summary"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const checkMetrics = useMutation({
    mutationFn: () =>
      api<{ checked: number; from_cache: number; api_calls: number; skipped_fresh: number }>(
        `/competitors/check-metrics?project_id=${projectId}&freshness_days=10`,
        { token, method: "POST" }
      ),
    onSuccess: (r) => {
      onNotice(
        `Metrics checked: ${r.checked} domain(s) — ${r.from_cache} reused from our own checks, ` +
          `${r.api_calls} API call(s), ${r.skipped_fresh} already fresh.`
      );
      queryClient.invalidateQueries({ queryKey: ["competitor-domains"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const exportCsv = () => {
    // Use the shared CSV helper (UTF-8 BOM + proper escaping) — was hand-rolled.
    downloadCsv(
      "competitor-opportunities.csv",
      ["domain", "status", "competitor_links", "our_links", "indexed_pct", "da", "pa", "guest_post"],
      (domains.data || []).map((d) => [
        d.domain_key,
        d.decision === "dismissed" ? "dismissed" : d.category,
        d.url_count,
        d.our_link_count,
        d.our_indexed_pct ?? "",
        d.da ?? "",
        d.pa ?? "",
        d.has_guest_post ? "yes" : ""
      ])
    );
  };
  const ingest = useMutation({
    mutationFn: () =>
      api<CompetitorSheet>("/competitors/ingest", {
        token,
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          competitor_url: compUrl.trim(),
          name: name.trim(),
          text: pasted
        })
      }),
    onSuccess: (sh) => {
      onNotice(
        `“${sh.name}” imported — ${sh.total_rows} links, ${sh.new_domains} new domain${sh.new_domains === 1 ? "" : "s"}, ${sh.existing_domains} seen before.`
      );
      setPasted("");
      setPreview(null);
      queryClient.invalidateQueries({ queryKey: ["competitor-summary"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-domains"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-sheets"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-parents"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-parent-links"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const runImport = () => {
    const label = name.trim() || compUrl.trim().replace(/^https?:\/\//, "").split("/")[0];
    const count = preview?.row_count;
    if (
      window.confirm(
        `Import ${count ?? "these"} competitor link${count === 1 ? "" : "s"} for “${label}”?\n\nDuplicates of earlier uploads are counted as “seen before”, and opportunities are recalculated.`
      )
    )
      ingest.mutate();
  };

  if (!projectId) return <Empty label="Select a project to analyze competitor backlinks." />;

  const s = summary.data;
  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-ink">Competitor analysis</h2>
        <p className="text-sm text-muted">
          Paste a competitor&apos;s backlink source URLs (one per line; optional “, anchor, rel”). We
          group them by domain and flag which domains you don&apos;t have yet — your outreach opportunities.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Domains" value={s?.domains ?? 0} icon={Globe} tone="ink"
          help="All the websites your competitor has links from (grouped by domain)." />
        <Metric label="New opportunities" value={s?.new_opportunities ?? 0} icon={Star} tone="ocean"
          help="Websites the competitor has links from but this project doesn't yet — your outreach list." />
        <Metric label="Already have" value={s?.existing ?? 0} icon={CheckCircle2} tone="plum"
          help="Websites where this project already has a link — removed from the opportunity list automatically." />
        <Metric label="Competitor links" value={s?.competitor_links ?? 0} icon={Link2} tone="ink"
          help="Total competitor backlinks you've uploaded for this project." />
        <Metric label="Avg DA" value={s?.avg_da ?? "—"} icon={Gauge} tone="ink"
          help="Average Moz Domain Authority of the competitor's source domains (where known)." />
        <Metric label="Avg AS" value={s?.avg_as ?? "—"} icon={Gauge} tone="ink"
          help="Average Semrush Authority Score (where known)." />
      </div>

      <section className="rounded-xl border border-line bg-panel shadow-card p-4">
        <SectionTitle title="Add competitor upload" flush />
        <div className="space-y-3 pt-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Competitor website URL (required)" value={compUrl} onChange={setCompUrl} name="competitor-url" />
            <Field label="Display name (optional — domain is used when empty)" value={name} onChange={setName} />
          </div>
          <textarea
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            rows={6}
            placeholder={"Paste their backlinks — one URL per line, OR paste a SEMrush backlink export (with headers) directly:\nhttps://blog.example.com/post-linking-to-competitor\nhttps://directory.example.com/listing, brand anchor, dofollow, Guest Post"}
            className="w-full rounded-md border border-line p-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending || !pasted.trim()}
              title="See how the pasted columns will be read BEFORE importing"
              className="flex h-10 items-center gap-2 rounded-md border border-line px-4 text-sm font-semibold text-ink transition hover:bg-field disabled:opacity-50"
            >
              {previewMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
              Preview mapping
            </button>
            <button
              onClick={runImport}
              disabled={ingest.isPending || !pasted.trim() || !compUrl.trim()}
              title={!compUrl.trim() ? "Enter the competitor's website URL first" : "Import the pasted links"}
              className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900 disabled:opacity-50"
            >
              {ingest.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              Import links
            </button>
            <button
              onClick={() =>
                downloadCsv(
                  "competitor-backlinks-template.csv",
                  ["Source url", "Anchor", "Nofollow", "Link type"],
                  [
                    ["https://example-blog.com/best-tools-2026", "best tools", "FALSE", "Article"],
                    ["https://another-site.com/resources", "resources page", "TRUE", "Business Listing"],
                    ["https://writers-hub.com/guest-column", "brand anchor", "FALSE", "Guest Post"]
                  ]
                )
              }
              className="flex h-10 items-center gap-2 rounded-md border border-line px-4 text-sm font-medium text-ink transition hover:bg-field"
              title="A sample sheet matching the SEMrush backlink export format — only 'Source url' is required"
            >
              <Download className="h-4 w-4" />
              Sample sheet
            </button>
            <span className="text-xs text-muted">
              SEMrush exports are detected automatically — extra columns are ignored, missing optional columns don&apos;t block.
            </span>
          </div>
          {preview ? (
            <div className="rounded-lg border border-line bg-field/40 p-3 text-sm">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-ocean/10 px-2.5 py-0.5 text-xs font-semibold text-ocean">
                  {preview.format === "semrush" ? "SEMrush export detected" : preview.format === "headers" ? "Header row detected" : "Plain list"}
                </span>
                <span className="text-xs text-muted">{preview.row_count} link{preview.row_count === 1 ? "" : "s"} will be imported</span>
                {Object.entries(preview.mapping).map(([col, field]) => (
                  <span key={col} className="rounded bg-panel px-1.5 py-0.5 text-[11px] text-muted">
                    {col} → <span className="font-medium text-ink">{field}</span>
                  </span>
                ))}
              </div>
              {preview.sample.length ? (
                <div className="space-y-1">
                  {preview.sample.map((r, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="max-w-[380px] truncate font-medium text-ink" title={r.url}>{r.url}</span>
                      {r.anchor ? <span className="text-muted">“{r.anchor}”</span> : null}
                      {r.rel ? <span className="rounded bg-panel px-1.5 py-0.5 text-muted">{r.rel}</span> : null}
                      {r.link_type ? <span className="rounded bg-plum/10 px-1.5 py-0.5 text-plum">{r.link_type}</span> : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {preview.warnings.length ? (
                <div className="mt-2 space-y-0.5">
                  {preview.warnings.map((w, i) => (
                    <p key={i} className="text-xs text-ember">{w}</p>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {(parents.data || []).length ? (
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
            <h3 className="text-sm font-semibold text-ink">Competitors</h3>
            <input
              value={parentSearch}
              onChange={(e) => setParentSearch(e.target.value)}
              placeholder="Search competitors…"
              className="h-9 w-52 rounded-md border border-line bg-panel px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
            />
          </div>
          <div className="divide-y divide-line">
            {(parents.data || [])
              .filter((p) => {
                const q = parentSearch.trim().toLowerCase();
                if (!q) return true;
                return (
                  p.display_name.toLowerCase().includes(q) || p.competitor.toLowerCase().includes(q)
                );
              })
              .map((p) => {
                const isOpen = openCompetitor === p.competitor;
                const uploads = (sheets.data || []).filter((s) => p.sheet_ids.includes(s.id));
                return (
                  <div key={p.competitor}>
                    <div
                      onClick={() => setOpenCompetitor(isOpen ? null : p.competitor)}
                      title="Click to see every backlink across this competitor's uploads"
                      className={clsx(
                        "flex cursor-pointer flex-wrap items-center justify-between gap-2 p-3 text-sm transition hover:bg-field/50",
                        isOpen && "bg-ocean/5"
                      )}
                    >
                      <div className="min-w-0">
                        <Swords className={clsx("mr-1 inline-block h-4 w-4 text-muted transition", isOpen && "text-ocean")} />
                        <span className="font-semibold text-ink">{p.display_name}</span>{" "}
                        {p.competitor && p.competitor !== p.display_name ? (
                          <span className="mr-1 text-xs text-muted">({p.competitor})</span>
                        ) : null}
                        {p.competitor_url ? (
                          <a
                            href={p.competitor_url}
                            target="_blank"
                            rel="noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            title="Open the competitor's website"
                            className="text-xs text-ocean hover:underline"
                          >
                            visit ↗
                          </a>
                        ) : null}
                      </div>
                      <span className="whitespace-nowrap text-xs text-muted" title="New domains = domains first seen from this competitor that this project doesn't have yet">
                        {p.uploads} upload{p.uploads === 1 ? "" : "s"} · {p.total_rows} links · {p.new_domains} new domain{p.new_domains === 1 ? "" : "s"} · last {formatDate(p.last_upload_at)}
                      </span>
                    </div>
                    {isOpen ? (
                      <div className="space-y-3 border-t border-line bg-field/40 p-3">
                        <div>
                          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
                            Uploads
                          </div>
                          <div className="space-y-1">
                            {uploads.map((sh) => (
                              <div key={sh.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                                <span className="min-w-0 truncate">
                                  <span className="font-medium text-ink">{sh.name}</span>{" "}
                                  <span className="text-muted">
                                    {sh.total_rows} links · {formatDate(sh.created_at)}
                                  </span>
                                </span>
                                <button
                                  onClick={() => {
                                    if (window.confirm(`Delete upload “${sh.name}” and its ${sh.total_rows} competitor links? Opportunities will be recalculated.`)) {
                                      deleteSheet.mutate(sh.id);
                                    }
                                  }}
                                  className="grid h-7 w-7 place-items-center rounded-md border border-line text-danger transition hover:bg-danger/10"
                                  aria-label={`Delete upload ${sh.name}`}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div>
                          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                            <span className="text-xs font-semibold uppercase tracking-wide text-muted">Backlinks</span>
                            <input
                              value={compQ}
                              onChange={(e) => setCompQ(e.target.value)}
                              placeholder="Search this competitor's source URLs…"
                              className="h-8 w-64 rounded-md border border-line bg-panel px-2 text-xs focus:outline-none focus:ring-2 focus:ring-ocean/20"
                            />
                          </div>
                          {parentLinks.isLoading ? (
                            <div className="flex justify-center p-3"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
                          ) : (
                            <div className="max-h-80 space-y-1 overflow-y-auto">
                              {(parentLinks.data || []).map((l, i) => (
                                <div key={i} className="flex flex-wrap items-center gap-2 text-xs">
                                  <a href={l.url} target="_blank" rel="noreferrer" className="max-w-[420px] truncate text-ocean hover:underline" title={l.url}>
                                    {l.url}
                                  </a>
                                  {l.source_domain ? <span className="rounded bg-panel px-1.5 py-0.5 text-muted">{l.source_domain}</span> : null}
                                  {l.anchor ? <span className="text-muted">“{l.anchor}”</span> : null}
                                  {l.rel ? <span className="rounded bg-panel px-1.5 py-0.5 text-muted">{l.rel}</span> : null}
                                  {l.link_type ? <span className="rounded bg-plum/10 px-1.5 py-0.5 text-plum">{l.link_type}</span> : null}
                                  <MetricTag label="DA" value={l.da} />
                                  <MetricTag label="AS" value={l.semrush_as} />
                                  {l.domain_category === "new_opportunity" && l.decision !== "dismissed" ? <span className="rounded bg-ocean/10 px-1.5 py-0.5 font-semibold text-ocean">Opportunity</span> : null}
                                  {l.domain_category === "existing" ? <span className="rounded bg-plum/10 px-1.5 py-0.5 text-plum">Already have</span> : null}
                                  {l.decision === "dismissed" ? <span className="rounded bg-field px-1.5 py-0.5 text-muted">Dismissed</span> : null}
                                  {l.upload_name ? <span className="rounded bg-field px-1.5 py-0.5 text-muted">via {l.upload_name}</span> : null}
                                </div>
                              ))}
                              {!(parentLinks.data || []).length ? <p className="text-xs text-muted">No links match.</p> : null}
                              {(parentLinks.data || []).length >= 500 ? (
                                <p className="pt-1 text-[11px] text-muted">Showing the first 500 — refine the search to narrow down.</p>
                              ) : null}
                            </div>
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Competitor source domains</h3>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={domSearch}
              onChange={(e) => setDomSearch(e.target.value)}
              placeholder="Search domain…"
              className="h-9 w-40 rounded-md border border-line bg-panel px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
            />
            <select
              value={cat}
              onChange={(e) => setCat(e.target.value)}
              className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
            >
              <option value="">All</option>
              <option value="new_opportunity">New opportunities</option>
              <option value="existing">Already have</option>
            </select>
            <button
              onClick={() => setHideDismissed((v) => !v)}
              className={clsx(
                "h-8 rounded-full border px-3 text-xs font-medium transition",
                hideDismissed ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
              )}
            >
              Hide dismissed
            </button>
            <button
              onClick={() => setHideGuest((v) => !v)}
              title="Hide domains whose competitor links are tagged Guest Post"
              className={clsx(
                "h-8 rounded-full border px-3 text-xs font-medium transition",
                hideGuest ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
              )}
            >
              Hide guest posts
            </button>
            <button
              onClick={() => checkMetrics.mutate()}
              disabled={checkMetrics.isPending || !(domains.data || []).length}
              title="Fill DA/PA for these domains — reuses our own recent checks first (no API cost), only calls the API for what's missing or stale (10-day freshness)"
              className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
            >
              {checkMetrics.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Gauge className="h-3.5 w-3.5" />}
              Check metrics
            </button>
            <button
              onClick={exportCsv}
              disabled={!(domains.data || []).length}
              className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
            >
              <Download className="h-3.5 w-3.5" /> Export CSV
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10 bg-field text-xs uppercase text-muted">
              <tr>
                <SortTh label="Domain" sortKey="domain" sort={domSort} dir={domDir} onSort={onDomSort} />
                <Th>Status</Th>
                <SortTh label="Competitor links" sortKey="links" sort={domSort} dir={domDir} onSort={onDomSort} />
                <SortTh label="Our links" sortKey="ours" sort={domSort} dir={domDir} onSort={onDomSort} />
                <SortTh label="Indexed %" sortKey="indexed" sort={domSort} dir={domDir} onSort={onDomSort} />
                <SortTh label="DA" sortKey="da" sort={domSort} dir={domDir} onSort={onDomSort}
                  help="Domain authority (Moz). Click to rank the outreach list by strongest domains." />
                <SortTh label="PA" sortKey="pa" sort={domSort} dir={domDir} onSort={onDomSort} />
                <Th>Action</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(domains.data || []).map((d) => (
                <Fragment key={d.id}>
                  <tr
                    onClick={() => setOpenDomain(openDomain === d.domain_key ? null : d.domain_key)}
                    className={clsx(
                      "cursor-pointer hover:bg-field/60",
                      d.decision === "dismissed" && "opacity-55",
                      openDomain === d.domain_key && "bg-ocean/5"
                    )}
                  >
                    <Td>
                      <a
                        href={`https://${d.domain_key}`}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-ocean hover:underline"
                      >
                        {d.domain_key}
                      </a>
                      {d.has_guest_post ? (
                        <span
                          className="ml-1.5 rounded bg-plum/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-plum"
                          title="At least one competitor link here is tagged Guest Post (Guest Post / guestpost / GP)"
                        >
                          Guest post
                        </span>
                      ) : null}
                    </Td>
                    <Td>
                      {d.decision === "dismissed" ? (
                        <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-muted" title={d.decision_reason || "Dismissed manually"}>
                          Dismissed
                        </span>
                      ) : d.category === "new_opportunity" ? (
                        <span className="rounded bg-ocean/10 px-2 py-0.5 text-xs font-medium text-ocean">Opportunity</span>
                      ) : (
                        <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-muted" title="Removed from opportunities because this project already has a link from this domain">
                          Already used
                        </span>
                      )}
                    </Td>
                    <Td>{d.url_count}</Td>
                    <Td>{d.our_link_count}</Td>
                    <Td>{d.our_indexed_pct != null ? `${d.our_indexed_pct}%` : "-"}</Td>
                    <Td>{d.da ?? "—"}</Td>
                    <Td>{d.pa ?? "—"}</Td>
                    <Td>
                      {d.category === "new_opportunity" ? (
                        d.decision === "dismissed" ? (
                          <button
                            onClick={(e) => { e.stopPropagation(); decide.mutate({ domain_key: d.domain_key, status: "open" }); }}
                            className="text-xs font-medium text-ocean hover:underline"
                          >
                            Re-open
                          </button>
                        ) : (
                          <button
                            onClick={(e) => { e.stopPropagation(); decide.mutate({ domain_key: d.domain_key, status: "dismissed" }); }}
                            className="text-xs font-medium text-muted hover:text-danger hover:underline"
                          >
                            Dismiss
                          </button>
                        )
                      ) : null}
                    </Td>
                  </tr>
                  {openDomain === d.domain_key ? (
                    <tr>
                      <td colSpan={8} className="bg-field/40 p-3">
                        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
                          Competitor links on {d.domain_key}
                        </div>
                        {domainLinks.isLoading ? (
                          <div className="flex justify-center p-3"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
                        ) : (
                          <div className="max-h-64 space-y-1 overflow-y-auto">
                            {(domainLinks.data || []).map((l, i) => (
                              <div key={i} className="flex flex-wrap items-center gap-2 text-xs">
                                <a href={l.url} target="_blank" rel="noreferrer" className="max-w-[420px] truncate text-ocean hover:underline" title={l.url}>
                                  {l.url}
                                </a>
                                {l.anchor ? <span className="text-muted">“{l.anchor}”</span> : null}
                                {l.rel ? <span className="rounded bg-panel px-1.5 py-0.5 text-muted">{l.rel}</span> : null}
                                {l.link_type ? <span className="rounded bg-plum/10 px-1.5 py-0.5 text-plum">{l.link_type}</span> : null}
                                <span className="text-muted">from “{l.upload_name}”</span>
                              </div>
                            ))}
                            {!(domainLinks.data || []).length ? (
                              <p className="text-xs text-muted">No stored links for this domain.</p>
                            ) : null}
                          </div>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!domains.isLoading && !(domains.data || []).length ? (
            <Empty label="No competitor data yet — paste some links above." />
          ) : null}
          {(domains.data || []).length >= domLimit ? (
            <div className="border-t border-line p-2 text-center">
              <button
                onClick={() => setDomLimit((l) => l + 200)}
                className="h-9 rounded-lg border border-line px-4 text-sm font-medium text-ink transition hover:bg-field"
              >
                Load more domains
              </button>
            </div>
          ) : null}
        </div>
      </section>
    </section>
  );
}

function AlertsDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();

  // ── Notification center ────────────────────────────────────────────────
  type Notif = {
    id: string; project_id: string | null; backlink_id: string | null;
    channel: string; status: string; severity: string | null;
    title: string; body: string | null; created_at: string; read_at: string | null;
  };
  const [fSeverity, setFSeverity] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const notifQS = () => {
    const p = new URLSearchParams();
    if (fSeverity) p.set("severity", fSeverity);
    if (fStatus) p.set("status", fStatus);
    if (unreadOnly) p.set("unread_only", "true");
    const s = p.toString();
    return s ? `?${s}` : "";
  };
  const notifs = useQuery({
    queryKey: ["notifications", token, fSeverity, fStatus, unreadOnly],
    enabled: Boolean(token),
    queryFn: () => api<Notif[]>(`/notifications${notifQS()}`, { token })
  });
  const stats = useQuery({
    queryKey: ["notification-stats", token],
    enabled: Boolean(token),
    queryFn: () =>
      api<{ total: number; unread: number; by_severity: Record<string, number> }>(
        "/notifications/stats",
        { token }
      )
  });
  const refreshNotif = () => {
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
    queryClient.invalidateQueries({ queryKey: ["notification-stats"] });
  };
  const markRead = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/notifications/${id}/read`, { token, method: "POST" }),
    onSuccess: refreshNotif
  });
  const markAll = useMutation({
    mutationFn: () => api<{ message: string }>("/notifications/read-all", { token, method: "POST" }),
    onSuccess: (r) => {
      onNotice(r.message);
      refreshNotif();
    }
  });

  // ── Rule management ────────────────────────────────────────────────────
  const [name, setName] = useState("Critical backlink regressions");
  const [minSeverity, setMinSeverity] = useState("HIGH");
  const alerts = useQuery({
    queryKey: ["alerts", token],
    enabled: Boolean(token),
    queryFn: () => api<AlertRule[]>("/alert-rules", { token })
  });
  const create = useMutation({
    mutationFn: () =>
      api<AlertRule>("/alert-rules", {
        token,
        method: "POST",
        body: JSON.stringify({
          name,
          project_id: projectId || null,
          min_severity: minSeverity,
          event_types: [],
          channels: ["in_app"],
          dedup_window_minutes: 60
        })
      }),
    onSuccess: () => {
      onNotice("Alert rule saved");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });
  const deleteRule = useMutation({
    mutationFn: (id: string) =>
      api<{ message: string }>(`/alert-rules/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Alert rule deleted");
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  return (
    <section className="space-y-5">
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line p-4">
          <div>
            <h2 className="text-base font-semibold text-ink">Notifications</h2>
            <p className="text-sm text-muted">
              {stats.data?.unread ?? 0} unread of {stats.data?.total ?? 0}
              {Object.entries(stats.data?.by_severity || {}).length ? " · " : ""}
              {Object.entries(stats.data?.by_severity || {})
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={fSeverity}
              onChange={(e) => setFSeverity(e.target.value)}
              className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
            >
              <option value="">All severities</option>
              {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              value={fStatus}
              onChange={(e) => setFStatus(e.target.value)}
              className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
            >
              <option value="">All statuses</option>
              {["pending", "sent", "failed", "read"].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              onClick={() => setUnreadOnly((v) => !v)}
              className={clsx(
                "h-9 rounded-md border px-3 text-sm font-medium",
                unreadOnly ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:bg-field"
              )}
            >
              Unread only
            </button>
            <button
              onClick={() => markAll.mutate()}
              disabled={markAll.isPending}
              className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm font-medium text-ink hover:bg-field"
            >
              {markAll.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
              Mark all read
            </button>
          </div>
        </div>
        <div className="max-h-[460px] divide-y divide-line overflow-y-auto">
          {(notifs.data || []).map((n) => (
            <div
              key={n.id}
              className={clsx("flex items-start justify-between gap-3 p-3", n.status !== "read" && "bg-ocean/5")}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Severity value={n.severity || "INFO"} />
                  <span className="truncate text-sm font-medium text-ink">{n.title}</span>
                </div>
                {n.body ? <div className="mt-1 break-words text-xs text-muted">{n.body}</div> : null}
                <div className="mt-1 text-xs text-muted">{formatDate(n.created_at)} · {n.status}</div>
              </div>
              {n.status !== "read" ? (
                <button
                  onClick={() => markRead.mutate(n.id)}
                  className="shrink-0 text-xs font-medium text-ocean hover:underline"
                >
                  Mark read
                </button>
              ) : null}
            </div>
          ))}
          {!notifs.isLoading && !(notifs.data || []).length ? <Empty label="No notifications" /> : null}
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
        <form
          className="rounded-xl border border-line bg-panel shadow-card p-4"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate();
          }}
        >
          <SectionTitle title="New alert rule" flush />
          <div className="space-y-3 pt-3">
            <Field label="Name" value={name} onChange={setName} />
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase text-muted">Minimum severity</span>
              <select
                className="h-10 w-full rounded-md border border-line bg-panel px-3 text-sm"
                value={minSeverity}
                onChange={(event) => setMinSeverity(event.target.value)}
              >
                <option>CRITICAL</option>
                <option>HIGH</option>
                <option>MEDIUM</option>
                <option>LOW</option>
              </select>
            </label>
            <p className="text-xs text-muted">
              {projectId ? "Scoped to the selected project." : "Applies across all projects."}
            </p>
            <button className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white">
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
              Save rule
            </button>
          </div>
        </form>
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Alert rules" />
          <div className="divide-y divide-line">
            {(alerts.data || []).map((rule) => (
              <div key={rule.id} className="flex items-center justify-between gap-3 p-4">
                <div className="min-w-0">
                  <div className="truncate font-medium text-ink">{rule.name}</div>
                  <div className="mt-1 text-xs text-muted">
                    {rule.channels.join(", ")} · {rule.dedup_window_minutes}m dedup
                    {rule.is_active ? "" : " · paused"}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Severity value={rule.min_severity} />
                  <button
                    onClick={() => {
                      if (window.confirm(`Delete alert rule “${rule.name}”?`)) deleteRule.mutate(rule.id);
                    }}
                    className="grid h-8 w-8 place-items-center rounded-md border border-line text-danger transition hover:bg-danger/10"
                    aria-label={`Delete rule ${rule.name}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
            {!alerts.isLoading && !alerts.data?.length ? <Empty label="No alert rules yet" /> : null}
          </div>
        </section>
      </section>
    </section>
  );
}

// Report filter dropdowns (dim → filter key → label), driven by analytics facets.
const REPORT_FACETS: Array<[string, string, string]> = [
  ["status", "status", "QA status"],
  ["index_status", "index_status", "Index"],
  ["duplicate_status", "duplicate_status", "Duplicate"],
  ["user", "assigned_user_label", "Assigned user"],
  ["link_type", "link_type", "Link type"],
  ["source_domain", "source_domain", "Source domain"],
  ["scoring_version", "scoring_rule_version_id", "Scoring version"]
];

// Plain-language report types (non-technical labels + a one-line description).
const REPORT_TYPES: Array<{ value: string; label: string; desc: string }> = [
  { value: "monthly_qa", label: "Full QA report", desc: "Every selected link with its full QA result, score, index and duplicate status." },
  { value: "failed_links", label: "Problem links only", desc: "Only the links that are not qualified — the ones that need action." },
  { value: "change_history", label: "Change history", desc: "What changed over time: links lost, status flips, anchor / rel changes." },
  { value: "client", label: "Client summary", desc: "A clean, client-facing summary of backlink health." },
  { value: "vendor", label: "Vendor report", desc: "Results grouped for reviewing a vendor's delivered links." },
  { value: "campaign", label: "Campaign report", desc: "Results for one outreach campaign." },
  { value: "source_domain_summary", label: "Source-domain summary", desc: "One row per source domain: totals, pass/fail, indexed %, nofollow, duplicates." },
  { value: "link_type_summary", label: "Link-type summary", desc: "One row per link type: totals, pass/fail, indexed %, nofollow, duplicates." },
  { value: "user_performance", label: "User performance", desc: "One row per assigned user: volume, pass rate, average score." }
];

const REPORT_FORMATS: Array<{ value: string; label: string; hint: string }> = [
  { value: "xlsx", label: "Excel (.xlsx)", hint: "Best for filtering & sharing" },
  { value: "csv", label: "CSV", hint: "Plain data for import" },
  { value: "pdf", label: "PDF", hint: "Print / send to clients" }
];

const FILTER_LABELS: Record<string, string> = {
  status: "QA status",
  index_status: "Index",
  duplicate_status: "Duplicate",
  assigned_user_label: "User",
  link_type: "Link type",
  source_domain: "Source domain",
  scoring_rule_version_id: "Scoring version"
};

function typeLabel(t: string) {
  return REPORT_TYPES.find((x) => x.value === t)?.label || t.replace(/_/g, " ");
}

function ReportsDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [format, setFormat] = useState("xlsx");
  const [type, setType] = useState("monthly_qa");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const setFilter = (k: string, v: string) =>
    setFilters((f) => {
      const n = { ...f };
      if (v) n[k] = v;
      else delete n[k];
      return n;
    });

  // Saved report templates (type + filters + format), reusable in one click.
  type ReportTemplate = { name: string; type: string; format: string; filters: Record<string, string> };
  const [templates, setTemplates] = useState<ReportTemplate[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("ls_report_templates") || "[]");
    } catch {
      return [];
    }
  });
  const [templateName, setTemplateName] = useState("");
  const persistTemplates = (next: ReportTemplate[]) => {
    setTemplates(next);
    try {
      localStorage.setItem("ls_report_templates", JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };
  const saveTemplate = () => {
    const name = templateName.trim();
    if (!name) return;
    persistTemplates([...templates.filter((t) => t.name !== name), { name, type, format, filters }]);
    setTemplateName("");
    onNotice(`Template “${name}” saved`);
  };
  const applyTemplate = (t: ReportTemplate) => {
    setType(t.type);
    setFormat(t.format);
    setFilters(t.filters);
  };

  // Reuse the analytics engine to drive the report filter dropdowns + a live count.
  const facets = useQuery({
    queryKey: ["report-facets", token, projectId, filters],
    enabled: Boolean(token),
    queryFn: () =>
      api<AnalyticsResponse>("/analytics/query", {
        token,
        method: "POST",
        body: JSON.stringify({
          filters: projectId ? { ...filters, project_id: projectId } : filters,
          facets: REPORT_FACETS.map(([d]) => d)
        })
      })
  });
  const matchCount = Number(facets.data?.summary?.total ?? 0);

  const reports = useQuery({
    queryKey: ["reports", token],
    enabled: Boolean(token),
    // Live status while any report is still generating — no manual refresh.
    refetchInterval: (q) =>
      (q.state.data || []).some((r) => r.status === "generating" || r.status === "pending")
        ? 3000
        : false,
    queryFn: () => api<Report[]>("/reports", { token })
  });
  const [showBuilder, setShowBuilder] = useState(false);
  const [repSearch, setRepSearch] = useState("");
  const [repType, setRepType] = useState("");

  // Group reports into version stacks by (type + project) — the same scope the
  // backend uses for versioning. Sort each stack newest-first by time (robust even
  // for older rows imported before versioning existed); the card derives a clean
  // sequential version number from position so the history always reads v1..vN.
  const groups = useMemo(() => {
    const q = repSearch.trim().toLowerCase();
    const map = new Map<string, Report[]>();
    for (const r of reports.data || []) {
      if (projectId && r.project_id && r.project_id !== projectId) continue;
      if (repType && r.report_type !== repType) continue;
      if (q && !`${r.title || ""} ${r.report_type}`.toLowerCase().includes(q)) continue;
      const key = `${r.report_type}__${r.project_id || "all"}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(r);
    }
    const arr = [...map.values()].map((rs) =>
      rs.slice().sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    );
    arr.sort(
      (a, b) => new Date(b[0].created_at).getTime() - new Date(a[0].created_at).getTime()
    );
    return arr;
  }, [reports.data, repSearch, repType, projectId]);

  const create = useMutation({
    mutationFn: () => {
      const filterWords = Object.entries(filters)
        .map(([k, v]) => `${FILTER_LABELS[k] || k} ${v}`)
        .join(", ");
      const title = `${typeLabel(type)}${filterWords ? ` — ${filterWords}` : ""}`;
      return api<Report>("/reports", {
        token,
        method: "POST",
        body: JSON.stringify({
          project_id: projectId || null,
          report_type: type,
          format,
          title,
          filters: { ...filters, limit: 50000 }
        })
      });
    },
    onSuccess: () => {
      onNotice("Report is generating — it will appear below as a new version.");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["reports"] }), 2500);
    },
    onError: (err: Error) => onNotice(err.message)
  });

  async function download(report: Report) {
    try {
      const res = await fetch(`${API_BASE}/reports/${report.id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok) throw new Error(`Download failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${report.title || "report"}_v${report.version ?? 1}.${report.format}`.replace(/\s+/g, "_");
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      onNotice(err instanceof Error ? err.message : "Download failed");
    }
  }

  const activeType = REPORT_TYPES.find((t) => t.value === type);

  const deleteReport = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/reports/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Report deleted");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      setViewReport(null);
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // In-app report viewer (paginated over the stored file — no download needed).
  const [viewReport, setViewReport] = useState<Report | null>(null);
  const [viewOffset, setViewOffset] = useState(0);
  const viewRows = useQuery({
    queryKey: ["report-rows", token, viewReport?.id, viewOffset],
    enabled: Boolean(token) && Boolean(viewReport),
    queryFn: () =>
      api<{ headers: string[]; rows: string[][]; total: number; offset: number }>(
        `/reports/${viewReport!.id}/rows?offset=${viewOffset}&limit=50`,
        { token }
      )
  });

  // Rendered directly under the clicked report card — never at the page bottom.
  const viewerPanel = viewReport ? (
    <div className="rounded-xl border border-ocean/40 bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-ink">{viewReport.title}</h3>
          <p className="text-xs text-muted">
            {viewRows.data ? `${viewRows.data.total.toLocaleString()} rows` : "Loading…"}
            {viewRows.data && viewRows.data.total > 50
              ? ` · showing ${viewOffset + 1}–${Math.min(viewOffset + 50, viewRows.data.total)}`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            disabled={viewOffset === 0}
            onClick={() => setViewOffset((o) => Math.max(0, o - 50))}
            className="h-8 rounded-lg border border-line px-2.5 text-xs font-medium text-ink hover:bg-field disabled:opacity-40"
          >
            ← Prev
          </button>
          <button
            disabled={!viewRows.data || viewOffset + 50 >= viewRows.data.total}
            onClick={() => setViewOffset((o) => o + 50)}
            className="h-8 rounded-lg border border-line px-2.5 text-xs font-medium text-ink hover:bg-field disabled:opacity-40"
          >
            Next →
          </button>
          <button
            onClick={() => setViewReport(null)}
            className="text-xs font-medium text-ocean hover:underline"
          >
            Close
          </button>
        </div>
      </div>
      <div className="max-h-[480px] overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-field uppercase text-muted">
            <tr>
              {(viewRows.data?.headers || []).map((h, i) => (
                <th key={i} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(viewRows.data?.rows || []).map((r, i) => (
              <tr key={i} className="hover:bg-field/60">
                {r.map((c, j) => (
                  <td key={j} className="max-w-[280px] truncate px-3 py-1.5 align-top text-ink" title={c}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {viewRows.isLoading ? (
          <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
        ) : null}
        {viewRows.isError ? (
          <div className="p-4 text-center text-sm text-danger">
            {(viewRows.error as Error)?.message || "Could not open this report."}
          </div>
        ) : null}
      </div>
    </div>
  ) : null;

  return (
    <section className="space-y-4">
      {/* ── Header: list is primary; the builder opens on demand ── */}
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink">Reports</h2>
          <p className="text-sm text-muted">
            {projectId ? "This project's reports." : "All reports."} Every regeneration is kept as a version.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={repSearch}
            onChange={(e) => setRepSearch(e.target.value)}
            placeholder="Search reports…"
            className="h-9 w-44 rounded-lg border border-line bg-panel px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <select
            value={repType}
            onChange={(e) => setRepType(e.target.value)}
            className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
          >
            <option value="">All types</option>
            {REPORT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <button
            onClick={() => setShowBuilder((v) => !v)}
            className={clsx(
              "flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-semibold transition",
              showBuilder
                ? "border border-line text-ink hover:bg-field"
                : "bg-ocean text-white hover:opacity-90 dark:text-slate-900"
            )}
          >
            {showBuilder ? <XCircle className="h-4 w-4" /> : <FileSpreadsheet className="h-4 w-4" />}
            {showBuilder ? "Close builder" : "Generate report"}
          </button>
        </div>
      </div>
      {reports.isError ? (
        <p className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          Reports could not be loaded — {(reports.error as Error)?.message || "try refreshing"}.
        </p>
      ) : null}

      {showBuilder ? (
      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="border-b border-line p-4">
          <h2 className="text-base font-semibold text-ink">Build a report</h2>
          <p className="text-sm text-muted">
            Pick what to include, choose a file type, and generate. Each time you generate the
            same report, it&apos;s saved as a new <span className="font-medium text-ink">version</span>{" "}
            — older ones are kept so you always have history.
          </p>
        </div>

        <div className="space-y-4 p-4">
          {templates.length ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">Templates</span>
              {templates.map((t) => (
                <span key={t.name} className="inline-flex items-center gap-1 rounded-full border border-line bg-field px-2.5 py-1 text-xs">
                  <button onClick={() => applyTemplate(t)} className="font-medium text-ink hover:text-ocean">
                    {t.name}
                  </button>
                  <button
                    onClick={() => persistTemplates(templates.filter((x) => x.name !== t.name))}
                    aria-label={`Delete template ${t.name}`}
                    className="text-muted hover:text-danger"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          {/* Step 1 — type */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase text-muted">1 · What to report</div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {REPORT_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setType(t.value)}
                  className={clsx(
                    "rounded-lg border p-3 text-left transition",
                    type === t.value
                      ? "border-ocean bg-ocean/10 ring-1 ring-ocean/30"
                      : "border-line bg-panel hover:border-ocean/40"
                  )}
                >
                  <div className="text-sm font-semibold text-ink">{t.label}</div>
                  <div className="mt-0.5 text-xs leading-snug text-muted">{t.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Step 2 — which links (scope + filters + live count) */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase text-muted">2 · Which links</div>
            <div className="rounded-md border border-line bg-panel p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
                <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-ink">
                  Scope: {projectId ? "selected project" : "🏢 all projects"}
                </span>
                <span className="text-muted">
                  This report will include{" "}
                  <span className="font-semibold text-ink">{matchCount.toLocaleString()}</span> links.
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {REPORT_FACETS.map(([dim, key, label]) => {
                  const opts = facets.data?.facets?.[dim] || [];
                  return (
                    <select
                      key={dim}
                      className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
                      value={filters[key] || ""}
                      onChange={(e) => setFilter(key, e.target.value)}
                    >
                      <option value="">{label}: all</option>
                      {opts.map((o) => (
                        <option key={String(o.value)} value={String(o.value)}>
                          {String(o.label || o.value)} ({o.count})
                        </option>
                      ))}
                    </select>
                  );
                })}
                <label className="flex items-center gap-1 text-xs text-muted">
                  Checked
                  <input
                    type="date"
                    value={filters.checked_from || ""}
                    onChange={(e) => setFilter("checked_from", e.target.value)}
                    className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
                  />
                  –
                  <input
                    type="date"
                    value={filters.checked_to || ""}
                    onChange={(e) => setFilter("checked_to", e.target.value)}
                    className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
                  />
                </label>
                {Object.keys(filters).length ? (
                  <button
                    onClick={() => setFilters({})}
                    className="text-xs font-medium text-ocean hover:underline"
                  >
                    Clear filters
                  </button>
                ) : null}
              </div>
            </div>
          </div>

          {/* Step 3 — format + generate */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase text-muted">3 · File type</div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap gap-2">
                {REPORT_FORMATS.map((f) => (
                  <button
                    key={f.value}
                    onClick={() => setFormat(f.value)}
                    title={f.hint}
                    className={clsx(
                      "rounded-lg border px-3 py-2 text-sm transition",
                      format === f.value
                        ? "border-ocean bg-ocean/10 font-semibold text-ocean"
                        : "border-line bg-panel text-ink hover:border-ocean/40"
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveTemplate();
                  }}
                  placeholder="Save as template…"
                  className="h-9 w-40 rounded-xl border border-line bg-panel shadow-card px-2 text-xs"
                />
                <button
                  onClick={saveTemplate}
                  disabled={!templateName.trim()}
                  className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
                >
                  Save
                </button>
                <button
                  onClick={() => create.mutate()}
                  disabled={create.isPending}
                  className="flex h-11 items-center justify-center gap-2 rounded-lg bg-ocean px-5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
                >
                  {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
                  Generate {activeType?.label || "report"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
      ) : null}

      {/* ── Saved reports (grouped by version) ──────────────────── */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <History className="h-4 w-4 text-muted" />
          <h3 className="text-sm font-semibold text-ink">Your reports</h3>
          <span className="text-xs text-muted">— newest version on top, older versions tucked underneath. Click View to read a report right here.</span>
        </div>
        <div className="space-y-3">
          {groups.map((versions) => (
            <Fragment key={versions[0].id}>
              <ReportGroup
                versions={versions}
                onDownload={download}
                onView={(r) => {
                  setViewReport(viewReport?.id === r.id ? null : r);
                  setViewOffset(0);
                }}
                onDelete={(r) => deleteReport.mutate(r.id)}
              />
              {viewReport && versions.some((v) => v.id === viewReport.id) ? viewerPanel : null}
            </Fragment>
          ))}
          {reports.isLoading ? <Empty label="Loading reports…" /> : null}
          {!reports.isLoading && !groups.length ? (
            <Empty label={repSearch || repType ? "No reports match this search/filter." : "No reports yet — click “Generate report” above to build one."} />
          ) : null}
        </div>
      </div>
    </section>
  );
}

function FilterSummary({ filters }: { filters?: Record<string, unknown> }) {
  const entries = Object.entries(filters || {}).filter(([k]) => k !== "limit");
  if (!entries.length) {
    return <div className="mt-1 text-[11px] text-muted">All links (no filter)</div>;
  }
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded bg-field px-1.5 py-0.5 text-[10px] font-medium text-muted">
          {FILTER_LABELS[k] || k}: {String(v)}
        </span>
      ))}
    </div>
  );
}

function ReportGroup({
  versions,
  onDownload,
  onView,
  onDelete
}: {
  versions: Report[];
  onDownload: (r: Report) => void;
  onView: (r: Report) => void;
  onDelete: (r: Report) => void;
}) {
  const [open, setOpen] = useState(false);
  const latest = versions[0];
  const older = versions.slice(1);
  // Clean sequential version numbers from position: newest = highest.
  const total = versions.length;
  const displayV = (i: number) => total - i;

  return (
    <div className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-ocean" />
            <span className="font-semibold text-ink">{typeLabel(latest.report_type)}</span>
            <span className="rounded bg-field px-1.5 py-0.5 text-[11px] font-medium text-ink">
              {latest.project_name || "All projects"}
            </span>
            <span className="rounded bg-ocean/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ocean">
              Latest · v{displayV(0)}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted">
            {latest.row_count ?? "—"} links · {(latest.format || "").toUpperCase()} ·{" "}
            {formatDate(latest.created_at)}
          </div>
          <FilterSummary filters={latest.filters} />
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Status value={latest.status.toUpperCase()} />
          {latest.status === "completed" && latest.format !== "pdf" ? (
            <button
              onClick={() => onView(latest)}
              className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
            >
              View
            </button>
          ) : null}
          <button
            onClick={() => {
              if (window.confirm(`Delete report “${latest.title}” (latest version)?`)) onDelete(latest);
            }}
            title="Delete this report version"
            className="grid h-9 w-9 place-items-center rounded-md border border-line text-danger transition hover:bg-danger/10"
            aria-label="Delete report"
          >
            <Trash2 className="h-4 w-4" />
          </button>
          <button
            disabled={latest.status !== "completed"}
            onClick={() => onDownload(latest)}
            className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            Download
          </button>
        </div>
      </div>

      {older.length ? (
        <div className="border-t border-line">
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center gap-1.5 px-4 py-2 text-xs font-medium text-muted transition hover:bg-field"
          >
            {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {open ? "Hide" : "Show"} {older.length} older version{older.length > 1 ? "s" : ""}
          </button>
          {open ? (
            <div className="divide-y divide-line border-t border-line">
              {older.map((r, i) => (
                <div key={r.id} className="flex items-center justify-between gap-3 px-4 py-2">
                  <div className="flex items-center gap-2 text-xs text-muted">
                    <span className="rounded bg-field px-1.5 py-0.5 font-semibold">v{displayV(i + 1)}</span>
                    <span>
                      {r.row_count ?? "—"} links · {(r.format || "").toUpperCase()} · {formatDate(r.created_at)}
                    </span>
                  </div>
                  <span className="flex items-center gap-1.5">
                    <button
                      onClick={() => {
                        if (window.confirm("Delete this older report version?")) onDelete(r);
                      }}
                      title="Delete this version"
                      className="grid h-7 w-7 place-items-center rounded-md border border-line text-danger transition hover:bg-danger/10"
                      aria-label="Delete report version"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      disabled={r.status !== "completed"}
                      onClick={() => onDownload(r)}
                      className="flex items-center gap-1 rounded-md border border-line bg-panel px-2 py-1 text-xs font-medium text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Download className="h-3.5 w-3.5" /> Download
                    </button>
                  </span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type ProjectDomainRow = {
  domain_key: string;
  project_links?: number;
  indexed?: number;
  avg_score?: number | null;
  da?: number | null;
  global_links?: number;
  project_count?: number;
};

function ProjectDomainsPanel({
  token,
  projectId,
  onOpenBacklinks
}: {
  token: string | null;
  projectId: string;
  onOpenBacklinks: (filters: Record<string, string>) => void;
}) {
  const [mode, setMode] = useState<"used" | "available">("used");
  const PAGE = 200;
  type PV = {
    used: ProjectDomainRow[]; available: ProjectDomainRow[];
    used_count: number; available_count: number;
    used_has_more?: boolean; available_has_more?: boolean;
  };
  const view = useInfiniteQuery({
    queryKey: ["sd-project-view", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api<PV>(
        `/source-domains/project-view?project_id=${projectId}&limit=${PAGE}&offset=${pageParam}`,
        { token }
      ),
    // Keep paging while EITHER tab still has rows; each page carries the next slice
    // of both lists (true totals live on page 0), so we flatten per tab below.
    getNextPageParam: (last, all) =>
      last.used_has_more || last.available_has_more ? all.length * PAGE : undefined
  });
  const pages = useMemo(() => view.data?.pages || [], [view.data]);
  const usedRows = useMemo(() => pages.flatMap((p) => p.used || []), [pages]);
  const availRows = useMemo(() => pages.flatMap((p) => p.available || []), [pages]);
  const rows = mode === "used" ? usedRows : availRows;
  const usedCount = pages[0]?.used_count ?? 0;
  const availCount = pages[0]?.available_count ?? 0;
  const last = pages[pages.length - 1];
  const modeHasMore = mode === "used" ? Boolean(last?.used_has_more) : Boolean(last?.available_has_more);
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
        <h3 className="text-sm font-semibold text-ink">This project&apos;s source domains</h3>
        <div className="flex gap-1.5">
          <button
            onClick={() => setMode("used")}
            className={clsx(
              "h-8 rounded-full border px-3 text-xs font-medium transition",
              mode === "used" ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
            )}
          >
            Used here ({usedCount})
          </button>
          <button
            onClick={() => setMode("available")}
            title="Domains the workspace already knows, but this project has no link from yet — adding one counts as a NEW source domain for this project"
            className={clsx(
              "h-8 rounded-full border px-3 text-xs font-medium transition",
              mode === "available" ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
            )}
          >
            Available — not used yet ({availCount})
          </button>
        </div>
      </div>
      <div className="max-h-[340px] overflow-y-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-field text-xs uppercase text-muted">
            <tr>
              <Th>Domain</Th>
              {mode === "used" ? <Th>Links here</Th> : <Th>Links elsewhere</Th>}
              {mode === "used" ? <Th>Indexed</Th> : <Th>Projects using it</Th>}
              <Th>DA</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr
                key={r.domain_key}
                title={mode === "used" ? "Click to open this project's links from this website" : "This website has links in other projects — click to see them"}
                onClick={() => onOpenBacklinks({ source_domain: r.domain_key })}
                className="cursor-pointer hover:bg-field/60"
              >
                <Td>
                  <span className="inline-flex items-center gap-1">
                    <span className="break-all text-ocean hover:underline">{r.domain_key}</span>
                    <CopyButton text={r.domain_key} title="Copy domain" />
                  </span>
                </Td>
                <Td>{mode === "used" ? r.project_links : r.global_links}</Td>
                <Td>{mode === "used" ? (r.indexed ?? 0) : (r.project_count ?? 0)}</Td>
                <Td>{r.da != null ? <MetricTag label="DA" value={r.da} /> : "-"}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {view.isLoading ? (
          <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
        ) : null}
        {!view.isLoading && !rows.length ? (
          <Empty label={mode === "used" ? "No domains used yet." : "Every known domain is already used here."} />
        ) : null}
        {modeHasMore ? (
          <div className="flex justify-center border-t border-line p-2">
            <button
              onClick={() => view.fetchNextPage()}
              disabled={view.isFetchingNextPage}
              className="flex h-8 items-center gap-2 rounded-lg border border-line px-3 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-60"
            >
              {view.isFetchingNextPage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              Load more ({mode === "used" ? usedCount - usedRows.length : availCount - availRows.length} more)
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );
}

// ── Source-Domains enterprise desk (rich filters + stats + rules + exports) ──
// The whitelisted numeric filter fields — MUST mirror the backend
// _NUMERIC_FILTER_COLUMNS / _RANGE_PARAMS whitelist (source_domain_service.py).
// {min/max query-param prefix, human label, whether the value is a percentage}.
const SD_NUMERIC_FILTERS: Array<{ key: string; label: string; pct?: boolean }> = [
  { key: "da", label: "DA" },
  { key: "pa", label: "PA" },
  { key: "spam", label: "Spam" },
  { key: "as", label: "AS (Semrush)" },
  { key: "backlinks", label: "Backlinks" },
  { key: "qualified", label: "Qualified count" },
  { key: "referring", label: "Referring domains" },
  { key: "qualified_pct", label: "Qualified %", pct: true },
  { key: "not_qualified_pct", label: "Not-qualified %", pct: true },
  { key: "indexed_pct", label: "Indexed %", pct: true }
];

// Sortable columns — MUST mirror backend _SORT_COLUMNS keys.
type SdSort =
  | "domain"
  | "backlinks"
  | "referring_domains_count"
  | "indexed_pct"
  | "qualified_count"
  | "qualified_pct"
  | "not_qualified_pct"
  | "da"
  | "pa"
  | "spam_score"
  | "semrush_as"
  | "avg_score"
  | "duplicates";

// Whitelisted rule fields (backend _NUMERIC_FILTER_COLUMNS + origin string field).
const SD_RULE_NUMERIC_FIELDS: Array<{ value: string; label: string }> = [
  { value: "da", label: "DA" },
  { value: "pa", label: "PA" },
  { value: "spam_score", label: "Spam score" },
  { value: "semrush_as", label: "AS (Semrush)" },
  { value: "backlink_count", label: "Backlinks" },
  { value: "qualified_count", label: "Qualified count" },
  { value: "referring_domains_count", label: "Referring domains" },
  { value: "qualified_pct", label: "Qualified %" },
  { value: "not_qualified_pct", label: "Not-qualified %" },
  { value: "indexed_pct", label: "Indexed %" }
];
const SD_RULE_OPS: Array<{ value: string; label: string }> = [
  { value: ">=", label: "≥" },
  { value: "<=", label: "≤" },
  { value: ">", label: ">" },
  { value: "<", label: "<" },
  { value: "==", label: "=" },
  { value: "between", label: "between" }
];

// Spam is inverted (low is good): reuse MetricTag coloring by flipping the value.
function SpamTag({ value }: { value: number | null }) {
  if (value == null) return <MetricTag label="Spam" value={null} />;
  const tone = value <= 5 ? "bg-ocean/10 text-ocean" : value <= 20 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger";
  return (
    <span
      className={clsx("inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", tone)}
      title="Spam score — lower is better"
    >
      Spam {value}
    </span>
  );
}

// ── Opportunities tab (Enterprise §7): available domains nobody is working on ──
// Server pre-filters (unassigned + robots-ok + spam<30); the score blends the
// signals users care about so the list reads best-first without any setup.
function opportunityScore(d: {
  da: number | null; qualified_pct: number; indexed_pct: number;
  spam_score: number | null; robots_band?: string | null; backlink_count: number;
}): number {
  const da = d.da ?? 20;                       // unknown DA → neutral-low
  const spamBonus = 100 - Math.min(100, (d.spam_score ?? 10) * 3);
  const robots = (d.robots_band || "unknown") === "allowed" ? 100 : 60;
  const proven = d.backlink_count > 0 ? Math.min(100, d.qualified_pct) : 50;
  return Math.round(0.35 * da + 0.25 * proven + 0.2 * spamBonus + 0.1 * d.indexed_pct + 0.1 * robots);
}

function OpportunitiesPanel({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [recommendFor, setRecommendFor] = useState<string | null>(null); // domain_key
  const [pickUser, setPickUser] = useState("");
  const list = useQuery({
    queryKey: ["sd-opportunities", token, search],
    enabled: Boolean(token),
    queryFn: () =>
      api<{ items: SourceDomain[]; total: number }>(
        `/source-domains?opportunity=true&limit=300${search ? `&search=${encodeURIComponent(search)}` : ""}`,
        { token }
      )
  });
  const labelsQ = useQuery({
    queryKey: ["workforce-labels", token],
    enabled: Boolean(token) && Boolean(recommendFor),
    queryFn: () => api<string[]>("/workforce/labels", { token })
  });
  const recommend = useMutation({
    mutationFn: (v: { domain_key: string; user_label: string }) =>
      api("/source-domains/recommendations", {
        token, method: "POST",
        body: JSON.stringify({ domain_key: v.domain_key, user_label: v.user_label, reason: "Picked from the Opportunities tab" })
      }),
    onSuccess: (_d, v) => {
      onNotice(`${v.domain_key} recommended to ${v.user_label} — it appears on their My Work.`);
      setRecommendFor(null);
      setPickUser("");
      queryClient.invalidateQueries({ queryKey: ["sd-opportunities"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const rows = useMemo(() => {
    const items = (list.data?.items || []).map((d) => ({ ...d, opp: opportunityScore(d) }));
    items.sort((a, b) => b.opp - a.opp);
    return items;
  }, [list.data]);
  const exportRows = () =>
    downloadCsv(
      "opportunity-domains.csv",
      ["Domain", "Opportunity score", "DA", "PA", "AS", "Spam", "Robots", "Indexed %", "Qualified %", "Backlinks", "Projects", "Last checked"],
      rows.map((d) => [d.domain_key, d.opp, d.da, d.pa, d.semrush_as, d.spam_score, d.robots_band, Math.round(d.indexed_pct), Math.round(d.qualified_pct), d.backlink_count, d.project_count, d.metrics_updated_at])
    );
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Available opportunities" value={list.data?.total ?? 0} icon={Globe} tone="ocean"
          help="Catalog domains not assigned to anyone, not robots-blocked and not spammy — ready to hand out." />
        <Metric label="Never used" value={rows.filter((d) => d.backlink_count === 0).length} icon={Plus} tone="plum"
          help="Fresh imported domains with no links from any project yet — completely untapped." />
        <Metric label="High quality (score ≥ 70)" value={rows.filter((d) => d.opp >= 70).length} icon={CheckCircle2} tone="ink"
          help="Opportunity score blends DA, proven qualified rate, low spam, indexation and robots access." />
      </div>
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search domain…"
            className="h-9 w-56 rounded-lg border border-line bg-panel px-3 text-sm"
          />
          <span className="text-xs text-muted">Sorted by opportunity score — best prospects first.</span>
          <span className="ml-auto"><ExportButton onClick={exportRows} disabled={!rows.length} /></span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Domain</Th><Th>Score</Th><Th>DA</Th><Th>PA</Th><Th>AS</Th><Th>Spam</Th>
                <Th>Robots</Th><Th>Indexed</Th><Th>Qualified</Th><Th>Links</Th><Th>Projects</Th><Th>Checked</Th><Th>{" "}</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((d) => (
                <tr key={d.id} className="hover:bg-field/50">
                  <Td>
                    <span className="inline-flex items-center gap-1">
                      <span className="break-all font-medium text-ink">{d.domain_key}</span>
                      <CopyButton text={d.domain_key} title="Copy domain" />
                    </span>
                  </Td>
                  <Td>
                    <span className={clsx(
                      "rounded px-2 py-0.5 text-xs font-bold",
                      d.opp >= 70 ? "bg-ocean/10 text-ocean" : d.opp >= 45 ? "bg-ember/10 text-ember" : "bg-field text-muted"
                    )}>
                      {d.opp}
                    </span>
                  </Td>
                  <Td><MetricTag label="DA" value={d.da} /></Td>
                  <Td><MetricTag label="PA" value={d.pa} /></Td>
                  <Td><MetricTag label="AS" value={d.semrush_as} /></Td>
                  <Td><SpamTag value={d.spam_score} /></Td>
                  <Td>
                    <span className={clsx(
                      "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                      (d.robots_band || "unknown") === "allowed" ? "bg-ocean/10 text-ocean"
                        : d.robots_band === "partially_blocked" ? "bg-ember/10 text-ember" : "bg-field text-muted"
                    )}>
                      {(d.robots_band || "unknown").replaceAll("_", " ")}
                    </span>
                  </Td>
                  <Td>{d.backlink_count ? `${Math.round(d.indexed_pct)}%` : "—"}</Td>
                  <Td>{d.backlink_count ? `${Math.round(d.qualified_pct)}%` : "—"}</Td>
                  <Td>{d.backlink_count}</Td>
                  <Td>{d.project_count}</Td>
                  <Td><span className="whitespace-nowrap">{d.metrics_updated_at ? formatDay(d.metrics_updated_at) : "—"}</span></Td>
                  <Td>
                    {recommendFor === d.domain_key ? (
                      <span className="flex items-center gap-1">
                        <SearchSelect
                          value={pickUser}
                          onChange={setPickUser}
                          options={(labelsQ.data || []).map((l) => ({ value: l, label: l }))}
                          placeholder="Pick person…"
                          width="w-36"
                        />
                        <button
                          onClick={() => pickUser && recommend.mutate({ domain_key: d.domain_key, user_label: pickUser })}
                          disabled={!pickUser || recommend.isPending}
                          className="rounded bg-ocean px-2 py-1 text-[11px] font-semibold text-white disabled:opacity-50 dark:text-slate-900"
                        >
                          Send
                        </button>
                        <button onClick={() => setRecommendFor(null)} className="text-xs text-muted hover:text-ink">×</button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setRecommendFor(d.domain_key)}
                        className="whitespace-nowrap rounded border border-ocean/40 px-2 py-1 text-[11px] font-medium text-ocean hover:bg-ocean/10"
                      >
                        Recommend →
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.isLoading ? (
            <div className="flex justify-center p-6"><Loader2 className="h-5 w-5 animate-spin text-muted" /></div>
          ) : null}
          {!list.isLoading && !rows.length ? (
            <Empty label="No available opportunities — import more domains or free some up by skipping stale recommendations." />
          ) : null}
        </div>
      </section>
    </div>
  );
}

function SourceDomainsDesk({
  token,
  projectId,
  onNotice,
  onOpenBacklinks,
  onImportDomains
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
  onOpenBacklinks: (filters: Record<string, string>) => void;
  onImportDomains?: () => void;
}) {
  const queryClient = useQueryClient();
  const PAGE = 100;
  const [search, setSearch] = useState("");
  const [origin, setOrigin] = useState(""); // "" | "derived" | "imported"
  // numeric filters: keyed by "<prefix>_min" / "<prefix>_max" → string value.
  const [ranges, setRanges] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<SdSort>("backlinks");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [showFilters, setShowFilters] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [sdMode, setSdMode] = useState<"catalog" | "opportunities">("catalog");
  const [showRules, setShowRules] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [savedOpen, setSavedOpen] = useState(false);

  // Build the shared query-param string that drives BOTH the list and the stats.
  const filterParams = useMemo(() => {
    const p = new URLSearchParams();
    if (search.trim()) p.set("search", search.trim());
    if (origin) p.set("origin", origin);
    for (const [k, v] of Object.entries(ranges)) {
      if (v != null && String(v).trim() !== "") p.set(k, String(v).trim());
    }
    return p;
  }, [search, origin, ranges]);
  const filterKey = filterParams.toString();

  const domains = useInfiniteQuery({
    queryKey: ["source-domains", token, sort, dir, filterKey],
    enabled: Boolean(token),
    initialPageParam: 0,
    getNextPageParam: (last: SourceDomainList, all: SourceDomainList[]) => {
      const loaded = all.reduce((n, pg) => n + pg.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    queryFn: ({ pageParam }) => {
      const p = new URLSearchParams(filterKey);
      p.set("sort", sort);
      p.set("order", dir);
      p.set("limit", String(PAGE));
      p.set("offset", String(pageParam));
      return api<SourceDomainList>(`/source-domains?${p.toString()}`, { token });
    }
  });
  const rows = useMemo(
    () => (domains.data?.pages || []).flatMap((pg) => pg.items),
    [domains.data]
  );
  const total = domains.data?.pages?.[0]?.total ?? 0;

  const stats = useQuery({
    queryKey: ["source-domains-stats", token, filterKey],
    enabled: Boolean(token),
    queryFn: () => api<SourceDomainStats>(`/source-domains/stats?${filterKey}`, { token })
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["source-domains"] });
    queryClient.invalidateQueries({ queryKey: ["source-domains-stats"] });
  };

  const recompute = useMutation({
    mutationFn: () => api<SourceDomainList>("/source-domains/recompute", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Source-domain metrics refreshed");
      invalidateAll();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const fetchMoz = useMutation({
    mutationFn: () => api<SourceDomainList>("/source-domains/fetch-metrics?providers=moz", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Moz DA/PA check started for the stalest domains");
      invalidateAll();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const fetchSemrush = useMutation({
    mutationFn: () => api<SourceDomainList>("/source-domains/fetch-metrics?providers=semrush", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Semrush AS check started — needs the Semrush API endpoint configured on the server");
      invalidateAll();
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // Saved filters (per-workspace store).
  const savedFilters = useQuery({
    queryKey: ["source-domains-saved-filters", token],
    enabled: Boolean(token),
    queryFn: () => api<SourceDomainSavedFilter[]>("/source-domains/saved-filters", { token })
  });
  const saveFilter = useMutation({
    mutationFn: (name: string) =>
      api<SourceDomainSavedFilter[]>("/source-domains/saved-filters", {
        token,
        method: "PUT",
        body: JSON.stringify({ name, params: Object.fromEntries(filterParams.entries()) })
      }),
    onSuccess: () => {
      setSaveName("");
      onNotice("Filter saved");
      queryClient.invalidateQueries({ queryKey: ["source-domains-saved-filters"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const deleteFilter = useMutation({
    mutationFn: (name: string) =>
      api<SourceDomainSavedFilter[]>(`/source-domains/saved-filters?name=${encodeURIComponent(name)}`, {
        token,
        method: "DELETE"
      }),
    onSuccess: () => {
      onNotice("Filter deleted");
      queryClient.invalidateQueries({ queryKey: ["source-domains-saved-filters"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  function applySaved(f: SourceDomainSavedFilter) {
    const p = f.params || {};
    setSearch(String(p.search || ""));
    setOrigin(String(p.origin || ""));
    const next: Record<string, string> = {};
    for (const [k, v] of Object.entries(p)) {
      if (k !== "search" && k !== "origin" && v != null && String(v) !== "") next[k] = String(v);
    }
    setRanges(next);
    setSavedOpen(false);
    setShowFilters(true);
  }

  function clearFilters() {
    setSearch("");
    setOrigin("");
    setRanges({});
  }
  const activeFilterCount =
    (search.trim() ? 1 : 0) +
    (origin ? 1 : 0) +
    Object.values(ranges).filter((v) => String(v).trim() !== "").length;

  function setRange(key: string, value: string) {
    setRanges((prev) => {
      const next = { ...prev };
      if (value.trim() === "") delete next[key];
      else next[key] = value;
      return next;
    });
  }

  function onSort(key: string) {
    if (sort === key) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(key as SdSort);
      setDir("desc");
    }
  }

  // Export the CURRENT filtered set via the server (CSV or XLSX), auth via token.
  async function exportServer(format: "csv" | "xlsx") {
    try {
      const p = new URLSearchParams(filterKey);
      p.set("format", format);
      p.set("sort", sort);
      p.set("order", dir);
      const res = await fetch(`${API_BASE}/source-domains/export?${p.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `source-domains.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      onNotice(err instanceof Error ? err.message : "Export failed");
    }
  }

  // Export just the selected rows (client-side CSV — respects the current selection).
  function exportSelected() {
    const chosen = rows.filter((r) => selected.has(r.id));
    if (!chosen.length) {
      onNotice("Select some domains first");
      return;
    }
    downloadCsv(
      "source-domains-selected.csv",
      [
        "Domain",
        "Backlinks",
        "Referring",
        "Indexed %",
        "Qualified",
        "Qualified %",
        "Not-qualified %",
        "DA",
        "PA",
        "Spam",
        "AS",
        "Traffic",
        "Age (days)",
        "Projects",
        "Avg score",
        "Origin"
      ],
      chosen.map((r) => [
        r.domain_key,
        r.backlink_count,
        r.referring_domains_count,
        r.indexed_pct,
        r.qualified_count,
        r.qualified_pct,
        r.not_qualified_pct,
        r.da ?? "",
        r.pa ?? "",
        r.spam_score ?? "",
        r.semrush_as ?? "",
        r.semrush_traffic ?? "",
        r.domain_age_days ?? "",
        r.project_count,
        r.avg_score ?? "",
        r.origin
      ])
    );
  }

  const allOnPageSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));
  function toggleSelectAll() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) rows.forEach((r) => next.delete(r.id));
      else rows.forEach((r) => next.add(r.id));
      return next;
    });
  }
  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const st = stats.data;
  const modePills = (
    <span className="flex w-fit overflow-hidden rounded-lg border border-line text-xs font-medium">
      <button
        onClick={() => setSdMode("catalog")}
        className={clsx("px-2.5 py-1 transition", sdMode === "catalog" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
      >
        Catalog
      </button>
      <button
        onClick={() => setSdMode("opportunities")}
        title="Available domains nobody is working on yet — quality-scored, robots-checked, ready to hand out"
        className={clsx("px-2.5 py-1 transition", sdMode === "opportunities" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
      >
        Opportunities
      </button>
    </span>
  );
  if (sdMode === "opportunities") {
    return (
      <section className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-1 flex items-center gap-1.5 text-base font-semibold text-ink">
            Source Domains
            <HelpTip text="Opportunities = catalog domains still AVAILABLE: not assigned to anyone, not blocked by robots.txt, not spammy — ranked by an opportunity score so the best prospects surface first." />
          </h2>
          {modePills}
        </div>
        <OpportunitiesPanel token={token} onNotice={onNotice} />
      </section>
    );
  }
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 flex items-center gap-1.5 text-base font-semibold text-ink">
          Source Domains
          <HelpTip text="Every backlink grouped by its source website. Filter, sort and export the catalog; build reusable rules to surface the domains that matter." />
        </h2>
        {modePills}
        {/* All actions on one responsive row */}
        {onImportDomains ? (
          <button
            onClick={onImportDomains}
            title="Paste a list of websites — they land in a review batch and join this catalog only when you approve them"
            className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            <Upload className="h-4 w-4" />
            Import domains
          </button>
        ) : null}
        <button
          onClick={() => recompute.mutate()}
          className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
        >
          {recompute.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Recompute
        </button>
        <button
          onClick={() => fetchMoz.mutate()}
          className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
        >
          {fetchMoz.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
          Check DA/PA (Moz)
        </button>
        <button
          onClick={() => fetchSemrush.mutate()}
          className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
        >
          {fetchSemrush.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
          Check AS (Semrush)
        </button>
      </div>

      {/* Stat cards — refetched with the active filters */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-8">
        <Metric label="Domains" value={st ? st.total_domains : "—"} icon={Globe} tone="ink" />
        <Metric
          label="Total backlinks"
          value={st ? compactNum(st.total_backlinks) : "—"}
          icon={Link2}
          tone="ocean"
        />
        <Metric
          label="Qualified %"
          value={st ? `${Math.round(st.overall_qualified_pct)}%` : "—"}
          icon={CheckCircle2}
          tone="ocean"
        />
        <Metric
          label="Indexed %"
          value={st ? `${Math.round(st.overall_indexed_pct)}%` : "—"}
          icon={Activity}
          tone="ocean"
        />
        <Metric
          label="Avg DA"
          value={st?.avg_da != null ? Math.round(st.avg_da) : "—"}
          icon={Gauge}
          tone="plum"
        />
        <Metric
          label="Avg AS"
          value={st?.avg_as != null ? Math.round(st.avg_as) : "—"}
          icon={Gauge}
          tone="plum"
        />
        <Metric
          label="Avg Spam"
          value={st?.avg_spam != null ? Math.round(st.avg_spam) : "—"}
          icon={ShieldAlert}
          tone="ember"
        />
        <Metric
          label="DA ≥ 50"
          value={st ? st.count_da_ge_50 : "—"}
          icon={Star}
          tone="ocean"
          help="Domains with a Moz Domain Authority of 50 or higher."
        />
      </div>

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <input
            className="h-9 w-full rounded-md border border-line bg-panel px-3 text-sm"
            placeholder="Search domain…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <button
          onClick={() => setShowFilters((v) => !v)}
          className={clsx(
            "flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition",
            activeFilterCount
              ? "border-ocean bg-ocean/10 text-ocean"
              : "border-line bg-panel text-ink hover:bg-field"
          )}
        >
          <SlidersHorizontal className="h-4 w-4" />
          Filters
          {activeFilterCount ? (
            <span className="rounded-full bg-ocean px-1.5 text-[11px] font-bold text-white dark:text-slate-900">
              {activeFilterCount}
            </span>
          ) : null}
        </button>
        {/* Saved filters dropdown */}
        <div className="relative">
          <button
            onClick={() => setSavedOpen((v) => !v)}
            className="flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            <Star className="h-4 w-4" />
            Saved
            <ChevronDown className="h-3.5 w-3.5 text-muted" />
          </button>
          {savedOpen ? (
            <div className="absolute right-0 top-full z-30 mt-1 w-72 rounded-xl border border-line bg-panel p-2 shadow-pop">
              <div className="max-h-56 overflow-y-auto">
                {(savedFilters.data || []).length ? (
                  (savedFilters.data || []).map((f) => (
                    <div
                      key={f.name}
                      className="flex items-center gap-1 rounded-md px-1.5 py-1 hover:bg-field"
                    >
                      <button
                        onClick={() => applySaved(f)}
                        className="flex-1 truncate text-left text-sm text-ink"
                      >
                        {f.name}
                      </button>
                      <button
                        onClick={() => deleteFilter.mutate(f.name)}
                        title="Delete saved filter"
                        className="text-muted hover:text-danger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="px-2 py-2 text-xs text-muted">No saved filters yet.</p>
                )}
              </div>
              <div className="mt-2 flex items-center gap-1 border-t border-line pt-2">
                <input
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Save current as…"
                  className="h-8 flex-1 rounded-md border border-line bg-field/50 px-2 text-xs"
                />
                <button
                  disabled={!saveName.trim() || saveFilter.isPending}
                  onClick={() => saveFilter.mutate(saveName.trim())}
                  className="h-8 rounded-md bg-ocean px-2.5 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
                >
                  Save
                </button>
              </div>
            </div>
          ) : null}
        </div>
        <button
          onClick={() => setShowRules((v) => !v)}
          className={clsx(
            "flex h-9 items-center gap-1.5 rounded-md border px-3 text-sm font-medium transition",
            showRules ? "border-ocean bg-ocean/10 text-ocean" : "border-line bg-panel text-ink hover:bg-field"
          )}
        >
          <Filter className="h-4 w-4" />
          Rules
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => exportServer("csv")}
            title="Download all filtered domains as CSV"
            className="flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            <Download className="h-4 w-4" /> CSV
          </button>
          <button
            onClick={() => exportServer("xlsx")}
            title="Download all filtered domains as Excel"
            className="flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            <FileSpreadsheet className="h-4 w-4" /> Excel
          </button>
        </div>
      </div>

      {/* Advanced filter panel */}
      {showFilters ? (
        <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-ink">Advanced filters</h3>
            <button onClick={clearFilters} className="text-xs font-medium text-muted hover:text-danger">
              Clear all
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SD_NUMERIC_FILTERS.map((f) => (
              <div key={f.key} className="flex items-center gap-2">
                <label className="w-32 shrink-0 text-xs font-medium text-muted">{f.label}</label>
                <input
                  type="number"
                  placeholder="min"
                  value={ranges[`${f.key}_min`] ?? ""}
                  onChange={(e) => setRange(`${f.key}_min`, e.target.value)}
                  className="h-8 w-full rounded-md border border-line bg-field/50 px-2 text-sm"
                />
                <span className="text-muted">–</span>
                <input
                  type="number"
                  placeholder="max"
                  value={ranges[`${f.key}_max`] ?? ""}
                  onChange={(e) => setRange(`${f.key}_max`, e.target.value)}
                  className="h-8 w-full rounded-md border border-line bg-field/50 px-2 text-sm"
                />
              </div>
            ))}
            <div className="flex items-center gap-2">
              <label className="w-32 shrink-0 text-xs font-medium text-muted">Origin</label>
              <select
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                className="h-8 w-full rounded-md border border-line bg-panel px-2 text-sm"
              >
                <option value="">All origins</option>
                <option value="derived">Derived (from backlinks)</option>
                <option value="imported">Imported (catalog)</option>
              </select>
            </div>
          </div>
        </section>
      ) : null}

      {/* Rules engine panel */}
      {showRules ? (
        <SourceDomainRules
          token={token}
          projectId={projectId}
          onNotice={onNotice}
          onApplied={(count) => onNotice(`Rule matches ${count} domain${count === 1 ? "" : "s"}`)}
        />
      ) : null}

      {projectId ? (
        <ProjectDomainsPanel token={token} projectId={projectId} onOpenBacklinks={onOpenBacklinks} />
      ) : null}

      {/* Bulk action bar */}
      {selected.size ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-ocean/40 bg-ocean/5 px-3 py-2 text-sm">
          <span className="font-medium text-ink">{selected.size} selected</span>
          <button
            onClick={exportSelected}
            className="flex h-8 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 text-xs font-medium text-ink transition hover:bg-field"
          >
            <Download className="h-3.5 w-3.5" /> Export selected (CSV)
          </button>
          <button
            onClick={() => fetchMoz.mutate()}
            title="The metrics fetch runs over the stalest domains workspace-wide (no per-selection scope on the endpoint)."
            className="flex h-8 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 text-xs font-medium text-ink transition hover:bg-field"
          >
            <Globe className="h-3.5 w-3.5" /> Check DA/PA
          </button>
          <button
            onClick={() => fetchSemrush.mutate()}
            title="The metrics fetch runs over the stalest domains workspace-wide (no per-selection scope on the endpoint)."
            className="flex h-8 items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 text-xs font-medium text-ink transition hover:bg-field"
          >
            <Globe className="h-3.5 w-3.5" /> Check AS
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-xs font-medium text-muted hover:text-ink"
          >
            Clear selection
          </button>
        </div>
      ) : null}

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <th className="w-8 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={allOnPageSelected}
                    onChange={toggleSelectAll}
                    className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
                    aria-label="Select all"
                  />
                </th>
                <SortTh label="Domain" sortKey="domain" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Backlinks" sortKey="backlinks" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Referring" sortKey="referring_domains_count" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Indexed %" sortKey="indexed_pct" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Qualified" sortKey="qualified_count" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Qual %" sortKey="qualified_pct" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Not-qual %" sortKey="not_qualified_pct" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="DA" sortKey="da" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="PA" sortKey="pa" sort={sort} dir={dir} onSort={onSort} />
                <SortTh label="Spam" sortKey="spam_score" sort={sort} dir={dir} onSort={onSort} help="Spam score — lower is better." />
                <SortTh label="AS" sortKey="semrush_as" sort={sort} dir={dir} onSort={onSort} />
                <Th>Traffic</Th>
                <Th>Age</Th>
                <Th>Projects</Th>
                <SortTh label="Avg score" sortKey="avg_score" sort={sort} dir={dir} onSort={onSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((d) => (
                <SourceDomainRow
                  key={d.id}
                  d={d}
                  token={token}
                  selected={selected.has(d.id)}
                  onToggle={() => toggleRow(d.id)}
                />
              ))}
            </tbody>
          </table>
          {!domains.isLoading && !rows.length ? (
            <Empty label="No source domains match — clear filters, or click Recompute / import some backlinks." />
          ) : null}
        </div>
        {rows.length ? (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-muted">
            <span>
              Showing {rows.length} of {total}
            </span>
            {domains.hasNextPage ? (
              <button
                onClick={() => domains.fetchNextPage()}
                disabled={domains.isFetchingNextPage}
                className="flex h-8 items-center gap-1.5 rounded-md border border-line bg-panel px-3 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
              >
                {domains.isFetchingNextPage ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Load more
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </section>
  );
}

function SourceDomainRow({
  d,
  token,
  selected,
  onToggle
}: {
  d: SourceDomain;
  token: string | null;
  selected: boolean;
  onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["source-domain", token, d.id],
    enabled: Boolean(token && open),
    queryFn: () => api<SourceDomainDetail>(`/source-domains/${d.id}`, { token })
  });
  const dist = Object.entries(d.link_type_distribution || {});
  return (
    <>
      <tr className="hover:bg-field/40">
        <Td>
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            onClick={(e) => e.stopPropagation()}
            className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
            aria-label={`Select ${d.domain_key}`}
          />
        </Td>
        <Td>
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 text-left"
          >
            {open ? (
              <ChevronUp className="h-4 w-4 shrink-0 text-muted" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted" />
            )}
            <span className="font-medium text-ink">{d.domain_key}</span>
            <CopyButton text={d.domain_key} title="Copy domain" />
            {d.origin === "imported" ? (
              <span className="rounded bg-plum/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-plum">
                imported
              </span>
            ) : null}
          </button>
        </Td>
        <Td>{d.backlink_count}</Td>
        <Td>{d.referring_domains_count}</Td>
        <Td>
          <span className="font-medium text-ink">{d.indexed_pct}%</span>{" "}
          <span className="text-xs text-muted">
            ({d.indexed_count}/{d.indexed_count + d.not_indexed_count})
          </span>
        </Td>
        <Td>{d.qualified_count}</Td>
        <Td>
          <MetricTag label="" value={Math.round(d.qualified_pct)} title={`${d.qualified_pct}% qualified`} />
        </Td>
        <Td>{Math.round(d.not_qualified_pct)}%</Td>
        <Td>{d.da != null ? <MetricTag label="DA" value={d.da} /> : "—"}</Td>
        <Td>{d.pa != null ? <MetricTag label="PA" value={d.pa} /> : "—"}</Td>
        <Td>
          <SpamTag value={d.spam_score} />
        </Td>
        <Td>{d.semrush_as != null ? <MetricTag label="AS" value={d.semrush_as} /> : "—"}</Td>
        <Td>{d.semrush_traffic != null ? compactNum(d.semrush_traffic) : "—"}</Td>
        <Td>
          {d.domain_age_days != null ? (
            <span title={`${d.domain_age_days} days`}>{Math.floor(d.domain_age_days / 365)}y</span>
          ) : (
            "—"
          )}
        </Td>
        <Td>{d.project_count}</Td>
        <Td>{d.avg_score ?? "—"}</Td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={16} className="bg-field/30 px-4 py-3">
            <div className="grid gap-4 md:grid-cols-[260px_1fr]">
              <div>
                <div className="text-xs font-semibold uppercase text-muted">Index status</div>
                <div className="mt-1 text-sm text-ink">
                  {d.indexed_count} indexed · {d.not_indexed_count} not · {d.uncertain_count} uncertain
                  · {d.unchecked_count} unchecked
                </div>
                <div className="mt-3 text-xs font-semibold uppercase text-muted">Link types</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  {dist.length ? (
                    dist.map(([k, v]) => (
                      <span key={k} className="rounded border border-line bg-panel px-2 py-0.5 text-xs">
                        {k}: {v}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-muted">—</span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-xs font-semibold uppercase text-muted">Backlinks on this domain</div>
                {detail.isLoading ? (
                  <div className="p-3 text-sm text-muted">Loading…</div>
                ) : (
                  <div className="mt-1 max-h-64 overflow-auto rounded border border-line">
                    <table className="w-full text-xs">
                      <thead className="bg-field text-left uppercase text-muted">
                        <tr>
                          <Th>Project</Th>
                          <Th>Source page</Th>
                          <Th>User</Th>
                          <Th>Status</Th>
                          <Th>Idx</Th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line">
                        {(detail.data?.backlinks || []).map((b) => (
                          <tr key={b.id}>
                            <Td>{b.project_name || "—"}</Td>
                            <Td>
                              <span className="block max-w-[240px] truncate" title={b.source_page_url}>
                                {b.source_page_url}
                              </span>
                            </Td>
                            <Td>{b.assigned_user_label || "—"}</Td>
                            <Td>{b.status ? <Status value={b.status} /> : "—"}</Td>
                            <Td>{b.index_status || "—"}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

// ── Rules engine: list + condition builder + apply/export/delete ──────────────
type SdRuleDraft = {
  name: string;
  description: string;
  match: "all" | "any";
  conditions: SourceDomainRuleCondition[];
};

function emptyRuleDraft(): SdRuleDraft {
  return {
    name: "",
    description: "",
    match: "all",
    conditions: [{ field: "da", op: ">=", value: 0 }]
  };
}

function SourceDomainRules({
  token,
  projectId,
  onNotice,
  onApplied
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
  onApplied: (count: number) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<SdRuleDraft | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [applied, setApplied] = useState<{ ruleId: string; items: SourceDomain[]; total: number; match: number } | null>(
    null
  );

  const rules = useQuery({
    queryKey: ["source-domain-rules", token],
    enabled: Boolean(token),
    queryFn: () => api<SourceDomainRule[]>("/source-domains/rules", { token })
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["source-domain-rules"] });

  function draftToDefinition(d: SdRuleDraft): SourceDomainRuleDefinition {
    return {
      match: d.match,
      conditions: d.conditions.map((c) => {
        if (c.field === "origin") {
          return { field: "origin", op: "==", value_str: (c.value_str || "").trim() || null };
        }
        return {
          field: c.field,
          op: c.op,
          value: c.value == null || Number.isNaN(c.value) ? 0 : Number(c.value),
          value2: c.op === "between" ? (c.value2 == null || Number.isNaN(c.value2) ? 0 : Number(c.value2)) : null
        };
      })
    };
  }

  const createRule = useMutation({
    mutationFn: (d: SdRuleDraft) =>
      api<SourceDomainRule>("/source-domains/rules", {
        token,
        method: "POST",
        body: JSON.stringify({
          name: d.name.trim(),
          description: d.description.trim() || null,
          project_id: projectId || null,
          is_shared: true,
          definition: draftToDefinition(d)
        })
      }),
    onSuccess: () => {
      onNotice("Rule saved");
      setDraft(null);
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const updateRule = useMutation({
    mutationFn: (v: { id: string; d: SdRuleDraft }) =>
      api<SourceDomainRule>(`/source-domains/rules/${v.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({
          name: v.d.name.trim(),
          description: v.d.description.trim() || null,
          definition: draftToDefinition(v.d)
        })
      }),
    onSuccess: () => {
      onNotice("Rule updated");
      setDraft(null);
      setEditingId(null);
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const deleteRule = useMutation({
    mutationFn: (id: string) => api(`/source-domains/rules/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Rule deleted");
      setApplied((a) => (a ? null : a));
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const applyRule = useMutation({
    mutationFn: (id: string) =>
      api<{ items: SourceDomain[]; total: number; match_count: number }>(
        `/source-domains/rules/${id}/apply?limit=100&offset=0`,
        { token }
      ).then((r) => ({ id, ...r })),
    onSuccess: (r) => {
      setApplied({ ruleId: r.id, items: r.items, total: r.total, match: r.match_count });
      onApplied(r.match_count);
    },
    onError: (e: Error) => onNotice(e.message)
  });

  async function exportRule(id: string, format: "csv" | "xlsx") {
    try {
      const res = await fetch(`${API_BASE}/source-domains/rules/${id}/export?format=${format}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `rule-matches.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      onNotice(err instanceof Error ? err.message : "Export failed");
    }
  }

  function startEdit(r: SourceDomainRule) {
    const def = r.definition || { match: "all", conditions: [] };
    setDraft({
      name: r.name,
      description: r.description || "",
      match: def.match === "any" ? "any" : "all",
      conditions: (def.conditions || []).map((c) => ({
        field: c.field,
        op: c.field === "origin" ? "==" : c.op,
        value: c.value ?? 0,
        value2: c.value2 ?? null,
        value_str: c.value_str ?? null
      }))
    });
    setEditingId(r.id);
  }

  function updateCondition(idx: number, patch: Partial<SourceDomainRuleCondition>) {
    setDraft((d) =>
      d
        ? { ...d, conditions: d.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c)) }
        : d
    );
  }
  function addCondition() {
    setDraft((d) => (d ? { ...d, conditions: [...d.conditions, { field: "da", op: ">=", value: 0 }] } : d));
  }
  function removeCondition(idx: number) {
    setDraft((d) => (d ? { ...d, conditions: d.conditions.filter((_, i) => i !== idx) } : d));
  }

  const saving = createRule.isPending || updateRule.isPending;
  function saveDraft() {
    if (!draft || !draft.name.trim()) {
      onNotice("Give the rule a name");
      return;
    }
    if (editingId) updateRule.mutate({ id: editingId, d: draft });
    else createRule.mutate(draft);
  }

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-sm font-semibold text-ink">Rules engine</h3>
        <button
          onClick={() => {
            setDraft(emptyRuleDraft());
            setEditingId(null);
          }}
          className="flex h-8 items-center gap-1.5 rounded-md bg-ocean px-2.5 text-xs font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
        >
          <Plus className="h-3.5 w-3.5" /> New rule
        </button>
      </div>

      {/* Rule editor */}
      {draft ? (
        <div className="space-y-3 border-b border-line bg-field/20 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Rule name"
              className="h-9 w-56 rounded-md border border-line bg-panel px-3 text-sm"
            />
            <input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder="Description (optional)"
              className="h-9 flex-1 min-w-[180px] rounded-md border border-line bg-panel px-3 text-sm"
            />
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Match</span>
            <select
              value={draft.match}
              onChange={(e) => setDraft({ ...draft, match: e.target.value as "all" | "any" })}
              className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
            >
              <option value="all">all conditions</option>
              <option value="any">any condition</option>
            </select>
          </div>
          <div className="space-y-2">
            {draft.conditions.map((c, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select
                  value={c.field}
                  onChange={(e) => {
                    const field = e.target.value;
                    updateCondition(i, field === "origin" ? { field, op: "==" } : { field, op: c.op === "==" ? ">=" : c.op });
                  }}
                  className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
                >
                  {SD_RULE_NUMERIC_FIELDS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                  <option value="origin">Origin</option>
                </select>
                {c.field === "origin" ? (
                  <>
                    <span className="text-sm text-muted">is</span>
                    <select
                      value={c.value_str || ""}
                      onChange={(e) => updateCondition(i, { value_str: e.target.value })}
                      className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
                    >
                      <option value="">—</option>
                      <option value="derived">derived</option>
                      <option value="imported">imported</option>
                    </select>
                  </>
                ) : (
                  <>
                    <select
                      value={c.op}
                      onChange={(e) => updateCondition(i, { op: e.target.value })}
                      className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
                    >
                      {SD_RULE_OPS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <input
                      type="number"
                      value={c.value ?? ""}
                      onChange={(e) => updateCondition(i, { value: e.target.value === "" ? null : Number(e.target.value) })}
                      className="h-8 w-24 rounded-md border border-line bg-panel px-2 text-sm"
                    />
                    {c.op === "between" ? (
                      <>
                        <span className="text-sm text-muted">and</span>
                        <input
                          type="number"
                          value={c.value2 ?? ""}
                          onChange={(e) =>
                            updateCondition(i, { value2: e.target.value === "" ? null : Number(e.target.value) })
                          }
                          className="h-8 w-24 rounded-md border border-line bg-panel px-2 text-sm"
                        />
                      </>
                    ) : null}
                  </>
                )}
                {draft.conditions.length > 1 ? (
                  <button
                    onClick={() => removeCondition(i)}
                    className="text-muted hover:text-danger"
                    title="Remove condition"
                  >
                    <XCircle className="h-4 w-4" />
                  </button>
                ) : null}
              </div>
            ))}
            <button onClick={addCondition} className="flex items-center gap-1 text-xs font-medium text-ocean hover:underline">
              <Plus className="h-3.5 w-3.5" /> Add condition
            </button>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={saveDraft}
              disabled={saving}
              className="h-9 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
            >
              {saving ? "Saving…" : editingId ? "Update rule" : "Save rule"}
            </button>
            <button
              onClick={() => {
                setDraft(null);
                setEditingId(null);
              }}
              className="h-9 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {/* Rule list */}
      <div className="divide-y divide-line">
        {(rules.data || []).map((r) => (
          <div key={r.id} className="px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-medium text-ink">{r.name}</div>
                {r.description ? <div className="text-xs text-muted">{r.description}</div> : null}
                <div className="mt-0.5 text-xs text-muted">
                  Match {r.definition?.match === "any" ? "any" : "all"} ·{" "}
                  {(r.definition?.conditions || [])
                    .map((c) =>
                      c.field === "origin"
                        ? `origin = ${c.value_str}`
                        : `${c.field} ${c.op} ${c.value}${c.op === "between" ? `–${c.value2}` : ""}`
                    )
                    .join(r.definition?.match === "any" ? " OR " : " AND ") || "no conditions"}
                </div>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => applyRule.mutate(r.id)}
                  className="flex h-8 items-center gap-1.5 rounded-md bg-ocean px-2.5 text-xs font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
                >
                  {applyRule.isPending && applyRule.variables === r.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                  Apply
                </button>
                <button
                  onClick={() => exportRule(r.id, "csv")}
                  title="Export matches (CSV)"
                  className="flex h-8 items-center gap-1 rounded-md border border-line bg-panel px-2 text-xs font-medium text-ink transition hover:bg-field"
                >
                  <Download className="h-3.5 w-3.5" /> CSV
                </button>
                <button
                  onClick={() => startEdit(r)}
                  className="flex h-8 items-center gap-1 rounded-md border border-line bg-panel px-2 text-xs font-medium text-ink transition hover:bg-field"
                >
                  Edit
                </button>
                <button
                  onClick={() => deleteRule.mutate(r.id)}
                  title="Delete rule"
                  className="grid h-8 w-8 place-items-center rounded-md border border-line bg-panel text-muted transition hover:text-danger"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Inline matches for the applied rule */}
            {applied && applied.ruleId === r.id ? (
              <div className="mt-3 rounded-lg border border-line">
                <div className="flex items-center justify-between border-b border-line bg-field/40 px-3 py-1.5 text-xs">
                  <span className="font-medium text-ink">
                    {applied.match} match{applied.match === 1 ? "" : "es"}
                  </span>
                  <button onClick={() => setApplied(null)} className="text-muted hover:text-ink">
                    Close
                  </button>
                </div>
                <div className="max-h-64 overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-field text-left uppercase text-muted">
                      <tr>
                        <Th>Domain</Th>
                        <Th>Backlinks</Th>
                        <Th>DA</Th>
                        <Th>PA</Th>
                        <Th>Spam</Th>
                        <Th>AS</Th>
                        <Th>Qual %</Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {applied.items.map((d) => (
                        <tr key={d.id}>
                          <Td>
                            <span className="inline-flex items-center gap-1">
                              <span className="font-medium text-ink">{d.domain_key}</span>
                              <CopyButton text={d.domain_key} title="Copy domain" />
                            </span>
            <CopyButton text={d.domain_key} title="Copy domain" />
                          </Td>
                          <Td>{d.backlink_count}</Td>
                          <Td>{d.da ?? "—"}</Td>
                          <Td>{d.pa ?? "—"}</Td>
                          <Td>{d.spam_score ?? "—"}</Td>
                          <Td>{d.semrush_as ?? "—"}</Td>
                          <Td>{Math.round(d.qualified_pct)}%</Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {applied.total > applied.items.length ? (
                  <div className="border-t border-line px-3 py-1.5 text-xs text-muted">
                    Showing first {applied.items.length} of {applied.total} — export for the full set.
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ))}
        {!rules.isLoading && !(rules.data || []).length && !draft ? (
          <Empty label="No rules yet — click New rule to build one." />
        ) : null}
      </div>
    </section>
  );
}

function EmployeesDesk({
  token,
  onNotice
}: {
  token: string | null;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [newCode, setNewCode] = useState("");
  const [newCodeName, setNewCodeName] = useState("");

  const data = useQuery({
    queryKey: ["employees", token],
    enabled: Boolean(token),
    queryFn: () => api<EmployeeOverview>("/employees", { token })
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["employees"] });

  const sync = useMutation({
    mutationFn: () => api<EmployeeOverview>("/employees/sync", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Synced employees from sheet data");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const mapUser = useMutation({
    mutationFn: (v: { id: string; user_id: string | null }) =>
      api(`/employees/mappings/${v.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ user_id: v.user_id })
      }),
    onSuccess: () => {
      onNotice("Mapping updated");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const setActiveMut = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) =>
      api(`/employees/mappings/${v.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ is_active: v.is_active })
      }),
    onSuccess: () => {
      onNotice("Saved");
      queryClient.invalidateQueries({ queryKey: ["employees"] });
      queryClient.invalidateQueries({ queryKey: ["workforce-labels"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const addCode = useMutation({
    mutationFn: () =>
      api("/employees/codes", {
        token,
        method: "POST",
        body: JSON.stringify({ code: newCode.trim(), display_name: newCodeName.trim() || null })
      }),
    onSuccess: () => {
      setNewCode("");
      setNewCodeName("");
      onNotice("Employee code added");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const updateCode = useMutation({
    mutationFn: (v: { id: string; patch: Record<string, unknown> }) =>
      api(`/employees/codes/${v.id}`, {
        token,
        method: "PATCH",
        body: JSON.stringify(v.patch)
      }),
    onSuccess: () => invalidate(),
    onError: (e: Error) => onNotice(e.message)
  });
  const deleteCode = useMutation({
    mutationFn: (id: string) => api(`/employees/codes/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Employee code removed");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // ── Merge misspelled / alternate spellings of one person ──────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [canonicalName, setCanonicalName] = useState("");
  const [mergeUserId, setMergeUserId] = useState("");
  const suggestions = useQuery({
    queryKey: ["employee-suggestions", token],
    enabled: Boolean(token),
    queryFn: () => api<LabelSuggestions>("/employees/label-suggestions", { token })
  });
  // A merge rewrites assigned_user_label everywhere, so drop every cache that
  // groups/filters on the (now canonical) label.
  const invalidateIdentity = () => {
    [
      "employees", "employee-suggestions", "workforce-labels", "dashboard",
      "dashboard-trends", "performance", "user-dashboard", "user-dash-history",
      "user-dash-weakest", "user-dash-month", "user-dashboards-team", "backlinks"
    ].forEach((k) => queryClient.invalidateQueries({ queryKey: [k] }));
  };
  const merge = useMutation({
    mutationFn: (v: { canonical_label: string; alias_labels: string[]; user_id: string | null }) =>
      api<{ rows_relabeled: number }>("/employees/merge", { token, method: "POST", body: JSON.stringify(v) }),
    onSuccess: (r, v) => {
      onNotice(`Merged ${v.alias_labels.length} name${v.alias_labels.length === 1 ? "" : "s"} into “${v.canonical_label}” (${r.rows_relabeled} links)`);
      setSelected(new Set());
      setCanonicalName("");
      setMergeUserId("");
      invalidateIdentity();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const toggleLabel = (label: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });

  const d = data.data;
  const users = d?.app_users || [];
  const pickMergeUser = (id: string) => {
    setMergeUserId(id);
    if (!canonicalName.trim()) {
      const u = users.find((x) => x.id === id);
      if (u) setCanonicalName(u.name || u.email);
    }
  };
  const userOptions = (
    <>
      <option value="">— unmapped —</option>
      {users.map((u) => (
        <option key={u.id} value={u.id}>
          {u.name || u.email}
        </option>
      ))}
    </>
  );

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          Connect the sheet &quot;User&quot; names to real accounts, and manage employee codes.
        </p>
        <button
          onClick={() => sync.mutate()}
          className="flex h-9 items-center gap-2 self-start rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
        >
          {sync.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Sync from sheets
        </button>
      </div>

      {(suggestions.data?.clusters?.length ?? 0) > 0 ? (
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Smart suggestions — possible duplicate people" />
          <div className="space-y-2.5 p-3">
            <p className="text-xs text-muted">
              These sheet names look like spelling variants of one person. Review each group, tick in any
              extra name that belongs (a nickname or a different name for the same person, e.g. “Kashif”),
              then merge — their links, dashboards and performance all combine under one name.
            </p>
            {suggestions.data!.clusters.map((c) => (
              <MergeSuggestionCard
                key={c.key}
                cluster={c}
                allLabels={(d?.mappings || []).map((m) => ({ label: m.sheet_user_label, backlink_count: m.backlink_count }))}
                pending={merge.isPending}
                onMerge={(v) => merge.mutate(v)}
              />
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Sheet users → app accounts" />
        {selected.size > 0 ? (
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-field/50 px-3 py-2">
            <span className="text-xs font-semibold text-ink">{selected.size} selected</span>
            <span className="text-xs text-muted">Merge into</span>
            <input
              list="employee-label-list"
              className="h-8 w-44 rounded-md border border-line bg-panel px-2 text-sm"
              placeholder="Canonical name"
              value={canonicalName}
              onChange={(e) => setCanonicalName(e.target.value)}
            />
            <span className="text-xs text-muted">map to</span>
            <select
              className="h-8 rounded-md border border-line bg-panel px-2 text-sm"
              value={mergeUserId}
              onChange={(e) => pickMergeUser(e.target.value)}
            >
              {userOptions}
            </select>
            <button
              disabled={!canonicalName.trim() || merge.isPending}
              onClick={() => {
                const canon = canonicalName.trim();
                const aliases = Array.from(selected).filter((l) => l.toLowerCase() !== canon.toLowerCase());
                if (!aliases.length) {
                  onNotice("Pick a canonical name different from the selected labels.");
                  return;
                }
                merge.mutate({ canonical_label: canon, alias_labels: aliases, user_id: mergeUserId || null });
              }}
              className="flex h-8 items-center gap-1.5 rounded-md bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
            >
              {merge.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitCompare className="h-3.5 w-3.5" />}
              Merge {selected.size}
            </button>
            <button onClick={() => setSelected(new Set())} className="text-xs text-muted hover:text-ink">
              Clear
            </button>
          </div>
        ) : null}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <Th> </Th>
                <Th>Sheet user</Th>
                <Th>Backlinks</Th>
                <Th>Mapped to</Th>
                <Th>
                  <span title="Laid off = excluded from assignment pickers, the planner and weekly templates. All their past work stays visible everywhere.">
                    Status
                  </span>
                </Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(d?.mappings || []).map((m) => (
                <tr key={m.id}>
                  <Td>
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={selected.has(m.sheet_user_label)}
                      onChange={() => toggleLabel(m.sheet_user_label)}
                    />
                  </Td>
                  <Td>
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-ink">{m.sheet_user_label}</span>
                      {m.canonical_label && m.canonical_label.trim().toLowerCase() !== m.sheet_user_label.trim().toLowerCase() ? (
                        <span
                          title={`Counts toward “${m.canonical_label}”`}
                          className="inline-flex items-center gap-0.5 rounded-full border border-ocean/30 bg-ocean/10 px-1.5 py-0.5 text-[10px] font-medium text-ocean"
                        >
                          <GitCompare className="h-3 w-3" /> {m.canonical_label}
                        </span>
                      ) : null}
                    </div>
                  </Td>
                  <Td>{m.backlink_count}</Td>
                  <Td>
                    <select
                      className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
                      value={m.user_id || ""}
                      onChange={(event) =>
                        mapUser.mutate({ id: m.id, user_id: event.target.value || null })
                      }
                    >
                      {userOptions}
                    </select>
                  </Td>
                  <Td>
                    <button
                      onClick={() => {
                        const laidOff = m.is_active === false;
                        const msg = laidOff
                          ? `Mark ${m.sheet_user_label} as ACTIVE again? They return to the assignment pickers and planner.`
                          : `Mark ${m.sheet_user_label} as LAID OFF?

They disappear from assignment pickers, the planner and weekly templates — all their past work stays.`;
                        if (window.confirm(msg)) setActiveMut.mutate({ id: m.id, is_active: laidOff });
                      }}
                      className={clsx(
                        "rounded-full border px-2.5 py-1 text-xs font-semibold transition",
                        m.is_active === false
                          ? "border-danger/40 bg-danger/10 text-danger hover:bg-danger/20"
                          : "border-ocean/40 bg-ocean/10 text-ocean hover:bg-ocean/20"
                      )}
                    >
                      {m.is_active === false ? "Laid off" : "Active"}
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {d && !d.mappings.length ? (
            <Empty label="No sheet users yet — click 'Sync from sheets'." />
          ) : null}
        </div>
        <datalist id="employee-label-list">
          {Array.from(
            new Set((d?.mappings || []).map((m) => (m.canonical_label || m.sheet_user_label).trim()).filter(Boolean))
          ).map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Employee codes" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Linked account</Th>
                <Th>Active</Th>
                <Th> </Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(d?.codes || []).map((c) => (
                <tr key={c.id}>
                  <Td>
                    <span className="font-medium text-ink">{c.code}</span>
                  </Td>
                  <Td>{c.display_name || "—"}</Td>
                  <Td>
                    <select
                      className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
                      value={c.user_id || ""}
                      onChange={(event) =>
                        updateCode.mutate({ id: c.id, patch: { user_id: event.target.value || null } })
                      }
                    >
                      {userOptions}
                    </select>
                  </Td>
                  <Td>
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={c.is_active}
                      onChange={(event) =>
                        updateCode.mutate({ id: c.id, patch: { is_active: event.target.checked } })
                      }
                    />
                  </Td>
                  <Td>
                    <button
                      onClick={() => deleteCode.mutate(c.id)}
                      aria-label="Remove code"
                      className="grid h-7 w-7 place-items-center rounded border border-line bg-panel text-muted transition hover:bg-field hover:text-danger"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {d && !d.codes.length ? (
            <Empty label="No employee codes — add one below or sync from sheets." />
          ) : null}
        </div>
        <form
          className="flex flex-wrap gap-2 border-t border-line p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (newCode.trim()) addCode.mutate();
          }}
        >
          <input
            className="h-9 w-32 rounded-md border border-line bg-panel px-2 text-sm"
            placeholder="Code"
            value={newCode}
            onChange={(event) => setNewCode(event.target.value)}
          />
          <input
            className="h-9 flex-1 rounded-md border border-line bg-panel px-2 text-sm"
            placeholder="Name (optional)"
            value={newCodeName}
            onChange={(event) => setNewCodeName(event.target.value)}
          />
          <button className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
            {addCode.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add code
          </button>
        </form>
      </section>
    </section>
  );
}

// One fuzzy-suggestion cluster: shows the likely-same spellings as toggle chips,
// lets you pull in an extra name (e.g. a different name for the same person), pick
// the keeper, and merge in one click.
function MergeSuggestionCard({
  cluster,
  allLabels,
  pending,
  onMerge
}: {
  cluster: LabelSuggestionCluster;
  allLabels: { label: string; backlink_count: number }[];
  pending: boolean;
  onMerge: (v: { canonical_label: string; alias_labels: string[]; user_id: string | null }) => void;
}) {
  const [canonical, setCanonical] = useState(cluster.canonical);
  const [members, setMembers] = useState<Set<string>>(() => new Set(cluster.members.map((m) => m.label)));
  const inCluster = new Set(cluster.members.map((m) => m.label));
  const byLabel = new Map(allLabels.map((l) => [l.label, l] as const));
  const chips = [
    ...cluster.members,
    ...Array.from(members).filter((l) => !inCluster.has(l)).map((l) => byLabel.get(l) || { label: l, backlink_count: 0 })
  ];
  const addable = allLabels.filter((l) => !inCluster.has(l.label) && !members.has(l.label));
  const toggle = (label: string) =>
    setMembers((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  const aliases = Array.from(members).filter((l) => l.trim() && l.toLowerCase() !== canonical.trim().toLowerCase());
  const canMerge = Boolean(canonical.trim()) && aliases.length >= 1 && !pending;

  return (
    <div className="space-y-2.5 rounded-lg border border-line bg-field/40 p-3">
      <div className="flex items-center gap-2 text-sm">
        <Users className="h-4 w-4 text-ocean" />
        <span className="font-medium text-ink">These look like one person</span>
        <span className="rounded-full bg-ocean/10 px-1.5 py-0.5 text-[10px] font-semibold text-ocean">
          {Math.round(cluster.score * 100)}% match
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((m) => {
          const on = members.has(m.label);
          return (
            <button
              key={m.label}
              onClick={() => toggle(m.label)}
              title={on ? "Included — click to leave out" : "Excluded — click to include"}
              className={clsx(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition",
                on ? "border-ocean/40 bg-ocean/10 text-ink" : "border-line bg-panel text-muted line-through"
              )}
            >
              {m.label}
              <span className="text-[10px] text-muted">{m.backlink_count}</span>
            </button>
          );
        })}
      </div>
      {addable.length ? (
        <div className="flex items-center gap-2">
          <UserPlus className="h-3.5 w-3.5 text-muted" />
          <select
            className="h-8 rounded-md border border-line bg-panel px-2 text-xs"
            value=""
            onChange={(e) => { if (e.target.value) toggle(e.target.value); }}
          >
            <option value="">Add another name to this person…</option>
            {addable.map((l) => (
              <option key={l.label} value={l.label}>{l.label} ({l.backlink_count})</option>
            ))}
          </select>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted">Keep as</span>
        <input
          list="employee-label-list"
          className="h-8 min-w-[150px] flex-1 rounded-md border border-line bg-panel px-2 text-sm"
          value={canonical}
          onChange={(e) => setCanonical(e.target.value)}
        />
        <button
          disabled={!canMerge}
          onClick={() => onMerge({ canonical_label: canonical.trim(), alias_labels: aliases, user_id: null })}
          className="flex h-8 items-center gap-1.5 rounded-md bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
        >
          {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <GitCompare className="h-3.5 w-3.5" />}
          Merge into {canonical.trim() || "…"}
        </button>
      </div>
    </div>
  );
}

type MergeGroup = {
  suggested_master: string;
  suggested_master_id: string;
  members: Array<{ id: string; name: string; backlinks: number }>;
  total_backlinks: number;
};

function LinkTypesCard({
  token,
  onNotice
}: {
  token: string | null;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  // Standardization review state: proposal groups + per-group winner/final-name
  // overrides. NOTHING merges until the admin explicitly clicks per group.
  const [proposal, setProposal] = useState<MergeGroup[] | null>(null);
  const [winnerPick, setWinnerPick] = useState<Record<number, string>>({});
  const [finalName, setFinalName] = useState<Record<number, string>>({});
  const [busyGroup, setBusyGroup] = useState<number | null>(null);
  const [doneGroups, setDoneGroups] = useState<Record<number, string>>({});
  const [renameFor, setRenameFor] = useState<{ id: string; name: string } | null>(null);
  const types = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["link-types"] });
    queryClient.invalidateQueries({ queryKey: ["backlinks"] });
  };
  const create = useMutation({
    mutationFn: () =>
      api("/link-types", { token, method: "POST", body: JSON.stringify({ name: name.trim() }) }),
    onSuccess: () => {
      setName("");
      onNotice("Link type added");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/link-types/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Link type removed");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const scan = useMutation({
    mutationFn: () => api<{ groups: MergeGroup[] }>("/link-types/merge-proposal", { token }),
    onSuccess: (d) => {
      setProposal(d.groups);
      setWinnerPick({});
      setFinalName({});
      setDoneGroups({});
      if (!d.groups.length) onNotice("No duplicate or misspelled link types found — catalog is clean.");
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const renameOne = useMutation({
    mutationFn: (v: { id: string; name: string }) =>
      api<{ changed: Record<string, number>; tab_renames: Array<{ ok: boolean }> }>(
        `/link-types/${v.id}/rename`,
        { token, method: "POST", body: JSON.stringify({ name: v.name, rename_tabs: true }) }
      ),
    onSuccess: (d) => {
      onNotice(
        `Renamed everywhere — ${d.changed?.backlinks ?? 0} links, ${(d.tab_renames || []).filter((t) => t.ok).length} sheet tabs updated`
      );
      setRenameFor(null);
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // Execute ONE reviewed group: merge every non-winner member into the winner,
  // then (if the admin edited the final spelling) rename the winner. Sequential —
  // the server serializes per-workspace anyway (advisory lock).
  const applyGroup = async (gi: number, g: MergeGroup) => {
    const winnerId = winnerPick[gi] || g.suggested_master_id;
    const winner = g.members.find((m) => m.id === winnerId);
    if (!winner) return;
    const target = (finalName[gi] ?? g.suggested_master).trim() || winner.name;
    const losers = g.members.filter((m) => m.id !== winnerId);
    if (
      !window.confirm(
        `Merge ${losers.length} variant${losers.length === 1 ? "" : "s"} (${losers
          .map((m) => `"${m.name}"`)
          .join(", ")}) into "${target}"?\n\nThis updates ${g.total_backlinks} links plus tasks, rates, scoring and the Google Sheet tab names. The change is logged and merged names keep redirecting.`
      )
    )
      return;
    setBusyGroup(gi);
    try {
      let links = 0;
      let tabs = 0;
      let tabFails = 0;
      for (const loser of losers) {
        const r = await api<{ changed: Record<string, number>; tab_renames: Array<{ ok: boolean }> }>(
          `/link-types/${loser.id}/merge`,
          { token, method: "POST", body: JSON.stringify({ winner_id: winnerId, rename_tabs: true }) }
        );
        links += r.changed?.backlinks ?? 0;
        tabs += (r.tab_renames || []).filter((t) => t.ok).length;
        tabFails += (r.tab_renames || []).filter((t) => !t.ok).length;
      }
      if (target !== winner.name) {
        const r = await api<{ changed: Record<string, number>; tab_renames: Array<{ ok: boolean }> }>(
          `/link-types/${winnerId}/rename`,
          { token, method: "POST", body: JSON.stringify({ name: target, rename_tabs: true }) }
        );
        links += r.changed?.backlinks ?? 0;
        tabs += (r.tab_renames || []).filter((t) => t.ok).length;
        tabFails += (r.tab_renames || []).filter((t) => !t.ok).length;
      }
      setDoneGroups((d) => ({
        ...d,
        [gi]: `Done — ${links} links updated, ${tabs} sheet tabs renamed${tabFails ? `, ${tabFails} tab rename${tabFails === 1 ? "" : "s"} failed (see audit log)` : ""}`
      }));
      onNotice(`"${target}" standardized (${links} links)`);
      invalidate();
    } catch (e) {
      onNotice((e as Error).message);
    } finally {
      setBusyGroup(null);
    }
  };

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <SectionTitle title="Link types (workspace catalog)" />
      <div className="space-y-3 p-4">
        <p className="text-xs text-muted">
          The catalog of backlink types (Web 2.0, Profile, Guest Post…). Used by scoring, filters,
          and competitor analysis. Imports auto‑add types they encounter — misspellings are folded
          back into the master automatically once merged here.
        </p>
        <div className="flex flex-wrap gap-2">
          {(types.data || []).map((t) => (
            <span
              key={t.id}
              className="inline-flex items-center gap-1.5 rounded-full border border-line bg-field px-3 py-1 text-sm"
            >
              {t.name}
              <span className="text-xs text-muted">({t.backlink_count})</span>
              <button
                onClick={() => setRenameFor({ id: t.id, name: t.name })}
                aria-label="Rename link type everywhere"
                title="Rename everywhere (links, tasks, rates, sheet tabs)"
                className="text-muted transition hover:text-ink"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => remove.mutate(t.id)}
                aria-label="Remove link type"
                className="text-muted transition hover:text-danger"
              >
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
          {types.data && !types.data.length ? (
            <span className="text-sm text-muted">No link types yet — add one below.</span>
          ) : null}
        </div>
        {renameFor ? (
          <form
            className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-field/50 p-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (renameFor.name.trim()) renameOne.mutate({ id: renameFor.id, name: renameFor.name.trim() });
            }}
          >
            <span className="text-xs font-semibold text-muted">Rename everywhere:</span>
            <input
              className="h-8 w-56 rounded-md border border-line bg-panel px-2 text-sm"
              value={renameFor.name}
              maxLength={60}
              autoFocus
              onChange={(e) => setRenameFor({ ...renameFor, name: e.target.value })}
            />
            <button className="h-8 rounded-md bg-ocean px-3 text-xs font-semibold text-white dark:text-slate-900">
              {renameOne.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Apply"}
            </button>
            <button type="button" onClick={() => setRenameFor(null)} className="h-8 rounded-md border border-line px-3 text-xs">
              Cancel
            </button>
            <span className="w-full text-[11px] text-muted">
              Updates every link, task, rate, scoring rule and the Google Sheet tab names using this type.
            </span>
          </form>
        ) : null}
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) create.mutate();
          }}
        >
          <input
            className="h-9 flex-1 rounded-md border border-line bg-panel px-3 text-sm"
            placeholder="New link type (e.g. Web 2.0)"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add
          </button>
        </form>

        {/* ── Standardization: scan → REVIEW → merge (nothing runs unreviewed) ── */}
        <div className="border-t border-line pt-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 text-sm font-semibold text-ink">
                Clean up duplicates &amp; misspellings
                <HelpTip text="Scans the catalog for spelling mistakes, casing/plural variants and abbreviations of the same link type (e.g. 'Busniess Listing' → 'Business Listing'). You review every group and pick the final name — merging updates all links, tasks, rates, scoring and renames the Google Sheet tabs. Merged names keep redirecting, so old sheets can't re-create them." />
              </div>
              <p className="text-xs text-muted">Review each group and choose the final master name before merging.</p>
            </div>
            <button
              onClick={() => scan.mutate()}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
            >
              {scan.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitCompare className="h-4 w-4" />}
              Scan for duplicates
            </button>
          </div>
          {proposal && proposal.length ? (
            <div className="mt-3 space-y-3">
              {proposal.map((g, gi) => {
                const winnerId = winnerPick[gi] || g.suggested_master_id;
                return (
                  <div key={gi} className="rounded-lg border border-line bg-field/40 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-bold uppercase tracking-wide text-muted">Group {gi + 1}</span>
                      <span className="text-xs text-muted">{g.total_backlinks} links affected</span>
                      {doneGroups[gi] ? (
                        <span className="ml-auto text-xs font-medium text-ocean">{doneGroups[gi]}</span>
                      ) : null}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {g.members.map((m) => (
                        <span
                          key={m.id}
                          className={clsx(
                            "rounded-full border px-2.5 py-0.5 text-xs",
                            m.id === winnerId
                              ? "border-ocean bg-ocean/10 font-semibold text-ocean"
                              : "border-line bg-panel text-muted"
                          )}
                        >
                          {m.name} · {m.backlinks}
                        </span>
                      ))}
                    </div>
                    {!doneGroups[gi] ? (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <label className="text-xs text-muted">Keep:</label>
                        <select
                          value={winnerId}
                          onChange={(e) => setWinnerPick((w) => ({ ...w, [gi]: e.target.value }))}
                          className="h-8 rounded-md border border-line bg-panel px-2 text-xs"
                        >
                          {g.members.map((m) => (
                            <option key={m.id} value={m.id}>{m.name}</option>
                          ))}
                        </select>
                        <label className="text-xs text-muted">Final name:</label>
                        <input
                          className="h-8 w-52 rounded-md border border-line bg-panel px-2 text-xs"
                          value={finalName[gi] ?? g.suggested_master}
                          maxLength={60}
                          onChange={(e) => setFinalName((f) => ({ ...f, [gi]: e.target.value }))}
                        />
                        <button
                          onClick={() => applyGroup(gi, g)}
                          disabled={busyGroup !== null}
                          className="flex h-8 items-center gap-1.5 rounded-md bg-ocean px-3 text-xs font-semibold text-white disabled:opacity-60 dark:text-slate-900"
                        >
                          {busyGroup === gi ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          Merge group
                        </button>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : null}
          {proposal && !proposal.length ? (
            <p className="mt-2 text-sm text-muted">Catalog is clean — no duplicate groups detected.</p>
          ) : null}
        </div>
      </div>
    </section>
  );
}

// ── Scoring guide (Enterprise §13): how the 0-100 score works, in plain words ──
// Content is shared by the Backlinks-toolbar modal AND the user Guidance desk.
function ScoringGuideContent() {
  const row = (sev: string, pts: string, cls: string, examples: string) => (
    <tr>
      <Td><span className={clsx("rounded px-1.5 py-0.5 text-xs font-bold", cls)}>{sev}</span></Td>
      <Td><span className="font-semibold text-ink">{pts}</span></Td>
      <Td><span className="text-muted">{examples}</span></Td>
    </tr>
  );
  return (
        <div className="space-y-5 text-sm">
          <div>
            <h3 className="mb-1 font-semibold text-ink">1. Every link starts at 100</h3>
            <p className="text-muted">
              Each problem found during a QA check subtracts points based on how serious it is.
              The final number is the link&apos;s quality score.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-ink">2. What problems cost</h3>
            <table className="w-full text-left text-sm">
              <thead className="bg-field text-xs uppercase text-muted">
                <tr><Th>Severity</Th><Th>Points</Th><Th>Typical examples</Th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {row("Critical", "−60 + capped at 25", "bg-danger/10 text-danger", "Link missing, page dead (404), domain gone — the score can never exceed 25 while a critical issue exists")}
                {row("High", "−25", "bg-danger/10 text-danger", "Link hidden by CSS, wrong target URL, page-level nofollow, cross-domain canonical")}
                {row("Medium", "−10", "bg-ember/10 text-ember", "rel=nofollow on the link, sponsored/UGC placement, JS-only link")}
                {row("Low", "−3", "bg-field text-muted", "Footer/sidebar placement, matched only after URL normalization")}
                {row("Info", "0", "bg-ocean/10 text-ocean", "Notes only — e.g. found via a GBP/Maps listing, multiple links to the target")}
              </tbody>
            </table>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-ink">3. What the number means</h3>
            <p className="text-muted">
              <span className="font-semibold text-ocean">80–100 Qualified</span> · nothing to do.{" "}
              <span className="font-semibold text-ember">30–79 Needs improvement</span> · works but lost value.{" "}
              <span className="font-semibold text-danger">below 30 Not qualified</span> · serious problem, fix or replace.
              Thresholds are tunable per link type / project in the Scoring desk.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-ink">4. Domain metrics (optional factors)</h3>
            <p className="text-muted">
              DA, Authority Score, domain age, external index status and duplicates can also add or
              subtract points — they are <span className="font-semibold text-ink">off (0 points) by default</span> and
              only count once an admin assigns them points in the Scoring desk. So a blank DA never
              silently hurts a link&apos;s score.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-ink">5. Where to see it per link</h3>
            <p className="text-muted">
              Open any link → <span className="font-semibold text-ink">“Why this score”</span> lists every deduction
              biggest-first, each with a 💡 “how to improve” suggestion. Statuses like{" "}
              <span className="font-semibold text-ink">Needs review</span> mean “we couldn&apos;t verify — check by hand”,
              never a hidden penalty: unverifiable pages don&apos;t lose points.
            </p>
          </div>
          <div>
            <h3 className="mb-1 font-semibold text-ink">6. How to raise scores</h3>
            <ul className="list-inside list-disc space-y-0.5 text-muted">
              <li>Fix missing/dead links first — a single critical caps the score at 25.</li>
              <li>Ask publishers to drop rel=nofollow where dofollow was agreed (+10 back).</li>
              <li>Prefer in-content placements over footers/sidebars.</li>
              <li>Get source pages indexed (share, internal links) and run an index check.</li>
              <li>Use higher-quality domains — the Opportunities tab ranks the best available ones.</li>
            </ul>
          </div>
        </div>
  );
}

function ScoringGuideModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-line bg-panel p-6 shadow-pop scrollbar-thin"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-ink">How link scoring works</h2>
          <button onClick={onClose} className="text-muted hover:text-ink">✕</button>
        </div>
        <ScoringGuideContent />
      </div>
    </div>
  );
}

function cleanScoringRules(
  draft: Record<string, Record<string, number | "">>
): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {};
  for (const [param, outcomes] of Object.entries(draft)) {
    const block: Record<string, number> = {};
    for (const [oc, v] of Object.entries(outcomes)) {
      if (v === "" || v === null || v === undefined || Number.isNaN(Number(v))) continue;
      block[oc] = Math.trunc(Number(v));
    }
    if (Object.keys(block).length) out[param] = block;
  }
  return out;
}

function ScoringDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  // In project context, open directly on the project's own scoring rules.
  const [scope, setScope] = useState<"global" | "link_type" | "project">(
    projectId ? "project" : "global"
  );
  const [refId, setRefId] = useState<string>(projectId || "");
  // Optional second axis inside a project: configure ONE link type for THIS
  // project (owners: "each project sets scoring for all 7 link types").
  const [projLt, setProjLt] = useState<string>("");
  const [draft, setDraft] = useState<Record<string, Record<string, number | "">>>({});
  const [bands, setBands] = useState<{ fail_below: number; warn_below: number }>({
    fail_below: 30,
    warn_below: 80
  });
  const [preview, setPreview] = useState<RescoreResult | null>(null);

  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  const projects = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });

  // Default the "by project" scope to whatever project is selected in the sidebar.
  useEffect(() => {
    if (scope === "project" && !refId && projectId) setRefId(projectId);
  }, [scope, projectId, refId]);

  const effectiveRef = scope === "global" ? "" : refId;
  // Project + a chosen link type = the combined project_link_type scope.
  const effectiveScope = scope === "project" && projLt ? "project_link_type" : scope;
  const ltParam = effectiveScope === "project_link_type" ? `&link_type_id=${projLt}` : "";
  const ready = scope === "global" || Boolean(effectiveRef);
  const cfgKey = ["scoring-config", token, effectiveScope, effectiveRef, projLt];
  const config = useQuery({
    queryKey: cfgKey,
    enabled: Boolean(token) && ready,
    queryFn: () =>
      api<ScoringConfig>(
        `/scoring/config?scope=${effectiveScope}${effectiveRef ? `&scope_ref_id=${effectiveRef}` : ""}${ltParam}`,
        { token }
      )
  });

  useEffect(() => {
    if (config.data) {
      setDraft(JSON.parse(JSON.stringify(config.data.rules || {})));
      setBands({ ...config.data.bands });
      setPreview(null);
    }
  }, [config.data]);

  const body = () =>
    JSON.stringify({
      scope: effectiveScope,
      scope_ref_id: effectiveRef || null,
      link_type_id: effectiveScope === "project_link_type" ? projLt : null,
      rules: cleanScoringRules(draft),
      bands
    });

  const save = useMutation({
    mutationFn: () => api<ScoringConfig>("/scoring/config", { token, method: "PUT", body: body() }),
    onSuccess: () => {
      onNotice("Scoring saved as a new version");
      queryClient.invalidateQueries({ queryKey: cfgKey });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const rescore = (apply: boolean) =>
    api<RescoreResult>("/scoring/rescore", {
      token,
      method: "POST",
      body: JSON.stringify({
        scope: effectiveScope,
        scope_ref_id: effectiveRef || null,
        link_type_id: effectiveScope === "project_link_type" ? projLt : null,
        preview: !apply
      })
    });
  const previewMut = useMutation({
    mutationFn: () => rescore(false),
    onSuccess: (r) => setPreview(r),
    onError: (e: Error) => onNotice(e.message)
  });
  const applyMut = useMutation({
    mutationFn: () => rescore(true),
    onSuccess: (r) => {
      setPreview(r);
      onNotice(`Re-scored ${r.changed} of ${r.total} backlinks`);
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const cfg = config.data;
  const setCell = (param: string, outcome: string, value: string) => {
    setDraft((d) => {
      const next: Record<string, Record<string, number | "">> = { ...d, [param]: { ...(d[param] || {}) } };
      if (value === "") delete next[param][outcome];
      else next[param][outcome] = Number(value);
      if (Object.keys(next[param]).length === 0) delete next[param];
      return next;
    });
  };

  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-ink">Scoring rules</h2>
        <p className="text-sm text-muted">
          Set how many points each parameter adds or subtracts. Project and link-type rules
          override the global defaults; leave a box blank to inherit (the faint number is what
          applies). Saving creates a new version; “Apply now” re-scores existing links instantly
          (no re-crawl).
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(["global", "link_type", "project"] as const).map((s) => (
          <button
            key={s}
            onClick={() => {
              setScope(s);
              setRefId(s === "project" && projectId ? projectId : "");
              setProjLt("");
            }}
            className={clsx(
              "h-9 rounded-md border px-3 text-sm font-medium transition",
              scope === s ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:bg-field"
            )}
          >
            {s === "global" ? "Global" : s === "link_type" ? "By link type" : "By project"}
          </button>
        ))}
        {scope === "link_type" ? (
          <select
            value={refId}
            onChange={(e) => setRefId(e.target.value)}
            className="h-9 rounded-md border border-line bg-panel px-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
          >
            <option value="">Select link type…</option>
            {(linkTypes.data || []).map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name}
              </option>
            ))}
          </select>
        ) : null}
        {scope === "project" ? (
          <select
            value={refId}
            onChange={(e) => {
              setRefId(e.target.value);
              setProjLt("");
            }}
            className="h-9 rounded-md border border-line bg-panel px-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
          >
            <option value="">Select project…</option>
            {(projects.data || []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        ) : null}
        {scope === "project" && refId ? (
          <select
            value={projLt}
            onChange={(e) => setProjLt(e.target.value)}
            title="Configure one link type for this project — the most specific rule; wins over the project default and the link type's own rules"
            className="h-9 rounded-md border border-line bg-panel px-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
          >
            <option value="">All link types (project default)</option>
            {(linkTypes.data || []).map((lt) => (
              <option key={lt.id} value={lt.id}>
                Link type: {lt.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {!ready ? (
        <Empty label="Pick a link type or project to configure its scoring." />
      ) : config.isLoading || !cfg ? (
        <div className="flex justify-center p-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted" />
        </div>
      ) : (
        <>
          <section className="rounded-xl border border-line bg-panel shadow-card">
            <SectionTitle title={`Status thresholds · ${cfg.version ? `v${cfg.version}` : "inherited"}`} />
            <div className="flex flex-wrap items-end gap-4 p-4">
              <label className="text-sm">
                <span className="mb-1 block text-xs uppercase text-muted">Fail below</span>
                <input
                  type="number"
                  value={bands.fail_below}
                  onChange={(e) => setBands((b) => ({ ...b, fail_below: Number(e.target.value) }))}
                  className="h-9 w-24 rounded-md border border-line px-2 text-sm"
                />
              </label>
              <label className="text-sm">
                <span className="mb-1 block text-xs uppercase text-muted">Warn below</span>
                <input
                  type="number"
                  value={bands.warn_below}
                  onChange={(e) => setBands((b) => ({ ...b, warn_below: Number(e.target.value) }))}
                  className="h-9 w-24 rounded-md border border-line px-2 text-sm"
                />
              </label>
              <div className="ml-auto flex flex-wrap gap-2">
                <button
                  onClick={() => save.mutate()}
                  disabled={save.isPending}
                  className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
                >
                  {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  Save version
                </button>
                <button
                  onClick={() => previewMut.mutate()}
                  disabled={previewMut.isPending}
                  className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm font-medium text-ink hover:bg-field"
                >
                  {previewMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />}
                  Preview re-score
                </button>
                <button
                  onClick={() => applyMut.mutate()}
                  disabled={applyMut.isPending}
                  className="flex h-9 items-center gap-2 rounded-md border border-ember/40 px-3 text-sm font-medium text-ember hover:bg-ember/10"
                >
                  {applyMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Apply now
                </button>
              </div>
            </div>
            {preview ? (
              <div className="border-t border-line p-4 text-sm">
                <span className="font-medium text-ink">{preview.applied ? "Applied" : "Preview"}:</span>{" "}
                <span className="text-muted">
                  {preview.changed} of {preview.total} backlinks change (avg{" "}
                  {preview.avg_score_delta > 0 ? "+" : ""}
                  {preview.avg_score_delta} pts)
                </span>
                {Object.keys(preview.transitions).length ? (
                  <span className="ml-2 text-muted">
                    · {Object.entries(preview.transitions).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                  </span>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="rounded-xl border border-line bg-panel shadow-card">
            <SectionTitle title="Parameters" />
            <div className="divide-y divide-line">
              {cfg.parameters.map((p) => (
                <div key={p.key} className="p-4">
                  <div className="mb-2">
                    <div className="text-sm font-semibold text-ink">{p.display_name}</div>
                    {p.description ? <div className="text-xs text-muted">{p.description}</div> : null}
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {p.outcomes.map((oc) => {
                      const own = draft[p.key]?.[oc.key];
                      const inherited = cfg.inherited_rules[p.key]?.[oc.key];
                      const fallback = inherited !== undefined ? inherited : p.default_points[oc.key] ?? 0;
                      return (
                        <label key={oc.key} className="text-xs">
                          <span className="mb-1 block text-muted">{oc.label}</span>
                          <input
                            type="number"
                            value={own === undefined ? "" : own}
                            placeholder={String(fallback)}
                            onChange={(e) => setCell(p.key, oc.key, e.target.value)}
                            className="h-9 w-20 rounded-md border border-line px-2 text-sm"
                          />
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        </>
      )}
    </section>
  );
}

// Company + per-project branding (admin, Settings desk). Company branding drives
// the login screen / top bar via the public /auth/branding endpoint; project
// logos live in the "project_logos" setting and show in the project picker.
function BrandingCard({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [companyName, setCompanyName] = useState("");
  const [companyDomain, setCompanyDomain] = useState("");
  const [logoDataUri, setLogoDataUri] = useState("");
  const [announcement, setAnnouncement] = useState("");

  const settings = useQuery({
    queryKey: ["workspace-settings", token],
    enabled: Boolean(token),
    retry: false,
    queryFn: () =>
      api<Array<{ key: string; value: Record<string, unknown> }>>("/settings", { token })
  });

  // Prefill the form from the stored "branding" setting once it loads.
  useEffect(() => {
    const branding = settings.data?.find((s) => s.key === "branding")?.value as
      | { company_name?: string | null; company_domain?: string | null; logo_data_uri?: string | null; announcement?: string | null }
      | undefined;
    if (branding) {
      setCompanyName(branding.company_name || "");
      setCompanyDomain(branding.company_domain || "");
      setLogoDataUri(branding.logo_data_uri || "");
      setAnnouncement(branding.announcement || "");
    }
  }, [settings.data]);

  const projectLogos =
    ((settings.data || []).find((s) => s.key === "project_logos")?.value as
      Record<string, string>) || {};
  const projectLogo = projectId ? projectLogos[projectId] || "" : "";

  // FileReader → data URI. Logos are stored inline in settings, so keep them small.
  const readLogo = (file: File | undefined, set: (uri: string) => void) => {
    if (!file) return;
    if (file.size > 300 * 1024) {
      onNotice("Logo too large — keep it under 300 KB");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => set(String(reader.result || ""));
    reader.readAsDataURL(file);
  };

  const saveBranding = useMutation({
    mutationFn: () =>
      api<{ message: string }>("/settings", {
        token,
        method: "PUT",
        body: JSON.stringify({
          key: "branding",
          value: {
            company_name: companyName.trim() || null,
            company_domain: companyDomain.trim() || null,
            logo_data_uri: logoDataUri || null,
            announcement: announcement.trim() || null
          },
          is_secret: false
        })
      }),
    onSuccess: () => {
      onNotice("Branding saved");
      queryClient.invalidateQueries({ queryKey: ["branding"] });
      queryClient.invalidateQueries({ queryKey: ["workspace-settings"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const saveProjectLogo = useMutation({
    mutationFn: (uri: string) => {
      // Merge into the shared {projectId: dataURI} map so other projects keep theirs.
      const next = { ...projectLogos };
      if (uri) next[projectId] = uri;
      else delete next[projectId];
      return api<{ message: string }>("/settings", {
        token,
        method: "PUT",
        body: JSON.stringify({ key: "project_logos", value: next, is_secret: false })
      });
    },
    onSuccess: () => {
      onNotice("Project logo saved");
      queryClient.invalidateQueries({ queryKey: ["workspace-settings"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <SectionTitle title="Company & branding" />
      <div className="space-y-3 p-4">
        <p className="text-xs text-muted">
          Company name and logo appear on the login screen and top bar. The company domain is
          used for auto‑created user emails.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Company name" value={companyName} onChange={setCompanyName} />
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">
              Company domain
            </span>
            <input
              className="h-10 w-full rounded-xl border border-line bg-panel shadow-card px-3 text-sm shadow-sm transition focus:border-ocean focus:outline-none focus:ring-2 focus:ring-ocean/20"
              placeholder="techsa.com — used for auto-created user emails"
              value={companyDomain}
              onChange={(event) => setCompanyDomain(event.target.value)}
            />
          </label>
          <label className="block flex-1 min-w-[260px]">
            <span className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted">
              Login-page announcement
              <HelpTip text="Optional one-liner shown to everyone on the sign-in page (e.g. maintenance notice, welcome message). Leave empty to hide." />
            </span>
            <input
              className="h-9 w-full rounded-md border border-line bg-panel px-3 text-sm"
              placeholder="e.g. Maintenance window Sunday 02:00–03:00 UTC"
              maxLength={200}
              value={announcement}
              onChange={(event) => setAnnouncement(event.target.value)}
            />
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">
              Company logo
            </span>
            <input
              type="file"
              accept="image/*"
              className="block text-sm text-muted"
              onChange={(event) => readLogo(event.target.files?.[0], setLogoDataUri)}
            />
          </label>
          {logoDataUri ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoDataUri}
              alt=""
              className="h-10 w-10 rounded-lg border border-line object-contain"
            />
          ) : null}
          <button
            onClick={() => saveBranding.mutate()}
            disabled={saveBranding.isPending}
            className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
          >
            {saveBranding.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <CheckCircle2 className="h-4 w-4" />
            )}
            Save
          </button>
        </div>
        {projectId ? (
          <div className="space-y-2 border-t border-line pt-3">
            <p className="text-xs text-muted">
              <strong className="text-ink">Project logo</strong> — shown in the project picker
              instead of the initials.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                type="file"
                accept="image/*"
                className="block text-sm text-muted"
                onChange={(event) =>
                  readLogo(event.target.files?.[0], (uri) => saveProjectLogo.mutate(uri))
                }
              />
              {projectLogo ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={projectLogo}
                  alt=""
                  className="h-10 w-10 rounded-lg border border-line object-cover"
                />
              ) : null}
              {projectLogo ? (
                <button
                  onClick={() => saveProjectLogo.mutate("")}
                  disabled={saveProjectLogo.isPending}
                  className="rounded border border-line bg-panel px-2 py-1 text-xs font-medium text-muted transition hover:bg-field hover:text-danger"
                >
                  Remove
                </button>
              ) : null}
              {saveProjectLogo.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted" />
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}

const QA_KNOB_META: Record<string, { label: string; help: string; group: string }> = {
  chunk_size: { label: "Links per task", help: "How many staged links each QA worker task checks at once. Higher = fewer tasks, more parallel load.", group: "Throughput" },
  rate_per_sec: { label: "Requests/sec per domain", help: "Politeness: how fast we hit a single source site. Lower is gentler.", group: "Throughput" },
  burst: { label: "Burst per domain", help: "How many requests can fire back-to-back before rate limiting kicks in.", group: "Throughput" },
  connect_timeout: { label: "Connect timeout (s)", help: "How long to wait to open a connection before giving up.", group: "Timeouts" },
  read_timeout: { label: "Read timeout (s)", help: "How long to wait for the page body once connected.", group: "Timeouts" },
  total_timeout: { label: "Total timeout (s)", help: "Overall cap for one page fetch (connect + read + redirects).", group: "Timeouts" },
  render_enabled: { label: "Render JS pages", help: "Use the headless browser for JavaScript-only pages during QA.", group: "Rendering" },
  render_timeout_ms: { label: "Render timeout (ms)", help: "How long the browser waits for a JS page to settle.", group: "Rendering" },
  render_wait_until: { label: "Render wait-until", help: "When the browser considers a page 'loaded' (networkidle is strictest).", group: "Rendering" }
};

function QaSettingsCard({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  type QaMeta = { default: number | boolean | string; min: number | null; max: number | null; kind: string; overridden: boolean };
  type QaSettings = { effective: Record<string, number | boolean | string>; meta: Record<string, QaMeta>; wait_until_choices: string[] };
  const [draft, setDraft] = useState<Record<string, string | boolean>>({});
  const q = useQuery({
    queryKey: ["qa-settings", token],
    enabled: Boolean(token),
    queryFn: () => api<QaSettings>("/qa-settings", { token })
  });
  const save = useMutation({
    mutationFn: (overrides: Record<string, unknown>) =>
      api<QaSettings>("/qa-settings", { token, method: "PUT", body: JSON.stringify({ overrides }) }),
    onSuccess: () => {
      onNotice("QA execution settings saved");
      setDraft({});
      queryClient.invalidateQueries({ queryKey: ["qa-settings"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const d = q.data;
  if (!d) {
    return (
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="QA execution settings" />
        <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      </section>
    );
  }
  const val = (k: string) => (k in draft ? draft[k] : d.effective[k]);
  const keys = Object.keys(QA_KNOB_META).filter((k) => k in d.meta);
  const groups = Array.from(new Set(keys.map((k) => QA_KNOB_META[k].group)));
  const onSave = () => {
    // Send only knobs the user touched; "" clears an override back to default.
    const overrides: Record<string, unknown> = {};
    for (const k of Object.keys(draft)) {
      const v = draft[k];
      overrides[k] = v === "" ? null : v;
    }
    save.mutate(overrides);
  };
  const resetOne = (k: string) => save.mutate({ [k]: null });

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-4">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
          QA execution settings
          <HelpTip text="Advanced controls for how QA checks run in this workspace: throughput, timeouts and rendering. Unset knobs use the platform default. Admin only." />
        </h3>
        <button
          onClick={onSave}
          disabled={save.isPending || !Object.keys(draft).length}
          className="flex h-8 items-center gap-1.5 rounded-lg bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
        >
          {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
          Save changes
        </button>
      </div>
      <div className="space-y-4 p-4">
        {groups.map((g) => (
          <div key={g}>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">{g}</p>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {keys.filter((k) => QA_KNOB_META[k].group === g).map((k) => {
                const meta = d.meta[k];
                const changed = k in draft;
                return (
                  <div key={k} className="rounded-lg border border-line bg-field/40 p-2.5">
                    <div className="flex items-center justify-between gap-1">
                      <span className="flex items-center gap-1 text-xs font-medium text-ink">
                        {QA_KNOB_META[k].label}
                        <HelpTip text={QA_KNOB_META[k].help} />
                      </span>
                      {meta.overridden ? (
                        <button onClick={() => resetOne(k)} title="Reset to platform default" className="text-[10px] font-semibold text-plum hover:underline">
                          custom · reset
                        </button>
                      ) : (
                        <span className="text-[10px] text-muted">default</span>
                      )}
                    </div>
                    <div className="mt-1.5">
                      {meta.kind === "bool" ? (
                        <label className="flex items-center gap-2 text-sm text-ink">
                          <input
                            type="checkbox"
                            checked={Boolean(val(k))}
                            onChange={(e) => setDraft((x) => ({ ...x, [k]: e.target.checked }))}
                            className="h-4 w-4 rounded border-line"
                          />
                          {Boolean(val(k)) ? "Enabled" : "Disabled"}
                        </label>
                      ) : meta.kind === "enum" ? (
                        <select
                          value={String(val(k))}
                          onChange={(e) => setDraft((x) => ({ ...x, [k]: e.target.value }))}
                          className="h-8 w-full rounded-lg border border-line bg-panel px-2 text-sm"
                        >
                          {d.wait_until_choices.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      ) : (
                        <input
                          type="number"
                          value={String(val(k) ?? "")}
                          min={meta.min ?? undefined}
                          max={meta.max ?? undefined}
                          step={meta.kind === "float" ? 0.1 : 1}
                          onChange={(e) => setDraft((x) => ({ ...x, [k]: e.target.value }))}
                          className={clsx("h-8 w-full rounded-lg border bg-panel px-2 text-sm", changed ? "border-ocean" : "border-line")}
                        />
                      )}
                    </div>
                    <div className="mt-1 text-[10px] text-muted">
                      default {String(meta.default)}
                      {meta.min != null ? ` · ${meta.min}–${meta.max}` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

// Global productivity rates (links per hour, per link type) — the workspace-wide
// default that per-user overrides (in the Tasks desk) beat. Lives in Settings so
// the baseline lives with the other global config.
function ProductivityCard({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  type Prod = { global: Array<{ link_type_name: string; links_per_hour: number }>; overrides: Array<{ user_label: string; link_type_name: string; links_per_hour: number }> };
  const q = useQuery({
    queryKey: ["productivity", token],
    enabled: Boolean(token),
    queryFn: () => api<Prod>("/workforce/productivity", { token })
  });
  const save = useMutation({
    mutationFn: (p: { link_type_name: string; links_per_hour: number }) =>
      api<{ message: string }>("/workforce/productivity", { token, method: "PUT", body: JSON.stringify(p) }),
    onSuccess: () => { onNotice("Global rate saved"); queryClient.invalidateQueries({ queryKey: ["productivity"] }); },
    onError: (e: Error) => onNotice(e.message)
  });
  const rows = q.data?.global || [];
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="flex items-center gap-2 border-b border-line p-4">
        <h3 className="text-sm font-semibold text-ink">Productivity — links per hour (global)</h3>
        <HelpTip text="The workspace default rate for each link type, used to turn planned hours into an expected-links target. A person's own rate (set in the Tasks desk) beats this. Edit a value and click away to save." />
      </div>
      {q.isLoading ? (
        <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
      ) : !rows.length ? (
        <Empty label="No link types yet — add link types first (Settings → Link types)." />
      ) : (
        <div className="divide-y divide-line">
          {rows.map((g) => (
            <div key={g.link_type_name} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
              <span className="font-medium text-ink">{linkTypeLabel(g.link_type_name)}</span>
              <span className="flex items-center gap-2">
                <input
                  type="number" min={0.1} step={0.5} defaultValue={g.links_per_hour}
                  onBlur={(e) => { const v = Number(e.target.value); if (v > 0 && v !== g.links_per_hour) save.mutate({ link_type_name: g.link_type_name, links_per_hour: v }); }}
                  className="h-8 w-24 rounded-lg border border-line bg-panel px-2 text-right text-sm"
                />
                <span className="text-xs text-muted">/hour</span>
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="px-4 py-2 text-[11px] text-muted">Per-person overrides live in the Tasks desk (they win over these).</p>
    </section>
  );
}

function SettingsDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [newDomain, setNewDomain] = useState("");

  const settings = useQuery({
    queryKey: ["project-settings", token, projectId],
    enabled: Boolean(token && projectId),
    queryFn: () => api<ProjectSettings>(`/projects/${projectId}/settings`, { token })
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["project-settings", token, projectId] });

  const addDomain = useMutation({
    mutationFn: () =>
      api<ProjectSettings>(`/projects/${projectId}/domains`, {
        token,
        method: "POST",
        body: JSON.stringify({ domain: newDomain.trim() })
      }),
    onSuccess: () => {
      setNewDomain("");
      onNotice("Main domain added");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const removeDomain = useMutation({
    mutationFn: (id: string) =>
      api<ProjectSettings>(`/projects/${projectId}/domains/${id}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Main domain removed");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const setPrimary = useMutation({
    mutationFn: (id: string) =>
      api<ProjectSettings>(`/projects/${projectId}/domains/${id}/primary`, {
        token,
        method: "POST"
      }),
    onSuccess: () => {
      onNotice("Primary domain updated");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const saveSettings = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api<ProjectSettings>(`/projects/${projectId}/settings`, {
        token,
        method: "PUT",
        body: JSON.stringify(patch)
      }),
    onSuccess: () => {
      onNotice("Settings saved");
      invalidate();
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const projectsForName = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });
  const deleteProject = useMutation({
    mutationFn: async (typedName: string) => {
      const current = (projectsForName.data || []).find((p) => p.id === projectId);
      if (!current) throw new Error("Project not found.");
      if (typedName.toLowerCase() !== current.name.trim().toLowerCase()) {
        throw new Error("The name you typed doesn't match — nothing was deleted.");
      }
      return api<{ message: string }>(`/projects/${projectId}`, { token, method: "DELETE" });
    },
    onSuccess: () => {
      onNotice("Project deleted.");
      try {
        localStorage.setItem("ls_project", "");
        localStorage.setItem("ls_tab", "overview");
      } catch {
        /* ignore */
      }
      window.location.href = `${window.location.pathname}?tab=overview`;
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const s = settings.data;
  return (
    <section className="space-y-5">
      <BrandingCard token={token} projectId={projectId} onNotice={onNotice} />
      <LinkTypesCard token={token} onNotice={onNotice} />
      <ProductivityCard token={token} onNotice={onNotice} />
      <QaSettingsCard token={token} onNotice={onNotice} />
      {!projectId ? (
        <div className="rounded-xl border border-line bg-panel shadow-card">
          <Empty label="Select a project (top‑left) to manage its main domains and QA policy." />
        </div>
      ) : (
      <section className="grid gap-5 xl:grid-cols-2">
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Main domains" />
        <div className="space-y-3 p-4">
          <p className="text-xs text-muted">
            The website(s) this project builds links to. The <strong>primary</strong> domain is the
            project&apos;s target for QA, reports and analytics.
          </p>
          <div className="divide-y divide-line rounded-md border border-line">
            {(s?.domains || []).map((d) => (
              <div key={d.id} className="flex items-center justify-between gap-2 p-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Star
                    className={clsx("h-4 w-4 shrink-0", d.is_primary ? "text-ember" : "text-muted/40")}
                    aria-hidden
                  />
                  <span className="truncate font-medium text-ink">{d.domain}</span>
                  {d.is_primary ? (
                    <span className="rounded border border-ember/30 bg-ember/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ember">
                      Primary
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {!d.is_primary ? (
                    <button
                      onClick={() => setPrimary.mutate(d.id)}
                      className="rounded border border-line bg-panel px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
                    >
                      Set primary
                    </button>
                  ) : null}
                  <button
                    onClick={() => removeDomain.mutate(d.id)}
                    aria-label="Remove domain"
                    className="grid h-7 w-7 place-items-center rounded border border-line bg-panel text-muted transition hover:bg-field hover:text-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
            {s && !s.domains.length ? (
              <Empty label="No main domain yet — add one below." />
            ) : null}
          </div>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (newDomain.trim()) addDomain.mutate();
            }}
          >
            <input
              className="h-10 flex-1 rounded-md border border-line bg-panel px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
              placeholder="example.com"
              value={newDomain}
              onChange={(event) => setNewDomain(event.target.value)}
            />
            <button className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
              {addDomain.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Add
            </button>
          </form>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="QA policy" />
        <div className="space-y-4 p-4">
          <label className="flex items-center justify-between gap-3">
            <span className="text-sm text-ink">Treat sponsored / UGC links as dofollow</span>
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={Boolean(s?.treat_sponsored_as_follow)}
              disabled={!s || saveSettings.isPending}
              onChange={(event) =>
                saveSettings.mutate({ treat_sponsored_as_follow: event.target.checked })
              }
            />
          </label>
          <label className="flex items-center justify-between gap-3">
            <span className="text-sm text-ink">Expect pages to be indexable</span>
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={Boolean(s?.index_expected)}
              disabled={!s || saveSettings.isPending}
              onChange={(event) => saveSettings.mutate({ index_expected: event.target.checked })}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">
              Scoring profile
            </span>
            <select
              className="h-10 w-full rounded-md border border-line bg-panel px-3 text-sm"
              value={s?.scoring_profile || "inherit_global"}
              disabled={!s || saveSettings.isPending}
              onChange={(event) => saveSettings.mutate({ scoring_profile: event.target.value })}
            >
              <option value="inherit_global">Inherit global scoring</option>
              <option value="custom">Custom (per‑project scoring)</option>
            </select>
          </label>
          <p className="text-xs text-muted">
            Per‑parameter scoring weights live in <strong>Global Settings → Scoring</strong> and can
            be overridden per project there.
          </p>
        </div>
      </section>

      <section className="rounded-xl border border-danger/30 bg-danger/5">
        <SectionTitle title="Danger zone" />
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="max-w-md text-sm text-muted">
            Deleting this project removes <strong className="text-ink">all of its backlinks,
            imports, sheets, competitor data and tasks</strong>. Past runs stay in Batches for
            audit. This cannot be undone.
          </p>
          <button
            onClick={() => {
              const name = window.prompt(
                "This permanently deletes the project and all its data.\nType the project name to confirm:"
              );
              if (name === null) return;
              deleteProject.mutate(name.trim());
            }}
            disabled={deleteProject.isPending}
            className="flex h-10 items-center gap-2 rounded-lg bg-danger px-4 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {deleteProject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Delete project
          </button>
        </div>
      </section>
      </section>
      )}
    </section>
  );
}

function ConflictsDesk({
  token,
  onNotice
}: {
  token: string | null;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  // ── Filters (whitelisted; all drive the list query) ──
  const [scopeF, setScopeF] = useState<string[]>([]);
  const [statusF, setStatusF] = useState<string[]>(["open"]);
  const [minMembers, setMinMembers] = useState<string>("");
  const [minSim, setMinSim] = useState<string>("");
  const [targetDomains, setTargetDomains] = useState<string[]>([]);
  const [sourcePages, setSourcePages] = useState<string[]>([]);
  const [userF, setUserF] = useState<string[]>([]);
  const [search, setSearch] = useState<string>("");
  // Date filter = the backlink's real creation (placement) date, not detection/import.
  const [createdFrom, setCreatedFrom] = useState<string>("");
  const [createdTo, setCreatedTo] = useState<string>("");
  // Comparison view + bulk selection.
  const [openId, setOpenId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [gran, setGran] = useState("week");
  const _cwDays =
    createdFrom && createdTo
      ? Math.max(1, Math.round((Date.parse(createdTo) - Date.parse(createdFrom)) / 86400000))
      : 365;
  const allowDay = _cwDays <= 180;
  const effGran = gran === "day" && !allowDay ? "week" : gran;

  const query = useMemo(() => {
    const p = new URLSearchParams();
    scopeF.forEach((v) => p.append("scope", v));
    statusF.forEach((v) => p.append("status", v));
    if (minMembers.trim()) p.set("min_members", minMembers.trim());
    if (minSim.trim()) p.set("min_similarity", minSim.trim());
    if (targetDomains.length) p.set("target_domain", targetDomains.join(","));
    if (sourcePages.length) p.set("source_page", sourcePages.join(","));
    if (userF.length) p.set("user", userF.join(","));
    if (search.trim()) p.set("search", search.trim());
    if (createdFrom) p.set("created_from", createdFrom);
    if (createdTo) p.set("created_to", createdTo);
    p.set("limit", "200");
    return p.toString();
  }, [scopeF, statusF, minMembers, minSim, targetDomains, sourcePages, userF, search, createdFrom, createdTo]);

  const summary = useQuery({
    queryKey: ["conflict-summary", token, createdFrom, createdTo, effGran],
    enabled: Boolean(token),
    queryFn: () => {
      // Date range drives the KPI cards + weekly chart too (not just the list).
      const p = new URLSearchParams({ granularity: effGran });
      if (createdFrom) p.set("created_from", createdFrom);
      if (createdTo) p.set("created_to", createdTo);
      return api<ConflictSummary>(`/conflicts/summary?${p.toString()}`, { token });
    }
  });
  const conflictsRaw = useQuery({
    queryKey: ["conflicts", token, query],
    enabled: Boolean(token),
    queryFn: () =>
      api<{ items?: ConflictGroup[]; list?: ConflictGroup[]; total: number }>(
        `/conflicts?${query}`,
        { token }
      )
  });
  const groups = conflictsRaw.data?.items || conflictsRaw.data?.list || [];

  // ── Selectable filter options ──
  // Users: authoritative workspace roster (incl. laid-off with real work), so the
  // User filter is populated even before any group is expanded.
  const people = useQuery({
    queryKey: ["conflict-people", token],
    enabled: Boolean(token),
    queryFn: () => api<Array<{ user_label: string; active: boolean }>>("/workforce/people", { token })
  });
  const userOpts = useMemo(
    () => (people.data || []).map((p) => ({ value: p.user_label, label: p.active ? p.user_label : `${p.user_label} (laid off)` })),
    [people.data]
  );
  // Target domain + source page: distinct values from the loaded groups' members
  // (allowCustom stays on, so anything not on-page can still be typed).
  const { targetDomainOpts, sourcePageOpts } = useMemo(() => {
    const td = new Set<string>();
    const sp = new Set<string>();
    for (const g of groups) {
      for (const m of g.members || []) {
        const d = (m.target_domain || m.target_url || "").trim();
        if (d) td.add(d);
        const s = (m.source_page_url || "").trim();
        if (s) sp.add(s);
      }
    }
    const mk = (set: Set<string>) =>
      [...set].sort((a, b) => a.localeCompare(b)).map((v) => ({ value: v, label: v }));
    return { targetDomainOpts: mk(td), sourcePageOpts: mk(sp) };
  }, [groups]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["conflicts"] });
    queryClient.invalidateQueries({ queryKey: ["conflict-summary"] });
    queryClient.invalidateQueries({ queryKey: ["conflict-detail"] });
  };
  const rebuild = useMutation({
    mutationFn: () => api<ConflictSummary>("/conflicts/rebuild", { method: "POST", token }),
    onSuccess: (s) => {
      onNotice(`Duplicate scan complete — ${s.total} group(s) found`);
      refresh();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const resolve = useMutation({
    mutationFn: (v: { id: string; status: string }) =>
      api<ConflictSummary>(`/conflicts/${v.id}/resolve`, {
        method: "POST",
        token,
        body: JSON.stringify({ resolution_status: v.status })
      }),
    onSuccess: () => {
      onNotice("Conflict updated");
      refresh();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const bulk = useMutation({
    mutationFn: (v: { ids: string[]; action: string }) =>
      api<{ updated: number }>("/conflicts/bulk", {
        method: "POST",
        token,
        body: JSON.stringify({ conflict_ids: v.ids, action: v.action })
      }),
    onSuccess: (r, v) => {
      onNotice(`${v.action} applied to ${r.updated} group(s)`);
      setSelected([]);
      refresh();
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const toggleSel = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  const allSelected = groups.length > 0 && selected.length === groups.length;

  const s = summary.data;
  const scopeOpts = [
    { value: "same_project", label: "Same project" },
    { value: "cross_project", label: "Across projects" },
    { value: "cross_user", label: "Across users" }
  ];
  const statusOpts = [
    { value: "open", label: "Open" },
    { value: "acknowledged", label: "Acknowledged" },
    { value: "resolved", label: "Resolved" },
    { value: "ignored", label: "Ignored" }
  ];

  return (
    <section className="space-y-4">
      <div>
        <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
          Duplicates
          <HelpTip text="Two or more records pointing at the same page. 'Same project' = the page appears twice in one project (remove the extras). 'Across projects' or 'Across users' = coordinate so you don't pay twice for the same placement. Open a group to compare the records field-by-field and keep the best one." />
        </h2>
        <p className="text-sm text-muted">Every group shows why it's a duplicate, how similar the records are, and where the original lives.</p>
      </div>

      {/* ── KPI row ── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Metric label="Duplicate groups" value={s?.total ?? 0} icon={Layers} tone="ink"
          help="Each group = one page URL that appears in more than one record." />
        <Metric label="Open" value={s?.open ?? 0} icon={AlertTriangle} tone="ember"
          help="Groups nobody has dealt with yet — review these first." />
        <Metric label="Resolved" value={s?.resolved ?? 0} icon={CheckCircle2} tone="ocean"
          help="Groups someone reviewed and closed." />
        <Metric label="Duplicate links" value={s?.total_duplicate_links ?? 0} icon={Copy} tone="plum"
          help="Total redundant records = sum of (records in group − 1). Remove these to de-duplicate." />
        <Metric label="Avg similarity" value={s?.avg_similarity != null ? `${Math.round(s.avg_similarity)}%` : "—"} icon={Gauge} tone="ink"
          help="Average how alike the records inside each group are. 100% = identical rows." />
      </div>

      {(s?.weekly || []).length ? (
        <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
          <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
              New duplicate groups per week
            </span>
            <span className="text-[11px] text-muted">
              by link creation date ·{" "}
              {createdFrom || createdTo
                ? `${createdFrom ? fmtChartLabel(createdFrom, true) : "start"} → ${createdTo ? fmtChartLabel(createdTo, true) : "now"}`
                : "last 12 months"}
            </span>
            <GranularityToggle value={gran} onChange={setGran} allowDay={allowDay} />
          </div>
          <TrendChart
            height={130}
            labels={(s?.weekly || []).map((w) => w.week)}
            labelFmt={(w) => bucketLabel(w, effGran)}
            tickFmt={(w) => bucketTick(w, effGran)}
            onPointClick={(i) => {
              const w = (s?.weekly || [])[i]?.week;
              if (!w) return;
              const r = bucketRange(w, effGran);
              setCreatedFrom(r.from);
              setCreatedTo(r.to);
            }}
            series={[
              { name: "New duplicate groups", cssVar: "--ember", values: (s?.weekly || []).map((w) => w.new_groups) }
            ]}
          />
        </section>
      ) : null}

      {/* ── Filter bar ── */}
      <section className="rounded-xl border border-line bg-panel p-3 shadow-card">
        <div className="flex flex-wrap items-center gap-2">
          <FilterMultiSelect label="Scope" options={scopeOpts} selected={scopeF} onChange={setScopeF} />
          <FilterMultiSelect label="Status" options={statusOpts} selected={statusF} onChange={setStatusF} />
          <input
            type="number"
            min={2}
            value={minMembers}
            onChange={(e) => setMinMembers(e.target.value)}
            placeholder="Min records"
            className="h-9 w-28 rounded-lg border border-line bg-panel px-2.5 text-sm focus:border-ocean focus:outline-none"
          />
          <input
            type="number"
            min={0}
            max={100}
            value={minSim}
            onChange={(e) => setMinSim(e.target.value)}
            placeholder="Min sim %"
            className="h-9 w-28 rounded-lg border border-line bg-panel px-2.5 text-sm focus:border-ocean focus:outline-none"
          />
          <FilterMultiSelect label="Target domain" options={targetDomainOpts} selected={targetDomains} onChange={setTargetDomains} allowCustom />
          <FilterMultiSelect label="Source page" options={sourcePageOpts} selected={sourcePages} onChange={setSourcePages} allowCustom />
          <FilterMultiSelect label="User" options={userOpts} selected={userF} onChange={setUserF} allowCustom />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search canonical URL"
            className="h-9 w-52 rounded-lg border border-line bg-panel px-2.5 text-sm focus:border-ocean focus:outline-none"
          />
          <label className="flex items-center gap-1 text-xs text-muted" title="Filter by the backlink's real creation (placement) date">
            Created from
            <input type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)}
              className="h-9 rounded-lg border border-line bg-panel px-2 text-sm focus:border-ocean focus:outline-none" />
          </label>
          <label className="flex items-center gap-1 text-xs text-muted">
            To
            <input type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)}
              className="h-9 rounded-lg border border-line bg-panel px-2 text-sm focus:border-ocean focus:outline-none" />
          </label>
          {(scopeF.length || statusF.join() !== "open" || minMembers || minSim || targetDomains.length || sourcePages.length || userF.length || search || createdFrom || createdTo) ? (
            <button
              onClick={() => {
                setScopeF([]); setStatusF(["open"]); setMinMembers(""); setMinSim("");
                setTargetDomains([]); setSourcePages([]); setUserF([]); setSearch(""); setCreatedFrom(""); setCreatedTo("");
              }}
              className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-muted transition hover:text-ink"
            >
              Reset
            </button>
          ) : null}
        </div>
      </section>

      {/* ── Group list ── */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs font-medium text-muted">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() => setSelected(allSelected ? [] : groups.map((g) => g.id))}
                className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
              />
              {selected.length ? `${selected.length} selected` : "Select all"}
            </label>
            <span className="text-xs text-muted">{groups.length} group(s)</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {selected.length ? (
              <div className="flex items-center gap-1">
                {(["resolve", "acknowledge", "ignore", "reopen"] as const).map((a) => (
                  <button
                    key={a}
                    onClick={() => {
                      if ((a === "ignore" || a === "resolve") && !window.confirm(`${a === "ignore" ? "Ignore" : "Resolve"} ${selected.length} group(s)?`)) return;
                      bulk.mutate({ ids: selected, action: a });
                    }}
                    className="h-8 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field"
                  >
                    {a[0].toUpperCase() + a.slice(1)}
                  </button>
                ))}
              </div>
            ) : null}
            <ExportButton
              disabled={!groups.length}
              onClick={() =>
                downloadCsv(
                  "duplicate-groups.csv",
                  ["Page URL", "Scope", "Reason", "Similarity", "Records", "Status", "First found"],
                  groups.map((g) => [
                    g.canonical_url, g.scope, g.reason || "",
                    g.similarity != null ? `${g.similarity}%` : "",
                    g.member_count, g.resolution_status, g.detected_at || g.created_at
                  ])
                )
              }
            />
            <button
              onClick={() => rebuild.mutate()}
              className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              {rebuild.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Rebuild
            </button>
          </div>
        </div>
        <div className="divide-y divide-line">
          {groups.map((g) => (
            <ConflictRow
              key={g.id}
              conflict={g}
              selected={selected.includes(g.id)}
              onToggleSelect={() => toggleSel(g.id)}
              onOpen={() => setOpenId(g.id)}
            />
          ))}
          {!conflictsRaw.isLoading && !groups.length ? (
            <Empty label="No duplicate groups match these filters." />
          ) : null}
        </div>
      </section>

      {openId ? (
        <ConflictComparisonModal
          conflictId={openId}
          token={token}
          onClose={() => setOpenId(null)}
          onNotice={onNotice}
          onChanged={refresh}
        />
      ) : null}
    </section>
  );
}

const CONFLICT_SCOPE_LABEL: Record<string, string> = {
  same_project: "Same project",
  cross_project: "Across projects",
  cross_user: "Across users"
};

function ScopeChip({ scope }: { scope: string }) {
  const tone =
    scope === "cross_project"
      ? "border-plum/30 bg-plum/10 text-plum"
      : scope === "cross_user"
        ? "border-ember/30 bg-ember/10 text-ember"
        : "border-line bg-field text-muted";
  return (
    <span className={clsx("rounded border px-2 py-0.5 text-[11px] font-semibold", tone)}>
      {CONFLICT_SCOPE_LABEL[scope] || scope.replaceAll("_", " ")}
    </span>
  );
}

// Similarity meter — how alike the records in a group are (0-100).
function SimilarityMeter({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-xs text-muted">—</span>;
  const v = Math.max(0, Math.min(100, value));
  const cssVar = v >= 90 ? "--danger" : v >= 60 ? "--ember" : "--ocean";
  return (
    <span className="inline-flex items-center gap-1.5" title={`${v}% similar`}>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-field">
        <span className="block h-full rounded-full" style={{ width: `${v}%`, background: `rgb(var(${cssVar}))` }} />
      </span>
      <span className="text-[11px] font-semibold text-ink">{v}%</span>
    </span>
  );
}

function ConflictRow({
  conflict,
  selected,
  onToggleSelect,
  onOpen
}: {
  conflict: ConflictGroup;
  selected: boolean;
  onToggleSelect: () => void;
  onOpen: () => void;
}) {
  // Distinct users behind this group (drives the "Across users" scope + the User filter).
  const users = Array.from(
    new Set((conflict.members || []).map((m) => (m.assigned_user_label || "").trim()).filter(Boolean))
  );
  const targetDomains = Array.from(
    new Set((conflict.members || []).map((m) => (m.target_domain || "").trim()).filter(Boolean))
  );
  return (
    <div className={clsx("flex items-center gap-3 p-4 transition hover:bg-field/40", selected && "bg-ocean/5")}>
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggleSelect}
        onClick={(e) => e.stopPropagation()}
        className="h-4 w-4 shrink-0 accent-[rgb(var(--ocean))]"
      />
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <GitCompare className="h-4 w-4 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium text-ink">
            {conflict.canonical_url || "(unknown URL)"}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="rounded border border-line bg-field px-2 py-0.5 font-semibold">
              {conflict.member_count} records
            </span>
            <ScopeChip scope={conflict.scope} />
            {users.length ? (
              <span
                className="flex items-center gap-1 rounded-full bg-ocean/10 px-2 py-0.5 font-medium text-ocean"
                title={`Users: ${users.join(", ")}`}
              >
                <Users className="h-3 w-3" />
                {users.length === 1 ? users[0] : `${users[0]} +${users.length - 1}`}
              </span>
            ) : null}
            {targetDomains.length === 1 ? (
              <span className="rounded-full bg-plum/10 px-2 py-0.5 font-medium text-plum" title={`Target: ${targetDomains[0]}`}>
                {targetDomains[0]}
              </span>
            ) : null}
            {conflict.reason ? <span className="italic">{conflict.reason}</span> : null}
          </div>
        </div>
        <div className="hidden shrink-0 sm:block">
          <SimilarityMeter value={conflict.similarity} />
        </div>
        <span className="hidden shrink-0 text-xs text-muted md:block">
          {formatDate(conflict.detected_at || conflict.created_at)}
        </span>
        <div className="shrink-0">
          <Status value={conflict.resolution_status} />
        </div>
        <ChevronRight className="h-4 w-4 shrink-0 text-muted" />
      </button>
    </div>
  );
}

// ── Comparison view: side-by-side field matrix + per-group actions ──
function ConflictComparisonModal({
  conflictId,
  token,
  onClose,
  onNotice,
  onChanged
}: {
  conflictId: string;
  token: string | null;
  onClose: () => void;
  onNotice: (text: string) => void;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const [reassignTo, setReassignTo] = useState("");
  const [diffOnly, setDiffOnly] = useState(false);

  const detail = useQuery({
    queryKey: ["conflict-detail", token, conflictId],
    enabled: Boolean(token),
    queryFn: () => api<ConflictDetail>(`/conflicts/${conflictId}`, { token })
  });
  const labels = useQuery({
    queryKey: ["workforce-labels", token],
    enabled: Boolean(token),
    queryFn: () => api<string[]>("/workforce/labels", { token })
  });

  const afterAction = (msg: string) => {
    onNotice(msg);
    queryClient.invalidateQueries({ queryKey: ["conflict-detail", token, conflictId] });
    onChanged();
  };

  const keepOne = useMutation({
    mutationFn: (backlinkId: string) =>
      api<{ deleted_count: number }>(`/conflicts/${conflictId}/keep-one`, {
        method: "POST",
        token,
        body: JSON.stringify({ keep_backlink_id: backlinkId })
      }),
    onSuccess: (r) => {
      afterAction(`Kept one record, removed ${r.deleted_count} duplicate(s)`);
      onClose();
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const reassign = useMutation({
    mutationFn: (label: string) =>
      api<{ changed: number; to_user_label: string }>(`/conflicts/${conflictId}/reassign`, {
        method: "POST",
        token,
        body: JSON.stringify({ to_user_label: label })
      }),
    onSuccess: (r) => afterAction(`Reassigned ${r.changed} record(s) to ${r.to_user_label}`),
    onError: (e: Error) => onNotice(e.message)
  });
  const resolve = useMutation({
    mutationFn: (status: string) =>
      api<ConflictSummary>(`/conflicts/${conflictId}/resolve`, {
        method: "POST",
        token,
        body: JSON.stringify({ resolution_status: status })
      }),
    onSuccess: (_r, status) => afterAction(`Group marked ${status}`),
    onError: (e: Error) => onNotice(e.message)
  });

  const d = detail.data;
  // Show every returned record (the API already caps huge groups); the table
  // scrolls horizontally rather than hiding columns.
  const members = d?.members || [];
  const extraMembers = (d?.total_members || d?.member_count || 0) - members.length;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 backdrop-blur-sm">
      <div className="relative my-6 w-full max-w-6xl rounded-2xl border border-line bg-panel shadow-pop">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-base font-semibold text-ink">
              <GitCompare className="h-4 w-4 text-ocean" /> Compare duplicate records
            </h2>
            <div className="mt-1 truncate text-sm text-muted" title={d?.canonical_url || ""}>
              {d?.canonical_url || "(unknown URL)"}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              {d ? <ScopeChip scope={d.scope} /> : null}
              {d ? <SimilarityMeter value={d.similarity} /> : null}
              {d?.reason ? <span className="italic text-muted">{d.reason}</span> : null}
              {d ? <Status value={d.resolution_status} /> : null}
            </div>
          </div>
          <button onClick={onClose} className="shrink-0 rounded-lg border border-line p-1.5 text-muted transition hover:text-ink">
            <X className="h-4 w-4" />
          </button>
        </div>

        {detail.isLoading ? (
          <div className="p-10 text-center text-sm text-muted">Loading comparison…</div>
        ) : !d ? (
          <div className="p-10"><Empty label="Could not load this group." /></div>
        ) : (
          <div className="space-y-4 p-5">
            {/* Group-level actions */}
            <div className="flex flex-wrap items-center gap-2">
              <ExportButton
                onClick={() =>
                  downloadCsv(
                    `conflict-${conflictId}-members.csv`,
                    ["Backlink", "Project", "User", "Target", "Anchor", "Rel", "Status", "Index", "Score", "Placed", "Created"],
                    members.map((m) => [
                      m.source_page_url, m.project_name, m.assigned_user_label, m.target_url,
                      m.current_anchor_text, m.current_rel, m.status, m.index_status, m.score,
                      m.placement_date, m.created_at
                    ])
                  )
                }
              />
              <div className="flex items-center gap-1.5">
                <SearchSelect
                  value={reassignTo}
                  onChange={setReassignTo}
                  options={(labels.data || []).map((l) => ({ value: l }))}
                  placeholder="Reassign all to…"
                  allowCustom
                  width="w-52"
                />
                <button
                  disabled={!reassignTo || reassign.isPending}
                  onClick={() => {
                    if (!window.confirm(`Reassign every record in this group to "${reassignTo}"?`)) return;
                    reassign.mutate(reassignTo);
                  }}
                  className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
                >
                  Reassign
                </button>
              </div>
              <div className="ml-auto flex items-center gap-1.5">
                {d.resolution_status !== "acknowledged" ? (
                  <button onClick={() => resolve.mutate("acknowledged")}
                    className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field">
                    Acknowledge
                  </button>
                ) : null}
                {d.resolution_status !== "ignored" ? (
                  <button onClick={() => { if (window.confirm("Ignore this group?")) resolve.mutate("ignored"); }}
                    className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-muted transition hover:bg-field">
                    Ignore
                  </button>
                ) : null}
                {d.resolution_status !== "resolved" ? (
                  <button onClick={() => resolve.mutate("resolved")}
                    className="h-9 rounded-lg bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
                    Resolve
                  </button>
                ) : (
                  <button onClick={() => resolve.mutate("open")}
                    className="h-9 rounded-lg border border-line px-2.5 text-xs font-medium text-muted transition hover:bg-field">
                    Reopen
                  </button>
                )}
              </div>
            </div>

            {/* Side-by-side comparison: one column per member, one row per field.
                Fields where the records disagree are highlighted; each cell that
                differs from the suggested-keep record gets a stronger tint. */}
            {(() => {
              const rows = d.field_matrix || [];
              const diffCount = rows.filter((r) => !r.all_same).length;
              const shownRows = diffOnly ? rows.filter((r) => !r.all_same) : rows;
              const keepIdx = Math.max(0, members.findIndex((m) => m.backlink_id === d.suggested_keep));
              const cellOf = (row: ConflictFieldMatrixRow, i: number) => (row.cells || row.values || [])[i];
              return (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-muted">
                      {members.length} record{members.length === 1 ? "" : "s"} ·{" "}
                      <span className={diffCount ? "font-semibold text-ember" : "text-muted"}>
                        {diffCount} field{diffCount === 1 ? "" : "s"} differ
                      </span>
                    </span>
                    <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-muted">
                      <input type="checkbox" checked={diffOnly} onChange={(e) => setDiffOnly(e.target.checked)}
                        className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]" />
                      Show differences only
                    </label>
                    <span className="inline-flex items-center gap-1 text-muted">
                      <span className="inline-block h-2.5 w-2.5 rounded-sm bg-ember/25" /> differs from ★ keep
                    </span>
                  </div>
                  <div className="overflow-x-auto rounded-xl border border-line">
                    <table className="min-w-full text-sm">
                      <thead>
                        <tr className="border-b border-line bg-field">
                          <th className="sticky left-0 z-10 bg-field px-3 py-2 text-left text-xs font-semibold uppercase text-muted">Field</th>
                          {members.map((m, mi) => (
                            <th key={m.backlink_id}
                              className={clsx("min-w-[160px] px-3 py-2 text-left align-top", d.suggested_keep === m.backlink_id && "bg-ember/10")}>
                              <div className="flex items-center gap-1.5">
                                {d.suggested_keep === m.backlink_id ? (
                                  <span title="Suggested keep — the best record to retain">
                                    <Star className="h-3.5 w-3.5 fill-ember text-ember" />
                                  </span>
                                ) : null}
                                <span className="text-xs font-semibold text-ink">Record {mi + 1}</span>
                                {d.suggested_keep === m.backlink_id ? (
                                  <span className="rounded-full bg-ember/15 px-1.5 text-[10px] font-semibold text-ember">keep</span>
                                ) : null}
                              </div>
                              {/* Distinguishing sub-line so identical-user columns are tellable apart. */}
                              <div className="mt-0.5 truncate text-[11px] text-muted" title={m.assigned_user_label || m.project_name || ""}>
                                {m.assigned_user_label || m.project_name || "—"}
                              </div>
                              <div className="text-[11px] text-muted tabular-nums">
                                {m.placement_date ? fmtChartLabel(String(m.placement_date), true) : "no date"}
                              </div>
                              <button
                                onClick={() => {
                                  if (!window.confirm(`Keep this record and DELETE the other ${members.length - 1} in this group? This cannot be undone.`)) return;
                                  keepOne.mutate(m.backlink_id);
                                }}
                                className="mt-1.5 flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-medium text-danger transition hover:bg-danger/10"
                              >
                                <Trash2 className="h-3 w-3" /> Keep this one
                              </button>
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {shownRows.map((row) => {
                          const keepVal = cellOf(row, keepIdx);
                          return (
                            <tr key={row.field} className="border-b border-line last:border-0">
                              <td className="sticky left-0 z-10 bg-panel px-3 py-2 text-xs font-medium text-muted">
                                <span className="flex items-center gap-1">
                                  {compareFieldLabel(row.field)}
                                  {!row.all_same ? <span className="text-[10px] font-semibold uppercase text-ember">differs</span> : null}
                                </span>
                              </td>
                              {members.map((m, i) => {
                                const val = cellOf(row, i);
                                const text = val == null || val === "" ? "—" : String(val);
                                const differs = !row.all_same && String(val ?? "") !== String(keepVal ?? "");
                                return (
                                  <td
                                    key={m.backlink_id}
                                    className={clsx(
                                      "px-3 py-2 align-top text-xs",
                                      differs ? "bg-ember/20 font-semibold text-ink" : row.all_same ? "text-muted" : "text-ink"
                                    )}
                                  >
                                    <span className="block max-w-[240px] truncate" title={text}>{text}</span>
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                        {!rows.length ? (
                          <tr><td colSpan={members.length + 1} className="p-4 text-center text-xs text-muted">No comparable fields.</td></tr>
                        ) : null}
                        {rows.length && !shownRows.length ? (
                          <tr><td colSpan={members.length + 1} className="p-4 text-center text-xs text-muted">All fields match across these records.</td></tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })()}
            {extraMembers > 0 ? (
              <p className="text-xs text-muted">+ {extraMembers} more record(s) in this very large group (not shown — export the group for the complete list).</p>
            ) : null}

            {/* Action history */}
            {(d.actions || []).length ? (
              <div className="rounded-xl border border-line bg-field/40 p-3">
                <SectionTitle title="Action history" flush />
                <ul className="mt-2 space-y-1 text-xs text-muted">
                  {(d.actions || []).map((a: ConflictAction) => (
                    <li key={a.id} className="flex items-center gap-2">
                      <span className="font-medium text-ink">{a.action.replaceAll("_", " ")}</span>
                      {a.note ? <span>· {a.note}</span> : null}
                      <span className="ml-auto">{formatDate(a.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  name,
  autoComplete
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  name?: string; // standard field name so browsers/password managers recognise it
  autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase text-muted">{label}</span>
      <input
        className="h-10 w-full rounded-xl border border-line bg-panel shadow-card px-3 text-sm shadow-sm transition focus:border-ocean focus:outline-none focus:ring-2 focus:ring-ocean/20"
        type={type}
        name={name}
        autoComplete={autoComplete}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function Metric({
  label,
  value,
  icon: Icon,
  tone,
  help,
  onClick,
  sub
}: {
  label: string;
  value: number | string;
  icon: typeof Gauge;
  tone: "ink" | "ocean" | "ember" | "danger" | "plum";
  help?: string;
  onClick?: () => void;
  sub?: string; // plain-words context line, e.g. "6% of total" or "Previous period: 0"
}) {
  const chip = {
    ink: "bg-field text-ink",
    ocean: "bg-ocean/10 text-ocean",
    ember: "bg-ember/10 text-ember",
    danger: "bg-danger/10 text-danger",
    plum: "bg-plum/10 text-plum"
  }[tone];
  return (
    <div
      onClick={onClick}
      title={onClick ? "Click to see these links" : undefined}
      className={clsx(
        "rounded-xl border border-line bg-panel p-3.5 shadow-card transition hover:shadow-soft",
        onClick && "cursor-pointer hover:border-ocean/50"
      )}
    >
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted">
          {label}
          {help ? <HelpTip text={help} /> : null}
        </span>
        <span className={clsx("grid h-8 w-8 place-items-center rounded-lg", chip)}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-1.5 text-3xl font-bold tracking-tight text-ink">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] font-medium text-muted">{sub}</div> : null}
    </div>
  );
}

// Compact clickable KPI stat box — a dense tile for the HTTP/index/quality/spam
// grids on Analytics + Overview. Tone drives the accent (danger for 404/broken/
// spam, ocean for 200/indexed/qualified, ember for redirects/duplicate).
function StatBox({
  label,
  value,
  tone,
  onClick,
  help
}: {
  label: string;
  value: number;
  tone: "ink" | "ocean" | "ember" | "danger" | "plum";
  onClick?: () => void;
  help?: string;
}) {
  const accent = {
    ink: "text-ink",
    ocean: "text-ocean",
    ember: "text-ember",
    danger: "text-danger",
    plum: "text-plum"
  }[tone];
  const ring = {
    ink: "hover:border-line",
    ocean: "hover:border-ocean/50",
    ember: "hover:border-ember/50",
    danger: "hover:border-danger/50",
    plum: "hover:border-plum/50"
  }[tone];
  return (
    <div
      onClick={onClick}
      title={help || (onClick ? "Click to filter to these links" : undefined)}
      className={clsx(
        "rounded-lg border border-line bg-panel px-3 py-2.5 text-center shadow-card transition",
        onClick ? clsx("cursor-pointer hover:shadow-soft", ring) : help && "cursor-help"
      )}
    >
      <div className={clsx("text-2xl font-bold leading-none tracking-tight", accent)}>{value}</div>
      <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</div>
    </div>
  );
}

function Issue({
  label,
  value,
  help,
  onClick
}: {
  label: string;
  value: number;
  help?: string;
  onClick?: () => void;
}) {
  return (
    <div
      title={help}
      onClick={onClick}
      className={clsx(
        "rounded-md border border-line bg-field p-3 transition",
        onClick ? "cursor-pointer hover:border-ocean/50 hover:bg-panel" : help && "cursor-help"
      )}
    >
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink">{value}</div>
    </div>
  );
}

// Plain-English explanations for the issue labels shown in lists.
const ISSUE_WORDS: Record<string, string> = {
  LINK_MISSING: "The backlink is no longer on the page.",
  LINK_NOFOLLOW: "The link is marked nofollow — it passes less SEO value.",
  LINK_SPONSORED: "The link sits in a sponsored/ad block.",
  LINK_UGC: "The link sits in a comments/user content area.",
  LINK_HIDDEN: "The link is hidden from visitors (CSS/comment/iframe).",
  SOURCE_404: "The page is gone (404/410).",
  SOURCE_403: "The website blocks automated visits (403).",
  SOURCE_5XX: "The website had a server error.",
  CAPTCHA_DETECTED: "The site shows a CAPTCHA to robots — open it yourself to confirm.",
  PAGE_NOINDEX: "The page tells Google not to index it.",
  X_ROBOTS_NOINDEX: "The server tells Google not to index the page.",
  ROBOTS_BLOCKED: "robots.txt blocks this page from crawlers.",
  WRONG_TARGET: "The page links to your domain, but not to the agreed URL.",
  ANCHOR_CHANGED: "The anchor text changed from what was agreed.",
  CANONICAL_MISMATCH: "The page declares a different page as the 'real' one.",
  CANONICAL_CROSS_DOMAIN: "The page's canonical points to another domain entirely.",
  SOFT_404: "The page looks like a 'not found' page even though it loads.",
  JS_RENDER_REQUIRED: "The link only appears after JavaScript runs — search engines may under-credit it.",
  HTTP_ERROR: "The page returned an HTTP error.",
  SSL_ERROR: "The site's HTTPS certificate has a problem.",
  DNS_ERROR: "The website's address could not be found.",
  TIMEOUT: "The website took too long to answer.",
  REDIRECT_CHAIN: "The page goes through several redirects before loading.",
  REDIRECT_LOOP: "The page redirects in a circle and never loads.",
  INDEXABILITY_UNKNOWN: "We couldn't tell whether the page can be indexed."
};

// Short, user-friendly display names for the ISSUE column (the raw enum like
// PAGE_NOINDEX read as "page noindex"). One consistent vocabulary everywhere.
const ISSUE_DISPLAY: Record<string, string> = {
  LINK_MISSING: "Link missing",
  LINK_FOUND: "Link found",
  LINK_NOFOLLOW: "Nofollow link",
  PAGE_NOFOLLOW: "Page nofollow",
  X_ROBOTS_NOFOLLOW: "Header nofollow",
  LINK_SPONSORED: "Sponsored link",
  LINK_UGC: "UGC link",
  LINK_HIDDEN: "Hidden link",
  SOURCE_404: "Page not found (404)",
  SOURCE_403: "Blocked (403)",
  SOURCE_5XX: "Server error (5xx)",
  CAPTCHA_DETECTED: "CAPTCHA / bot check",
  PAGE_NOINDEX: "Not indexable",
  X_ROBOTS_NOINDEX: "Not indexable",
  ROBOTS_BLOCKED: "Blocked by robots.txt",
  WRONG_TARGET: "Wrong target",
  ANCHOR_CHANGED: "Anchor changed",
  CANONICAL_MISMATCH: "Canonical mismatch",
  CANONICAL_CROSS_DOMAIN: "Canonical off-domain",
  SOFT_404: "Soft 404",
  JS_RENDER_REQUIRED: "Needs JavaScript",
  HTTP_ERROR: "HTTP error",
  SSL_ERROR: "SSL error",
  DNS_ERROR: "Address not found",
  TIMEOUT: "Timed out",
  REDIRECT_CHAIN: "Redirect chain",
  REDIRECT_LOOP: "Redirect loop",
  INDEXABILITY_UNKNOWN: "Index status unknown"
};
// Friendly label for any raw issue enum (used in the grid + drawer + reports).
function issueDisplay(label: string | null | undefined): string {
  if (!label) return "-";
  return ISSUE_DISPLAY[label] || label.replaceAll("_", " ").toLowerCase();
}

// Human labels for the duplicate compare grid's field rows.
const COMPARE_FIELD_LABELS: Record<string, string> = {
  source_page_url: "Source page",
  source_domain: "Source domain",
  target_url_normalized: "Target URL",
  target_domain: "Target domain",
  anchor: "Anchor text",
  rel: "Rel",
  link_type: "Link type",
  assigned_user_label: "User",
  project_id: "Project",
  status: "Status",
  score: "Score",
  index_status: "Index status",
  duplicate_status: "Duplicate status",
  placement_date: "Placement date (created)",
  created_at: "First seen",
  last_checked_at: "Last checked"
};
const compareFieldLabel = (f: string) => COMPARE_FIELD_LABELS[f] || f.replaceAll("_", " ");

function IssueWord({ label, count }: { label: string | null; count: number }) {
  if (!label) return <span>{count ? `${count} issues` : "-"}</span>;
  return (
    <span
      title={ISSUE_WORDS[label] || "Open the link for full details."}
      className="cursor-help whitespace-nowrap text-xs underline decoration-dotted decoration-line underline-offset-2"
    >
      {issueDisplay(label)}
    </span>
  );
}

function SectionTitle({ title, flush = false }: { title: string; flush?: boolean }) {
  return (
    <div className={clsx("border-b border-line", flush ? "pb-3" : "px-4 py-3")}>
      <h2 className="text-base font-semibold text-ink">{title}</h2>
    </div>
  );
}

function IconButton({ label, onClick, icon: Icon }: { label: string; onClick: () => void; icon: typeof RefreshCw }) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      className="grid h-8 w-8 place-items-center rounded-md border border-line bg-panel text-muted transition hover:bg-field hover:text-ink"
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

function Notice({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-ocean/30 bg-ocean/10 px-4 py-3 text-sm text-ink shadow-card">
      <span>{text}</span>
      <button onClick={onClose} className="rounded p-1 text-ocean hover:bg-ocean/10" aria-label="Dismiss">
        <XCircle className="h-4 w-4" />
      </button>
    </div>
  );
}

// Plain-English help for every status a non-technical user can meet.
// Each entry answers: what happened / what should you do next.
const STATUS_HELP: Record<string, { label?: string; what: string; next: string }> = {
  PASS: {
    label: "Qualified",
    what: "The link is live and everything we check looked good.",
    next: "Nothing to do."
  },
  WARNING: {
    label: "Needs improvement",
    what: "The link works, but something reduces its value (e.g. nofollow, weak page, redirects).",
    next: "Open the link to see which checks lowered the score."
  },
  FAIL: {
    label: "Not qualified",
    what: "A serious problem was found — the link is missing, the page is dead, or it can't be indexed.",
    next: "Open the link to see the exact reason, then fix or replace it."
  },
  UNKNOWN: {
    label: "Couldn't check",
    what: "We couldn't reach the page this time (timeout, rate limit, or a temporary API/server problem).",
    next: "It will NOT retry by itself (that would waste API quota) — use Recheck / “Retry failed” when ready."
  },
  waiting_api: {
    label: "Waiting for API",
    what: "The API quota (e.g. crawl proxy) ran out before this link could be checked, so QA paused instead of burning failed requests.",
    next: "Retry after the quota resets — “Retry failed” re-queues everything that's waiting."
  },
  api_failed: {
    label: "API failed",
    what: "The last QA try died on an external-API failure (limit, outage, timeout). The link keeps its previous status and won't auto-retry.",
    next: "Open the link to see exactly which API failed and why, then use Recheck to retry manually."
  },
  manual_retry: {
    label: "Manual retry",
    what: "QA for this link is paused until someone retries it by hand.",
    next: "Use Recheck when you want it checked again."
  },
  NEEDS_MANUAL_REVIEW: {
    label: "Needs review",
    what: "We couldn't decide automatically — usually bot protection or conflicting signals on the page.",
    next: "Open the page yourself and confirm; the reason is shown in the Issue column."
  },
  PENDING: {
    label: "QA pending",
    what: "This link hasn't been QA-checked yet.",
    next: "Use “Run QA check” in the Backlinks list to check it — checks don't start on their own."
  },
  indexed: { what: "Google shows this page in its index.", next: "Nothing to do." },
  not_indexed: { what: "Google does not show this page in its index.", next: "Low-value for SEO until indexed — consider requesting indexing or replacing." },
  uncertain: { label: "Index unclear", what: "The index check couldn't give a clear yes/no.", next: "Re-run the index check later." },
  unchecked: { what: "Index status hasn't been checked yet.", next: "Use “Check indexing”." },
  dup_same_project: { label: "Duplicate (same project)", what: "The same page URL appears more than once in this project.", next: "Keep one and remove the extras in the sheet." },
  dup_cross_project: { label: "Used by another project", what: "This page URL is already used by a different project.", next: "Check the Duplicates desk to see where the original lives." },
  dup_cross_user: { label: "Added by another user", what: "This page URL was already added by a different team member.", next: "Coordinate to avoid paying for the same placement twice." },
  duplicate: { what: "This link is a duplicate of another record.", next: "See the Duplicates desk for the full group." },
  unique: { what: "No other record uses this page URL.", next: "Nothing to do." },
  completed: { what: "This run finished successfully.", next: "Nothing to do." },
  partial: { what: "This run finished, but some rows failed.", next: "Open it to see the failed rows and why." },
  failed: { what: "This run stopped with an error.", next: "Open it to see the reason; fix and retry." },
  running: { what: "This run is still working.", next: "Progress updates live — no need to refresh." },
  pending: { what: "This run is queued and will start shortly.", next: "Nothing to do." }
};

// One-word pill labels for dense grids — the full wording + plain-English
// explanation stays in the hover tooltip.
const STATUS_SHORT: Record<string, string> = {
  PASS: "OK",
  WARNING: "Improve",
  FAIL: "Not OK",
  NEEDS_MANUAL_REVIEW: "Review",
  UNKNOWN: "Unclear",
  PENDING: "Pending"
};

// Live QA-run progress (Enterprise §9): floating panel that follows a running
// recheck batch in real time — never leaves the user wondering if QA is running.
function QaLiveProgress({
  token,
  batchId,
  onClose,
  onDone,
  onViewResults,
  onViewFailures
}: {
  token: string | null;
  batchId: string;
  onClose: () => void;
  onDone: () => void;
  onViewResults?: () => void;
  onViewFailures?: () => void;
}) {
  const [finishedNotified, setFinishedNotified] = useState(false);
  const batch = useQuery({
    queryKey: ["qa-live-batch", token, batchId],
    enabled: Boolean(token && batchId),
    refetchInterval: (q) => ((q.state.data as { status?: string } | undefined)?.status === "running" ? 2500 : false),
    queryFn: () =>
      api<{ id: string; seq: number; status: string; label: string | null; totals: Record<string, number>; counters: Record<string, number>; started_at: string; finished_at: string | null }>(
        `/batches/${batchId}`,
        { token }
      )
  });
  const b = batch.data;
  const total = Number(b?.totals?.total ?? 0);
  const done = Number(b?.counters?.processed ?? b?.counters?.done ?? 0);
  const ok = Number(b?.counters?.succeeded ?? b?.counters?.ok ?? 0);
  const failed = Number(b?.counters?.failed ?? 0);
  const running = b?.status === "running";
  const pct = total ? Math.min(100, Math.round((100 * done) / total)) : 0;
  const elapsedS = b?.started_at ? Math.max(1, Math.round((Date.now() - Date.parse(b.started_at)) / 1000)) : 0;
  const speed = elapsedS && done ? (done / elapsedS) : 0;
  const etaS = running && speed > 0 ? Math.round((total - done) / speed) : null;
  useEffect(() => {
    if (b && !running && !finishedNotified) {
      setFinishedNotified(true);
      onDone();
    }
  }, [b, running, finishedNotified, onDone]);
  return (
    <div className="fixed bottom-4 right-4 z-40 w-[340px] rounded-xl border border-line bg-panel p-4 shadow-pop">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink">
          {running ? <Loader2 className="h-4 w-4 animate-spin text-ocean" /> : <CheckCircle2 className="h-4 w-4 text-ocean" />}
          {running ? "QA check running…" : "QA check finished"}
        </span>
        <button onClick={onClose} className="text-muted hover:text-ink" aria-label="Dismiss">✕</button>
      </div>
      <p className="mt-0.5 truncate text-xs text-muted">{b?.label || `Batch #B-${b?.seq ?? ""}`}</p>
      <div className="mt-2 h-2 w-full overflow-hidden rounded bg-field">
        <div
          className={clsx("h-full rounded transition-all", running ? "bg-ocean" : failed ? "bg-ember" : "bg-ocean")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex items-center justify-between text-xs text-muted">
        <span><span className="font-semibold text-ink">{done.toLocaleString()}</span> / {total.toLocaleString()} checked ({pct}%)</span>
        {etaS != null ? <span>~{etaS >= 90 ? `${Math.round(etaS / 60)}m` : `${etaS}s`} left</span> : null}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-2 text-xs">
        <span className="rounded bg-ocean/10 px-1.5 py-0.5 font-semibold text-ocean">{ok.toLocaleString()} completed</span>
        {failed ? <span className="rounded bg-danger/10 px-1.5 py-0.5 font-semibold text-danger">{failed.toLocaleString()} failed</span> : null}
        {speed > 0 && running ? <span className="text-muted">{speed.toFixed(1)}/s</span> : null}
      </div>
      {!running && b ? (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-muted">
            Grid refreshed with the new verdicts. Full logs live in the Batches desk (#B-{b.seq}).
          </p>
          <div className="flex flex-wrap gap-2">
            {onViewResults ? (
              <button
                onClick={() => { onViewResults(); onClose(); }}
                className="rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-ink hover:bg-field"
              >
                Show freshly checked
              </button>
            ) : null}
            {failed > 0 && onViewFailures ? (
              <button
                onClick={() => { onViewFailures(); onClose(); }}
                className="rounded-lg border border-danger/40 px-2.5 py-1 text-xs font-medium text-danger hover:bg-danger/10"
              >
                Show problems ({failed})
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// QA wait badge (Enterprise §1/§4): why QA is intentionally paused for a link.
// Hovering explains the state; the "why isn't this checked?" answer at a glance.
function QaWaitBadge({ reason }: { reason: string }) {
  const meta =
    reason === "waiting_api"
      ? { label: "Waiting for API", cls: "bg-ember/10 text-ember border-ember/30", icon: "⏸" }
      : reason === "api_failed"
      ? { label: "API failed", cls: "bg-danger/10 text-danger border-danger/30", icon: "⚡" }
      : { label: "Manual retry", cls: "bg-field text-muted border-line", icon: "✋" };
  const help = STATUS_HELP[reason];
  return (
    <span
      title={help ? `${help.what}\n\nWhat to do: ${help.next}` : meta.label}
      className={clsx("inline-flex items-center gap-0.5 rounded border px-1 py-0.5 text-[10px] font-semibold", meta.cls)}
    >
      {meta.icon} {meta.label}
    </span>
  );
}

function Status({ value, reason, compact }: { value: string; reason?: string | null; compact?: boolean }) {
  const tone =
    value === "PASS" || value === "completed"
      ? "bg-ocean/10 text-ocean border-ocean/30"
      : value === "FAIL" || value === "failed"
        ? "bg-danger/10 text-danger border-danger/30"
        : value === "WARNING" || value === "partial" || value === "running"
          ? "bg-ember/10 text-ember border-ember/30"
          : value === "NEEDS_MANUAL_REVIEW"
            ? "bg-plum/10 text-plum border-plum/30"
            : "bg-field text-muted border-line";
  const help = STATUS_HELP[value];
  const label = compact
    ? STATUS_SHORT[value] || (help?.label || value).replaceAll("_", " ")
    : (help?.label || value).replaceAll("_", " ");
  return (
    <span className="group relative inline-flex">
      <span
        className={clsx(
          "inline-flex cursor-default whitespace-nowrap rounded-full border font-semibold",
          compact ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs",
          tone
        )}
      >
        {label}
      </span>
      {help ? (
        <span className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-72 rounded-lg border border-line bg-panel p-2.5 text-left shadow-pop group-hover:block">
          {compact ? (
            <span className="block text-xs font-semibold normal-case text-ink">
              {(help.label || value).replaceAll("_", " ")}
            </span>
          ) : null}
          <span className="block text-xs font-normal normal-case text-ink">{help.what}</span>
          {reason ? (
            <span className="mt-1 block text-xs font-medium normal-case text-ember">
              Why: {String(reason).replaceAll("_", " ").toLowerCase()}
            </span>
          ) : null}
          <span className="mt-1 block text-[11px] font-normal normal-case text-muted">→ {help.next}</span>
        </span>
      ) : null}
    </span>
  );
}

function Severity({ value }: { value: string }) {
  return (
    <span className={clsx("rounded px-2 py-1 text-xs font-semibold", severityClass(value))}>
      {value}
    </span>
  );
}

function ScoreTip({
  token,
  backlinkId,
  score
}: {
  token: string | null;
  backlinkId: string;
  score: number | null;
}) {
  const [hovered, setHovered] = useState(false);
  // Lazy: the breakdown is fetched only on first hover, then cached.
  const detail = useQuery({
    queryKey: ["score-tip", token, backlinkId],
    enabled: Boolean(token) && hovered,
    staleTime: 5 * 60_000,
    queryFn: () => api<BacklinkDetail>(`/backlinks/${backlinkId}`, { token })
  });
  const steps = (detail.data?.score_breakdown || []) as Array<{
    code: string; delta: number; note?: string; cap_applied?: number | null;
  }>;
  const shown = steps.filter((s) => s.delta !== 0 || s.cap_applied != null);
  return (
    <span
      className="group relative inline-flex"
      onMouseEnter={() => setHovered(true)}
    >
      <span className="cursor-help font-semibold underline decoration-dotted decoration-line underline-offset-2">
        {score ?? "-"}
      </span>
      <span className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-80 rounded-lg border border-line bg-panel p-2.5 text-left shadow-pop group-hover:block">
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-muted">
          How this score was calculated
        </span>
        {!hovered || detail.isLoading ? (
          <span className="mt-1 block text-xs text-muted">Loading breakdown…</span>
        ) : shown.length ? (
          <span className="mt-1 block space-y-0.5">
            <span className="flex justify-between text-xs text-muted">
              <span>Starting score</span><span>100</span>
            </span>
            {shown.map((s, i) => (
              <span key={i} className="flex justify-between gap-2 text-xs">
                <span className="truncate text-ink">
                  {(s.note || s.code).replaceAll("_", " ").toLowerCase()}
                </span>
                <span className={clsx("shrink-0 font-semibold", s.delta < 0 ? "text-danger" : "text-ocean")}>
                  {s.cap_applied != null ? `capped at ${s.cap_applied}` : `${s.delta > 0 ? "+" : ""}${s.delta}`}
                </span>
              </span>
            ))}
            <span className="mt-1 flex justify-between border-t border-line pt-1 text-xs font-bold text-ink">
              <span>Final score</span><span>{score ?? "-"}</span>
            </span>
          </span>
        ) : (
          <span className="mt-1 block text-xs text-muted">
            No deductions — every checked parameter passed (score {score ?? "-"}).
          </span>
        )}
      </span>
    </span>
  );
}

// Select-2.0-style single select: a button that opens a searchable dropdown.
// Use for any picker with more than a handful of options (people, projects).
function SearchSelect({
  value,
  onChange,
  options,
  placeholder,
  allowClear = true,
  allowCustom = false,
  width = "w-44"
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label?: string }>;
  placeholder: string;
  allowClear?: boolean;
  allowCustom?: boolean; // typed text can be used as a brand-new value
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);
  const current = options.find((o) => o.value === value);
  const shown = options.filter((o) =>
    (o.label || o.value).toLowerCase().includes(q.trim().toLowerCase())
  );
  return (
    <div ref={ref} className={clsx("relative", width)}>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          setQ("");
        }}
        className={clsx(
          "flex h-9 w-full items-center justify-between gap-1 rounded-lg border bg-panel px-2.5 text-sm transition",
          value ? "border-ocean/40 font-medium text-ink" : "border-line text-muted"
        )}
      >
        <span className="truncate">{current ? current.label || current.value : placeholder}</span>
        <span className="flex shrink-0 items-center gap-1">
          {allowClear && value ? (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onChange("");
              }}
              className="text-muted hover:text-danger"
              aria-label="Clear"
            >
              ×
            </span>
          ) : null}
          <ChevronDown className="h-3.5 w-3.5 text-muted" />
        </span>
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 w-64 rounded-lg border border-line bg-panel p-1.5 shadow-pop">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Type to search…"
            className="mb-1 h-8 w-full rounded-md border border-line bg-field/50 px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <div className="max-h-56 overflow-y-auto">
            {shown.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={clsx(
                  "block w-full truncate rounded-md px-2 py-1.5 text-left text-sm transition hover:bg-field",
                  o.value === value ? "bg-ocean/10 font-semibold text-ocean" : "text-ink"
                )}
              >
                {o.label || o.value}
              </button>
            ))}
            {allowCustom && q.trim() && !options.some((o) => o.value.toLowerCase() === q.trim().toLowerCase()) ? (
              <button
                type="button"
                onClick={() => {
                  onChange(q.trim());
                  setOpen(false);
                }}
                className="block w-full truncate rounded-md px-2 py-1.5 text-left text-sm font-medium text-ocean transition hover:bg-field"
              >
                + Use “{q.trim()}”
              </button>
            ) : null}
            {!shown.length && !(allowCustom && q.trim()) ? (
              <p className="px-2 py-2 text-xs text-muted">No matches.</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function FilterMultiSelect({
  label,
  options,
  selected,
  onChange,
  withBlanks = false,
  allowCustom = false
}: {
  label: string;
  options: Array<{ value: string; label?: string; count?: number }>;
  selected: string[];
  onChange: (vals: string[]) => void;
  withBlanks?: boolean;
  allowCustom?: boolean; // let the user type + Enter to add a free-form value
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  // Custom (typed) values that aren't in the option list but are selected.
  const customSelected = allowCustom
    ? selected.filter((v) => !options.some((o) => o.value === v) && v !== "(blanks)")
    : [];
  const baseAll = withBlanks ? [...options, { value: "(blanks)", label: "(Blanks)" }] : options;
  const all: Array<{ value: string; label?: string; count?: number }> = [
    ...customSelected.map((v) => ({ value: v, label: v })),
    ...baseAll,
  ];
  const shown = all.filter((o) =>
    (o.label || o.value).toLowerCase().includes(q.trim().toLowerCase())
  );
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  const addCustom = () => {
    const v = q.trim();
    if (v && !selected.includes(v)) onChange([...selected, v]);
    setQ("");
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          "flex h-9 items-center gap-1.5 rounded-lg border px-2.5 text-sm transition",
          selected.length
            ? "border-ocean bg-ocean/10 font-medium text-ocean"
            : "border-line bg-panel text-ink hover:border-ocean/40"
        )}
      >
        {label}
        {selected.length ? (
          <span className="rounded-full bg-ocean px-1.5 text-[11px] font-bold text-white dark:text-slate-900">
            {selected.length}
          </span>
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-muted" />
        )}
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-30 mt-1 w-64 rounded-xl border border-line bg-panel p-2 shadow-pop">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (allowCustom && e.key === "Enter") { e.preventDefault(); addCustom(); } }}
            placeholder={allowCustom ? "Search or type + Enter to add…" : "Search…"}
            autoFocus
            className="mb-1.5 h-8 w-full rounded-md border border-line bg-panel px-2 text-xs focus:border-ocean focus:outline-none"
          />
          {allowCustom && q.trim() && !all.some((o) => o.value.toLowerCase() === q.trim().toLowerCase()) ? (
            <button type="button" onClick={addCustom} className="mb-1 w-full rounded-md bg-ocean/10 px-2 py-1 text-left text-xs font-medium text-ocean hover:bg-ocean/20">
              + Add “{q.trim()}”
            </button>
          ) : null}
          <div className="mb-1 flex items-center justify-between px-1 text-[11px] font-medium">
            <button
              type="button"
              onClick={() => onChange(shown.map((o) => o.value))}
              className="text-ocean hover:underline"
            >
              Select all
            </button>
            <button type="button" onClick={() => onChange([])} className="text-muted hover:underline">
              Clear
            </button>
          </div>
          <div className="max-h-56 overflow-y-auto">
            {shown.map((o) => (
              <label
                key={o.value}
                className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-sm hover:bg-field"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(o.value)}
                  onChange={() => toggle(o.value)}
                  className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
                />
                <span className="flex-1 truncate text-ink">{o.label || o.value}</span>
                {o.count != null ? <span className="text-xs text-muted">{o.count}</span> : null}
              </label>
            ))}
            {!shown.length ? <div className="p-2 text-center text-xs text-muted">No matches</div> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="p-8 text-center text-sm text-muted">{label}</div>;
}

function SheetsDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId?: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const config = useQuery({
    queryKey: ["sheet-config", token],
    enabled: Boolean(token),
    queryFn: () => api<SheetConfig>("/sheets/config", { token })
  });
  const sheets = useQuery({
    queryKey: ["sheets", token],
    enabled: Boolean(token),
    queryFn: () => api<SheetSource[]>("/sheets", { token })
  });

  // ── Realtime sync progress: poll sheet_sync runs while any is active ────
  const syncBatches = useQuery({
    queryKey: ["sheet-sync-batches", token],
    enabled: Boolean(token),
    queryFn: () => api<Batch[]>("/batches?kind=sheet_sync&limit=20", { token }),
    refetchInterval: (q) =>
      (q.state.data || []).some((b) => b.status === "running" || b.status === "pending") ? 2500 : 10000
  });
  const runningFor = (sourceId: string) =>
    (syncBatches.data || []).find(
      (b) =>
        (b.status === "running" || b.status === "pending") &&
        String((b.meta as Record<string, unknown>)?.sheet_source_id || "") === sourceId
    );
  // Completion detection → toast with the NEW-links result + refresh the table.
  const prevRunning = useRef<Set<string>>(new Set());
  useEffect(() => {
    const nowRunning = new Set(
      (syncBatches.data || []).filter((b) => b.status === "running" || b.status === "pending").map((b) => b.id)
    );
    prevRunning.current.forEach((id) => {
      if (!nowRunning.has(id)) {
        const done = (syncBatches.data || []).find((b) => b.id === id);
        if (done) {
          const newLinks = Number(done.counters?.new_links ?? 0);
          const failed = Number(done.totals?.failed ?? 0);
          onNotice(
            done.status === "failed"
              ? `Sync failed: ${done.error || "see Batches for details"}`
              : `Sync finished — ${newLinks} new link${newLinks === 1 ? "" : "s"} added` +
                  (failed ? `, ${failed} row(s) failed` : "") + "."
          );
          queryClient.invalidateQueries({ queryKey: ["sheets"] });
          queryClient.invalidateQueries({ queryKey: ["backlinks"] });
        }
      }
    });
    prevRunning.current = nowRunning;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncBatches.data]);

  const [mappingFor, setMappingFor] = useState<string | null>(null);

  const syncAll = useMutation({
    mutationFn: () => api<{ message: string }>("/sheets/sync", { method: "POST", token }),
    onSuccess: (r) => {
      onNotice(r.message || "Main sheet sync started");
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["sheet-sync-batches"] }), 1200);
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["sheets"] }), 1500);
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const syncOne = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/sheets/${id}/sync`, { method: "POST", token }),
    onSuccess: (r) => {
      onNotice(r.message || "Sync started — progress shows below.");
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["sheet-sync-batches"] }), 1200);
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const writeBack = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/sheets/${id}/writeback`, { method: "POST", token }),
    onSuccess: (r) => onNotice(r.message || "Write-back started"),
    onError: (e: Error) => onNotice(e.message)
  });

  // Sync ALL sheets — one click, queued sequentially (manual trigger only).
  const syncEverySheet = useMutation({
    mutationFn: () => api<{ message: string }>("/sheets/sync-all", { method: "POST", token }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // ── Google Sheets API read-rate limit (global; guards Google's ~300/min quota) ──
  const apiLimit = useQuery({
    queryKey: ["sheets-api-limit", token],
    enabled: Boolean(token) && !projectId,
    queryFn: () => api<{ reads_per_min: number; default: number; max: number }>("/sheets/api-limit", { token })
  });
  const [limitDraft, setLimitDraft] = useState<string>("");
  useEffect(() => {
    if (apiLimit.data) setLimitDraft(String(apiLimit.data.reads_per_min));
  }, [apiLimit.data]);
  const saveLimit = useMutation({
    mutationFn: (v: number) =>
      api<{ reads_per_min: number }>("/sheets/api-limit", {
        method: "PUT", token, body: JSON.stringify({ reads_per_min: v })
      }),
    onSuccess: (r) => {
      onNotice(`Sheets API read limit set to ${r.reads_per_min}/min`);
      queryClient.invalidateQueries({ queryKey: ["sheets-api-limit"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const cfg = config.data;
  // Project scope: entering a project narrows the desk to that project's sheets.
  const visibleSheets = (sheets.data || []).filter((s) => !projectId || s.project_id === projectId);
  return (
    <section className="space-y-4">
      {!projectId ? (
      <div className="rounded-xl border border-line bg-panel shadow-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Google Sheets</h2>
            <p className="text-sm text-muted">
              <span className="font-medium text-ink">Sync from main sheet</span> only discovers projects
              (their name, sheet link + tabs). Then set each project&apos;s mapping — including any tabs
              to ignore — and click <span className="font-medium text-ink">Sync</span> on that project to pull its links.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => syncAll.mutate()}
              disabled={!cfg?.enabled || syncAll.isPending}
              className="flex items-center gap-2 rounded-md bg-ocean px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900 disabled:opacity-50"
            >
              {syncAll.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Discover projects from main sheet
            </button>
            <button
              onClick={() => {
                if (window.confirm(`Sync ALL ${visibleSheets.length} connected sheets now? They run one at a time (respecting the API limit) — live progress appears below, and each sheet reports its own new/refreshed counts.`))
                  syncEverySheet.mutate();
              }}
              disabled={!cfg?.enabled || syncEverySheet.isPending || !visibleSheets.length}
              title="Queue a sync for every connected project sheet — manual trigger only, never automatic"
              className="flex items-center gap-2 rounded-md border border-ocean/40 px-4 py-2 text-sm font-semibold text-ocean transition hover:bg-ocean/10 disabled:opacity-50"
            >
              {syncEverySheet.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Sync all sheets ({visibleSheets.length})
            </button>
          </div>
        </div>
        {/* API read-rate limit — keeps syncs under Google's ~300 reads/min quota. */}
        {cfg?.enabled ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-field p-3 text-sm">
            <span className="font-medium text-ink">Sheets API read limit</span>
            <input
              type="number" min={0} max={300} value={limitDraft}
              onChange={(e) => setLimitDraft(e.target.value)}
              className="h-8 w-24 rounded-md border border-line bg-panel px-2 text-sm focus:border-ocean focus:outline-none"
            />
            <span className="text-xs text-muted">reads/min (Google&apos;s cap is 300; 0 = no throttle)</span>
            <button
              onClick={() => saveLimit.mutate(Math.max(0, Math.min(300, Number(limitDraft) || 0)))}
              disabled={saveLimit.isPending || limitDraft === String(apiLimit.data?.reads_per_min ?? "")}
              className="ml-auto h-8 rounded-md border border-line px-3 text-xs font-medium text-ink transition hover:bg-panel disabled:opacity-40"
            >
              Save limit
            </button>
          </div>
        ) : null}
        {cfg && !cfg.enabled ? (
          <div className="mt-3 rounded-md border border-line bg-field p-3 text-sm text-muted">
            Google Sheets is not configured yet. Set the service account + main sheet ID in the
            server <code>.env</code>, then share both the main sheet and every project sheet with
            this service-account email:
            <div className="mt-1 font-mono text-xs text-ink">
              {cfg.service_account_email || "(service account not loaded — check GOOGLE_SA_JSON_BASE64)"}
            </div>
          </div>
        ) : null}
        {cfg?.enabled ? (
          <div className="mt-3 text-xs text-muted">
            Share sheets with: <span className="font-mono text-ink">{cfg.service_account_email}</span>
          </div>
        ) : null}
      </div>
      ) : null}

      {projectId ? <p className="text-xs text-muted">Showing only this project&apos;s sheets.</p> : null}
      <div className="overflow-x-auto rounded-xl border border-line bg-panel shadow-card">
        <table className="min-w-[760px] w-full text-left text-sm">
          <thead className="bg-field text-xs uppercase text-muted">
            <tr>
              <Th>Project</Th>
              <Th>Status</Th>
              <Th>Rows</Th>
              <Th>New / Updated</Th>
              <Th>Last synced</Th>
              <Th>Action</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {visibleSheets.map((s) => {
              const live = runningFor(s.id);
              const newCount = Math.max(0, s.imported_count - s.updated_count);
              return (
                <Fragment key={s.id}>
                  <tr>
                    <Td>
                      <div className="font-medium text-ink">{s.project_name}</div>
                      <div className="max-w-[280px] truncate text-xs text-muted" title={s.source_url || ""}>
                        {s.source_url}
                      </div>
                    </Td>
                    <Td>
                      {live ? (
                        <span className="flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium text-ember">
                          <Loader2 className="h-3 w-3 animate-spin" /> syncing…
                        </span>
                      ) : (
                        <span
                          className={clsx(
                            "rounded px-2 py-0.5 text-xs font-medium",
                            s.last_sync_status === "ok" && "bg-ocean/10 text-ocean",
                            s.last_sync_status === "error" && "bg-danger/10 text-danger",
                            s.last_sync_status === "running" && "bg-ember/10 text-ember",
                            !s.last_sync_status && "bg-field text-muted"
                          )}
                          title={s.last_sync_error || ""}
                        >
                          {s.last_sync_status || "never"}
                        </span>
                      )}
                    </Td>
                    <Td>{s.row_count}</Td>
                    <Td>
                      <span title="New = links added for the first time. Refreshed = rows that already existed and were just updated from the sheet.">
                        <span className="font-semibold text-ocean">{newCount} new</span>
                        <span className="text-muted"> · {s.updated_count} refreshed</span>
                      </span>
                    </Td>
                    <Td><span className="whitespace-nowrap">{formatDate(s.last_synced_at)}</span></Td>
                    <Td>
                      <div className="flex gap-1">
                        <button
                          onClick={() => syncOne.mutate(s.id)}
                          disabled={Boolean(live)}
                          className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-50"
                        >
                          <RefreshCw className="h-3.5 w-3.5" /> Sync
                        </button>
                        <button
                          onClick={() => writeBack.mutate(s.id)}
                          title="Write QA/index results back to result columns in the sheet"
                          className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
                        >
                          <Upload className="h-3.5 w-3.5" /> Write back
                        </button>
                        <button
                          onClick={() => setMappingFor(mappingFor === s.id ? null : s.id)}
                          title="Choose which sheet column feeds each field, and which result columns write-back uses"
                          className={clsx(
                            "flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition",
                            mappingFor === s.id
                              ? "border-ocean bg-ocean/10 text-ocean"
                              : "border-line text-ink hover:bg-field"
                          )}
                        >
                          <SlidersHorizontal className="h-3.5 w-3.5" /> Mapping
                        </button>
                      </div>
                    </Td>
                  </tr>
                  {live ? (
                    <tr>
                      <td colSpan={6} className="bg-ocean/5 px-4 py-2.5">
                        <div className="flex flex-wrap items-center gap-3 text-xs">
                          <BatchProgress totals={live.totals || {}} />
                          <span className="text-muted">
                            {String((live.meta as Record<string, unknown>)?.current_step || "Working…")}
                          </span>
                          {Number(live.counters?.new_links ?? 0) > 0 ? (
                            <span className="font-medium text-ocean">
                              {Number(live.counters?.new_links)} new so far
                            </span>
                          ) : null}
                          <span className="text-muted">
                            {Number(live.totals?.done_tabs ?? 0)}/{Number(live.totals?.total_tabs ?? 0)} tabs
                          </span>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                  {mappingFor === s.id ? (
                    <tr>
                      <td colSpan={6} className="bg-field/40 p-4">
                        <SheetMappingEditor token={token} sheetId={s.id} onNotice={onNotice} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {!sheets.isLoading && !visibleSheets.length ? (
          <Empty label={projectId ? "No sheets for this project yet." : "No project sheets yet — run a sync from the main sheet"} />
        ) : null}
      </div>
    </section>
  );
}

function SheetMappingEditor({
  token,
  sheetId,
  onNotice
}: {
  token: string | null;
  sheetId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  type FieldMeta = { key: string; label: string; required: boolean; group: string; help: string };
  type MappingData = {
    tabs: Array<{ id: string; tab_name: string; import_enabled: boolean }>;
    tab_id: string | null;
    headers: string[];
    header_error: string | null;
    sample_rows: Array<Record<string, string>>;
    row_count: number;
    mapping: Record<string, string>;
    tab_mapping: Record<string, string>;
    source_mapping: Record<string, string>;
    is_manual: boolean;
    auto: { mapping: Record<string, string>; matched: string[]; unmatched: string[] };
    field_constants: Record<string, string>;
    header_row: number;
    fields: string[];
    field_meta: FieldMeta[];
    writeback_options: string[];
    writeback_columns: string[];
    project_target: string | null;
    required_ok: boolean;
  };

  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const data = useQuery({
    queryKey: ["sheet-mapping", token, sheetId, selectedTab],
    enabled: Boolean(token),
    queryFn: () =>
      api<MappingData>(
        `/sheets/${sheetId}/mapping${selectedTab ? `?tab_id=${encodeURIComponent(selectedTab)}` : ""}`,
        { token }
      )
  });

  const [draftMapping, setDraftMapping] = useState<Record<string, string>>({});
  const [draftConstants, setDraftConstants] = useState<Record<string, string>>({});
  const [headerRow, setHeaderRow] = useState(1);
  const [wbCols, setWbCols] = useState<string[]>([]);
  // Constant-adder local state
  const [newConstField, setNewConstField] = useState("");
  const [newConstValue, setNewConstValue] = useState("");

  const d = data.data;

  // Seed all drafts whenever the loaded tab's data changes (load or tab switch).
  useEffect(() => {
    if (!d) return;
    if (selectedTab === null && d.tab_id) setSelectedTab(d.tab_id);
    setDraftMapping({ ...d.mapping });
    setDraftConstants({ ...d.field_constants });
    setHeaderRow(d.header_row || 1);
    setWbCols([...d.writeback_columns]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d?.tab_id, d?.header_row]);

  const save = useMutation({
    mutationFn: (apply_to: "tab" | "source" | "all_tabs") =>
      api<{ message: string }>(`/sheets/${sheetId}/mapping`, {
        token,
        method: "PUT",
        body: JSON.stringify({
          tab_id: selectedTab,
          column_mapping: draftMapping,
          field_constants: draftConstants,
          header_row: headerRow,
          writeback_columns: wbCols,
          apply_to
        })
      }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["sheet-mapping", token, sheetId] });
      queryClient.invalidateQueries({ queryKey: ["sheets"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  // Ignore / include a whole sub-sheet (tab). Ignored tabs are fully skipped on
  // sync — no reads, no mapping, no links imported from them.
  const toggleTab = useMutation({
    mutationFn: (p: { id: string; import_enabled: boolean }) =>
      api<{ id: string }>(`/sheets/tabs/${p.id}`, {
        token, method: "PATCH", body: JSON.stringify({ import_enabled: p.import_enabled })
      }),
    onSuccess: (_r, p) => {
      onNotice(p.import_enabled ? "Tab included — it will sync" : "Tab ignored — it won't sync");
      queryClient.invalidateQueries({ queryKey: ["sheet-mapping", token, sheetId] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const fieldLabel = (f: string) => {
    const m = d?.field_meta.find((x) => x.key === f);
    return m ? m.label : f.replaceAll("_", " ");
  };

  if (data.isLoading) {
    return <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>;
  }
  if (!d) return <Empty label="Could not load mapping." />;

  const meta = d.field_meta;
  // Reverse lookup: which sheet header currently feeds each field.
  const headerForField = (f: string): string | null => {
    for (const [h, field] of Object.entries(draftMapping)) if (field === f) return h;
    return null;
  };
  // Fields not yet mapped to any column AND without a constant — candidates for a fixed value.
  const mappedFields = new Set(Object.values(draftMapping));
  const constantCandidates = meta.filter(
    (m) => !mappedFields.has(m.key) && !(m.key in draftConstants)
  );

  const setColumnField = (header: string, field: string) =>
    setDraftMapping((prev) => {
      const next = { ...prev };
      if (field) next[header] = field;
      else delete next[header];
      return next;
    });

  const addConstant = () => {
    if (!newConstField) return;
    setDraftConstants((prev) => ({ ...prev, [newConstField]: newConstValue }));
    setNewConstField("");
    setNewConstValue("");
  };
  const removeConstant = (f: string) =>
    setDraftConstants((prev) => {
      const next = { ...prev };
      delete next[f];
      return next;
    });

  const resetToAuto = () => {
    setDraftMapping({ ...d.auto.mapping });
    setDraftConstants({});
  };

  // The hard requirement: a source URL, from a column or a constant.
  const allRequiredOk =
    Object.values(draftMapping).includes("source_page_url") ||
    "source_page_url" in draftConstants;

  // Core fields to surface in the coverage panel: required + group "core".
  const coreFields = meta.filter((m) => m.required || m.group === "core");
  const activeTab = d.tabs.find((t) => t.id === (selectedTab ?? d.tab_id));

  const truncate = (v: string, n = 40) => (v.length > n ? `${v.slice(0, n)}…` : v);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 text-sm font-semibold text-ink">
          Column mapping
          <HelpTip text="Tell the sync which sheet column feeds each field. Auto-detect handles common names ('Source URL', 'User', 'Anchor'…); set a column manually when your sheet uses different wording. '(ignore)' columns are simply skipped, and a fixed value fills fields your sheet doesn't have a column for." />
        </div>
        {activeTab ? (
          <span className="text-xs text-muted">
            Tab <span className="font-medium text-ink">{activeTab.tab_name}</span>
          </span>
        ) : null}
        <span className="rounded-full bg-field px-2 py-0.5 text-[10px] font-semibold uppercase text-muted">
          {d.is_manual ? "Manual" : "Auto-detected"}
        </span>
        {activeTab ? (
          <button
            onClick={() => toggleTab.mutate({ id: activeTab.id, import_enabled: !activeTab.import_enabled })}
            disabled={toggleTab.isPending}
            title={activeTab.import_enabled ? "Ignore this tab — it will be fully skipped on sync" : "Include this tab in sync"}
            className={clsx(
              "ml-auto flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium transition disabled:opacity-50",
              activeTab.import_enabled
                ? "border-line text-muted hover:bg-field"
                : "border-ember/40 bg-ember/10 text-ember"
            )}
          >
            {activeTab.import_enabled ? "Ignore this tab" : "Ignored — click to include"}
          </button>
        ) : null}
      </div>

      {/* TAB SWITCHER */}
      {d.tabs.length > 1 ? (
        <div className="flex items-center gap-1.5 overflow-x-auto">
          <span className="shrink-0 text-xs text-muted">Mapping tab:</span>
          <span className="inline-flex rounded-lg border border-line bg-field/40 p-0.5 text-xs font-medium">
            {d.tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedTab(t.id)}
                title={t.import_enabled ? t.tab_name : `${t.tab_name} — ignored (won't sync)`}
                className={clsx(
                  "rounded-md px-2.5 py-1 transition",
                  (selectedTab ?? d.tab_id) === t.id ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field",
                  !t.import_enabled && (selectedTab ?? d.tab_id) !== t.id && "line-through opacity-50"
                )}
              >
                {t.tab_name}{!t.import_enabled ? " ·ignored" : ""}
              </button>
            ))}
          </span>
        </div>
      ) : null}

      {/* AUTO SCORECARD */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-field/40 px-3 py-2 text-xs">
        <span className="text-muted">
          <span className="font-semibold text-ink">{d.auto.matched.length}</span> of{" "}
          <span className="font-semibold text-ink">{d.headers.length}</span> columns auto-detected
          {" · "}
          {d.auto.unmatched.length} ignored
        </span>
        <button
          onClick={resetToAuto}
          className="ml-auto rounded-md border border-line px-2 py-1 font-medium text-muted transition hover:bg-field"
        >
          Reset to auto-detect
        </button>
      </div>

      {/* HEADER ROW control */}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5 font-medium text-ink">
          Headers are in row
          <input
            type="number"
            min={1}
            max={50}
            value={headerRow}
            onChange={(e) => setHeaderRow(Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
            className="h-8 w-16 rounded-lg border border-line bg-panel px-2 text-xs"
          />
        </label>
        <span className="text-muted">
          Increase if your sheet has a title/banner above the column names. Applies on save, then re-reads the sheet.
        </span>
      </div>

      {d.header_error ? (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
          Couldn&apos;t read the sheet&apos;s headers right now: {d.header_error}
        </div>
      ) : null}

      {/* REQUIRED-FIELD / COVERAGE PANEL */}
      <div className="rounded-lg border border-line bg-panel p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink">
          Core fields
          <HelpTip text="Where each key field comes from. Source page URL is mandatory — from a column or a fixed value. Target URL can default to the project target when left unmapped." />
        </div>
        <div className="grid gap-1.5 sm:grid-cols-2">
          {coreFields.map((m) => {
            const col = headerForField(m.key);
            const constant = m.key in draftConstants ? draftConstants[m.key] : null;
            let detail: React.ReactNode;
            if (col) {
              detail = <span className="rounded-full bg-ocean/10 px-2 py-0.5 font-medium text-ocean">from “{col}”</span>;
            } else if (constant !== null) {
              detail = <span className="rounded-full bg-plum/10 px-2 py-0.5 font-medium text-plum">= {constant || "(blank)"}</span>;
            } else if (m.key === "target_url" && d.project_target) {
              detail = <span className="rounded-full bg-field px-2 py-0.5 text-muted">defaults to {truncate(d.project_target, 32)}</span>;
            } else if (m.required) {
              detail = <span className="rounded-full bg-danger/10 px-2 py-0.5 font-medium text-danger">Not mapped — required</span>;
            } else {
              detail = <span className="rounded-full bg-danger/10 px-2 py-0.5 font-medium text-danger">Not mapped</span>;
            }
            return (
              <div key={m.key} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-ink" title={m.help}>
                  {m.label}
                  {m.required ? <span className="text-danger"> *</span> : null}
                </span>
                {detail}
              </div>
            );
          })}
        </div>
        {!allRequiredOk ? (
          <p className="mt-2 text-xs text-danger">
            Map a column to <span className="font-semibold">Source page URL</span> (or set a fixed value) before saving.
          </p>
        ) : null}
      </div>

      {/* LIVE PREVIEW TABLE */}
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-ink">
          Live preview
          <HelpTip text="Real rows from your sheet. Pick the field each column feeds from the dropdown under its name — the sample values below show exactly what will be imported." />
        </div>
        {d.header_error ? (
          <div className="rounded-lg border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
            Preview unavailable — the sheet headers couldn&apos;t be read.
          </div>
        ) : !d.headers.length ? (
          <Empty label="No columns found — check the header row above." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="min-w-full border-collapse text-xs">
              <thead>
                <tr className="bg-field/60">
                  {d.headers.map((h) => (
                    <th key={h} className="border-b border-r border-line p-1.5 text-left align-top last:border-r-0">
                      <span className="mb-1 block max-w-[9rem] truncate font-semibold text-ink" title={h}>{h}</span>
                      <select
                        value={draftMapping[h] || ""}
                        onChange={(e) => setColumnField(h, e.target.value)}
                        className="h-7 w-full min-w-[8rem] rounded-md border border-line bg-panel px-1.5 text-[11px]"
                      >
                        <option value="">(ignore)</option>
                        {meta.map((m) => (
                          <option key={m.key} value={m.key}>
                            {m.label}{m.required ? " *" : ""}
                          </option>
                        ))}
                      </select>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.sample_rows.slice(0, 8).map((row, i) => (
                  <tr key={i} className="odd:bg-panel even:bg-field/20">
                    {d.headers.map((h) => (
                      <td key={h} className="border-b border-r border-line p-1.5 align-top text-muted last:border-r-0" title={row[h] || ""}>
                        {row[h] ? truncate(row[h]) : <span className="text-muted/50">—</span>}
                      </td>
                    ))}
                  </tr>
                ))}
                {!d.sample_rows.length ? (
                  <tr>
                    <td colSpan={d.headers.length} className="p-3 text-center text-muted">
                      No sample rows below the header row.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* CONSTANTS */}
      <div className="rounded-lg border border-line bg-panel p-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink">
          Fixed values
          <HelpTip text="Fill a field with the same value for every row when your sheet has no column for it — e.g. Link type = Guest Post, or Vendor = a supplier name." />
        </div>
        {Object.keys(draftConstants).length ? (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {Object.entries(draftConstants).map(([f, v]) => (
              <span key={f} className="inline-flex items-center gap-1 rounded-full border border-line bg-field px-2.5 py-1 text-xs">
                <span className="font-medium text-ink">{fieldLabel(f)}</span> = {v || "(blank)"}
                <button
                  onClick={() => removeConstant(f)}
                  className="text-muted transition hover:text-danger"
                  aria-label="Remove"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <SearchSelect
            value={newConstField}
            onChange={setNewConstField}
            options={constantCandidates.map((m) => ({ value: m.key, label: m.label }))}
            placeholder="Choose a field…"
            width="w-52"
          />
          <input
            value={newConstValue}
            onChange={(e) => setNewConstValue(e.target.value)}
            placeholder="Fixed value"
            className="h-9 w-44 rounded-lg border border-line bg-panel px-2.5 text-sm"
          />
          <button
            onClick={addConstant}
            disabled={!newConstField}
            className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>

      {/* WRITE-BACK */}
      <div>
        <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-ink">
          Write-back columns
          <HelpTip text="Which result columns 'Write back' adds to the sheet. They always go into their own block to the right of your data — your input columns are never touched, and re-syncing keeps working." />
        </div>
        <div className="flex flex-wrap gap-2">
          {d.writeback_options.map((c) => (
            <label key={c} className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs hover:bg-field">
              <input
                type="checkbox"
                checked={wbCols.includes(c)}
                onChange={() =>
                  setWbCols((cur) => (cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c]))
                }
                className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
              />
              {c}
            </label>
          ))}
        </div>
      </div>

      {/* SAVE */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => save.mutate("tab")}
          disabled={save.isPending || !allRequiredOk}
          title={!allRequiredOk ? "Map Source page URL (or set a fixed value) first" : undefined}
          className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          Save for this tab
        </button>
        {d.tabs.length > 1 ? (
          <button
            onClick={() => {
              if (window.confirm("Apply this mapping to every tab in the sheet?")) save.mutate("all_tabs");
            }}
            disabled={save.isPending || !allRequiredOk}
            title={!allRequiredOk ? "Map Source page URL (or set a fixed value) first" : undefined}
            className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field disabled:opacity-50"
          >
            Apply to all tabs
          </button>
        ) : null}
        <button
          onClick={() => save.mutate("source")}
          disabled={save.isPending || !allRequiredOk}
          title={!allRequiredOk ? "Map Source page URL (or set a fixed value) first" : "Use as the fallback for tabs without their own mapping"}
          className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field disabled:opacity-50"
        >
          Save as sheet default
        </button>
      </div>
    </div>
  );
}

// Maps a facet dimension → the filter key it sets + a human label.
const ANALYTICS_FACETS: Array<[string, string, string]> = [
  ["project", "project_id", "Project"],
  ["user", "assigned_user_label", "User"],
  ["link_type", "link_type", "Link type"],
  ["status", "status", "QA status"],
  ["index_status", "index_status", "Index"],
  ["duplicate_status", "duplicate_status", "Duplicate"],
  ["rel", "rel", "Rel"],
  ["source_domain", "source_domain", "Source domain"],
  ["scoring_version", "scoring_rule_version_id", "Scoring version"]
];

const GROUP_OPTIONS: Array<[string, string]> = [
  ["user", "User"],
  ["project", "Project"],
  ["link_type", "Link type"],
  ["status", "QA status"],
  ["http_status", "HTTP status"],
  ["score_band", "Score band"],
  ["index_status", "Index status"],
  ["duplicate_status", "Duplicate status"],
  ["rel", "Rel"],
  ["vendor", "Vendor"],
  ["source_domain", "Source domain"],
  ["scoring_version", "Scoring version"],
  // Month buckets (YYYY-MM) — pivot links by any date type.
  ["placement_month", "Month · placed"],
  ["discovered_month", "Month · discovered"],
  ["qa_month", "Month · QA checked"],
  ["completed_month", "Month · completed"],
  ["imported_month", "Month · imported"]
];

// Backlinks-grid date-type axes: which BacklinkRow field the "Link date" column
// shows, its keyset sort key (null = not server-sortable), and the /backlinks
// filter _from/_to query params for the range picker.
const BACKLINK_DATE_AXES: Array<{
  key: string;
  label: string;
  field: keyof BacklinkRow;
  sort: string | null;
  from: string | null;
  to: string | null;
}> = [
  { key: "placement", label: "Placement", field: "placement_date", sort: "placement_date", from: "placement_from", to: "placement_to" },
  { key: "discovered", label: "Discovery", field: "discovered_at", sort: "discovered_at", from: "discovered_from", to: "discovered_to" },
  { key: "qa", label: "QA checked", field: "last_checked_at", sort: "last_checked_at", from: "qa_from", to: "qa_to" },
  { key: "completed", label: "Completion", field: "qa_completed_at", sort: "qa_completed_at", from: "completed_from", to: "completed_to" },
  { key: "imported", label: "Import", field: "created_at", sort: "created_at", from: "imported_from", to: "imported_to" },
  { key: "sheet", label: "Sheet", field: "sheet_created_date", sort: null, from: "sheet_from", to: "sheet_to" },
  { key: "assigned", label: "Assignment", field: "assigned_at", sort: "assigned_at", from: "assigned_from", to: "assigned_to" },
  { key: "updated", label: "Update", field: "updated_at", sort: "updated_at", from: "updated_from", to: "updated_to" }
];

// Analytics date-type axes → the matching analytics filter _from/_to keys.
const ANALYTICS_DATE_AXES: Array<{ key: string; label: string; from: string; to: string }> = [
  { key: "checked", label: "QA checked", from: "checked_from", to: "checked_to" },
  { key: "placement", label: "Placement", from: "placement_from", to: "placement_to" },
  { key: "discovered", label: "Discovery", from: "discovered_from", to: "discovered_to" },
  { key: "completed", label: "Completion", from: "completed_from", to: "completed_to" },
  { key: "imported", label: "Import", from: "created_from", to: "created_to" },
  { key: "sheet", label: "Sheet", from: "sheet_from", to: "sheet_to" },
  { key: "assigned", label: "Assignment", from: "assigned_from", to: "assigned_to" },
  { key: "updated", label: "Update", from: "updated_from", to: "updated_to" },
  { key: "index", label: "Index check", from: "index_from", to: "index_to" }
];

// Spam KPI threshold — mirrors backend settings.ANALYTICS_SPAM_THRESHOLD (30):
// the `spam` summary bucket + the analytics `spam` filter count a link as spammy
// when its source domain's spam score is at or above this value.
const ANALYTICS_SPAM_THRESHOLD = 30;

// Score-band select options for the analytics filter (mirrors _SCORE_BAND_SQL /
// GradeBand.from_score: perfect=100 · good=80–99 · warning=60–79 · risky=30–59 ·
// failed=0–29).
const SCORE_BAND_OPTIONS: Array<[string, string]> = [
  ["perfect", "Perfect (100)"],
  ["good", "Good (80–99)"],
  ["warning", "Warning (60–79)"],
  ["risky", "Risky (30–59)"],
  ["failed", "Failed (0–29)"]
];

// Exact HTTP-status options for the analytics multiselect (comma-list → http_status).
const HTTP_STATUS_OPTIONS: Array<[string, string]> = [
  ["200", "200 OK"],
  ["301", "301 Moved"],
  ["302", "302 Found"],
  ["404", "404 Not found"],
  ["500", "500 Server error"]
];

function pct(n: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((n / total) * 100)}%`;
}

type SavedView = { name: string; filters: Record<string, string>; groupBy: string };

function loadViews(key: string): SavedView[] {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]");
  } catch {
    return [];
  }
}

function AnalyticsDesk({
  token,
  projectId,
  onNotice,
  onOpenBacklinks
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
  onOpenBacklinks: (filters: Record<string, string>) => void;
}) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [groupBy, setGroupBy] = useState("user");
  const [drillKey, setDrillKey] = useState<string | null>(null);
  const [views, setViews] = useState<SavedView[]>(() => loadViews("ls_views_analytics"));
  const [viewName, setViewName] = useState("");
  const [linksLimit, setLinksLimit] = useState(50);
  const [detailId, setDetailId] = useState<string | null>(null);
  // Which date type the from/to range in the filter bar applies to.
  const [dateAxis, setDateAxis] = useState("checked");

  // The actual backlink rows behind the analytics numbers — same filter whitelist
  // the cards use, so "Matching links" always agrees with the pivots above. The
  // /backlinks endpoint accepts these keys directly; analytics-only keys that map
  // to a different /backlinks name (spam→spam_min, nofollow→rel) are translated.
  const backlinkParams = () => {
    const map: Record<string, string> = {};
    // Keys the Backlinks list accepts verbatim — kept 1:1 with the analytics
    // filter vocabulary so the "Matching links" list always equals the summary.
    [
      "status", "index_status", "duplicate_status", "rel", "link_type",
      "source_domain", "assigned_user_label", "project_id",
      "http_status", "http_class", "broken", "orphaned",
      "link_missing", "da_min", "pa_min", "as_min", "search",
      // Date ranges the Backlinks endpoint shares by name (esp. placement = link
      // creation) so the list matches the summary/time-range selector exactly.
      "placement_from", "placement_to", "discovered_from", "discovered_to",
      "completed_from", "completed_to", "sheet_from", "sheet_to"
    ].forEach((k) => {
      if (filters[k]) map[k] = filters[k];
    });
    // analytics `spam` holds a threshold value; /backlinks reads it as `spam_min`.
    if (filters.spam) map.spam_min = filters.spam;
    // analytics `nofollow` is a truthy toggle; /backlinks filters via rel.
    if (filters.nofollow && !map.rel) map.rel = "nofollow";
    return map;
  };

  // Project context: analytics is automatically scoped to the selected project.
  useEffect(() => {
    setFilters((f) => {
      const next = { ...f };
      if (projectId) next.project_id = projectId;
      else delete next.project_id;
      return next;
    });
    setDrillKey(null);
  }, [projectId]);

  const saveView = () => {
    const name = viewName.trim();
    if (!name) return;
    const next = [...views.filter((v) => v.name !== name), { name, filters, groupBy }];
    setViews(next);
    setViewName("");
    try {
      localStorage.setItem("ls_views_analytics", JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };
  const applyView = (name: string) => {
    const v = views.find((x) => x.name === name);
    if (!v) return;
    const f = { ...v.filters };
    if (projectId) f.project_id = projectId; // stay inside project context
    setFilters(f);
    setGroupBy(v.groupBy);
    setDrillKey(null);
  };
  const deleteView = (name: string) => {
    const next = views.filter((v) => v.name !== name);
    setViews(next);
    try {
      localStorage.setItem("ls_views_analytics", JSON.stringify(next));
    } catch {
      /* ignore */
    }
  };

  const drill = useQuery({
    queryKey: ["analytics-records", token, filters, groupBy, drillKey],
    enabled: Boolean(token) && drillKey !== null,
    queryFn: () =>
      api<{ records: Array<Record<string, any>> }>("/analytics/records", {
        token,
        method: "POST",
        body: JSON.stringify({ filters, group_by: groupBy, group_key: drillKey, limit: 50 })
      })
  });

  const q = useQuery({
    queryKey: ["analytics", token, filters, groupBy],
    enabled: Boolean(token),
    queryFn: () =>
      api<AnalyticsResponse>("/analytics/query", {
        token,
        method: "POST",
        body: JSON.stringify({
          filters,
          group_by: groupBy,
          facets: ANALYTICS_FACETS.map(([dim]) => dim)
        })
      })
  });

  const links = useQuery({
    queryKey: ["analytics-links", token, filters, linksLimit],
    enabled: Boolean(token),
    queryFn: () => {
      // Backend caps limit at 200 — clamp so a large "Load more" never 422s.
      const p = new URLSearchParams({ ...backlinkParams(), limit: String(Math.min(200, linksLimit)), with_total: "true" });
      return api<{ items: BacklinkRow[]; total?: number | null }>(`/backlinks?${p.toString()}`, { token });
    }
  });

  const s = q.data?.summary || {};
  const total = Number(s.total || 0);
  const maxGroup = Math.max(1, ...(q.data?.groups || []).map((g) => Number(g.total || 0)));
  const setFilter = (key: string, value: string) =>
    setFilters((f) => {
      const next = { ...f };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });
  // Apply a KPI stat-box's filter(s) and refocus the pivots (close any drill).
  const kpiFilter = (patch: Record<string, string>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setDrillKey(null);
  };

  // ── Time range (drives cards + charts + tables). Filters by the link's real
  // creation (placement) date, so every figure reflects when links went live. ──
  const _todayIso = new Date().toISOString().slice(0, 10);
  const _isoAgo = (opts: { days?: number; months?: number }) => {
    const d = new Date();
    if (opts.days) d.setDate(d.getDate() - opts.days);
    if (opts.months) d.setMonth(d.getMonth() - opts.months);
    return d.toISOString().slice(0, 10);
  };
  const RANGES: Array<[string, string, () => string | null]> = [
    ["30d", "Last 30 days", () => _isoAgo({ days: 30 })],
    ["3m", "Last 3 months", () => _isoAgo({ months: 3 })],
    ["6m", "Last 6 months", () => _isoAgo({ months: 6 })],
    ["all", "All time", () => null],
    ["custom", "Custom", () => filters.placement_from || null]
  ];
  const [rangeKey, setRangeKey] = useState<string>("all");
  const applyRange = (key: string) => {
    setRangeKey(key);
    if (key === "custom") return; // custom uses the two date inputs below
    const preset = RANGES.find((r) => r[0] === key);
    const from = preset ? preset[2]() : null;
    setFilters((f) => {
      const n = { ...f };
      if (from) { n.placement_from = from; n.placement_to = _todayIso; }
      else { delete n.placement_from; delete n.placement_to; }
      return n;
    });
    setDrillKey(null);
  };
  const setCustomBound = (which: "placement_from" | "placement_to", v: string) => {
    setRangeKey("custom");
    setFilters((f) => {
      const n = { ...f };
      if (v) n[which] = v; else delete n[which];
      return n;
    });
  };

  return (
    <section className="space-y-4">
      {/* Filter bar (connected facets with live counts) */}
      <div className="rounded-xl border border-line bg-panel shadow-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">Analytics</h2>
          {Object.keys(filters).length ? (
            <button onClick={() => { setFilters({}); setRangeKey("all"); }} className="text-xs font-medium text-ocean hover:underline">
              Clear filters
            </button>
          ) : null}
        </div>
        {/* Time range — presets + custom, all by link creation (placement) date. */}
        <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-line pb-3">
          <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-muted">Range</span>
          {RANGES.map(([key, label]) => (
            <button
              key={key}
              onClick={() => applyRange(key)}
              className={clsx(
                "h-8 rounded-full border px-3 text-xs font-medium transition",
                rangeKey === key
                  ? "border-ocean bg-ocean/10 text-ocean"
                  : "border-line bg-panel text-muted hover:bg-field"
              )}
            >
              {label}
            </button>
          ))}
          {rangeKey === "custom" ? (
            <span className="flex items-center gap-1.5">
              <input type="date" value={filters.placement_from || ""}
                onChange={(e) => setCustomBound("placement_from", e.target.value)}
                className="h-8 rounded-lg border border-line bg-panel px-2 text-xs focus:border-ocean focus:outline-none" />
              <span className="text-xs text-muted">to</span>
              <input type="date" value={filters.placement_to || ""}
                onChange={(e) => setCustomBound("placement_to", e.target.value)}
                className="h-8 rounded-lg border border-line bg-panel px-2 text-xs focus:border-ocean focus:outline-none" />
            </span>
          ) : null}
          <span className="ml-auto text-xs text-muted">
            {filters.placement_from
              ? `Showing ${fmtChartLabel(filters.placement_from, true)} → ${fmtChartLabel(filters.placement_to || _todayIso, true)} · by link creation date`
              : "Showing all time · by link creation date"}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {ANALYTICS_FACETS.filter(([dim]) => !(projectId && dim === "project")).map(
            ([dim, key, label]) => {
              const opts = q.data?.facets?.[dim] || [];
              return (
                <FilterMultiSelect
                  key={dim}
                  label={label}
                  withBlanks
                  options={opts.map((o) => ({
                    value: String(o.value),
                    label: String(o.label || o.value),
                    count: Number(o.count) || 0
                  }))}
                  selected={filters[key] ? filters[key].split(",") : []}
                  onChange={(vals) => setFilter(key, vals.join(","))}
                />
              );
            }
          )}
          {(() => {
            const axis = ANALYTICS_DATE_AXES.find((a) => a.key === dateAxis) || ANALYTICS_DATE_AXES[0];
            return (
              <label className="flex items-center gap-1 text-xs text-muted">
                <select
                  value={dateAxis}
                  onChange={(e) => {
                    // Switching the date type moves the current range onto the new keys.
                    const prev = ANALYTICS_DATE_AXES.find((a) => a.key === dateAxis) || ANALYTICS_DATE_AXES[0];
                    const next = ANALYTICS_DATE_AXES.find((a) => a.key === e.target.value) || ANALYTICS_DATE_AXES[0];
                    setFilters((f) => {
                      const nf = { ...f };
                      const from = nf[prev.from];
                      const to = nf[prev.to];
                      delete nf[prev.from];
                      delete nf[prev.to];
                      if (from) nf[next.from] = from;
                      if (to) nf[next.to] = to;
                      return nf;
                    });
                    setDateAxis(e.target.value);
                  }}
                  title="Which date type the range below filters on"
                  className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
                >
                  {ANALYTICS_DATE_AXES.map((a) => (
                    <option key={a.key} value={a.key}>{a.label}</option>
                  ))}
                </select>
                <input
                  type="date"
                  value={filters[axis.from] || ""}
                  onChange={(e) => setFilter(axis.from, e.target.value)}
                  className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
                />
                –
                <input
                  type="date"
                  value={filters[axis.to] || ""}
                  onChange={(e) => setFilter(axis.to, e.target.value)}
                  className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
                />
              </label>
            );
          })()}
        </div>

        {/* Advanced filters — exact HTTP status, score band, authority mins, quick toggles */}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <FilterMultiSelect
            label="HTTP status"
            options={HTTP_STATUS_OPTIONS.map(([value, label]) => ({ value, label }))}
            selected={filters.http_status ? filters.http_status.split(",") : []}
            onChange={(vals) => setFilter("http_status", vals.join(","))}
          />
          <select
            value={filters.score_band || ""}
            onChange={(e) => setFilter("score_band", e.target.value)}
            title="Filter by quality grade band"
            className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
          >
            <option value="">Score band…</option>
            {SCORE_BAND_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          {(["da_min", "pa_min", "as_min"] as const).map((k) => (
            <input
              key={k}
              type="number"
              min={0}
              max={100}
              inputMode="numeric"
              value={filters[k] || ""}
              onChange={(e) => setFilter(k, e.target.value)}
              placeholder={{ da_min: "DA ≥", pa_min: "PA ≥", as_min: "AS ≥" }[k]}
              title={{ da_min: "Min domain authority (Moz DA)", pa_min: "Min page authority (Moz PA)", as_min: "Min authority score (Semrush AS)" }[k]}
              className="h-9 w-20 rounded-xl border border-line bg-panel shadow-card px-2 text-sm text-ink"
            />
          ))}
          {(
            [
              ["spam", String(ANALYTICS_SPAM_THRESHOLD), "Spam", `Source domain spam score ≥ ${ANALYTICS_SPAM_THRESHOLD}`],
              ["orphaned", "1", "Orphaned", "Source domain has no catalog/metrics row"],
              ["link_missing", "1", "Link missing", "The backlink is no longer on the page"],
              ["nofollow", "1", "Nofollow", "Links marked rel=nofollow"]
            ] as Array<[string, string, string, string]>
          ).map(([key, on, label, title]) => {
            const active = Boolean(filters[key]);
            return (
              <button
                key={key}
                onClick={() => setFilter(key, active ? "" : on)}
                title={title}
                className={clsx(
                  "h-9 rounded-full border px-3 text-xs font-medium transition",
                  active
                    ? "border-ocean bg-ocean/10 text-ocean"
                    : "border-line bg-panel text-muted hover:bg-field"
                )}
              >
                {label}
              </button>
            );
          })}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">Views</span>
          {views.map((v) => (
            <span key={v.name} className="inline-flex items-center gap-1 rounded-full border border-line bg-field px-2.5 py-1 text-xs">
              <button onClick={() => applyView(v.name)} className="font-medium text-ink hover:text-ocean">
                {v.name}
              </button>
              <button onClick={() => deleteView(v.name)} aria-label={`Delete view ${v.name}`} className="text-muted hover:text-danger">
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
          <input
            value={viewName}
            onChange={(e) => setViewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") saveView();
            }}
            placeholder="Save current as…"
            className="h-8 w-40 rounded-xl border border-line bg-panel shadow-card px-2 text-xs"
          />
          <button
            onClick={saveView}
            disabled={!viewName.trim()}
            className="h-8 rounded-lg border border-line px-2.5 text-xs font-medium text-ink transition hover:bg-field disabled:opacity-40"
          >
            Save view
          </button>
        </div>
      </div>

      {/* KPI stat boxes — ordered by the QA workflow (outcome first, then the
          technical HTTP/index breakdown). Clicking sets the matching analytics
          filter AND clears any open drill so the pivots refocus. */}
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 xl:grid-cols-12">
        {/* ── Workflow outcome (Qualified → Needs review → Not qualified → Broken → Duplicates → Missing → Spam) ── */}
        <StatBox label="Qualified" value={Number(s.qualified ?? s.pass ?? 0)} tone="ocean"
          help="Links that passed every check. Click to filter."
          onClick={() => kpiFilter({ status: "PASS" })} />
        <StatBox label="Needs review" value={Number(s.review || 0)} tone="plum"
          help="A human needs to look (e.g. JS page / CAPTCHA). Click to filter."
          onClick={() => kpiFilter({ status: "NEEDS_MANUAL_REVIEW" })} />
        <StatBox label="Not qualified" value={Number(s.non_qualified ?? s.fail ?? 0)} tone="danger"
          help="Links with a serious problem. Click to filter."
          onClick={() => kpiFilter({ status: "FAIL" })} />
        <StatBox label="Broken" value={Number(s.broken || 0)} tone="danger"
          help="Any 4xx/5xx source page (dead or erroring). Click to filter."
          onClick={() => kpiFilter({ broken: "1" })} />
        <StatBox label="Duplicates" value={Number(s.duplicates || 0)} tone="ember"
          help="Links pointing at a page another record already uses. Click to filter."
          onClick={() => kpiFilter({ duplicate_status: "duplicate" })} />
        <StatBox label="Missing" value={Number(s.link_missing || 0)} tone="danger"
          help="The backlink was not found on the page. Click to filter."
          onClick={() => kpiFilter({ link_missing: "1" })} />
        <StatBox label="Spam" value={Number(s.spam || 0)} tone="danger"
          help={`Links on a source domain with spam score ≥ ${ANALYTICS_SPAM_THRESHOLD}. Click to filter.`}
          onClick={() => kpiFilter({ spam: String(ANALYTICS_SPAM_THRESHOLD) })} />
        {/* ── Technical breakdown (index + HTTP status + orphaned) ── */}
        <StatBox label="Indexed" value={Number(s.indexed || 0)} tone="ocean"
          help="Pages Google shows in its index. Click to filter."
          onClick={() => kpiFilter({ index_status: "indexed" })} />
        <StatBox label="Not indexed" value={Number(s.not_indexed || 0)} tone="danger"
          help="Pages Google does not show. Click to filter."
          onClick={() => kpiFilter({ index_status: "not_indexed" })} />
        <StatBox label="200 OK" value={Number(s.http_200 || 0)} tone="ocean"
          help="Links whose source page returned HTTP 200 (loads fine). Click to filter."
          onClick={() => kpiFilter({ http_status: "200" })} />
        <StatBox label="404" value={Number(s.http_404 || 0)} tone="danger"
          help="Source page not found (404). Click to filter."
          onClick={() => kpiFilter({ http_status: "404" })} />
        <StatBox label="Orphaned" value={Number(s.orphaned || 0)} tone="plum"
          help="Links whose source domain has no catalog/metrics row. Click to filter."
          onClick={() => kpiFilter({ orphaned: "1" })} />
      </div>

      {/* Summary cards — number first, share-of-total as its own line, click = filter */}
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Total" value={total} icon={Link2} tone="ink"
          sub="Links matching the filters"
          help="How many links match the filters above. Change a filter and this updates instantly." />
        <Metric label="Indexed" value={Number(s.indexed || 0)} icon={CheckCircle2} tone="ocean"
          sub={`${pct(Number(s.indexed || 0), total)} of total`}
          help="Links whose page Google shows in its index — these actually help SEO. Click to filter to them."
          onClick={() => { setFilters((f) => ({ ...f, index_status: "indexed" })); setDrillKey(null); }} />
        <Metric label="Not indexed" value={Number(s.not_indexed || 0)} icon={XCircle} tone="danger"
          sub={`${pct(Number(s.not_indexed || 0), total)} of total`}
          help="Google does not show these pages — low SEO value until they get indexed. Click to filter to them."
          onClick={() => { setFilters((f) => ({ ...f, index_status: "not_indexed" })); setDrillKey(null); }} />
        <Metric label="Not qualified" value={Number(s.fail || 0)} icon={XCircle} tone="danger"
          sub={`${pct(Number(s.fail || 0), total)} of total`}
          help="Links with a serious problem (missing, dead page, blocked). These need action. Click to filter to them."
          onClick={() => { setFilters((f) => ({ ...f, status: "FAIL" })); setDrillKey(null); }} />
        <Metric label="Nofollow" value={Number(s.nofollow || 0)} icon={AlertTriangle} tone="ember"
          sub={`${pct(Number(s.nofollow || 0), total)} of total`}
          help="Links marked rel=nofollow — they pass less SEO value than dofollow links. Click to filter to them."
          onClick={() => { setFilters((f) => ({ ...f, rel: "nofollow" })); setDrillKey(null); }} />
        <Metric label="Duplicates" value={Number(s.duplicates || 0)} icon={Filter} tone="plum"
          sub={`${pct(Number(s.duplicates || 0), total)} of total`}
          help="Links that point at a page another record already uses. Click to filter to them."
          onClick={() => { setFilters((f) => ({ ...f, duplicate_status: "duplicate" })); setDrillKey(null); }} />
      </div>

      {/* Group-by pivot */}
      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
            Breakdown
            <HelpTip text="Pick what to group the filtered links by (user, project, link type…). Every row shows totals, quality and index stats for that group. Click a row to see the exact links behind the numbers." />
          </h3>
          <div className="flex items-center gap-2">
          <ExportButton
            disabled={!(q.data?.groups || []).length}
            onClick={() =>
              downloadCsv(
                `analytics-by-${groupBy}.csv`,
                ["Group", "Total", "Avg score", "Pass", "Warning", "Fail", "Indexed", "Nofollow", "Duplicates"],
                (q.data?.groups || []).map((g) => [
                  (g.label && String(g.label)) || String(g.key), g.total, g.avg_score,
                  g.pass, g.warning, g.fail, g.indexed, g.nofollow, g.duplicates
                ])
              )
            }
          />
          <select
            className="h-9 rounded-md border border-line bg-panel px-3 text-sm"
            value={groupBy}
            onChange={(e) => {
              setGroupBy(e.target.value);
              setDrillKey(null);
            }}
          >
            {GROUP_OPTIONS.map(([v, l]) => (
              <option key={v} value={v}>Group by {l}</option>
            ))}
          </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>{GROUP_OPTIONS.find(([v]) => v === groupBy)?.[1] || "Group"}</Th>
                <Th>Total</Th>
                <Th>Avg score</Th>
                <Th>Pass / Warn / Fail</Th>
                <Th>Indexed %</Th>
                <Th>Nofollow %</Th>
                <Th>Dups</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(q.data?.groups || []).map((g, i) => {
                const t = Number(g.total || 0);
                const name = (g.label && String(g.label)) || String(g.key);
                const active = drillKey === String(g.key);
                return (
                  <Fragment key={i}>
                    <tr
                      onClick={() => setDrillKey(active ? null : String(g.key))}
                      className={clsx("cursor-pointer hover:bg-field/60", active && "bg-ocean/5")}
                    >
                      <Td>
                        <span className="font-medium text-ocean hover:underline">
                          {groupBy === "link_type" ? linkTypeLabel(name) || "—" : name || "—"}
                        </span>
                        <span className="mt-1.5 block h-1 max-w-[180px] overflow-hidden rounded-full bg-field">
                          <span
                            className="block h-full rounded-full bg-ocean/60"
                            style={{ width: `${Math.round((t / maxGroup) * 100)}%` }}
                          />
                        </span>
                      </Td>
                      <Td>{t}</Td>
                      <Td>{g.avg_score ?? "-"}</Td>
                      <Td>
                        <span className="text-ocean">{Number(g.pass || 0)}</span> /{" "}
                        <span className="text-ember">{Number(g.warning || 0)}</span> /{" "}
                        <span className="text-danger">{Number(g.fail || 0)}</span>
                      </Td>
                      <Td>{pct(Number(g.indexed || 0), t)}</Td>
                      <Td>{pct(Number(g.nofollow || 0), t)}</Td>
                      <Td>{Number(g.duplicates || 0)}</Td>
                    </tr>
                    {active ? (
                      <tr>
                        <td colSpan={7} className="bg-field/40 p-3">
                          <div className="mb-2 flex items-center justify-between">
                            <h4 className="text-sm font-semibold text-ink">
                              {groupBy === "user" ? `Links by “${name}”` : `Links in “${groupBy === "link_type" ? linkTypeLabel(name) : name}”`}
                            </h4>
                            <button
                              onClick={(e) => { e.stopPropagation(); setDrillKey(null); }}
                              className="text-xs font-medium text-ocean hover:underline"
                            >
                              Close
                            </button>
                          </div>
                          {drill.isLoading ? (
                            <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
                          ) : !(drill.data?.records || []).length ? (
                            <Empty label="No links in this group" />
                          ) : (
                            <div className="overflow-x-auto rounded-lg border border-line bg-panel">
                              <table className="w-full text-left text-sm">
                                <thead className="bg-field text-xs uppercase text-muted">
                                  <tr><Th>Source page</Th><Th>Status</Th><Th>Score</Th><Th>Rel</Th></tr>
                                </thead>
                                <tbody className="divide-y divide-line">
                                  {(drill.data?.records || []).map((r) => (
                                    <tr key={String(r.id)} onClick={() => setDetailId(String(r.id))} className="cursor-pointer hover:bg-field/60">
                                      <Td>
                                        <a href={String(r.source_page_url)} target="_blank" rel="noreferrer"
                                          onClick={(e) => e.stopPropagation()}
                                          className="break-all text-ocean hover:underline">
                                          {String(r.source_page_url)}
                                        </a>
                                      </Td>
                                      <Td><Status value={String(r.status)} /></Td>
                                      <Td>{r.score ?? "-"}</Td>
                                      <Td>{r.current_rel || "-"}</Td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
          {!q.isLoading && !(q.data?.groups || []).length ? <Empty label="No data for these filters" /> : null}
          {q.isLoading ? (
            <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
          ) : null}
        </div>
      </div>

      {/* The actual links behind the numbers — same filters as the cards above. */}
      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Matching links</h2>
            <p className="mt-0.5 text-xs text-muted">
              The actual links behind these numbers — filtered exactly like the cards above. Click a row for full detail.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {links.data?.total != null ? (
              <span className="whitespace-nowrap text-xs text-muted">{links.data.total} total</span>
            ) : null}
            <button
              onClick={() => {
                const f: Record<string, string> = {};
                if (filters.assigned_user_label) f.user = filters.assigned_user_label;
                ["status", "index_status", "duplicate_status", "rel", "link_type", "source_domain", "http_status", "broken", "orphaned"].forEach((k) => {
                  if (filters[k]) f[k] = filters[k];
                });
                if (filters.spam) f.spam_min = filters.spam;
                if (filters.nofollow && !f.rel) f.rel = "nofollow";
                onOpenBacklinks(f);
              }}
              className="rounded-lg border border-line bg-field px-3 py-1.5 text-xs font-medium text-ink hover:bg-field/70"
            >
              Open in Backlinks
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Source page</Th>
                <Th>Target</Th>
                <Th>Status</Th>
                <Th>Score</Th>
                <Th>Metrics</Th>
                <Th>Checked</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(links.data?.items || []).map((row) => {
                let host = "";
                try {
                  host = new URL(row.source_page_url).hostname.replace(/^www\./, "");
                } catch {
                  /* ignore unparseable urls */
                }
                return (
                  <tr
                    key={row.id}
                    onClick={() => setDetailId(row.id)}
                    className="cursor-pointer hover:bg-field/60"
                  >
                    <Td>
                      <div className="max-w-[330px] truncate font-medium text-ink" title={row.source_page_url}>
                        {row.source_page_url}
                      </div>
                      {host ? <div className="text-xs text-muted">{host}</div> : null}
                    </Td>
                    <Td>
                      <div className="max-w-[260px] truncate text-ink" title={row.target_url}>{row.target_url}</div>
                    </Td>
                    <Td><Status value={row.override_status || row.status} compact /></Td>
                    <Td>{row.score ?? "-"}</Td>
                    <Td>
                      {row.domain_da != null || row.domain_as != null ? (
                        <span className="flex flex-wrap gap-1">
                          <MetricTag label="DA" value={row.domain_da} />
                          <MetricTag label="AS" value={row.domain_as} />
                        </span>
                      ) : (
                        <span className="text-xs text-muted">—</span>
                      )}
                    </Td>
                    <Td><span className="whitespace-nowrap">{row.last_checked_at ? formatDate(row.last_checked_at) : "—"}</span></Td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {links.isLoading ? (
            <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
          ) : null}
          {!links.isLoading && !(links.data?.items || []).length ? (
            <Empty label="No links match these filters." />
          ) : null}
          {(links.data?.items || []).length >= linksLimit ? (
            <div className="border-t border-line p-3 text-center">
              <button
                onClick={() => setLinksLimit((l) => Math.min(200, l + 50))}
                className="rounded-lg border border-line bg-field px-3 py-1.5 text-xs font-medium text-ink hover:bg-field/70"
              >
                Load more
              </button>
            </div>
          ) : null}
        </div>
      </div>

      {detailId ? (
        <BacklinkDetailDrawer token={token} backlinkId={detailId} onClose={() => setDetailId(null)} onNotice={onNotice} />
      ) : null}
    </section>
  );
}

function IndexBadge({ value }: { value: string }) {
  const map: Record<string, string> = {
    indexed: "bg-ocean/10 text-ocean",
    not_indexed: "bg-danger/10 text-danger",
    uncertain: "bg-ember/10 text-ember"
  };
  const label: Record<string, string> = {
    indexed: "indexed",
    not_indexed: "not indexed",
    uncertain: "idx ?"
  };
  return (
    <span className={clsx("mt-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", map[value] || "bg-field text-muted")}>
      {label[value] || value}
    </span>
  );
}

// 0-100 authority tag (DA/PA/AS): higher is better — ocean ≥ 60, ember 30-59, danger < 30.
function MetricTag({ label, value, title }: { label: string; value: number | null | undefined; title?: string }) {
  if (value == null) return <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase bg-field text-muted" title={title}>{label} —</span>;
  const tone = value >= 60 ? "bg-ocean/10 text-ocean" : value >= 30 ? "bg-ember/10 text-ember" : "bg-danger/10 text-danger";
  return <span className={clsx("inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", tone)} title={title}>{label} {value}</span>;
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="whitespace-nowrap px-3 py-2 font-semibold">{children}</th>;
}

// Clickable sortable column header — the one sorting affordance used everywhere.
function SortTh({
  label,
  sortKey,
  sort,
  dir,
  onSort,
  help
}: {
  label: string;
  sortKey: string;
  sort: string;
  dir: "asc" | "desc";
  onSort: (key: string) => void;
  help?: string;
}) {
  const active = sort === sortKey;
  return (
    <th className="whitespace-nowrap px-3 py-2 font-semibold">
      <button
        onClick={() => onSort(sortKey)}
        title={help || `Sort by ${label} (click again to flip direction)`}
        className={clsx(
          "inline-flex items-center gap-1 uppercase transition hover:text-ink",
          active ? "text-ocean" : ""
        )}
      >
        {label}
        <span className={clsx("text-[9px] leading-none", active ? "opacity-100" : "opacity-30")}>
          {active ? (dir === "asc" ? "▲" : "▼") : "▲▼"}
        </span>
      </button>
    </th>
  );
}

// Client-side sort helper for tables whose full data is already loaded.
function sortRows<T>(rows: T[], key: string, dir: "asc" | "desc", get: (row: T, key: string) => unknown): T[] {
  const mul = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = get(a, key);
    const bv = get(b, key);
    if (av == null && bv == null) return 0;
    if (av == null) return 1; // nulls always last
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * mul;
    return String(av).localeCompare(String(bv), undefined, { numeric: true }) * mul;
  });
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2 align-top">{children}</td>;
}

function Url({ value }: { value: string }) {
  return (
    <div className="flex max-w-[330px] items-center gap-1">
      <span className="min-w-0 truncate font-medium text-ink" title={value}>{value}</span>
      <CopyButton text={value} title="Copy URL" />
    </div>
  );
}

// One-line date+time, e.g. "04 Jul, 10:32 PM" — never wraps.
function formatDate(value: string | null) {
  if (!value) return "-";
  const text = new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  return text;
}

// Date only, e.g. "04 Jul 2026" — for link dates, joined dates, calendars.
function formatDay(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}

// Every date a backlink carries, in a sensible reading order. Reused by the grid
// cell tooltip, the CSV export, and the detail drawer so labels never drift.
// ``time`` = show time-of-day (formatDate) vs date only (formatDay).
const BACKLINK_DATE_FIELDS: Array<{ label: string; field: keyof BacklinkRow; time: boolean }> = [
  { label: "Placement", field: "placement_date", time: false },
  { label: "Discovery", field: "discovered_at", time: true },
  { label: "Import", field: "created_at", time: true },
  { label: "Sheet", field: "sheet_created_date", time: false },
  { label: "First QA", field: "first_qa_at", time: true },
  { label: "QA checked", field: "last_checked_at", time: true },
  { label: "Completion", field: "qa_completed_at", time: true },
  { label: "Index checked", field: "index_checked_at", time: true },
  { label: "Assignment", field: "assigned_at", time: true },
  { label: "Last modified", field: "updated_at", time: true }
];

// Multi-line tooltip listing every date type for a backlink row.
function dateAxisTooltip(row: BacklinkRow): string {
  return BACKLINK_DATE_FIELDS.map((d) => {
    const v = (row[d.field] as string | null | undefined) ?? null;
    return `${d.label}: ${v ? (d.time ? formatDate(v) : formatDay(v)) : "—"}`;
  }).join("\n");
}

// Sheet link types read like "Article Submission" — show the short human name
// ("Article") everywhere while keeping the raw value for filters/API calls.
function linkTypeLabel(name: string | null | undefined) {
  if (!name) return "";
  return name.replace(/\s*submissions?\s*$/i, "").trim() || name;
}

function compactNum(n: number) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

// Tooltip: how fresh the metric numbers are ("Checked recently" wording).
function metricAgeTitle(m?: SiteMetrics | null): string {
  const fetched = m?.fetched_at;
  if (!fetched) return "Metrics not checked yet";
  const days = Math.floor((Date.now() - new Date(fetched).getTime()) / 86400000);
  if (days <= 0) return "Checked today (reused if checked again soon — no extra API call)";
  return `Checked ${days} day${days === 1 ? "" : "s"} ago — reused while fresh to save API calls`;
}

// Compact grid cell: Similarweb → "#12.3K • 1.2M", Moz → "DA 50 / Spam 2".
function formatSiteMetric(m?: SiteMetrics | null) {
  if (!m) return "-";
  if (m.global_rank != null || m.monthly_visits != null) {
    const parts: string[] = [];
    if (m.global_rank != null) parts.push(`#${compactNum(m.global_rank)}`);
    if (m.monthly_visits != null) parts.push(compactNum(m.monthly_visits));
    return parts.join(" • ") || "-";
  }
  if (m.da != null || m.spam_score != null) {
    return `DA ${m.da ?? "-"} / Sp ${m.spam_score ?? "-"}`;
  }
  return "-";
}

// Fuller detail line with labels.
function formatSiteMetricLong(m?: SiteMetrics | null) {
  if (!m) return "Not fetched (metrics API not configured)";
  const parts: string[] = [];
  if (m.global_rank != null) parts.push(`Global rank #${m.global_rank.toLocaleString()}`);
  if (m.monthly_visits != null) parts.push(`Visits ${compactNum(m.monthly_visits)}`);
  if (m.category) parts.push(`Category ${m.category}`);
  if (m.da != null) parts.push(`DA ${m.da}`);
  if (m.pa != null) parts.push(`PA ${m.pa}`);
  if (m.spam_score != null) parts.push(`Spam ${m.spam_score}`);
  return parts.length ? parts.join("  •  ") : "No metrics returned for this domain";
}

function severityClass(value: string) {
  return {
    CRITICAL: "bg-danger/10 text-danger",
    HIGH: "bg-ember/15 text-ember",
    MEDIUM: "bg-ember/10 text-ember",
    LOW: "bg-field text-muted",
    INFO: "bg-ocean/10 text-ocean"
  }[value] || "bg-field text-muted";
}

const TEAM_ROLES: Role[] = ["admin", "manager", "qa", "viewer"];
const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  qa: "QA",
  viewer: "Viewer"
};
const ROLE_HINT: Record<Role, string> = {
  admin: "Full control, including team & workspace settings",
  manager: "Manage projects, links, alerts and reports",
  qa: "Run crawls, edit links and override verdicts",
  viewer: "Read-only dashboards and exports"
};

function MemberProjectsCell({
  token,
  userId,
  role,
  projects,
  onNotice
}: {
  token: string | null;
  userId: string;
  role: Role;
  projects: Project[];
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const scoped = useQuery({
    queryKey: ["member-projects", token, userId],
    enabled: Boolean(token) && role !== "admin",
    retry: false,
    queryFn: () => api<{ project_ids: string[] }>(`/team/members/${userId}/projects`, { token })
  });
  const save = useMutation({
    mutationFn: (ids: string[]) =>
      api<{ message: string }>(`/team/members/${userId}/projects`, {
        token,
        method: "PUT",
        body: JSON.stringify({ project_ids: ids })
      }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["member-projects", token, userId] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  if (role === "admin")
    return <span className="text-xs text-muted" title="Admins always see every project">All (admin)</span>;
  const ids = scoped.data?.project_ids || [];
  const emptyLabel = role === "viewer" ? "No projects yet" : "Dashboard";
  return (
    <span title="Which projects this member can see. Empty = a TeamLead/QA sees all; a User (viewer) sees none until you pick their projects.">
      <FilterMultiSelect
        label={ids.length ? `${ids.length} project${ids.length !== 1 ? "s" : ""}` : emptyLabel}
        options={projects.map((p) => ({ value: p.id, label: p.name }))}
        selected={ids}
        onChange={(v) => save.mutate(v)}
      />
    </span>
  );
}

type GmailAssignmentRow = { id: string; scope: string; target_label: string; assigned_at: string | null; notes: string | null };
type GmailAccountRow = {
  id: string; email: string; display_name: string | null; status: string;
  is_active: boolean; notes: string | null; last_used_at: string | null;
  user_count: number; project_count: number; assignments: GmailAssignmentRow[];
};

function GmailAccountsCard({
  token, members, projects, onNotice
}: {
  token: string | null;
  members: TeamMember[];
  projects: Project[];
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  // Per-account assign form state, keyed by account id.
  const [assignFor, setAssignFor] = useState<string | null>(null);
  const [scope, setScope] = useState<"user" | "project">("user");
  const [targetUser, setTargetUser] = useState("");
  const [targetProject, setTargetProject] = useState("");

  const [asgStatus, setAsgStatus] = useState<"all" | "active" | "revoked">("active");
  const [asgSearch, setAsgSearch] = useState("");
  const accountsQ = useQuery({
    queryKey: ["gmail-accounts", token],
    enabled: Boolean(token),
    queryFn: () => api<GmailAccountRow[]>("/gmail/accounts", { token })
  });
  type GmailAsgRow = {
    id: string; account_id: string; email: string; scope: string;
    user_name: string | null; project_name: string | null; assigned_by: string | null;
    assigned_at: string | null; unassigned_at: string | null; status: string;
    last_used_at: string | null; notes: string | null;
  };
  type GmailAsgResp = { items: GmailAsgRow[]; stats: { total: number; active: number; revoked: number; active_users: number; active_projects: number } };
  const assignmentsQ = useQuery({
    queryKey: ["gmail-assignments", token, asgStatus],
    enabled: Boolean(token),
    queryFn: () => api<GmailAsgResp>(`/gmail/assignments${asgStatus === "all" ? "" : `?status=${asgStatus}`}`, { token })
  });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["gmail-accounts"] });
    queryClient.invalidateQueries({ queryKey: ["gmail-assignments"] });
  };

  const create = useMutation({
    mutationFn: () => api<GmailAccountRow>("/gmail/accounts", { token, method: "POST", body: JSON.stringify({ email, display_name: displayName.trim() || null }) }),
    onSuccess: () => { onNotice("Gmail account added"); setEmail(""); setDisplayName(""); invalidate(); },
    onError: (e: Error) => onNotice(e.message)
  });
  const assign = useMutation({
    mutationFn: (accountId: string) => api<{ message: string }>("/gmail/assign", {
      token, method: "POST",
      body: JSON.stringify({ account_id: accountId, scope, user_id: scope === "user" ? targetUser : null, project_id: scope === "project" ? targetProject : null })
    }),
    onSuccess: (r) => { onNotice(r.message); setAssignFor(null); setTargetUser(""); setTargetProject(""); invalidate(); },
    onError: (e: Error) => onNotice(e.message)
  });
  const revoke = useMutation({
    mutationFn: (assignmentId: string) => api<{ message: string }>(`/gmail/assignments/${assignmentId}/revoke`, { token, method: "POST" }),
    onSuccess: () => { onNotice("Assignment revoked"); invalidate(); },
    onError: (e: Error) => onNotice(e.message)
  });
  const retire = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/gmail/accounts/${id}`, { token, method: "DELETE" }),
    onSuccess: (r) => { onNotice(r.message); invalidate(); },
    onError: (e: Error) => onNotice(e.message)
  });
  const markUsed = useMutation({
    mutationFn: (id: string) => api<GmailAccountRow>(`/gmail/accounts/${id}/used`, { token, method: "POST" }),
    onSuccess: () => { onNotice("Marked as used today"); invalidate(); },
    onError: (e: Error) => onNotice(e.message)
  });

  const accounts = accountsQ.data || [];
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="border-b border-line p-4">
          <h2 className="text-base font-semibold text-ink">Add a company Gmail account</h2>
          <p className="text-sm text-muted">
            Track which shared outreach address belongs to which person or project. This is a
            record-keeping layer — LinkSentinel doesn&apos;t connect to Gmail.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3 p-4">
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">Email</span>
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="outreach@company.com"
              className="h-9 w-64 rounded-lg border border-line bg-panel px-2 text-sm" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">Label (optional)</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="e.g. Outreach 1"
              className="h-9 w-48 rounded-lg border border-line bg-panel px-2 text-sm" />
          </label>
          <button onClick={() => create.mutate()} disabled={create.isPending || !email.includes("@")}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900">
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Add
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title={`Gmail accounts (${accounts.length})`} />
        {accountsQ.isLoading ? (
          <div className="p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
        ) : !accounts.length ? (
          <Empty label="No Gmail accounts yet — add one above." />
        ) : (
          <div className="divide-y divide-line">
            {accounts.map((a) => (
              <div key={a.id} className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="font-medium text-ink">{a.email}</span>
                    {a.display_name ? <span className="ml-2 text-xs text-muted">{a.display_name}</span> : null}
                    <div className="mt-0.5 text-[11px] text-muted">
                      {a.user_count} user{a.user_count === 1 ? "" : "s"} · {a.project_count} project{a.project_count === 1 ? "" : "s"}
                      {a.last_used_at ? ` · last used ${formatDay(a.last_used_at)}` : " · never marked used"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button onClick={() => markUsed.mutate(a.id)} className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:bg-field">Mark used</button>
                    <button onClick={() => setAssignFor(assignFor === a.id ? null : a.id)} className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ocean hover:bg-field">Assign</button>
                    <button onClick={() => { if (window.confirm(`Retire ${a.email}? Its history stays; active assignments are revoked.`)) retire.mutate(a.id); }} className="rounded-md border border-line px-2 py-1 text-xs font-medium text-muted hover:text-danger hover:bg-field">Retire</button>
                  </div>
                </div>

                {/* Active assignment chips */}
                {a.assignments.length ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {a.assignments.map((asg) => (
                      <span key={asg.id} className="flex items-center gap-1 rounded-full border border-line bg-field/60 px-2 py-0.5 text-[11px] text-ink">
                        <span className={clsx("rounded px-1 text-[9px] font-semibold uppercase", asg.scope === "user" ? "bg-ocean/15 text-ocean" : "bg-plum/15 text-plum")}>{asg.scope}</span>
                        {asg.target_label}
                        <button onClick={() => revoke.mutate(asg.id)} title="Revoke" className="text-muted hover:text-danger">×</button>
                      </span>
                    ))}
                  </div>
                ) : <p className="mt-2 text-xs text-muted">Not assigned to anyone yet.</p>}

                {/* Inline assign form */}
                {assignFor === a.id ? (
                  <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-field/40 p-2.5">
                    <select value={scope} onChange={(e) => setScope(e.target.value as "user" | "project")} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm">
                      <option value="user">To a user</option>
                      <option value="project">To a project</option>
                    </select>
                    {scope === "user" ? (
                      <select value={targetUser} onChange={(e) => setTargetUser(e.target.value)} className="h-8 w-56 rounded-lg border border-line bg-panel px-2 text-sm">
                        <option value="">Choose a user…</option>
                        {members.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name || m.email}</option>)}
                      </select>
                    ) : (
                      <select value={targetProject} onChange={(e) => setTargetProject(e.target.value)} className="h-8 w-56 rounded-lg border border-line bg-panel px-2 text-sm">
                        <option value="">Choose a project…</option>
                        {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    )}
                    <button
                      onClick={() => assign.mutate(a.id)}
                      disabled={assign.isPending || (scope === "user" ? !targetUser : !targetProject)}
                      className="h-8 rounded-lg bg-ocean px-3 text-xs font-semibold text-white transition hover:opacity-90 disabled:opacity-40 dark:text-slate-900"
                    >
                      Assign
                    </button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Detailed, filterable assignments table — who has which account, for what project */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
            Assignments
            <HelpTip text="Every Gmail assignment — to whom (user) and/or which project, who assigned it, when, and whether it's still active. Filter by status or search." />
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            {assignmentsQ.data ? (
              <span className="flex flex-wrap gap-1.5 text-[11px]">
                <span className="rounded-full bg-field px-2 py-0.5 text-muted">{assignmentsQ.data.stats.total} total</span>
                <span className="rounded-full bg-ocean/10 px-2 py-0.5 text-ocean">{assignmentsQ.data.stats.active} active</span>
                <span className="rounded-full bg-field px-2 py-0.5 text-muted">{assignmentsQ.data.stats.active_users} users</span>
                <span className="rounded-full bg-field px-2 py-0.5 text-muted">{assignmentsQ.data.stats.active_projects} projects</span>
              </span>
            ) : null}
            <input
              value={asgSearch}
              onChange={(e) => setAsgSearch(e.target.value)}
              placeholder="Search email / user / project…"
              className="h-8 w-52 rounded-lg border border-line bg-panel px-2 text-sm"
            />
            <select value={asgStatus} onChange={(e) => setAsgStatus(e.target.value as "all" | "active" | "revoked")} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm">
              <option value="active">Active</option>
              <option value="revoked">Revoked</option>
              <option value="all">All</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr><Th>Account</Th><Th>User</Th><Th>Project</Th><Th>Assigned by</Th><Th>Assigned</Th><Th>Last used</Th><Th>Status</Th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(assignmentsQ.data?.items || [])
                .filter((r) => {
                  const q = asgSearch.trim().toLowerCase();
                  if (!q) return true;
                  return [r.email, r.user_name, r.project_name].some((v) => (v || "").toLowerCase().includes(q));
                })
                .map((r) => (
                  <tr key={r.id} className="hover:bg-field/50">
                    <Td><span className="font-medium text-ink">{r.email}</span></Td>
                    <Td>{r.user_name ? <span className="rounded bg-ocean/10 px-1.5 py-0.5 text-xs text-ocean">{r.user_name}</span> : <span className="text-muted">—</span>}</Td>
                    <Td>{r.project_name ? <span className="rounded bg-plum/10 px-1.5 py-0.5 text-xs text-plum">{r.project_name}</span> : <span className="text-muted">—</span>}</Td>
                    <Td><span className="text-xs text-muted">{r.assigned_by || "—"}</span></Td>
                    <Td><span className="whitespace-nowrap text-xs text-muted">{r.assigned_at ? formatDay(r.assigned_at) : "—"}</span></Td>
                    <Td><span className="whitespace-nowrap text-xs text-muted">{r.last_used_at ? formatDay(r.last_used_at) : "never"}</span></Td>
                    <Td>
                      {r.status === "active" ? (
                        <button onClick={() => revoke.mutate(r.id)} className="rounded bg-ocean/10 px-1.5 py-0.5 text-xs font-medium text-ocean hover:bg-danger/10 hover:text-danger" title="Click to revoke">active ×</button>
                      ) : <span className="rounded bg-field px-1.5 py-0.5 text-xs text-muted">revoked</span>}
                    </Td>
                  </tr>
                ))}
            </tbody>
          </table>
          {assignmentsQ.data && !assignmentsQ.data.items.length ? <Empty label="No assignments yet." /> : null}
        </div>
      </section>
    </div>
  );
}

// ── Admin→user email composer (Phase 10 P8; SEND_EMAILS = Admin) ─────────────
function EmailUsersCard({
  token,
  members,
  projects,
  onNotice
}: {
  token: string | null;
  members: Array<{ user_id: string; email: string; full_name: string; role: string }>;
  projects: Project[];
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [roleTarget, setRoleTarget] = useState("");
  const [projectTarget, setProjectTarget] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const statusQ = useQuery({
    queryKey: ["email-status", token],
    enabled: Boolean(token),
    retry: false,
    queryFn: () => api<{ smtp_configured: boolean }>("/emails/status", { token })
  });
  const logQ = useQuery({
    queryKey: ["email-log", token],
    enabled: Boolean(token) && Boolean(statusQ.data),
    retry: false,
    queryFn: () =>
      api<Array<{ id: string; recipient: string | null; recipient_email: string | null; subject: string; status: string; error: string | null; created_at: string | null; sent_at: string | null }>>(
        "/emails/log?limit=50",
        { token }
      )
  });
  const templatesQ = useQuery({
    queryKey: ["email-templates", token],
    enabled: Boolean(token) && Boolean(statusQ.data),
    retry: false,
    queryFn: () => api<Array<{ name: string; subject: string; body: string }>>("/emails/templates", { token })
  });
  const send = useMutation({
    mutationFn: () =>
      api<{ queued: number }>("/emails/send", {
        token,
        method: "POST",
        body: JSON.stringify({
          user_ids: picked.size ? Array.from(picked) : null,
          role: roleTarget || null,
          project_id: projectTarget || null,
          subject: subject.trim(),
          body: body.trim()
        })
      }),
    onSuccess: (d) => {
      onNotice(`Queued ${d.queued} email${d.queued === 1 ? "" : "s"} — delivery status appears below.`);
      setSubject("");
      setBody("");
      setPicked(new Set());
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["email-log"] }), 1500);
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const toggle = (id: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const recipientSummary = picked.size
    ? `${picked.size} selected user${picked.size === 1 ? "" : "s"}`
    : roleTarget
    ? `every ${roleTarget}`
    : projectTarget
    ? `members of ${projects.find((p) => p.id === projectTarget)?.name || "the project"}`
    : "no recipients yet";

  if (statusQ.isError) {
    return (
      <section className="rounded-xl border border-line bg-panel p-6 text-center shadow-card">
        <p className="text-sm text-muted">Emailing users is available to workspace admins only.</p>
      </section>
    );
  }
  if (statusQ.data && !statusQ.data.smtp_configured) {
    return (
      <section className="rounded-xl border border-line bg-panel p-6 shadow-card">
        <h3 className="text-base font-semibold text-ink">Email is not set up yet</h3>
        <p className="mt-1 max-w-xl text-sm text-muted">
          To email your team from here, add the SMTP settings (SMTP_HOST, SMTP_PORT, SMTP_USER,
          SMTP_PASSWORD, SMTP_FROM) to the server&apos;s .env and restart. Everything else is ready —
          the composer, per-recipient delivery log and templates unlock automatically.
        </p>
      </section>
    );
  }
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Email users" />
        <div className="grid gap-4 p-4 lg:grid-cols-[300px_1fr]">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase text-muted">Recipients</div>
            <div className="max-h-[260px] space-y-1 overflow-y-auto rounded-lg border border-line p-2">
              {members.map((m) => (
                <label key={m.user_id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-field">
                  <input type="checkbox" checked={picked.has(m.user_id)} onChange={() => toggle(m.user_id)} />
                  <span className="min-w-0 flex-1 truncate">{m.full_name}</span>
                  <span className="text-[10px] uppercase text-muted">{m.role}</span>
                </label>
              ))}
            </div>
            <div className="mt-2 space-y-2">
              <select value={roleTarget} onChange={(e) => { setRoleTarget(e.target.value); if (e.target.value) setPicked(new Set()); }}
                className="h-9 w-full rounded-lg border border-line bg-panel px-2 text-sm">
                <option value="">…or a whole role</option>
                {["admin", "manager", "qa", "viewer"].map((r) => <option key={r} value={r}>Every {r}</option>)}
              </select>
              <SearchSelect
                value={projectTarget}
                onChange={(v) => { setProjectTarget(v); if (v) setPicked(new Set()); }}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
                placeholder="…or a project's members"
                width="w-full"
              />
            </div>
          </div>
          <div className="space-y-2">
            {templatesQ.data?.length ? (
              <select
                onChange={(e) => {
                  const t = (templatesQ.data || []).find((x) => x.name === e.target.value);
                  if (t) { setSubject(t.subject); setBody(t.body); }
                }}
                className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
                defaultValue=""
              >
                <option value="" disabled>Use a template…</option>
                {templatesQ.data.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
              </select>
            ) : null}
            <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200}
              placeholder="Subject" className="h-10 w-full rounded-lg border border-line bg-panel px-3 text-sm" />
            <textarea value={body} onChange={(e) => setBody(e.target.value)} maxLength={5000} rows={7}
              placeholder={"Message…\n\nPlaceholders: {{full_name}}, {{email}}, {{company}}"}
              className="w-full rounded-lg border border-line bg-panel p-3 text-sm" />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-muted">Sending to: <span className="font-semibold text-ink">{recipientSummary}</span></span>
              <button
                onClick={() => {
                  if (window.confirm(`Send this email to ${recipientSummary}?`)) send.mutate();
                }}
                disabled={send.isPending || !subject.trim() || !body.trim() || (!picked.size && !roleTarget && !projectTarget)}
                className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-4 text-sm font-semibold text-white disabled:opacity-50 dark:text-slate-900"
              >
                {send.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Send email
              </button>
            </div>
          </div>
        </div>
      </section>
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Delivery log" />
        <table className="w-full text-left text-sm">
          <thead className="bg-field text-xs uppercase text-muted">
            <tr><Th>To</Th><Th>Subject</Th><Th>Status</Th><Th>When</Th></tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(logQ.data || []).map((r) => (
              <tr key={r.id}>
                <Td>{r.recipient || "—"} <span className="text-xs text-muted">{r.recipient_email}</span></Td>
                <Td><span className="line-clamp-1">{r.subject}</span></Td>
                <Td>
                  <span className={clsx("rounded px-1.5 py-0.5 text-xs font-semibold",
                    r.status === "sent" ? "bg-ocean/10 text-ocean" : r.status === "failed" ? "bg-danger/10 text-danger" : "bg-field text-muted")}>
                    {r.status}
                  </span>
                  {r.error ? <span className="ml-2 text-xs text-danger">{r.error.slice(0, 60)}</span> : null}
                </Td>
                <Td>{formatDate(r.sent_at || r.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {!logQ.data?.length ? <Empty label="No emails sent yet." /> : null}
      </section>
    </div>
  );
}

function TeamDesk({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [password, setPassword] = useState("");
  // One desk, two sections: workspace accounts vs sheet-employee mapping.
  const [teamTab, setTeamTab] = useState<"members" | "employees" | "gmail" | "email">("members");

  const members = useQuery({
    queryKey: ["team", token],
    enabled: Boolean(token),
    retry: false,
    queryFn: () => api<TeamMember[]>("/team/members", { token })
  });
  const projectsQ = useQuery({
    queryKey: ["projects", token],
    enabled: Boolean(token),
    queryFn: () => api<Project[]>("/projects", { token })
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["team"] });

  const invite = useMutation({
    mutationFn: () =>
      api<TeamMember>("/team/members", {
        token,
        method: "POST",
        body: JSON.stringify({ email, full_name: fullName, role, password })
      }),
    onSuccess: () => {
      onNotice(`Invited ${email}`);
      setFullName("");
      setEmail("");
      setPassword("");
      setRole("viewer");
      invalidate();
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const changeRole = useMutation({
    mutationFn: (v: { userId: string; role: Role }) =>
      api<TeamMember>(`/team/members/${v.userId}`, {
        token,
        method: "PATCH",
        body: JSON.stringify({ role: v.role })
      }),
    onSuccess: () => {
      onNotice("Role updated");
      invalidate();
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const toggleActive = useMutation({
    mutationFn: (v: { userId: string; active: boolean }) =>
      api<TeamMember>(`/team/members/${v.userId}/active`, {
        token,
        method: "POST",
        body: JSON.stringify({ is_active: v.active })
      }),
    onSuccess: (m) => {
      onNotice(`${m.email} ${m.is_active ? "activated" : "deactivated"}`);
      invalidate();
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const resetPw = useMutation({
    mutationFn: (userId: string) =>
      api<{ temp_password: string }>(`/team/members/${userId}/reset-password`, {
        token,
        method: "POST"
      }),
    onSuccess: (r) => {
      window.prompt(
        "New temporary password (shown once — copy it and hand it to the user):",
        r.temp_password
      );
      onNotice("Password reset — temporary password shown.");
    },
    onError: (err: Error) => onNotice(err.message)
  });
  const leads = useQuery({
    queryKey: ["team-leads", token],
    enabled: Boolean(token),
    retry: false,
    queryFn: () =>
      api<Array<{ manager_user_id: string; labels: string[] }>>("/team/leads", { token })
  });
  const [leadDrafts, setLeadDrafts] = useState<Record<string, string>>({});
  const saveLeads = useMutation({
    mutationFn: (p: { manager_user_id: string; labels: string[] }) =>
      api<{ message: string }>("/team/leads", { token, method: "PUT", body: JSON.stringify(p) }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["team-leads"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  const remove = useMutation({
    mutationFn: (userId: string) =>
      api<{ message: string }>(`/team/members/${userId}`, { token, method: "DELETE" }),
    onSuccess: () => {
      onNotice("Member removed");
      invalidate();
    },
    onError: (err: Error) => onNotice(err.message)
  });

  if (members.error instanceof ApiError && members.error.status === 403) {
    return (
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Team & access" />
        <div className="p-8 text-center text-sm text-muted">
          <ShieldAlert className="mx-auto mb-3 h-8 w-8 text-plum" />
          Only workspace admins can manage team members.
        </div>
      </section>
    );
  }

  const canSubmit =
    Boolean(fullName.trim()) && Boolean(email.trim()) && password.length >= 10 && !invite.isPending;

  return (
    <div className="space-y-5">
      <span className="flex w-fit overflow-hidden rounded-lg border border-line text-xs font-medium">
        <button
          onClick={() => setTeamTab("members")}
          className={clsx("px-2.5 py-1 transition", teamTab === "members" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
        >
          Members &amp; roles
        </button>
        <button
          onClick={() => setTeamTab("employees")}
          title="Sheet employees — codes, name variants and account mapping"
          className={clsx("px-2.5 py-1 transition", teamTab === "employees" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
        >
          Employees &amp; mapping
        </button>
        <button
          onClick={() => setTeamTab("gmail")}
          title="Company Gmail accounts — who/what each address is assigned to"
          className={clsx("px-2.5 py-1 transition", teamTab === "gmail" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
        >
          Gmail accounts
        </button>
        <button
          onClick={() => setTeamTab("email")}
          title="Email your team members (needs SMTP configured on the server)"
          className={clsx("px-2.5 py-1 transition", teamTab === "email" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
        >
          Email users
        </button>
      </span>
      {teamTab === "gmail" ? (
        <GmailAccountsCard token={token} members={members.data || []} projects={projectsQ.data || []} onNotice={onNotice} />
      ) : null}
      {teamTab === "email" ? (
        <EmailUsersCard token={token} members={members.data || []} projects={projectsQ.data || []} onNotice={onNotice} />
      ) : null}
      {teamTab === "members" ? (<>
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="border-b border-line p-4">
          <h2 className="text-base font-semibold text-ink">Invite a teammate</h2>
          <p className="text-sm text-muted">
            Create an account in this workspace and assign a role. Share the temporary password so
            they can sign in and change it.
          </p>
        </div>
        <div className="grid gap-3 p-4 md:grid-cols-2 lg:grid-cols-4">
          <Field label="Full name" value={fullName} onChange={setFullName} />
          <Field label="Email" value={email} onChange={setEmail} />
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">Role</span>
            <select
              className="h-10 w-full rounded-md border border-line bg-panel px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
            >
              {TEAM_ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
          <Field label="Temp password (min 10)" value={password} onChange={setPassword} type="password" />
        </div>
        <div className="flex flex-col gap-3 border-t border-line p-4 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-xs text-muted">{ROLE_HINT[role]}</span>
          <button
            onClick={() => invite.mutate()}
            disabled={!canSubmit}
            className="flex h-9 items-center justify-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {invite.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            Invite member
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between border-b border-line p-4">
          <div>
            <h2 className="text-base font-semibold text-ink">Members</h2>
            <p className="text-sm text-muted">{members.data?.length ?? 0} in this workspace</p>
          </div>
          <Users className="h-5 w-5 text-ocean" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] text-left text-sm">
            <thead className="border-b border-line bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Member</Th>
                <Th>Role</Th>
                <Th>
                  <span title="Which projects this member can open. TeamLead/QA with none selected see all projects; Users (viewers) only see what you pick.">
                    Projects
                  </span>
                </Th>
                <Th>Status</Th>
                <Th>Last login</Th>
                <Th>Joined</Th>
                <Th> </Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(members.data || []).map((m) => (
                <tr key={m.user_id} className={clsx(!m.is_active && "opacity-60")}>
                  <Td>
                    <div className="font-medium text-ink">{m.full_name}</div>
                    <div className="text-xs text-muted">{m.email}</div>
                  </Td>
                  <Td>
                    <select
                      className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
                      value={m.role}
                      disabled={changeRole.isPending}
                      onChange={(e) =>
                        changeRole.mutate({ userId: m.user_id, role: e.target.value as Role })
                      }
                    >
                      {TEAM_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABEL[r]}
                        </option>
                      ))}
                    </select>
                  </Td>
                  <Td>
                    <MemberProjectsCell
                      token={token}
                      userId={m.user_id}
                      role={m.role}
                      projects={projectsQ.data || []}
                      onNotice={onNotice}
                    />
                  </Td>
                  <Td>
                    <span
                      className={clsx(
                        "inline-flex rounded border px-2 py-1 text-xs font-semibold",
                        m.is_active
                          ? "border-ocean/30 bg-ocean/10 text-ocean"
                          : "border-line bg-field text-muted"
                      )}
                    >
                      {m.is_active ? "Active" : "Inactive"}
                    </span>
                  </Td>
                  <Td>
                    <span className="whitespace-nowrap text-muted">{formatDay(m.last_login_at)}</span>
                  </Td>
                  <Td>
                    <span className="whitespace-nowrap text-muted">{formatDay(m.member_since)}</span>
                  </Td>
                  <Td>
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => resetPw.mutate(m.user_id)}
                        title="Set a new temporary password for this user"
                        className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:bg-field"
                      >
                        Reset password
                      </button>
                      <button
                        onClick={() => toggleActive.mutate({ userId: m.user_id, active: !m.is_active })}
                        className="rounded-md border border-line px-2 py-1 text-xs font-medium text-ink hover:bg-field"
                      >
                        {m.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(`Remove ${m.email} from this workspace?`)) {
                            remove.mutate(m.user_id);
                          }
                        }}
                        className="grid h-8 w-8 place-items-center rounded-md border border-line text-danger hover:bg-danger/10"
                        aria-label="Remove member"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {members.isLoading ? <Empty label="Loading members…" /> : null}
          {!members.isLoading && !members.data?.length ? <Empty label="No members yet" /> : null}
        </div>
      </section>

      {(members.data || []).some((m) => m.role === "manager") ? (
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Team lead assignments" />
          <p className="border-b border-line px-4 py-2.5 text-xs text-muted">
            Give each Team Lead (Manager role) the people they oversee — comma-separated user
            names as they appear in the sheets. With names set, that lead only sees those people
            in Performance, Tasks and Leave. Leave empty to let them see everyone.
          </p>
          <div className="divide-y divide-line">
            {(members.data || [])
              .filter((m) => m.role === "manager")
              .map((m) => {
                const saved = (leads.data || []).find((l) => l.manager_user_id === m.user_id);
                const value = leadDrafts[m.user_id] ?? (saved?.labels || []).join(", ");
                return (
                  <div key={m.user_id} className="flex flex-wrap items-center gap-2 p-3">
                    <span className="w-44 truncate text-sm font-medium text-ink">{m.full_name}</span>
                    <input
                      value={value}
                      onChange={(e) => setLeadDrafts((d) => ({ ...d, [m.user_id]: e.target.value }))}
                      placeholder="e.g. alex, tony, tim"
                      className="h-9 min-w-[240px] flex-1 rounded-lg border border-line bg-panel px-2 text-sm"
                    />
                    <button
                      onClick={() =>
                        saveLeads.mutate({
                          manager_user_id: m.user_id,
                          labels: value.split(",").map((s) => s.trim()).filter(Boolean)
                        })
                      }
                      disabled={saveLeads.isPending}
                      className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-ink transition hover:bg-field disabled:opacity-50"
                    >
                      Save
                    </button>
                  </div>
                );
              })}
          </div>
        </section>
      ) : null}
      </>) : (
        <EmployeesDesk token={token} onNotice={onNotice} />
      )}
    </div>
  );
}
