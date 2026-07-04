"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  EyeOff,
  FileSpreadsheet,
  Filter,
  Gauge,
  Globe,
  History,
  Info,
  Layers,
  Link2,
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
  UserCog,
  UserPlus,
  Users,
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
  BatchLog,
  ImportRowError,
  CompetitorDomain,
  CompetitorSheet,
  CompetitorSummary,
  ConflictGroup,
  ConflictSummary,
  Dashboard,
  EmployeeOverview,
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
  SiteMetrics,
  TeamMember,
  TokenPair
} from "@/lib/api";

type Tab = "overview" | "analytics" | "backlinks" | "conflicts" | "domains" | "competitors" | "imports" | "sheets" | "batches" | "alerts" | "reports" | "performance" | "tasks" | "team" | "employees" | "scoring" | "settings";

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

  const setActiveProjectId = (next: string) => {
    // Entering/leaving project context: keep the tab if the new nav has it,
    // otherwise land on the dashboard.
    const nextTab = navTabs(Boolean(next)).includes(tab) ? tab : "overview";
    setActiveProjectIdState(next);
    setTabState(nextTab);
    syncUrl(next, nextTab, true);
  };

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const p = q.get("project") ?? localStorage.getItem("ls_project") ?? "";
    const rawTab = q.get("tab") ?? localStorage.getItem("ls_tab");
    const t: Tab = isTab(rawTab) && navTabs(Boolean(p)).includes(rawTab) ? rawTab : "overview";
    setActiveProjectIdState(p);
    setTabState(t);
    syncUrl(p, t, false);

    const onPop = () => {
      const qq = new URLSearchParams(window.location.search);
      const pp = qq.get("project") || "";
      const tt = qq.get("tab");
      setActiveProjectIdState(pp);
      setTabState(isTab(tt) && navTabs(Boolean(pp)).includes(tt) ? tt : "overview");
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
            />
          </div>
        </aside>
        <section key={`${tab}-${activeProjectId}`} className="desk-enter min-w-0 flex-1 space-y-5">
          <MobileNav activeTab={tab} onTab={setTab} inProject={Boolean(activeProjectId)} />
          <div className="lg:hidden">
            <ProjectPanel
              token={token}
              projects={projects.data || []}
              activeProjectId={activeProjectId}
              onSelect={setActiveProjectId}
              onNotice={setNotice}
            />
          </div>
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
          {tab === "analytics" ? <AnalyticsDesk token={token} projectId={activeProjectId} /> : null}
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
            />
          ) : null}
          {tab === "competitors" ? (
            <CompetitorDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "imports" ? (
            <ImportDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "sheets" ? <SheetsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "batches" ? (
            <BatchesDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "performance" ? (
            <PerformanceDesk token={token} projectId={activeProjectId} />
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
          {tab === "employees" ? <EmployeesDesk token={token} onNotice={setNotice} /> : null}
          {tab === "scoring" ? (
            <ScoringDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "settings" ? (
            <SettingsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
        </section>
      </section>
    </main>
  );
}

function AuthPanel({ onToken }: { onToken: (tokens: TokenPair) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [fullName, setFullName] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [error, setError] = useState("");

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

  return (
    <main className="grid min-h-screen place-items-center px-5">
      <section className="w-full max-w-[460px] rounded-xl border border-line bg-panel shadow-card p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold uppercase text-ocean">LinkSentinel</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">
              {mode === "login" ? "Sign in" : "Create workspace"}
            </h1>
          </div>
          <ShieldAlert className="h-7 w-7 text-plum" aria-hidden />
        </div>
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
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">Password</span>
            <span className="relative block">
              <input
                type={showPw ? "text" : "password"}
                name="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
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
          {error ? <p className="rounded bg-danger/10 p-2 text-sm text-danger">{error}</p> : null}
          <button
            type="submit"
            disabled={submit.isPending || !email.trim() || !password}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-ocean px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
          >
            {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="w-full rounded-md border border-line px-4 py-2 text-sm font-medium text-ink transition hover:bg-field"
          >
            {mode === "login" ? "Create a new workspace" : "Use existing account"}
          </button>
        </form>
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
  { label: "Monitor", items: [["overview", "Overview", Gauge], ["analytics", "Analytics", BarChart3]] },
  {
    label: "Backlinks",
    items: [
      ["backlinks", "Backlinks", Link2],
      ["conflicts", "Duplicates", Layers],
      ["domains", "Source Domains", Globe],
      ["competitors", "Competitors", Swords]
    ]
  },
  { label: "Ingest", items: [["imports", "Imports", Upload], ["sheets", "Sheets", Sheet], ["batches", "Batches", History]] },
  { label: "Output", items: [["alerts", "Alerts", Bell], ["reports", "Reports", FileSpreadsheet]] },
  {
    label: "Workspace",
    items: [
      ["performance", "Performance", Activity],
      ["tasks", "Tasks & Calendar", CalendarDays],
      ["team", "Team", Users],
      ["employees", "Employees", UserCog],
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
  { label: "Ingest", items: [["imports", "Imports", Upload], ["batches", "Batches", History]] },
  {
    label: "Insights",
    items: [
      ["analytics", "Analytics", BarChart3],
      ["performance", "Performance", Activity],
      ["tasks", "Tasks", CalendarDays],
      ["reports", "Reports", FileSpreadsheet],
      ["alerts", "Alerts", Bell]
    ]
  },
  {
    label: "Configure",
    items: [["scoring", "Scoring", SlidersHorizontal], ["settings", "Settings", Settings]]
  }
];

const navGroups = (inProject: boolean): NavGroup[] => (inProject ? PROJECT_NAV : WORKSPACE_NAV);
const navTabs = (inProject: boolean): Tab[] =>
  navGroups(inProject).flatMap((g) => g.items.map(([id]) => id));
const ALL_TAB_IDS = new Set<string>([...navTabs(false), ...navTabs(true)]);
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
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-panel/70 backdrop-blur-xl">
      <div className="mx-auto flex w-full items-center justify-between px-5 py-1.5">
        <div className="flex items-center gap-2.5">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-ocean to-plum text-white shadow-soft">
            <Activity className="h-4 w-4" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-sm font-bold tracking-tight text-ink">LinkSentinel</span>
            <span className="hidden text-[10px] font-medium uppercase tracking-wide text-muted sm:inline">
              Backlink QA operations
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
  onNotice
}: {
  activeTab: Tab;
  onTab: (tab: Tab) => void;
  token: string | null;
  projects: Project[];
  activeProjectId: string;
  onSelect: (id: string) => void;
  onNotice: (text: string) => void;
}) {
  return (
    <div className="space-y-4">
      <ProjectPanel
        token={token}
        projects={projects}
        activeProjectId={activeProjectId}
        onSelect={onSelect}
        onNotice={onNotice}
      />
      {activeProjectId ? (
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
        {navGroups(Boolean(activeProjectId)).map((group) => (
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
  inProject
}: {
  activeTab: Tab;
  onTab: (tab: Tab) => void;
  inProject: boolean;
}) {
  return (
    <nav className="flex gap-1 overflow-x-auto rounded-xl border border-line bg-panel p-1 shadow-card scrollbar-thin lg:hidden">
      {navGroups(inProject).flatMap((g) => g.items).map(([id, label, Icon]) => (
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
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      onSelect(project.id);
      onNotice("Project created");
      setName("");
      setClient("");
      setDomain("");
      setShowCreate(false);
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
        <span
          className={clsx(
            "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xs font-bold text-white dark:text-slate-900",
            active ? "bg-gradient-to-br from-plum to-ocean" : "bg-gradient-to-br from-ocean to-teal-500"
          )}
        >
          {active ? initials(active.name) : <Globe className="h-4 w-4" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-ink">
            {active ? active.name : "All projects"}
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
                <span className="block text-sm font-medium text-ink">All projects</span>
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
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-plum to-ocean text-xs font-bold text-white dark:text-slate-900">
                  {initials(p.name)}
                </span>
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
                  createProject.mutate();
                }}
              >
                <Field label="Name" value={name} onChange={setName} />
                <Field label="Client" value={client} onChange={setClient} />
                <Field label="Target domain" value={domain} onChange={setDomain} />
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
  const [trendDays, setTrendDays] = useState("30");
  const trends = useQuery({
    queryKey: ["dashboard-trends", token, projectId, trendDays],
    enabled: Boolean(token),
    queryFn: () =>
      api<{
        new_links: number; new_domains: number; new_indexed: number;
        prev_links: number; prev_domains: number;
        weekly: Array<{ week: string; links: number; new_domains: number }>;
      }>(
        `/dashboard/trends?days=${trendDays}${projectId ? `&project_id=${projectId}` : ""}`,
        { token }
      )
  });

  const stats = dashboard.data;
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
        <Metric label="Needs improvement" value={stats?.totals.warning_count ?? 0} icon={AlertTriangle} tone="ember"
          help="Links that work but lost some value (e.g. nofollow, weak page, redirects). Click to review them."
          onClick={() => onOpenBacklinks({ status: "WARNING" })} />
        <Metric label="Not qualified" value={stats?.totals.fail_count ?? 0} icon={XCircle} tone="danger"
          help="Serious problems — the link is missing, the page is dead, or it can't be indexed. Click to fix them."
          onClick={() => onOpenBacklinks({ status: "FAIL" })} />
        <Metric label="Needs review" value={stats?.totals.review_count ?? 0} icon={ShieldAlert} tone="plum"
          help="We couldn't decide automatically (usually bot protection on the site). Click to check them yourself."
          onClick={() => onOpenBacklinks({ status: "NEEDS_MANUAL_REVIEW" })} />
        <Metric label="Avg score" value={stats?.totals.avg_score ?? "-"} icon={Gauge} tone="ink"
          help="Average quality score (0–100) across these links. Hover any score in the Backlinks list to see how it's calculated." />
      </div>

      {/* Timeframe activity + previous-period comparison */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Activity</h3>
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
        {(trends.data?.weekly || []).length ? (
          <div className="border-t border-line p-4">
            <TrendChart
              labels={(trends.data?.weekly || []).map((w) => w.week)}
              series={[
                { name: "Links added", cssVar: "--ocean", values: (trends.data?.weekly || []).map((w) => w.links) },
                { name: "New source domains", cssVar: "--plum", values: (trends.data?.weekly || []).map((w) => w.new_domains) }
              ]}
            />
          </div>
        ) : null}
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Issue Mix" />
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <Issue label="Nofollow" value={stats?.issues.nofollow_count ?? 0}
              help="Links marked rel=nofollow — they pass less SEO value. Click to see them."
              onClick={() => onOpenBacklinks({ rel: "nofollow" })} />
            <Issue label="Noindex" value={stats?.issues.noindex_count ?? 0}
              help="Pages that tell Google not to index them — the link there helps very little. Click to see them."
              onClick={() => onOpenBacklinks({ issue_label: "PAGE_NOINDEX" })} />
            <Issue label="Robots blocked" value={stats?.issues.robots_blocked_count ?? 0}
              help="Pages blocked by robots.txt — search engines can't even visit them. Click to see them."
              onClick={() => onOpenBacklinks({ issue_label: "ROBOTS_BLOCKED" })} />
            <Issue label="Canonical" value={stats?.issues.canonical_issue_count ?? 0}
              help="Pages that declare a different page as the 'real' one, weakening the link. Click to see them."
              onClick={() => onOpenBacklinks({ issue_label: "CANONICAL_MISMATCH" })} />
            <Issue label="Broken page" value={stats?.issues.broken_count ?? 0}
              help="Pages returning an error (404, 500…) — the link is effectively gone. Click to see them."
              onClick={() => onOpenBacklinks({ issue_label: "SOURCE_404" })} />
            <Issue label="Link missing" value={stats?.issues.link_missing_count ?? 0}
              help="The page loads fine, but your link is no longer on it. Click to see them."
              onClick={() => onOpenBacklinks({ issue_label: "LINK_MISSING" })} />
          </div>
        </section>
        <section className="rounded-xl border border-line bg-panel shadow-card">
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

          <section className="rounded-xl border border-line bg-panel shadow-card">
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
  const [sort, setSort] = useState("score");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [search, setSearch] = useState(() => fParam("search"));
  const [debouncedSearch, setDebouncedSearch] = useState(() => fParam("search"));
  const [targetInput, setTargetInput] = useState(() => fParam("target"));
  const [targetF, setTargetF] = useState(() => fParam("target"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Row selection for scoped "check these exact links" actions.
  const [picked, setPicked] = useState<Set<string>>(new Set());

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
  };
  const activeFilterCount = [status, dupFilter, indexFilter, rel, linkType, userF, domainF, issueLabel, debouncedSearch, targetF]
    .filter(Boolean).length;

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
    ["Duplicates", toks(dupFilter).includes("duplicate"), () => toggleTok(dupFilter, setDupFilter, "duplicate")]
  ];

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "50", with_total: "true" });
    if (projectId) params.set("project_id", projectId);  // omit → all projects
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
    if (sort) params.set("sort", sort);
    params.set("direction", sortDir);
    return params.toString();
  }, [projectId, status, dupFilter, indexFilter, rel, linkType, userF, domainF, issueLabel, debouncedSearch, targetF, sort, sortDir]);
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
    project_id: projectId || null,
    status: status || null,
    duplicate_status: dupFilter || null,
    index_status: indexFilter || null,
    rel: rel || null,
    link_type: linkType || null,
    assigned_user_label: userF || null,
    source_domain: domainF || null,
    issue_label: issueLabel || null,
    search: debouncedSearch || null,
    target: targetF || null
  });

  const [staleDays, setStaleDays] = useState("30");
  const recheck = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ job_id: string; queued: number }>("/backlinks/recheck", {
        token,
        method: "POST",
        body: JSON.stringify(body)
      }),
    onSuccess: (data) => {
      onNotice(
        data.queued
          ? `QA check started — ${data.queued} link${data.queued === 1 ? "" : "s"} queued. Watch progress in Batches.`
          : "Nothing to check in this scope — everything is already covered."
      );
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
            <ExportButton
              onClick={async () => {
                try {
                  const p2 = new URLSearchParams(query);
                  p2.set("limit", "200");
                  p2.set("with_total", "false");
                  const page = await api<Page<BacklinkRow>>(`/backlinks?${p2.toString()}`, { token });
                  downloadCsv(
                    "backlinks.csv",
                    ["Source URL", "Target URL", "Status", "Score", "Type", "User", "Index", "HTTP", "Rel", "Duplicate", "Link date", "Imported", "Checked"],
                    page.items.map((r) => [
                      r.source_page_url, r.target_url, r.override_status || r.status, r.score,
                      r.link_type, r.assigned_user_label, r.index_status, r.http_status,
                      r.current_rel, r.duplicate_status, r.sheet_created_date || "", r.created_at, r.last_checked_at
                    ])
                  );
                  onNotice(`Exported ${page.items.length} links (current filters).`);
                } catch (e) {
                  onNotice(e instanceof Error ? e.message : "Export failed");
                }
              }}
            />
            <button
              onClick={runIndexCheck}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Check whether source pages are indexed by Google (asks before spending API credits)"
            >
              {indexCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
              Check index
            </button>
            {picked.size ? (
              <button
                onClick={checkPicked}
                className="flex h-9 items-center gap-2 rounded-lg border border-ocean/40 bg-ocean/10 px-3 text-sm font-semibold text-ocean transition hover:bg-ocean/20"
                title="Re-crawl exactly the rows you ticked, even if they were checked recently"
              >
                <Play className="h-4 w-4" />
                Check selected ({picked.size})
              </button>
            ) : null}
            <button
              onClick={checkPending}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
              title="Check only links that have never been QA-checked (new imports) — the safe everyday action"
            >
              {recheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Check QA pending
            </button>
            <button
              onClick={checkFiltered}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Check exactly the links matching your current filters (asks first when no filter is set)"
            >
              <Filter className="h-4 w-4" />
              Check filtered
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
        </div>
      </div>
      <div className="max-h-[70vh] overflow-auto scrollbar-thin">
        <table className="min-w-[1600px] w-full border-collapse text-left text-sm">
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
              <SortTh label="Score" sortKey="score" sort={sort} dir={sortDir} onSort={onSortCol} />
              <SortTh label="Source" sortKey="source_domain" sort={sort} dir={sortDir} onSort={onSortCol}
                help="Sort by source domain A→Z" />
              <Th>Target</Th>
              <SortTh label="Type" sortKey="link_type" sort={sort} dir={sortDir} onSort={onSortCol} />
              <Th>User</Th>
              {!projectId ? <Th>Project</Th> : null}
              <Th>Index</Th>
              <SortTh label="HTTP" sortKey="http_status" sort={sort} dir={sortDir} onSort={onSortCol} />
              <Th>Rel</Th>
              <Th>Rank / Visits</Th>
              <Th>Issue</Th>
              <SortTh label="Link date" sortKey="created_at" sort={sort} dir={sortDir} onSort={onSortCol}
                help="The sheet's own link-building date when available (hover shows when it was imported). Sorted by import date." />
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
                <Td><Status value={row.override_status || row.status} reason={row.top_issue_label} /></Td>
                <Td>
                  <span onClick={(e) => e.stopPropagation()}>
                    <ScoreTip token={token} backlinkId={row.id} score={row.score} />
                  </span>
                </Td>
                <Td>
                  <Url value={row.source_page_url} />
                  {row.is_duplicate ? (
                    <span
                      className="mt-0.5 mr-1 inline-block rounded bg-ember/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ember"
                      title={row.duplicate_status || "duplicate"}
                    >
                      {(row.duplicate_status || "duplicate").replace("dup_", "").replace(/_/g, " ")}
                    </span>
                  ) : null}
                </Td>
                <Td>
                  <Url value={row.target_url} />
                  {(row.targets_on_source ?? 1) > 1 ? (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSearch(row.source_page_url);
                      }}
                      className="mt-0.5 inline-block rounded bg-plum/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-plum hover:bg-plum/20"
                      title={`This source page links to ${row.targets_on_source} different targets — click to see all of them`}
                    >
                      {row.targets_on_source} targets
                    </button>
                  ) : null}
                </Td>
                <Td><span className="whitespace-nowrap text-xs" title={row.link_type || undefined}>{linkTypeLabel(row.link_type) || "—"}</span></Td>
                <Td><span className="whitespace-nowrap text-xs font-medium text-ink">{row.assigned_user_label || "—"}</span></Td>
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
                <Td><span title={metricAgeTitle(row.extra?.metrics)}>{formatSiteMetric(row.extra?.metrics)}</span></Td>
                <Td><IssueWord label={row.top_issue_label} count={row.issue_count} /></Td>
                <Td>
                  <span
                    className="whitespace-nowrap text-xs text-muted"
                    title={`Imported ${formatDate(row.created_at ?? null)}${row.sheet_created_date ? " · Link date from the sheet" : " · No sheet date — showing import date"}`}
                  >
                    {formatDay(row.sheet_created_date ?? row.created_at ?? null)}
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

  const data = detail.data;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40 backdrop-blur-[2px]" onClick={onClose}>
      <aside
        className="h-full w-full max-w-[680px] overflow-y-auto bg-panel shadow-xl scrollbar-thin"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-panel px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink">Backlink detail</h2>
            <p className="truncate text-xs text-muted">{data?.source_page_url}</p>
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
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <KeyStat label="Status" node={<Status value={data.override_status || data.status} />} />
              <KeyStat label="Score" node={<span className="text-2xl font-semibold text-ink">{data.score ?? "-"}</span>} />
              <KeyStat label="HTTP" node={<span className="font-semibold">{data.http_status ?? "-"}</span>} />
              <KeyStat label="Indexable" node={<span className="font-medium">{data.indexability ?? "-"}</span>} />
            </div>

            <DetailBlock title="Link facts">
              <FactRow k="Target" v={data.target_url} />
              <FactRow k="Expected target" v={data.expected_target_url} />
              <FactRow k="Final URL" v={data.final_url} />
              <FactRow k="Rel (observed / expected)" v={`${data.current_rel ?? "-"} / ${data.expected_rel}`} />
              <FactRow k="Anchor (observed)" v={data.current_anchor_text} />
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
                v={data.index_status ? data.index_status.replace(/_/g, " ") : "not checked yet"}
              />
            </DetailBlock>

            {duplicates.data && duplicates.data.length > 0 ? (
              <DetailBlock title={`Duplicate occurrences (${duplicates.data.length})`}>
                <div className="space-y-1.5">
                  {duplicates.data.map((d) => (
                    <div key={d.id} className="rounded-md border border-line p-2 text-xs">
                      <div className="truncate font-medium text-ink" title={d.source_page_url}>{d.source_page_url}</div>
                      <div className="text-muted">
                        → {d.target_url} · {d.assigned_user_label || "no user"} · {(d.duplicate_status || "").replace(/_/g, " ")}
                      </div>
                    </div>
                  ))}
                </div>
              </DetailBlock>
            ) : null}

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
              <DetailBlock title="Score breakdown">
                <div className="space-y-1.5">
                  {data.score_breakdown.map((step, i) => (
                    <div key={`${step.code}-${i}`} className="flex items-center justify-between text-sm">
                      <span className="text-muted">
                        {step.code === "START" ? "Baseline" : step.code}
                        {step.note ? <span className="ml-2 text-xs">{step.note}</span> : null}
                      </span>
                      <span className={clsx("font-semibold", step.delta < 0 ? "text-danger" : "text-ink")}>
                        {step.cap_applied !== null ? `cap → ${step.cap_applied}` : step.delta === 0 ? "100" : step.delta}
                      </span>
                    </div>
                  ))}
                </div>
              </DetailBlock>
            ) : null}

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

function KeyStat({ label, node }: { label: string; node: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-field p-3">
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className="mt-1">{node}</div>
    </div>
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

function FactRow({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1 text-sm">
      <span className="shrink-0 text-muted">{k}</span>
      <span className="min-w-0 break-words text-right font-medium text-ink">{v || "-"}</span>
    </div>
  );
}

function ImportDesk({
  token,
  projectId,
  onNotice
}: {
  token: string | null;
  projectId: string;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [text, setText] = useState(samplePaste);
  const submit = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/imports/paste", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: projectId, text })
      }),
    onSuccess: (data) => {
      onNotice(`Import queued: ${data.id}`);
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });

  if (!projectId) {
    return (
      <section className="rounded-xl border border-line bg-panel shadow-card p-8 text-center text-sm text-muted">
        Select a project (top-left) to import links into it.
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <SectionTitle title="Paste Import" />
      <div className="space-y-3 p-4">
        <textarea
          className="min-h-[260px] w-full rounded-md border border-line bg-panel p-3 font-mono text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-ocean/20"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <button
          onClick={() => submit.mutate()}
          className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
        >
          {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          Queue import
        </button>
      </div>
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
  const todayIso = new Date().toISOString().slice(0, 10);
  const weekAgoIso = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10);
  const [from, setFrom] = useState(weekAgoIso);
  const [to, setTo] = useState(todayIso);

  type DayRow = {
    id: string; day: string; project_id: string; user_label: string; hours: number;
    link_type_names: string[]; expected_links: number; actual_links: number;
    completion_pct: number | null; excused: boolean; excuse_reason: string | null; note: string | null;
  };
  const report = useQuery({
    queryKey: ["day-report", token, from, to, projectId],
    enabled: Boolean(token),
    queryFn: () =>
      api<DayRow[]>(
        `/workforce/day-report?date_from=${from}&date_to=${to}${projectId ? `&project_id=${projectId}` : ""}`,
        { token }
      )
  });
  const [view, setView] = useState<"list" | "grid">("list");
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
  const [fDay, setFDay] = useState(todayIso);
  const [fUser, setFUser] = useState("");
  const [fProject, setFProject] = useState(projectId || "");
  const [fHours, setFHours] = useState("4");
  const [fTypes, setFTypes] = useState("");
  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  const addAssignment = useMutation({
    mutationFn: () =>
      api<{ id: string; expected_links: number }>("/workforce/assignments", {
        token,
        method: "POST",
        body: JSON.stringify({
          project_id: fProject || projectId, user_label: fUser.trim(), day: fDay,
          hours: Number(fHours) || 0,
          link_type_names: fTypes ? fTypes.split(",") : []
        })
      }),
    onSuccess: (r) => {
      onNotice(`Assigned — ${r.expected_links} links expected for that day.`);
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

  return (
    <section className="space-y-5">
      <div>
        <h2 className="text-base font-semibold text-ink">Tasks & calendar</h2>
        <p className="text-sm text-muted">
          Plan each person&apos;s day (hours × link types → expected links), then track completion
          against that day&apos;s plan. Approved leave and non-working days don&apos;t count against anyone.
        </p>
      </div>

      {/* Assign */}
      <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
        <SectionTitle title="Assign work" flush />
        <div className="flex flex-wrap items-end gap-2 pt-3">
          <input type="date" value={fDay} onChange={(e) => setFDay(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm" />
          <input value={fUser} onChange={(e) => setFUser(e.target.value)} placeholder="User (sheet name)…" className="h-9 w-40 rounded-lg border border-line bg-panel px-2 text-sm" />
          <select value={fProject} onChange={(e) => setFProject(e.target.value)} className="h-9 rounded-lg border border-line bg-panel px-2 text-sm">
            <option value="">Project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <input type="number" min={0} max={24} step={0.5} value={fHours} onChange={(e) => setFHours(e.target.value)} className="h-9 w-20 rounded-lg border border-line bg-panel px-2 text-sm" title="Hours" />
          <FilterMultiSelect
            label="Link types"
            options={(linkTypes.data || []).map((lt) => ({ value: lt.name }))}
            selected={fTypes ? fTypes.split(",") : []}
            onChange={(v) => setFTypes(v.join(","))}
          />
          <button
            onClick={() => addAssignment.mutate()}
            disabled={addAssignment.isPending || !fUser.trim() || !(fProject || projectId)}
            className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
          >
            {addAssignment.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Assign
          </button>
          <span className="text-xs text-muted">Expected links are calculated from the productivity settings below.</span>
        </div>
      </section>

      {/* Day report */}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line p-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
            Plan vs done
            <span className="flex overflow-hidden rounded-lg border border-line text-xs font-medium">
              <button
                onClick={() => setView("list")}
                className={clsx("px-2.5 py-1 transition", view === "list" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                List
              </button>
              <button
                onClick={() => setView("grid")}
                title="Schedule grid — people down the side, days across the top (like the Google Sheet)"
                className={clsx("px-2.5 py-1 transition", view === "grid" ? "bg-ocean text-white dark:text-slate-900" : "text-muted hover:bg-field")}
              >
                Schedule grid
              </button>
            </span>
          </h3>
          <div className="flex items-center gap-2 text-xs text-muted">
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm text-ink" />
            –
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-8 rounded-lg border border-line bg-panel px-2 text-sm text-ink" />
          </div>
        </div>
        {view === "grid" ? (
          <div className="overflow-x-auto">
            {(() => {
              const rows = report.data || [];
              const gridDays = Array.from(new Set(rows.map((r) => r.day))).sort();
              const gridUsers = Array.from(new Set(rows.map((r) => r.user_label))).sort();
              if (!rows.length)
                return report.isLoading ? (
                  <div className="flex justify-center p-5"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
                ) : (
                  <Empty label="No assignments in this period — add one above." />
                );
              return (
                <table className="w-full text-left text-sm">
                  <thead className="bg-field text-xs uppercase text-muted">
                    <tr>
                      <Th>User</Th>
                      {gridDays.map((d) => (
                        <Th key={d}><span title={d}>{d.slice(5)}</span></Th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {gridUsers.map((u) => (
                      <tr key={u} className="align-top">
                        <Td><span className="font-medium text-ink">{u}</span></Td>
                        {gridDays.map((d) => {
                          const cell = rows.filter((r) => r.user_label === u && r.day === d);
                          return (
                            <Td key={d}>
                              {cell.length ? (
                                <span className="block min-w-[110px] space-y-1">
                                  {cell.map((r) => (
                                    <span
                                      key={r.id}
                                      title={`${projectName(r.project_id)} — ${r.hours}h · ${r.link_type_names.map(linkTypeLabel).join(", ") || "any type"} · ${r.actual_links}/${r.expected_links} done${r.excused ? ` · ${r.excuse_reason}` : ""}`}
                                      className={clsx(
                                        "block rounded-md px-1.5 py-1 text-[11px] leading-tight",
                                        r.excused
                                          ? "bg-field text-muted"
                                          : (r.completion_pct ?? 0) >= 100
                                            ? "bg-ocean/10 text-ocean"
                                            : (r.completion_pct ?? 0) >= 60
                                              ? "bg-ember/10 text-ember"
                                              : "bg-danger/10 text-danger"
                                      )}
                                    >
                                      <span className="block truncate font-semibold">{projectName(r.project_id)}</span>
                                      <span className="block">
                                        {r.hours}h · {r.actual_links}/{r.expected_links}
                                        {r.excused ? " · excused" : ""}
                                      </span>
                                    </span>
                                  ))}
                                </span>
                              ) : (
                                <span className="text-xs text-muted">—</span>
                              )}
                            </Td>
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
                <Th>Expected</Th><Th>Done</Th><Th>Completion</Th><Th>{" "}</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(report.data || []).map((r) => (
                <tr key={r.id} className="hover:bg-field/60">
                  <Td>{r.day}</Td>
                  <Td><span className="font-medium text-ink">{r.user_label}</span></Td>
                  <Td>{projectName(r.project_id)}</Td>
                  <Td>{r.hours}h</Td>
                  <Td><span className="text-xs text-muted">{r.link_type_names.map(linkTypeLabel).join(", ") || "—"}</span></Td>
                  <Td>{r.expected_links}</Td>
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
                    <button
                      onClick={() => removeAssignment.mutate(r.id)}
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
          {!report.isLoading && !(report.data || []).length ? (
            <Empty label="No assignments in this period — add one above." />
          ) : null}
        </div>
        )}
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Productivity settings */}
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Productivity (links per hour)" />
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
          <div className="border-t border-line">
            <p className="flex items-center gap-1.5 px-3 pt-3 text-xs font-semibold uppercase tracking-wide text-muted">
              Per-person overrides
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
                {(productivity.data?.global || []).map((g) => (
                  <option key={g.link_type_name} value={g.link_type_name}>{g.link_type_name}</option>
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
function TrendChart({
  labels,
  series,
  height = 170
}: {
  labels: string[];
  series: Array<{ name: string; cssVar: string; values: number[] }>;
  height?: number;
}) {
  const W = 640;
  const H = height;
  const PADX = 34;
  const PADY = 22;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const x = (i: number) =>
    labels.length <= 1 ? W / 2 : PADX + (i * (W - PADX * 2)) / (labels.length - 1);
  const y = (v: number) => H - PADY - (v / max) * (H - PADY * 2);
  if (!labels.length) return <Empty label="Not enough data for a chart yet." />;
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap gap-3 px-1">
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5 text-[11px] font-medium text-muted">
            <span className="h-2 w-2 rounded-full" style={{ background: `rgb(var(${s.cssVar}))` }} />
            {s.name}
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
              {s.values.map((v, i) => (
                <circle key={i} cx={x(i)} cy={y(v)} r="3" fill={`rgb(var(${s.cssVar}))`}>
                  <title>{`${labels[i]} — ${s.name}: ${v}`}</title>
                </circle>
              ))}
            </g>
          );
        })}
        {labels.map((l, i) =>
          labels.length <= 8 || i === 0 || i === labels.length - 1 || i % Math.ceil(labels.length / 6) === 0 ? (
            <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="9" fill="rgb(var(--muted))">
              {l.slice(5)}
            </text>
          ) : null
        )}
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

const TIMEFRAMES: Array<[string, string]> = [
  ["30", "Last 30 days"],
  ["90", "Last 3 months"],
  ["180", "Last 6 months"],
  ["365", "Last 12 months"],
  ["3650", "All time"]
];

function PerformanceDesk({ token, projectId }: { token: string | null; projectId: string }) {
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
  const customReady = days !== "custom" || Boolean(customFrom && customTo);
  const cmpReady = cmpMode !== "custom" || Boolean(cmpFrom && cmpTo);
  const perf = useQuery({
    queryKey: ["performance", token, days, customFrom, customTo, cmpMode, cmpFrom, cmpTo, projectId],
    enabled: Boolean(token) && customReady && cmpReady,
    queryFn: () => {
      const p = new URLSearchParams();
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
          <TrendChart
            labels={weekly.map((w) => w.week)}
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
                    <Td><span className="font-medium text-ocean hover:underline">{u.user_label}</span></Td>
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
                                <a href={r.source_page_url} target="_blank" rel="noreferrer" className="flex-1 truncate text-ocean hover:underline">
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
  import: "Import",
  sheet_sync: "Sheet sync",
  writeback: "Write-back",
  crawl: "Check",
  recheck: "Recheck",
  index_check: "Index check",
  duplicate_scan: "Duplicate scan",
  rescore: "Re-score",
  competitor_import: "Competitor upload",
  competitor_check: "Competitor metrics check",
  report: "Report"
};

function BatchProgress({ totals }: { totals: Record<string, number> }) {
  const total = Number(totals.total || 0);
  const done = Number(totals.done ?? totals.ok ?? 0);
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
  const [errorImportId, setErrorImportId] = useState<string | null>(null);

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
    enabled: Boolean(token),
    queryFn: () => api<Batch[]>(`/batches${qs()}`, { token }),
    // Live progress: poll while anything is running.
    refetchInterval: (q) =>
      (q.state.data || []).some((b) => b.status === "running" || b.status === "pending") ? 3000 : false
  });
  const logs = useQuery({
    queryKey: ["batch-logs", token, openId],
    enabled: Boolean(token) && Boolean(openId),
    queryFn: () => api<BatchLog[]>(`/batches/${openId}/logs`, { token })
  });
  const rowErrors = useQuery({
    queryKey: ["import-errors", token, errorImportId],
    enabled: Boolean(token) && Boolean(errorImportId),
    queryFn: () =>
      api<{ total_errors: number; rows: ImportRowError[] }>(
        `/imports/${errorImportId}/errors.json`,
        { token }
      )
  });
  const queryClient = useQueryClient();
  const deleteBatch = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/batches/${id}`, { token, method: "DELETE" }),
    onSuccess: (r) => {
      onNotice(r.message);
      setOpenId(null);
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">Batches</h2>
        <p className="text-sm text-muted">
          Every run in one place — imports, sheet syncs, checks, duplicate scans, re-scores and
          reports — with live progress, counters and logs.
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
          {["running", "completed", "partial", "failed", "pending"].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <ExportButton
          disabled={!(batches.data || []).length}
          onClick={() =>
            downloadCsv(
              "batches.csv",
              ["Kind", "Label", "Status", "Total", "OK", "Failed", "Skipped", "Counters", "Started", "Finished", "Error"],
              (batches.data || []).map((b) => [
                BATCH_KIND_LABEL[b.kind] || b.kind, b.label, b.status,
                b.totals?.total, b.totals?.ok, b.totals?.failed, b.totals?.skipped,
                Object.entries(b.counters || {}).map(([k, v]) => `${k}=${v}`).join("; "),
                b.started_at, b.finished_at, b.error
              ])
            )
          }
        />
      </div>

      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr>
                <Th>What ran</Th><Th>Status</Th><Th>Progress</Th><Th>Counters</Th><Th>Started</Th><Th>Duration</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(batches.data || []).map((b) => {
                const open = openId === b.id;
                const dur =
                  b.finished_at
                    ? `${Math.max(1, Math.round((new Date(b.finished_at).getTime() - new Date(b.started_at).getTime()) / 1000))}s`
                    : "…";
                const counterBits = Object.entries(b.counters || {})
                  .filter(([, v]) => Number(v) > 0)
                  .map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`);
                return (
                  <Fragment key={b.id}>
                    <tr
                      onClick={() => {
                        setOpenId(open ? null : b.id);
                        setErrorImportId(null);
                      }}
                      className={clsx("cursor-pointer hover:bg-field/60", open && "bg-ocean/5")}
                    >
                      <Td>
                        <div className="font-medium text-ink">{BATCH_KIND_LABEL[b.kind] || b.kind}</div>
                        <div className="max-w-[320px] truncate text-xs text-muted">{b.label || "—"}</div>
                      </Td>
                      <Td><Status value={b.status} /></Td>
                      <Td><BatchProgress totals={b.totals || {}} /></Td>
                      <Td>
                        <span className="text-xs text-muted">
                          {counterBits.length ? counterBits.join(" · ") : "—"}
                        </span>
                      </Td>
                      <Td><span className="whitespace-nowrap">{formatDate(b.started_at)}</span></Td>
                      <Td>{dur}</Td>
                    </tr>
                    {open ? (
                      <tr>
                        <td colSpan={6} className="bg-field/40 p-4">
                          {b.error ? (
                            <div className="mb-2 rounded-lg border border-danger/30 bg-danger/10 p-2.5 text-sm text-danger">
                              Stopped because: {b.error}
                            </div>
                          ) : null}
                          {b.meta?.current_step ? (
                            <div className="mb-2 text-xs text-muted">Current step: {String(b.meta.current_step)}</div>
                          ) : null}
                          {b.status !== "running" ? (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                if (window.confirm("Remove this run and its logs from history? (Admin only)")) {
                                  deleteBatch.mutate(b.id);
                                }
                              }}
                              className="mb-2 flex items-center gap-1.5 text-xs font-medium text-danger hover:underline"
                            >
                              <Trash2 className="h-3.5 w-3.5" /> Remove from history
                            </button>
                          ) : null}
                          <div className="space-y-1">
                            {(logs.data || []).map((l, i) => (
                              <div key={i} className="flex items-start gap-2 text-xs">
                                <span
                                  className={clsx(
                                    "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                                    l.level === "error" ? "bg-danger" : l.level === "warn" ? "bg-ember" : "bg-ocean"
                                  )}
                                />
                                <span className="text-muted">{formatDate(l.created_at)}</span>
                                <span className="flex-1 text-ink">{l.message}</span>
                                {l.data && (l.data as Record<string, unknown>).import_id ? (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setErrorImportId(String((l.data as Record<string, unknown>).import_id));
                                    }}
                                    className="shrink-0 font-medium text-ocean hover:underline"
                                  >
                                    View row errors
                                  </button>
                                ) : null}
                              </div>
                            ))}
                            {logs.isLoading ? <div className="text-xs text-muted">Loading logs…</div> : null}
                            {!logs.isLoading && !(logs.data || []).length ? (
                              <div className="text-xs text-muted">No log entries for this run.</div>
                            ) : null}
                          </div>
                          {errorImportId ? (
                            <div className="mt-3 rounded-lg border border-line bg-panel p-2">
                              <div className="mb-1.5 flex items-center justify-between">
                                <span className="text-xs font-semibold text-ink">
                                  Row errors {rowErrors.data ? `(${rowErrors.data.total_errors})` : ""}
                                </span>
                                <button onClick={() => setErrorImportId(null)} className="text-xs text-ocean hover:underline">
                                  Close
                                </button>
                              </div>
                              <div className="max-h-64 overflow-y-auto">
                                {(rowErrors.data?.rows || []).map((r) => (
                                  <div key={r.row_number} className="border-b border-line py-1.5 text-xs last:border-0">
                                    <span className="font-semibold text-ink">Row {r.row_number}:</span>{" "}
                                    <span className="text-danger">{r.error}</span>
                                    <div className="mt-0.5 break-all text-muted">
                                      {Object.entries(r.raw || {})
                                        .filter(([, v]) => v)
                                        .slice(0, 6)
                                        .map(([k, v]) => `${k}: ${v}`)
                                        .join(" · ")}
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
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
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
    const rows = domains.data || [];
    const head = "domain,status,competitor_links,our_links,indexed_pct,da,pa,guest_post";
    const body = rows
      .map((d) =>
        [
          d.domain_key,
          d.decision === "dismissed" ? "dismissed" : d.category,
          d.url_count,
          d.our_link_count,
          d.our_indexed_pct ?? "",
          d.da ?? "",
          d.pa ?? "",
          d.has_guest_post ? "yes" : ""
        ].join(",")
      )
      .join("\n");
    const blob = new Blob([`${head}\n${body}`], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "competitor-opportunities.csv";
    a.click();
    URL.revokeObjectURL(url);
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

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Domains" value={s?.domains ?? 0} icon={Globe} tone="ink"
          help="All the websites your competitor has links from (grouped by domain)." />
        <Metric label="New opportunities" value={s?.new_opportunities ?? 0} icon={Star} tone="ocean"
          help="Websites the competitor has links from but this project doesn't yet — your outreach list." />
        <Metric label="Already have" value={s?.existing ?? 0} icon={CheckCircle2} tone="plum"
          help="Websites where this project already has a link — removed from the opportunity list automatically." />
        <Metric label="Competitor links" value={s?.competitor_links ?? 0} icon={Link2} tone="ink"
          help="Total competitor backlinks you've uploaded for this project." />
      </div>

      <section className="rounded-xl border border-line bg-panel shadow-card p-4">
        <SectionTitle title="Upload competitor links" flush />
        <div className="space-y-3 pt-3">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Competitor website URL (required)" value={compUrl} onChange={setCompUrl} name="competitor-url" />
            <Field label="Display name (optional — the domain is used if blank)" value={name} onChange={setName} />
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

      {(sheets.data || []).length ? (
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Uploads" />
          <div className="divide-y divide-line">
            {(sheets.data || []).map((sh) => (
              <div key={sh.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
                <div className="min-w-0">
                  <span className="font-medium text-ink">{sh.name}</span>{" "}
                  {sh.competitor_url ? (
                    <a
                      href={sh.competitor_url}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="mr-1 text-xs text-ocean hover:underline"
                    >
                      {sh.competitor_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
                    </a>
                  ) : null}
                  <span className="whitespace-nowrap text-xs text-muted" title="New = domains first seen in this upload · Seen before = domains an earlier upload already covered">
                    {sh.total_rows} links · {sh.new_domains} new domain{sh.new_domains === 1 ? "" : "s"} / {sh.existing_domains} seen before · {formatDate(sh.created_at)}
                  </span>
                </div>
                <button
                  onClick={() => {
                    if (window.confirm(`Delete upload “${sh.name}” and its ${sh.total_rows} competitor links? Opportunities will be recalculated.`)) {
                      deleteSheet.mutate(sh.id);
                    }
                  }}
                  className="grid h-8 w-8 place-items-center rounded-md border border-line text-danger transition hover:bg-danger/10"
                  aria-label={`Delete upload ${sh.name}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
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
  const view = useQuery({
    queryKey: ["sd-project-view", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () =>
      api<{ used: ProjectDomainRow[]; available: ProjectDomainRow[]; used_count: number; available_count: number }>(
        `/source-domains/project-view?project_id=${projectId}`,
        { token }
      )
  });
  const rows = mode === "used" ? view.data?.used || [] : view.data?.available || [];
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
            Used here ({view.data?.used_count ?? 0})
          </button>
          <button
            onClick={() => setMode("available")}
            title="Domains the workspace already knows, but this project has no link from yet — adding one counts as a NEW source domain for this project"
            className={clsx(
              "h-8 rounded-full border px-3 text-xs font-medium transition",
              mode === "available" ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
            )}
          >
            Available — not used yet ({view.data?.available_count ?? 0})
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
                <Td><span className="break-all text-ocean hover:underline">{r.domain_key}</span></Td>
                <Td>{mode === "used" ? r.project_links : r.global_links}</Td>
                <Td>{mode === "used" ? (r.indexed ?? 0) : (r.project_count ?? 0)}</Td>
                <Td>{r.da ?? "-"}</Td>
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
      </div>
    </section>
  );
}

function SourceDomainsDesk({
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
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("backlinks");

  const domains = useQuery({
    queryKey: ["source-domains", token, sort, search],
    enabled: Boolean(token),
    queryFn: () =>
      api<SourceDomain[]>(
        `/source-domains?sort=${sort}&order=desc&search=${encodeURIComponent(search)}`,
        { token }
      )
  });
  const recompute = useMutation({
    mutationFn: () => api<SourceDomain[]>("/source-domains/recompute", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Source-domain metrics refreshed");
      queryClient.invalidateQueries({ queryKey: ["source-domains"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const fetchMetrics = useMutation({
    mutationFn: () => api<SourceDomain[]>("/source-domains/fetch-metrics", { token, method: "POST" }),
    onSuccess: () => {
      onNotice("Domain metrics updated (age is live; DA/Semrush need RapidAPI keys)");
      queryClient.invalidateQueries({ queryKey: ["source-domains"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          Every backlink grouped by its source website. Ratios are read from stored counts — no full
          scans.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            className="h-9 w-44 rounded-md border border-line bg-panel px-3 text-sm"
            placeholder="Search domain…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="backlinks">Most backlinks</option>
            <option value="indexed">Most indexed</option>
            <option value="avg_score">Avg score</option>
            <option value="duplicates">Most duplicates</option>
            <option value="domain">Domain A–Z</option>
          </select>
          <button
            onClick={() => recompute.mutate()}
            className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
          >
            {recompute.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Recompute
          </button>
          <button
            onClick={() => fetchMetrics.mutate()}
            className="flex h-9 items-center gap-2 rounded-md border border-line bg-panel px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            {fetchMetrics.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
            Fetch metrics
          </button>
        </div>
      </div>
      {projectId ? (
        <ProjectDomainsPanel token={token} projectId={projectId} onOpenBacklinks={onOpenBacklinks} />
      ) : null}
      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <Th>Source domain</Th>
                <Th>Backlinks</Th>
                <Th>Indexed</Th>
                <Th>Dofollow</Th>
                <Th>DA</Th>
                <Th>AS</Th>
                <Th>Traffic</Th>
                <Th>Age</Th>
                <Th>Dupes</Th>
                <Th>Avg score</Th>
                <Th>Projects</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(domains.data || []).map((d) => (
                <SourceDomainRow key={d.id} d={d} token={token} />
              ))}
            </tbody>
          </table>
          {!domains.isLoading && !domains.data?.length ? (
            <Empty label="No source domains yet — click Recompute (or import some backlinks)." />
          ) : null}
        </div>
      </section>
    </section>
  );
}

function SourceDomainRow({ d, token }: { d: SourceDomain; token: string | null }) {
  const [open, setOpen] = useState(false);
  const detail = useQuery({
    queryKey: ["source-domain", token, d.id],
    enabled: Boolean(token && open),
    queryFn: () => api<SourceDomainDetail>(`/source-domains/${d.id}`, { token })
  });
  const dist = Object.entries(d.link_type_distribution || {});
  return (
    <>
      <tr className="cursor-pointer hover:bg-field/40" onClick={() => setOpen(!open)}>
        <Td>
          <div className="flex items-center gap-2">
            {open ? (
              <ChevronUp className="h-4 w-4 shrink-0 text-muted" />
            ) : (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted" />
            )}
            <span className="font-medium text-ink">{d.domain_key}</span>
          </div>
        </Td>
        <Td>{d.backlink_count}</Td>
        <Td>
          <span className="font-medium text-ink">{d.indexed_pct}%</span>{" "}
          <span className="text-xs text-muted">
            ({d.indexed_count}/{d.indexed_count + d.not_indexed_count})
          </span>
        </Td>
        <Td>{d.dofollow_pct}%</Td>
        <Td>{d.da ?? "—"}</Td>
        <Td>{d.semrush_as ?? "—"}</Td>
        <Td>{d.semrush_traffic != null ? compactNum(d.semrush_traffic) : "—"}</Td>
        <Td>
          {d.domain_age_days != null ? (
            <span title={`${d.domain_age_days} days`}>{Math.floor(d.domain_age_days / 365)}y</span>
          ) : (
            "—"
          )}
        </Td>
        <Td>{d.duplicate_count}</Td>
        <Td>{d.avg_score ?? "—"}</Td>
        <Td>{d.project_count}</Td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={11} className="bg-field/30 px-4 py-3">
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

  const d = data.data;
  const users = d?.app_users || [];
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

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <SectionTitle title="Sheet users → app accounts" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <Th>Sheet user</Th>
                <Th>Backlinks</Th>
                <Th>Mapped to</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(d?.mappings || []).map((m) => (
                <tr key={m.id}>
                  <Td>
                    <span className="font-medium text-ink">{m.sheet_user_label}</span>
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
                </tr>
              ))}
            </tbody>
          </table>
          {d && !d.mappings.length ? (
            <Empty label="No sheet users yet — click 'Sync from sheets'." />
          ) : null}
        </div>
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

function LinkTypesCard({
  token,
  onNotice
}: {
  token: string | null;
  onNotice: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const types = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["link-types"] });
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
  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <SectionTitle title="Link types (workspace catalog)" />
      <div className="space-y-3 p-4">
        <p className="text-xs text-muted">
          The catalog of backlink types (Web 2.0, Profile, Guest Post…). Used by scoring, filters,
          and competitor analysis. Imports auto‑add types they encounter.
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
      </div>
    </section>
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
      <LinkTypesCard token={token} onNotice={onNotice} />
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
  const [statusFilter, setStatusFilter] = useState<string>("open");
  // "New" = the group was first detected in the last 7 days (vs previously known).
  const [ageFilter, setAgeFilter] = useState<"" | "new" | "old">("");

  const summary = useQuery({
    queryKey: ["conflict-summary", token],
    enabled: Boolean(token),
    queryFn: () => api<ConflictSummary>("/conflicts/summary", { token })
  });
  const conflictsRaw = useQuery({
    queryKey: ["conflicts", token, statusFilter],
    enabled: Boolean(token),
    queryFn: () =>
      api<ConflictGroup[]>(
        `/conflicts${statusFilter ? `?status=${statusFilter}` : ""}`,
        { token }
      )
  });
  const weekAgo = Date.now() - 7 * 86400000;
  const isNew = (g: ConflictGroup) => {
    const t = g.detected_at || g.created_at;
    return Boolean(t) && new Date(t as string).getTime() >= weekAgo;
  };
  const conflicts = {
    ...conflictsRaw,
    data: (conflictsRaw.data || []).filter((g) =>
      ageFilter === "new" ? isNew(g) : ageFilter === "old" ? !isNew(g) : true
    )
  };

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["conflicts"] });
    queryClient.invalidateQueries({ queryKey: ["conflict-summary"] });
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

  const s = summary.data;
  return (
    <section className="space-y-4">
      <div>
        <h2 className="flex items-center gap-1.5 text-base font-semibold text-ink">
          Duplicates
          <HelpTip text="Two or more records pointing at the same page. 'Same project' = the page appears twice in one project (remove the extras). 'Used by another project' or 'Added by another user' = coordinate so you don't pay twice for the same placement. 'New (7 days)' shows groups found recently; 'Previously found' shows older, already-known ones." />
        </h2>
        <p className="text-sm text-muted">Every group shows why it's a duplicate and where the original lives.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Duplicate groups" value={s?.total ?? 0} icon={Layers} tone="ink"
          help="Each group = one page URL that appears in more than one record." />
        <Metric label="Open" value={s?.open ?? 0} icon={AlertTriangle} tone="ember"
          help="Groups nobody has dealt with yet — review these first." />
        <Metric label="Cross-project" value={s?.by_scope?.cross_project ?? 0} icon={Link2} tone="plum"
          help="The same page is used by two different projects — you may be paying twice for one placement." />
        <Metric label="Resolved" value={s?.resolved ?? 0} icon={CheckCircle2} tone="ocean"
          help="Groups someone reviewed and closed." />
      </div>

      {(s?.weekly || []).length ? (
        <section className="rounded-xl border border-line bg-panel p-4 shadow-card">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
            New duplicate groups per week
          </div>
          <TrendChart
            height={130}
            labels={(s?.weekly || []).map((w) => w.week)}
            series={[
              { name: "New duplicate groups", cssVar: "--ember", values: (s?.weekly || []).map((w) => w.new_groups) }
            ]}
          />
        </section>
      ) : null}

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Duplicate &amp; conflict groups</h2>
            <p className="mt-0.5 text-xs text-muted">
              Backlinks pointing at the same page (matched by URL fingerprint), grouped for review.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
              <option value="ignored">Ignored</option>
              <option value="">All</option>
            </select>
            <button
              onClick={() => setAgeFilter(ageFilter === "new" ? "" : "new")}
              title="Duplicate groups first found in the last 7 days"
              className={clsx(
                "h-8 rounded-full border px-3 text-xs font-medium transition",
                ageFilter === "new" ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
              )}
            >
              New (7 days)
            </button>
            <button
              onClick={() => setAgeFilter(ageFilter === "old" ? "" : "old")}
              title="Duplicate groups already known before the last 7 days"
              className={clsx(
                "h-8 rounded-full border px-3 text-xs font-medium transition",
                ageFilter === "old" ? "border-ocean bg-ocean/10 text-ocean" : "border-line text-muted hover:text-ink"
              )}
            >
              Previously found
            </button>
            <ExportButton
              disabled={!(conflicts.data || []).length}
              onClick={() =>
                downloadCsv(
                  "duplicate-groups.csv",
                  ["Page URL", "Type", "Status", "Links in group", "First found"],
                  (conflicts.data || []).map((g) => [
                    g.canonical_url, g.scope, g.resolution_status, g.member_count,
                    g.detected_at || g.created_at
                  ])
                )
              }
            />
            <button
              onClick={() => rebuild.mutate()}
              className="flex h-9 items-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              {rebuild.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Scan for duplicates
            </button>
          </div>
        </div>
        <div className="divide-y divide-line">
          {(conflicts.data || []).map((conflict) => (
            <ConflictRow
              key={conflict.id}
              conflict={conflict}
              onResolve={(status) => resolve.mutate({ id: conflict.id, status })}
            />
          ))}
          {!conflicts.isLoading && !conflicts.data?.length ? (
            <Empty label="No duplicate groups — every backlink is unique by fingerprint." />
          ) : null}
        </div>
      </section>
    </section>
  );
}

function ConflictRow({
  conflict,
  onResolve
}: {
  conflict: ConflictGroup;
  onResolve: (status: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <div className="flex items-start justify-between gap-3">
        <button onClick={() => setOpen(!open)} className="flex min-w-0 items-start gap-2 text-left">
          {open ? (
            <ChevronUp className="mt-1 h-4 w-4 shrink-0 text-muted" />
          ) : (
            <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-muted" />
          )}
          <div className="min-w-0">
            <div className="truncate font-medium text-ink">
              {conflict.canonical_url || "(unknown URL)"}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
              <span className="rounded border border-line bg-field px-2 py-0.5 font-semibold">
                {conflict.member_count} backlinks
              </span>
              <span className="rounded border border-plum/30 bg-plum/10 px-2 py-0.5 font-semibold text-plum">
                {conflict.scope.replaceAll("_", " ")}
              </span>
              {conflict.fingerprint ? (
                <span className="font-mono text-[11px]">{conflict.fingerprint.slice(0, 12)}…</span>
              ) : null}
            </div>
          </div>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          <Status value={conflict.resolution_status} />
          {conflict.resolution_status !== "resolved" ? (
            <button
              onClick={() => onResolve("resolved")}
              className="rounded border border-line bg-panel px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
            >
              Resolve
            </button>
          ) : (
            <button
              onClick={() => onResolve("open")}
              className="rounded border border-line bg-panel px-2 py-1 text-xs font-medium text-muted transition hover:bg-field"
            >
              Reopen
            </button>
          )}
        </div>
      </div>
      {open ? (
        <div className="mt-3 overflow-x-auto rounded-md border border-line">
          <table className="w-full text-sm">
            <thead className="bg-field text-left text-xs uppercase text-muted">
              <tr>
                <Th>Project</Th>
                <Th>Target</Th>
                <Th>User</Th>
                <Th>Type</Th>
                <Th>Status</Th>
                <Th>Score</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {conflict.members.map((m) => (
                <tr key={m.backlink_id}>
                  <Td>{m.project_name || "—"}</Td>
                  <Td>
                    <span className="block max-w-[280px] truncate" title={m.target_url}>
                      {m.target_url}
                    </span>
                  </Td>
                  <Td>{m.assigned_user_label || "—"}</Td>
                  <Td>{m.link_type || "—"}</Td>
                  <Td>{m.status ? <Status value={m.status} /> : "—"}</Td>
                  <Td>{m.score ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
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

function IssueWord({ label, count }: { label: string | null; count: number }) {
  if (!label) return <span>{count ? `${count} issues` : "-"}</span>;
  return (
    <span
      title={ISSUE_WORDS[label] || "Open the link for full details."}
      className="cursor-help whitespace-nowrap text-xs underline decoration-dotted decoration-line underline-offset-2"
    >
      {label.replaceAll("_", " ").toLowerCase()}
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
    what: "We couldn't reach the page this time (timeout or a temporary server problem).",
    next: "It will retry automatically — or use Recheck to try now."
  },
  NEEDS_MANUAL_REVIEW: {
    label: "Needs review",
    what: "We couldn't decide automatically — usually bot protection or conflicting signals on the page.",
    next: "Open the page yourself and confirm; the reason is shown in the Issue column."
  },
  PENDING: {
    label: "QA pending",
    what: "This link hasn't been QA-checked yet.",
    next: "Use “Check QA pending” in the Backlinks list to check it — checks don't start on their own."
  },
  indexed: { what: "Google shows this page in its index.", next: "Nothing to do." },
  not_indexed: { what: "Google does not show this page in its index.", next: "Low-value for SEO until indexed — consider requesting indexing or replacing." },
  uncertain: { label: "Index unclear", what: "The index check couldn't give a clear yes/no.", next: "Re-run the index check later." },
  unchecked: { what: "Index status hasn't been checked yet.", next: "Use “Check index”." },
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

function Status({ value, reason }: { value: string; reason?: string | null }) {
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
  const label = (help?.label || value).replaceAll("_", " ");
  return (
    <span className="group relative inline-flex">
      <span className={clsx("inline-flex cursor-default rounded-full border px-2 py-1 text-xs font-semibold", tone)}>
        {label}
      </span>
      {help ? (
        <span className="pointer-events-none absolute bottom-full left-0 z-30 mb-1.5 hidden w-72 rounded-lg border border-line bg-panel p-2.5 text-left shadow-pop group-hover:block">
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

function FilterMultiSelect({
  label,
  options,
  selected,
  onChange,
  withBlanks = false
}: {
  label: string;
  options: Array<{ value: string; label?: string; count?: number }>;
  selected: string[];
  onChange: (vals: string[]) => void;
  withBlanks?: boolean;
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

  const all = withBlanks ? [...options, { value: "(blanks)", label: "(Blanks)" }] : options;
  const shown = all.filter((o) =>
    (o.label || o.value).toLowerCase().includes(q.trim().toLowerCase())
  );
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);

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
            placeholder="Search…"
            autoFocus
            className="mb-1.5 h-8 w-full rounded-md border border-line bg-panel px-2 text-xs focus:border-ocean focus:outline-none"
          />
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
  onNotice
}: {
  token: string | null;
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

  const cfg = config.data;
  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-line bg-panel shadow-card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-ink">Google Sheets</h2>
            <p className="text-sm text-muted">
              Sync projects and backlinks from your main sheet. One project sheet = one project.
            </p>
          </div>
          <button
            onClick={() => syncAll.mutate()}
            disabled={!cfg?.enabled || syncAll.isPending}
            className="flex items-center gap-2 rounded-md bg-ocean px-4 py-2 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900 disabled:opacity-50"
          >
            {syncAll.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Sync from main sheet
          </button>
        </div>
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
            {(sheets.data || []).map((s) => {
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
        {!sheets.isLoading && !sheets.data?.length ? (
          <Empty label="No project sheets yet — run a sync from the main sheet" />
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
  type MappingData = {
    headers: string[];
    header_error: string | null;
    mapping: Record<string, string>;
    is_manual: boolean;
    auto_mapping: Record<string, string>;
    fields: string[];
    writeback_options: string[];
    writeback_columns: string[];
  };
  const data = useQuery({
    queryKey: ["sheet-mapping", token, sheetId],
    enabled: Boolean(token),
    queryFn: () => api<MappingData>(`/sheets/${sheetId}/mapping`, { token })
  });
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [wb, setWb] = useState<string[] | null>(null);
  const mapping = draft ?? data.data?.mapping ?? {};
  const wbCols = wb ?? data.data?.writeback_columns ?? [];

  const save = useMutation({
    mutationFn: () =>
      api<{ message: string }>(`/sheets/${sheetId}/mapping`, {
        token,
        method: "PUT",
        body: JSON.stringify({ column_mapping: mapping, writeback_columns: wbCols })
      }),
    onSuccess: (r) => {
      onNotice(r.message);
      queryClient.invalidateQueries({ queryKey: ["sheet-mapping", token, sheetId] });
      setDraft(null);
      setWb(null);
    },
    onError: (e: Error) => onNotice(e.message)
  });

  const fieldLabel = (f: string) => f.replaceAll("_", " ");
  if (data.isLoading) {
    return <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>;
  }
  const d = data.data;
  if (!d) return <Empty label="Could not load mapping." />;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-ink">
        Column mapping
        <HelpTip text="Tell the sync which sheet column feeds each field. Auto-detect handles common names ('Source URL', 'User', 'Anchor'…); set a column manually when your sheet uses different wording. '(ignored)' columns are simply skipped." />
        <span className="rounded-full bg-field px-2 py-0.5 text-[10px] font-semibold uppercase text-muted">
          {d.is_manual ? "Manual" : "Auto-detected"}
        </span>
      </div>
      {d.header_error ? (
        <div className="rounded-lg border border-ember/30 bg-ember/10 p-2 text-xs text-ember">
          Couldn&apos;t read the sheet&apos;s headers right now: {d.header_error}
        </div>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {(d.headers.length ? d.headers : Object.keys(mapping)).map((h) => (
          <label key={h} className="text-xs">
            <span className="mb-0.5 block truncate font-medium text-ink" title={h}>{h}</span>
            <select
              value={mapping[h] || ""}
              onChange={(e) =>
                setDraft((prev) => {
                  const next = { ...(prev ?? d.mapping) };
                  if (e.target.value) next[h] = e.target.value;
                  else delete next[h];
                  return next;
                })
              }
              className="h-8 w-full rounded-lg border border-line bg-panel px-2 text-xs"
            >
              <option value="">(ignored)</option>
              {d.fields.map((f) => (
                <option key={f} value={f}>{fieldLabel(f)}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
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
                  setWb((prev) => {
                    const cur = prev ?? d.writeback_columns;
                    return cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c];
                  })
                }
                className="h-3.5 w-3.5 accent-[rgb(var(--ocean))]"
              />
              {c}
            </label>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-50 dark:text-slate-900"
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          Save mapping
        </button>
        <button
          onClick={() => {
            setDraft({});
            setWb(d.writeback_options);
          }}
          title="Clear manual choices — the next sync auto-detects columns again"
          className="h-9 rounded-lg border border-line px-3 text-sm font-medium text-muted transition hover:bg-field"
        >
          Reset to auto
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
  ["index_status", "Index status"],
  ["duplicate_status", "Duplicate status"],
  ["rel", "Rel"],
  ["vendor", "Vendor"],
  ["source_domain", "Source domain"],
  ["scoring_version", "Scoring version"]
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

function AnalyticsDesk({ token, projectId }: { token: string | null; projectId: string }) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [groupBy, setGroupBy] = useState("user");
  const [drillKey, setDrillKey] = useState<string | null>(null);
  const [views, setViews] = useState<SavedView[]>(() => loadViews("ls_views_analytics"));
  const [viewName, setViewName] = useState("");

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

  return (
    <section className="space-y-4">
      {/* Filter bar (connected facets with live counts) */}
      <div className="rounded-xl border border-line bg-panel shadow-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">Analytics</h2>
          {Object.keys(filters).length ? (
            <button onClick={() => setFilters({})} className="text-xs font-medium text-ocean hover:underline">
              Clear filters
            </button>
          ) : null}
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
                                    <tr key={String(r.id)} className="hover:bg-field/60">
                                      <Td>
                                        <a href={String(r.source_page_url)} target="_blank" rel="noreferrer"
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
  return <div className="max-w-[330px] truncate font-medium text-ink" title={value}>{value}</div>;
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
  const emptyLabel = role === "viewer" ? "No projects yet" : "All projects";
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

function TeamDesk({ token, onNotice }: { token: string | null; onNotice: (text: string) => void }) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [password, setPassword] = useState("");

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
    </div>
  );
}
