"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  Bell,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Download,
  FileSpreadsheet,
  Filter,
  Gauge,
  Globe,
  History,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

type Tab = "overview" | "analytics" | "backlinks" | "conflicts" | "domains" | "competitors" | "imports" | "sheets" | "batches" | "alerts" | "reports" | "team" | "employees" | "scoring" | "settings";

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
      <section className="mx-auto flex w-full max-w-[1500px] gap-5 px-5 py-5">
        <aside className="hidden w-[260px] shrink-0 lg:block">
          <div className="sticky top-[76px]">
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
        <section className="min-w-0 flex-1 space-y-5">
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
            <Overview token={token} projectId={activeProjectId} />
          ) : null}
          {tab === "analytics" ? <AnalyticsDesk token={token} projectId={activeProjectId} /> : null}
          {tab === "backlinks" ? (
            <Backlinks token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "conflicts" ? <ConflictsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "domains" ? <SourceDomainsDesk token={token} onNotice={setNotice} /> : null}
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
              <Field label="Full name" value={fullName} onChange={setFullName} />
              <Field label="Workspace" value={workspaceName} onChange={setWorkspaceName} />
            </>
          ) : null}
          <Field label="Email" type="email" value={email} onChange={setEmail} />
          <Field label="Password" type="password" value={password} onChange={setPassword} />
          {error ? <p className="rounded bg-danger/10 p-2 text-sm text-danger">{error}</p> : null}
          <button className="flex w-full items-center justify-center gap-2 rounded-md bg-ocean px-4 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
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
      className="grid h-9 w-9 place-items-center rounded-xl border border-line bg-panel shadow-card text-muted transition hover:bg-field hover:text-ink"
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function TopBar({ onLogout, onRefresh }: { onLogout: () => void; onRefresh: () => void }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-panel/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1500px] items-center justify-between px-5 py-3">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-ocean to-plum text-white shadow-soft">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="text-base font-bold tracking-tight text-ink">LinkSentinel</div>
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted">Backlink QA operations</div>
          </div>
        </div>
        <div className="flex gap-2">
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

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-muted">Project</h2>
        <Plus className="h-4 w-4 text-ocean" />
      </div>
      <select
        className="mb-4 h-10 w-full rounded-md border border-line bg-panel px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
        value={activeProjectId}
        onChange={(event) => onSelect(event.target.value)}
      >
        <option value="">🏢 All projects (company)</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      {showCreate ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            createProject.mutate();
          }}
        >
          <Field label="Name" value={name} onChange={setName} />
          <Field label="Client" value={client} onChange={setClient} />
          <Field label="Target domain" value={domain} onChange={setDomain} />
          <div className="flex gap-2">
            <button className="flex h-9 flex-1 items-center justify-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900">
              {createProject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="h-9 rounded-md border border-line px-3 text-sm font-medium text-muted transition hover:bg-field"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-md border border-dashed border-line text-sm font-medium text-muted transition hover:border-ocean hover:text-ocean"
        >
          <Plus className="h-4 w-4" /> New project
        </button>
      )}
    </section>
  );
}

function Overview({ token, projectId }: { token: string | null; projectId: string }) {
  // No project selected → company-wide main dashboard; a project → project dashboard.
  const dashboard = useQuery({
    queryKey: ["dashboard", token, projectId],
    enabled: Boolean(token),
    queryFn: () =>
      api<Dashboard>(projectId ? `/dashboard?project_id=${projectId}` : "/dashboard", { token })
  });

  const stats = dashboard.data;
  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-ink">
            {projectId ? "Project dashboard" : "Company dashboard"}
          </h2>
          <p className="text-sm text-muted">
            {projectId ? "This project's backlinks" : "All projects across the workspace"}
          </p>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Total" value={stats?.totals.total ?? 0} icon={Link2} tone="ink" />
        <Metric label="Pass" value={stats?.totals.pass_count ?? 0} icon={CheckCircle2} tone="ocean" />
        <Metric label="Warning" value={stats?.totals.warning_count ?? 0} icon={AlertTriangle} tone="ember" />
        <Metric label="Fail" value={stats?.totals.fail_count ?? 0} icon={XCircle} tone="danger" />
        <Metric label="Review" value={stats?.totals.review_count ?? 0} icon={ShieldAlert} tone="plum" />
        <Metric label="Avg score" value={stats?.totals.avg_score ?? "-"} icon={Gauge} tone="ink" />
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
        <section className="rounded-xl border border-line bg-panel shadow-card">
          <SectionTitle title="Issue Mix" />
          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <Issue label="Nofollow" value={stats?.issues.nofollow_count ?? 0} />
            <Issue label="Noindex" value={stats?.issues.noindex_count ?? 0} />
            <Issue label="Robots blocked" value={stats?.issues.robots_blocked_count ?? 0} />
            <Issue label="Canonical" value={stats?.issues.canonical_issue_count ?? 0} />
            <Issue label="Broken page" value={stats?.issues.broken_count ?? 0} />
            <Issue label="Link missing" value={stats?.issues.link_missing_count ?? 0} />
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
                    <tr><Th>Link type</Th><Th>Total</Th><Th>Pass</Th><Th>Fail</Th><Th>Avg</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.link_type_breakdown || []).map((r) => (
                      <tr key={r.link_type} className="hover:bg-field/60">
                        <Td><span className="font-medium text-ink">{r.link_type}</span></Td>
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
                    <tr><Th>User</Th><Th>Total</Th><Th>Pass %</Th><Th>Fail</Th><Th>Avg</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.assigned_user_stats || []).map((r) => (
                      <tr key={r.assigned_user_label} className="hover:bg-field/60">
                        <Td><span className="font-medium text-ink">{r.assigned_user_label}</span></Td>
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
                    <tr><Th>Domain</Th><Th>Links</Th><Th>Pass</Th><Th>Fail</Th><Th>Indexed %</Th></tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {(stats.top_source_domains || []).map((r) => (
                      <tr key={r.source_domain} className="hover:bg-field/60">
                        <Td><span className="break-all text-ink">{r.source_domain}</span></Td>
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
                <div key={`${r.backlink_id}-${r.created_at}`} className="p-3">
                  <div className="truncate text-sm font-medium text-ink">{r.source_page_url}</div>
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
  const [status, setStatus] = useState("");
  const [dupFilter, setDupFilter] = useState("");
  const [indexFilter, setIndexFilter] = useState("");
  const [rel, setRel] = useState("");
  const [linkType, setLinkType] = useState("");
  const [issueLabel, setIssueLabel] = useState("");
  const [sort, setSort] = useState("score");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  const linkTypes = useQuery({
    queryKey: ["link-types", token],
    enabled: Boolean(token),
    queryFn: () => api<LinkType[]>("/link-types", { token })
  });

  const clearFilters = () => {
    setStatus("");
    setDupFilter("");
    setIndexFilter("");
    setRel("");
    setLinkType("");
    setIssueLabel("");
    setSearch("");
  };
  const activeFilterCount = [status, dupFilter, indexFilter, rel, linkType, issueLabel, debouncedSearch]
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
    ["Failing", toks(status).includes("FAIL"), () => toggleTok(status, setStatus, "FAIL")],
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
    if (issueLabel) params.set("issue_label", issueLabel);
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (sort) params.set("sort", sort);
    return params.toString();
  }, [projectId, status, dupFilter, indexFilter, rel, linkType, issueLabel, debouncedSearch, sort]);
  const backlinks = useQuery({
    queryKey: ["backlinks", token, query],
    enabled: Boolean(token),
    queryFn: () => api<Page<BacklinkRow>>(`/backlinks?${query}`, { token })
  });
  const [staleDays, setStaleDays] = useState("");
  const recheck = useMutation({
    mutationFn: () =>
      api<{ job_id: string; queued: number }>("/backlinks/recheck", {
        token,
        method: "POST",
        body: JSON.stringify({
          project_id: projectId || null,
          priority: true,
          older_than_days: staleDays ? Number(staleDays) : null
        })
      }),
    onSuccess: (data) => {
      onNotice(
        data.queued
          ? `Recheck started — ${data.queued} link${data.queued === 1 ? "" : "s"} queued.`
          : staleDays
            ? `Nothing to recheck — everything was checked within ${staleDays} days.`
            : "Nothing to recheck."
      );
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
      queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (err: Error) => onNotice(err.message)
  });
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

  return (
    <section className="rounded-xl border border-line bg-panel shadow-card">
      <div className="border-b border-line p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Backlinks</h2>
            <p className="text-sm text-muted">
              {backlinks.data?.total ?? 0} records
              {activeFilterCount ? ` · ${activeFilterCount} filter${activeFilterCount > 1 ? "s" : ""}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => indexCheck.mutate()}
              className="flex h-9 items-center gap-2 rounded-lg border border-line px-3 text-sm font-semibold text-ink transition hover:bg-field"
              title="Check whether source pages are indexed by Google (via proxy)"
            >
              {indexCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
              Check index
            </button>
            <select
              value={staleDays}
              onChange={(e) => setStaleDays(e.target.value)}
              title="Only recheck links whose last check is older than this"
              className="h-9 rounded-lg border border-line bg-panel px-2 text-sm"
            >
              <option value="">Recheck: everything</option>
              <option value="10">Older than 10 days</option>
              <option value="20">Older than 20 days</option>
              <option value="30">Older than 30 days</option>
            </select>
            <button
              onClick={() => recheck.mutate()}
              className="flex h-9 items-center gap-2 rounded-lg bg-ocean px-3 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900"
            >
              {recheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Recheck
            </button>
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
          <FilterMultiSelect
            label="Status"
            options={[
              { value: "PASS", label: "Pass" },
              { value: "WARNING", label: "Warning" },
              { value: "FAIL", label: "Fail" },
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
          <select
            className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="score">Sort: worst score first</option>
            <option value="last_checked_at">Sort: recently checked</option>
            <option value="created_at">Sort: newest</option>
          </select>
        </div>
      </div>
      <div className="overflow-x-auto scrollbar-thin">
        <table className="min-w-[1120px] w-full border-collapse text-left text-sm">
          <thead className="bg-field text-xs uppercase text-muted">
            <tr>
              <Th>Status</Th>
              <Th>Score</Th>
              <Th>Source</Th>
              <Th>Target</Th>
              <Th>HTTP</Th>
              <Th>Rel</Th>
              <Th>Rank / Visits</Th>
              <Th>Issue</Th>
              <Th>Checked</Th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(backlinks.data?.items || []).map((row) => (
              <tr
                key={row.id}
                onClick={() => setSelectedId(row.id)}
                className="cursor-pointer hover:bg-field/70"
              >
                <Td><Status value={row.override_status || row.status} reason={row.top_issue_label} /></Td>
                <Td><span className="font-semibold">{row.score ?? "-"}</span></Td>
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
                  {row.index_status ? <IndexBadge value={row.index_status} /> : null}
                  {row.assigned_user_label ? (
                    <span className="mt-0.5 block text-[11px] text-muted">👤 {row.assigned_user_label}</span>
                  ) : null}
                </Td>
                <Td><Url value={row.target_url} /></Td>
                <Td>{row.http_status ?? "-"}</Td>
                <Td>{row.current_rel ?? "-"}</Td>
                <Td><span title={metricAgeTitle(row.extra?.metrics)}>{formatSiteMetric(row.extra?.metrics)}</span></Td>
                <Td>{row.top_issue_label ?? (row.issue_count ? `${row.issue_count} issues` : "-")}</Td>
                <Td>{formatDate(row.last_checked_at)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {!backlinks.isLoading && !backlinks.data?.items.length ? <Empty label="No backlinks yet" /> : null}
      </div>
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
        <option value="FAIL">Fail</option>
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
                      <Td>{formatDate(b.started_at)}</Td>
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
  const [pasted, setPasted] = useState("");
  const [cat, setCat] = useState("");

  const summary = useQuery({
    queryKey: ["competitor-summary", token, projectId],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () => api<CompetitorSummary>(`/competitors/summary?project_id=${projectId}`, { token })
  });
  const domains = useQuery({
    queryKey: ["competitor-domains", token, projectId, cat],
    enabled: Boolean(token) && Boolean(projectId),
    queryFn: () =>
      api<CompetitorDomain[]>(
        `/competitors/domains?project_id=${projectId}${cat ? `&category=${cat}` : ""}`,
        { token }
      )
  });
  const ingest = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/competitors/ingest", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: projectId, name: name || "Competitor upload", text: pasted })
      }),
    onSuccess: () => {
      onNotice("Competitor links analyzed");
      setPasted("");
      queryClient.invalidateQueries({ queryKey: ["competitor-summary"] });
      queryClient.invalidateQueries({ queryKey: ["competitor-domains"] });
    },
    onError: (e: Error) => onNotice(e.message)
  });

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
        <Metric label="Domains" value={s?.domains ?? 0} icon={Globe} tone="ink" />
        <Metric label="New opportunities" value={s?.new_opportunities ?? 0} icon={Star} tone="ocean" />
        <Metric label="Already have" value={s?.existing ?? 0} icon={CheckCircle2} tone="plum" />
        <Metric label="Competitor links" value={s?.competitor_links ?? 0} icon={Link2} tone="ink" />
      </div>

      <section className="rounded-xl border border-line bg-panel shadow-card p-4">
        <SectionTitle title="Upload competitor links" flush />
        <div className="space-y-3 pt-3">
          <Field label="Name (optional)" value={name} onChange={setName} />
          <textarea
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            rows={6}
            placeholder={"https://blog.example.com/post-linking-to-competitor\nhttps://directory.example.com/listing, brand anchor, dofollow"}
            className="w-full rounded-md border border-line p-2 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ocean/20"
          />
          <button
            onClick={() => ingest.mutate()}
            disabled={ingest.isPending || !pasted.trim()}
            className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white transition hover:opacity-90 dark:text-slate-900 disabled:opacity-50"
          >
            {ingest.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Analyze
          </button>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Competitor source domains</h3>
          <select
            value={cat}
            onChange={(e) => setCat(e.target.value)}
            className="h-9 rounded-md border border-line bg-panel px-2 text-sm"
          >
            <option value="">All</option>
            <option value="new_opportunity">New opportunities</option>
            <option value="existing">Already have</option>
          </select>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-field text-xs uppercase text-muted">
              <tr><Th>Domain</Th><Th>Status</Th><Th>Competitor links</Th><Th>Our links</Th><Th>Indexed %</Th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {(domains.data || []).map((d) => (
                <tr key={d.id} className="hover:bg-field/60">
                  <Td>
                    <a href={`https://${d.domain_key}`} target="_blank" rel="noreferrer" className="text-ocean hover:underline">
                      {d.domain_key}
                    </a>
                  </Td>
                  <Td>
                    {d.category === "new_opportunity" ? (
                      <span className="rounded bg-ocean/10 px-2 py-0.5 text-xs font-medium text-ocean">Opportunity</span>
                    ) : (
                      <span className="rounded bg-field px-2 py-0.5 text-xs font-medium text-muted">Have it</span>
                    )}
                  </Td>
                  <Td>{d.url_count}</Td>
                  <Td>{d.our_link_count}</Td>
                  <Td>{d.our_indexed_pct != null ? `${d.our_indexed_pct}%` : "-"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
          {!domains.isLoading && !(domains.data || []).length ? (
            <Empty label="No competitor data yet — paste some links above." />
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
                <Severity value={rule.min_severity} />
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
  { value: "failed_links", label: "Problem links only", desc: "Only the links failing QA — the ones that need action." },
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
    queryFn: () => api<Report[]>("/reports", { token })
  });

  // Group reports into version stacks by (type + project) — the same scope the
  // backend uses for versioning. Sort each stack newest-first by time (robust even
  // for older rows imported before versioning existed); the card derives a clean
  // sequential version number from position so the history always reads v1..vN.
  const groups = useMemo(() => {
    const map = new Map<string, Report[]>();
    for (const r of reports.data || []) {
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
  }, [reports.data]);

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

  return (
    <section className="space-y-4">
      {/* ── Builder ─────────────────────────────────────────────── */}
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

      {/* ── Saved reports (grouped by version) ──────────────────── */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <History className="h-4 w-4 text-muted" />
          <h3 className="text-sm font-semibold text-ink">Your reports</h3>
          <span className="text-xs text-muted">— newest version on top, older versions tucked underneath</span>
        </div>
        <div className="space-y-3">
          {groups.map((versions) => (
            <ReportGroup key={versions[0].id} versions={versions} onDownload={download} />
          ))}
          {reports.isLoading ? <Empty label="Loading reports…" /> : null}
          {!reports.isLoading && !groups.length ? (
            <Empty label="No reports yet — build one above" />
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
  onDownload
}: {
  versions: Report[];
  onDownload: (r: Report) => void;
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
                  <button
                    disabled={r.status !== "completed"}
                    onClick={() => onDownload(r)}
                    className="flex items-center gap-1 rounded-md border border-line bg-panel px-2 py-1 text-xs font-medium text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Download className="h-3.5 w-3.5" /> Download
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SourceDomainsDesk({
  token,
  onNotice
}: {
  token: string | null;
  onNotice: (text: string) => void;
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
  const ready = scope === "global" || Boolean(effectiveRef);
  const cfgKey = ["scoring-config", token, scope, effectiveRef];
  const config = useQuery({
    queryKey: cfgKey,
    enabled: Boolean(token) && ready,
    queryFn: () =>
      api<ScoringConfig>(
        `/scoring/config?scope=${scope}${effectiveRef ? `&scope_ref_id=${effectiveRef}` : ""}`,
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
    JSON.stringify({ scope, scope_ref_id: effectiveRef || null, rules: cleanScoringRules(draft), bands });

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
      body: JSON.stringify({ scope, scope_ref_id: effectiveRef || null, preview: !apply })
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
            onChange={(e) => setRefId(e.target.value)}
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

  const summary = useQuery({
    queryKey: ["conflict-summary", token],
    enabled: Boolean(token),
    queryFn: () => api<ConflictSummary>("/conflicts/summary", { token })
  });
  const conflicts = useQuery({
    queryKey: ["conflicts", token, statusFilter],
    enabled: Boolean(token),
    queryFn: () =>
      api<ConflictGroup[]>(
        `/conflicts${statusFilter ? `?status=${statusFilter}` : ""}`,
        { token }
      )
  });

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
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Duplicate groups" value={s?.total ?? 0} icon={Layers} tone="ink" />
        <Metric label="Open" value={s?.open ?? 0} icon={AlertTriangle} tone="ember" />
        <Metric label="Cross-project" value={s?.by_scope?.cross_project ?? 0} icon={Link2} tone="plum" />
        <Metric label="Resolved" value={s?.resolved ?? 0} icon={CheckCircle2} tone="ocean" />
      </div>

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
  type = "text"
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase text-muted">{label}</span>
      <input
        className="h-10 w-full rounded-xl border border-line bg-panel shadow-card px-3 text-sm shadow-sm transition focus:border-ocean focus:outline-none focus:ring-2 focus:ring-ocean/20"
        type={type}
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
  tone
}: {
  label: string;
  value: number | string;
  icon: typeof Gauge;
  tone: "ink" | "ocean" | "ember" | "danger" | "plum";
}) {
  const chip = {
    ink: "bg-field text-ink",
    ocean: "bg-ocean/10 text-ocean",
    ember: "bg-ember/10 text-ember",
    danger: "bg-danger/10 text-danger",
    plum: "bg-plum/10 text-plum"
  }[tone];
  return (
    <div className="rounded-xl border border-line bg-panel p-4 shadow-card transition hover:shadow-soft">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
        <span className={clsx("grid h-8 w-8 place-items-center rounded-lg", chip)}>
          <Icon className="h-4 w-4" />
        </span>
      </div>
      <div className="mt-2 text-3xl font-bold tracking-tight text-ink">{value}</div>
    </div>
  );
}

function Issue({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-line bg-field p-3">
      <div className="text-xs font-semibold uppercase text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink">{value}</div>
    </div>
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
      className="grid h-9 w-9 place-items-center rounded-md border border-line bg-panel text-muted transition hover:bg-field hover:text-ink"
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
  PASS: { what: "The link is live and everything we check looked good.", next: "Nothing to do." },
  WARNING: {
    what: "The link works, but something reduces its value (e.g. nofollow, weak page, redirects).",
    next: "Open the link to see which checks lowered the score."
  },
  FAIL: {
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
  PENDING: { what: "This link hasn't been checked yet.", next: "It's queued — results appear after the first check." },
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

  const syncAll = useMutation({
    mutationFn: () => api<{ message: string }>("/sheets/sync", { method: "POST", token }),
    onSuccess: (r) => {
      onNotice(r.message || "Main sheet sync started");
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["sheets"] }), 1500);
    },
    onError: (e: Error) => onNotice(e.message)
  });
  const syncOne = useMutation({
    mutationFn: (id: string) => api<{ message: string }>(`/sheets/${id}/sync`, { method: "POST", token }),
    onSuccess: (r) => onNotice(r.message || "Sync started"),
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
            {(sheets.data || []).map((s) => (
              <tr key={s.id}>
                <Td>
                  <div className="font-medium text-ink">{s.project_name}</div>
                  <div className="max-w-[280px] truncate text-xs text-muted" title={s.source_url || ""}>
                    {s.source_url}
                  </div>
                </Td>
                <Td>
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
                </Td>
                <Td>{s.row_count}</Td>
                <Td>{s.imported_count} / {s.updated_count}</Td>
                <Td>{formatDate(s.last_synced_at)}</Td>
                <Td>
                  <div className="flex gap-1">
                    <button
                      onClick={() => syncOne.mutate(s.id)}
                      className="flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
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
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
        {!sheets.isLoading && !sheets.data?.length ? (
          <Empty label="No project sheets yet — run a sync from the main sheet" />
        ) : null}
      </div>
    </section>
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
                <select
                  key={dim}
                  className="h-9 rounded-xl border border-line bg-panel shadow-card px-2 text-sm"
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

      {/* Summary cards */}
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Total" value={total} icon={Link2} tone="ink" />
        <Metric label="Indexed" value={`${Number(s.indexed || 0)} · ${pct(Number(s.indexed || 0), total)}`} icon={CheckCircle2} tone="ocean" />
        <Metric label="Not indexed" value={Number(s.not_indexed || 0)} icon={XCircle} tone="danger" />
        <Metric label="Failing" value={`${Number(s.fail || 0)} · ${pct(Number(s.fail || 0), total)}`} icon={XCircle} tone="danger" />
        <Metric label="Nofollow" value={`${Number(s.nofollow || 0)} · ${pct(Number(s.nofollow || 0), total)}`} icon={AlertTriangle} tone="ember" />
        <Metric label="Duplicates" value={Number(s.duplicates || 0)} icon={Filter} tone="plum" />
      </div>

      {/* Group-by pivot */}
      <div className="rounded-xl border border-line bg-panel shadow-card">
        <div className="flex items-center justify-between border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Breakdown</h3>
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
                  <tr
                    key={i}
                    onClick={() => setDrillKey(active ? null : String(g.key))}
                    className={clsx("cursor-pointer hover:bg-field/60", active && "bg-ocean/5")}
                  >
                    <Td>
                      <span className="font-medium text-ocean hover:underline">{name || "—"}</span>
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
                );
              })}
            </tbody>
          </table>
          {!q.isLoading && !(q.data?.groups || []).length ? <Empty label="No data for these filters" /> : null}
        </div>
        {drillKey !== null ? (
          <div className="border-t border-line p-3">
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-ink">
                Backlinks in “{
                  (() => {
                    const g = (q.data?.groups || []).find((x) => String(x.key) === drillKey);
                    return (g && ((g.label && String(g.label)) || String(g.key))) || drillKey;
                  })()
                }”
              </h4>
              <button onClick={() => setDrillKey(null)} className="text-xs font-medium text-ocean hover:underline">
                Close
              </button>
            </div>
            {drill.isLoading ? (
              <div className="flex justify-center p-4"><Loader2 className="h-4 w-4 animate-spin text-muted" /></div>
            ) : !(drill.data?.records || []).length ? (
              <Empty label="No backlinks in this group" />
            ) : (
              <div className="overflow-x-auto">
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
          </div>
        ) : null}
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
  return <th className="px-4 py-3 font-semibold">{children}</th>;
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-4 py-3 align-top">{children}</td>;
}

function Url({ value }: { value: string }) {
  return <div className="max-w-[330px] truncate font-medium text-ink" title={value}>{value}</div>;
}

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
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
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="border-b border-line bg-field text-xs uppercase text-muted">
              <tr>
                <Th>Member</Th>
                <Th>Role</Th>
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
                    <span className="text-muted">{formatDate(m.last_login_at)}</span>
                  </Td>
                  <Td>
                    <span className="text-muted">{formatDate(m.member_since)}</span>
                  </Td>
                  <Td>
                    <div className="flex items-center justify-end gap-2">
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
    </div>
  );
}
