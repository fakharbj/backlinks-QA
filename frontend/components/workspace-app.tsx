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
  Play,
  Plus,
  RefreshCw,
  Settings,
  Sheet,
  ShieldAlert,
  Star,
  Trash2,
  Upload,
  UserCog,
  UserPlus,
  Users,
  XCircle
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FormEvent, useEffect, useMemo, useState } from "react";

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
  ConflictGroup,
  ConflictSummary,
  Dashboard,
  EmployeeOverview,
  Page,
  Project,
  ProjectDomain,
  ProjectSettings,
  Report,
  Role,
  SheetConfig,
  SheetSource,
  SourceDomain,
  SourceDomainDetail,
  SiteMetrics,
  TeamMember,
  TokenPair
} from "@/lib/api";

type Tab = "overview" | "analytics" | "backlinks" | "conflicts" | "domains" | "imports" | "sheets" | "alerts" | "reports" | "team" | "employees" | "settings";

const samplePaste = `source_url,target_url,expected_anchor_text,expected_rel,campaign,vendor,tags
https://example.com/best-tools,https://acme.test/seo,Acme SEO,dofollow,Q3 Outreach,EditorialHub,"guest-post,tier1"
https://publisher.test/review,https://acme.test/pricing,pricing guide,dofollow,Q3 Outreach,LinkDesk,"review,tier2"`;

export function WorkspaceApp() {
  const queryClient = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string>("");
  const [tab, setTab] = useState<Tab>("overview");
  const [notice, setNotice] = useState<string>("");

  useEffect(() => {
    loadTokens();
    setToken(getAccessToken());
    setRefreshToken(localStorage.getItem("ls_refresh"));

    // The token manager fires this when the refresh token is dead → real logout.
    const onExpired = () => {
      setToken(null);
      setRefreshToken(null);
      setActiveProjectId("");
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
    setActiveProjectId("");
    queryClient.clear();
  }

  if (!authed) {
    return <AuthPanel onToken={saveTokens} />;
  }

  return (
    <main className="min-h-screen">
      <TopBar
        activeTab={tab}
        onTab={setTab}
        onLogout={logout}
        onRefresh={() => {
          queryClient.invalidateQueries();
          setNotice("Refreshing workspace data");
        }}
      />
      <section className="mx-auto flex w-full max-w-[1500px] gap-5 px-5 py-5">
        <aside className="hidden w-[280px] shrink-0 lg:block">
          <ProjectPanel
            token={token}
            projects={projects.data || []}
            activeProjectId={activeProjectId}
            onSelect={setActiveProjectId}
            onNotice={setNotice}
          />
        </aside>
        <section className="min-w-0 flex-1 space-y-5">
          <div className="lg:hidden">
            <ProjectPanel
              token={token}
              projects={projects.data || []}
              activeProjectId={activeProjectId}
              onSelect={setActiveProjectId}
              onNotice={setNotice}
            />
          </div>
          {notice ? <Notice text={notice} onClose={() => setNotice("")} /> : null}
          {tab === "overview" ? (
            <Overview token={token} projectId={activeProjectId} />
          ) : null}
          {tab === "analytics" ? <AnalyticsDesk token={token} /> : null}
          {tab === "backlinks" ? (
            <Backlinks token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "conflicts" ? <ConflictsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "domains" ? <SourceDomainsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "imports" ? (
            <ImportDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "sheets" ? <SheetsDesk token={token} onNotice={setNotice} /> : null}
          {tab === "alerts" ? (
            <AlertsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "reports" ? (
            <ReportsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "team" ? <TeamDesk token={token} onNotice={setNotice} /> : null}
          {tab === "employees" ? <EmployeesDesk token={token} onNotice={setNotice} /> : null}
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
  const [email, setEmail] = useState("admin@linksentinel.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [fullName, setFullName] = useState("SEO Ops Admin");
  const [workspaceName, setWorkspaceName] = useState("Acme Link Ops");
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
      <section className="w-full max-w-[460px] rounded-lg border border-line bg-panel p-6 shadow-sm">
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
          {error ? <p className="rounded bg-red-50 p-2 text-sm text-danger">{error}</p> : null}
          <button className="flex w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-black">
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

function TopBar({
  activeTab,
  onTab,
  onLogout,
  onRefresh
}: {
  activeTab: Tab;
  onTab: (tab: Tab) => void;
  onLogout: () => void;
  onRefresh: () => void;
}) {
  const tabs: Array<[Tab, string, typeof Gauge]> = [
    ["overview", "Overview", Gauge],
    ["analytics", "Analytics", BarChart3],
    ["backlinks", "Backlinks", Link2],
    ["conflicts", "Duplicates", Layers],
    ["domains", "Source Domains", Globe],
    ["imports", "Imports", Upload],
    ["sheets", "Sheets", Sheet],
    ["alerts", "Alerts", Bell],
    ["reports", "Reports", FileSpreadsheet],
    ["team", "Team", Users],
    ["employees", "Employees", UserCog],
    ["settings", "Settings", Settings]
  ];

  return (
    <header className="border-b border-line bg-white">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-5 py-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-md bg-ink text-white">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <div className="text-base font-semibold text-ink">LinkSentinel</div>
            <div className="text-xs text-muted">Backlink QA operations</div>
          </div>
        </div>
        <nav className="flex min-w-0 gap-1 overflow-x-auto scrollbar-thin">
          {tabs.map(([id, label, Icon]) => (
            <button
              key={id}
              onClick={() => onTab(id)}
              className={clsx(
                "flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium transition",
                activeTab === id ? "bg-ink text-white" : "text-muted hover:bg-field hover:text-ink"
              )}
              title={label}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>
        <div className="flex gap-2">
          <IconButton label="Refresh" onClick={onRefresh} icon={RefreshCw} />
          <IconButton label="Log out" onClick={onLogout} icon={LogOut} />
        </div>
      </div>
    </header>
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
  const [name, setName] = useState("Acme Backlinks");
  const [client, setClient] = useState("Acme Co");
  const [domain, setDomain] = useState("acme.test");

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
    },
    onError: (err: Error) => onNotice(err.message)
  });

  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase text-muted">Project</h2>
        <Plus className="h-4 w-4 text-ocean" />
      </div>
      <select
        className="mb-4 h-10 w-full rounded-md border border-line bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
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
        <button className="flex h-9 w-full items-center justify-center gap-2 rounded-md bg-ocean px-3 text-sm font-semibold text-white hover:bg-teal-800">
          {createProject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          New project
        </button>
      </form>
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
        <section className="rounded-lg border border-line bg-panel">
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
        <section className="rounded-lg border border-line bg-panel">
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: "50", with_total: "true" });
    if (projectId) params.set("project_id", projectId);  // omit → all projects
    if (status) params.set("status", status);
    if (dupFilter) params.set("duplicate_status", dupFilter);
    if (indexFilter) params.set("index_status", indexFilter);
    return params.toString();
  }, [projectId, status, dupFilter, indexFilter]);
  const backlinks = useQuery({
    queryKey: ["backlinks", token, query],
    enabled: Boolean(token),
    queryFn: () => api<Page<BacklinkRow>>(`/backlinks?${query}`, { token })
  });
  const recheck = useMutation({
    mutationFn: () =>
      api<{ job_id: string; queued: number }>("/backlinks/recheck", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: projectId || null, priority: true })
      }),
    onSuccess: (data) => {
      onNotice(`Queued ${data.queued} backlinks`);
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
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
    <section className="rounded-lg border border-line bg-panel">
      <div className="flex flex-col gap-3 border-b border-line p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-base font-semibold text-ink">Backlinks</h2>
          <p className="text-sm text-muted">{backlinks.data?.total ?? 0} records</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="h-9 rounded-md border border-line bg-white px-3 text-sm"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="PASS">Pass</option>
            <option value="WARNING">Warning</option>
            <option value="FAIL">Fail</option>
            <option value="UNKNOWN">Unknown</option>
            <option value="NEEDS_MANUAL_REVIEW">Review</option>
            <option value="PENDING">Pending</option>
          </select>
          <select
            className="h-9 rounded-md border border-line bg-white px-3 text-sm"
            value={dupFilter}
            onChange={(event) => setDupFilter(event.target.value)}
          >
            <option value="">All links</option>
            <option value="duplicate">Duplicates only</option>
            <option value="dup_cross_project">Cross-project dup</option>
            <option value="dup_cross_user">Cross-user dup</option>
            <option value="dup_same_project">Same-project dup</option>
            <option value="unique">Unique only</option>
          </select>
          <select
            className="h-9 rounded-md border border-line bg-white px-3 text-sm"
            value={indexFilter}
            onChange={(event) => setIndexFilter(event.target.value)}
          >
            <option value="">Any index</option>
            <option value="indexed">Indexed</option>
            <option value="not_indexed">Not indexed</option>
            <option value="uncertain">Index uncertain</option>
            <option value="unchecked">Index unchecked</option>
          </select>
          <button
            onClick={() => indexCheck.mutate()}
            className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm font-semibold text-ink hover:bg-field"
            title="Check whether source pages are indexed by Google (via proxy)"
          >
            {indexCheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gauge className="h-4 w-4" />}
            Check index
          </button>
          <button
            onClick={() => recheck.mutate()}
            className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white hover:bg-black"
          >
            {recheck.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Recheck
          </button>
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
                <Td><Status value={row.override_status || row.status} /></Td>
                <Td><span className="font-semibold">{row.score ?? "-"}</span></Td>
                <Td>
                  <Url value={row.source_page_url} />
                  {row.is_duplicate ? (
                    <span
                      className="mt-0.5 mr-1 inline-block rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-700"
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
                <Td>{formatSiteMetric(row.extra?.metrics)}</Td>
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
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/30" onClick={onClose}>
      <aside
        className="h-full w-full max-w-[680px] overflow-y-auto bg-white shadow-xl scrollbar-thin"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-line bg-white px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-ink">Backlink detail</h2>
            <p className="truncate text-xs text-muted">{data?.source_page_url}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => recheck.mutate()}
              className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white hover:bg-black"
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
        className="h-9 rounded-md border border-line bg-white px-2 text-sm"
        value={status}
        onChange={(event) => setStatus(event.target.value)}
      >
        <option value="PASS">Pass</option>
        <option value="WARNING">Warning</option>
        <option value="FAIL">Fail</option>
        <option value="NEEDS_MANUAL_REVIEW">Review</option>
      </select>
      <input
        className="h-9 flex-1 rounded-md border border-line bg-white px-3 text-sm"
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
      <section className="rounded-lg border border-line bg-panel p-8 text-center text-sm text-muted">
        Select a project (top-left) to import links into it.
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-line bg-panel">
      <SectionTitle title="Paste Import" />
      <div className="space-y-3 p-4">
        <textarea
          className="min-h-[260px] w-full rounded-md border border-line bg-white p-3 font-mono text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-ocean/20"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <button
          onClick={() => submit.mutate()}
          className="flex h-10 items-center gap-2 rounded-md bg-ocean px-4 text-sm font-semibold text-white hover:bg-teal-800"
        >
          {submit.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          Queue import
        </button>
      </div>
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
          project_id: projectId,
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
    <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
      <form
        className="rounded-lg border border-line bg-panel p-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <SectionTitle title="New Rule" flush />
        <div className="space-y-3 pt-3">
          <Field label="Name" value={name} onChange={setName} />
          <label className="block">
            <span className="mb-1 block text-xs font-semibold uppercase text-muted">Severity</span>
            <select
              className="h-10 w-full rounded-md border border-line bg-white px-3 text-sm"
              value={minSeverity}
              onChange={(event) => setMinSeverity(event.target.value)}
            >
              <option>CRITICAL</option>
              <option>HIGH</option>
              <option>MEDIUM</option>
              <option>LOW</option>
            </select>
          </label>
          <button className="flex h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-semibold text-white">
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bell className="h-4 w-4" />}
            Save rule
          </button>
        </div>
      </form>
      <section className="rounded-lg border border-line bg-panel">
        <SectionTitle title="Alert Rules" />
        <div className="divide-y divide-line">
          {(alerts.data || []).map((rule) => (
            <div key={rule.id} className="flex items-center justify-between gap-3 p-4">
              <div className="min-w-0">
                <div className="truncate font-medium text-ink">{rule.name}</div>
                <div className="mt-1 text-xs text-muted">
                  {rule.channels.join(", ")} / {rule.dedup_window_minutes}m dedup
                </div>
              </div>
              <Severity value={rule.min_severity} />
            </div>
          ))}
          {!alerts.isLoading && !alerts.data?.length ? <Empty label="No alert rules yet" /> : null}
        </div>
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
  ["link_type", "link_type", "Link type"]
];

// Plain-language report types (non-technical labels + a one-line description).
const REPORT_TYPES: Array<{ value: string; label: string; desc: string }> = [
  { value: "monthly_qa", label: "Full QA report", desc: "Every selected link with its full QA result, score, index and duplicate status." },
  { value: "failed_links", label: "Problem links only", desc: "Only the links failing QA — the ones that need action." },
  { value: "change_history", label: "Change history", desc: "What changed over time: links lost, status flips, anchor / rel changes." },
  { value: "client", label: "Client summary", desc: "A clean, client-facing summary of backlink health." },
  { value: "vendor", label: "Vendor report", desc: "Results grouped for reviewing a vendor's delivered links." },
  { value: "campaign", label: "Campaign report", desc: "Results for one outreach campaign." }
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
  link_type: "Link type"
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
      <div className="rounded-lg border border-line bg-panel">
        <div className="border-b border-line p-4">
          <h2 className="text-base font-semibold text-ink">Build a report</h2>
          <p className="text-sm text-muted">
            Pick what to include, choose a file type, and generate. Each time you generate the
            same report, it&apos;s saved as a new <span className="font-medium text-ink">version</span>{" "}
            — older ones are kept so you always have history.
          </p>
        </div>

        <div className="space-y-4 p-4">
          {/* Step 1 — type */}
          <div>
            <div className="mb-1.5 text-xs font-semibold uppercase text-muted">1 · What to report</div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {REPORT_TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setType(t.value)}
                  className={clsx(
                    "rounded-md border p-3 text-left transition",
                    type === t.value
                      ? "border-ocean bg-teal-50 ring-1 ring-ocean/30"
                      : "border-line bg-white hover:border-ocean/40"
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
            <div className="rounded-md border border-line bg-white p-3">
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
                      className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
                      "rounded-md border px-3 py-2 text-sm transition",
                      format === f.value
                        ? "border-ink bg-ink text-white"
                        : "border-line bg-white text-ink hover:border-ink/40"
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => create.mutate()}
                disabled={create.isPending}
                className="flex h-11 items-center justify-center gap-2 rounded-md bg-ocean px-5 text-sm font-semibold text-white transition hover:bg-teal-800 disabled:opacity-50"
              >
                {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
                Generate {activeType?.label || "report"}
              </button>
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
    <div className="rounded-lg border border-line bg-panel">
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-ocean" />
            <span className="font-semibold text-ink">{typeLabel(latest.report_type)}</span>
            <span className="rounded bg-field px-1.5 py-0.5 text-[11px] font-medium text-ink">
              {latest.project_name || "All projects"}
            </span>
            <span className="rounded bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700">
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
            className="flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:opacity-50"
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
                    className="flex items-center gap-1 rounded-md border border-line bg-white px-2 py-1 text-xs font-medium text-ink transition hover:bg-field disabled:cursor-not-allowed disabled:opacity-50"
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
            className="h-9 w-44 rounded-md border border-line bg-white px-3 text-sm"
            placeholder="Search domain…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
            className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white transition hover:bg-black"
          >
            {recompute.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Recompute
          </button>
          <button
            onClick={() => fetchMetrics.mutate()}
            className="flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink transition hover:bg-field"
          >
            {fetchMetrics.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
            Fetch metrics
          </button>
        </div>
      </div>
      <section className="rounded-lg border border-line bg-panel">
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
                      <span key={k} className="rounded border border-line bg-white px-2 py-0.5 text-xs">
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
          className="flex h-9 items-center gap-2 self-start rounded-md bg-ink px-3 text-sm font-semibold text-white transition hover:bg-black"
        >
          {sync.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Sync from sheets
        </button>
      </div>

      <section className="rounded-lg border border-line bg-panel">
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
                      className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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

      <section className="rounded-lg border border-line bg-panel">
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
                      className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
                      className="grid h-7 w-7 place-items-center rounded border border-line bg-white text-muted transition hover:bg-field hover:text-danger"
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
            className="h-9 w-32 rounded-md border border-line bg-white px-2 text-sm"
            placeholder="Code"
            value={newCode}
            onChange={(event) => setNewCode(event.target.value)}
          />
          <input
            className="h-9 flex-1 rounded-md border border-line bg-white px-2 text-sm"
            placeholder="Name (optional)"
            value={newCodeName}
            onChange={(event) => setNewCodeName(event.target.value)}
          />
          <button className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white transition hover:bg-black">
            {addCode.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add code
          </button>
        </form>
      </section>
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

  if (!projectId) {
    return (
      <div className="rounded-lg border border-line bg-panel">
        <Empty label="Select a project (top‑left) to manage its settings and main domains." />
      </div>
    );
  }

  const s = settings.data;
  return (
    <section className="grid gap-5 xl:grid-cols-2">
      <section className="rounded-lg border border-line bg-panel">
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
                    <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-ember">
                      Primary
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {!d.is_primary ? (
                    <button
                      onClick={() => setPrimary.mutate(d.id)}
                      className="rounded border border-line bg-white px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
                    >
                      Set primary
                    </button>
                  ) : null}
                  <button
                    onClick={() => removeDomain.mutate(d.id)}
                    aria-label="Remove domain"
                    className="grid h-7 w-7 place-items-center rounded border border-line bg-white text-muted transition hover:bg-field hover:text-danger"
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
              className="h-10 flex-1 rounded-md border border-line bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
              placeholder="example.com"
              value={newDomain}
              onChange={(event) => setNewDomain(event.target.value)}
            />
            <button className="flex h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-semibold text-white transition hover:bg-black">
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

      <section className="rounded-lg border border-line bg-panel">
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
              className="h-10 w-full rounded-md border border-line bg-white px-3 text-sm"
              value={s?.scoring_profile || "inherit_global"}
              disabled={!s || saveSettings.isPending}
              onChange={(event) => saveSettings.mutate({ scoring_profile: event.target.value })}
            >
              <option value="inherit_global">Inherit global scoring</option>
              <option value="custom">Custom (per‑project scoring)</option>
            </select>
          </label>
          <p className="text-xs text-muted">
            Per‑parameter scoring weights arrive in a later step; this chooses whether the project
            uses global defaults or its own rules.
          </p>
        </div>
      </section>
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

      <section className="rounded-lg border border-line bg-panel">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">Duplicate &amp; conflict groups</h2>
            <p className="mt-0.5 text-xs text-muted">
              Backlinks pointing at the same page (matched by URL fingerprint), grouped for review.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <select
              className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
              className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white transition hover:bg-black"
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
              <span className="rounded border border-violet-200 bg-violet-50 px-2 py-0.5 font-semibold text-plum">
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
              className="rounded border border-line bg-white px-2 py-1 text-xs font-medium text-ink transition hover:bg-field"
            >
              Resolve
            </button>
          ) : (
            <button
              onClick={() => onResolve("open")}
              className="rounded border border-line bg-white px-2 py-1 text-xs font-medium text-muted transition hover:bg-field"
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
        className="h-10 w-full rounded-md border border-line bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
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
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase text-muted">{label}</span>
        <Icon className={clsx("h-4 w-4", toneClass(tone))} />
      </div>
      <div className="mt-3 text-3xl font-semibold text-ink">{value}</div>
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
      className="grid h-9 w-9 place-items-center rounded-md border border-line bg-white text-muted transition hover:bg-field hover:text-ink"
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

function Notice({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">
      <span>{text}</span>
      <button onClick={onClose} className="rounded p-1 hover:bg-teal-100" aria-label="Dismiss">
        <XCircle className="h-4 w-4" />
      </button>
    </div>
  );
}

function Status({ value }: { value: string }) {
  const tone =
    value === "PASS" || value === "completed"
      ? "bg-teal-50 text-ocean border-teal-200"
      : value === "FAIL" || value === "failed"
        ? "bg-red-50 text-danger border-red-200"
        : value === "WARNING"
          ? "bg-amber-50 text-ember border-amber-200"
          : value === "NEEDS_MANUAL_REVIEW"
            ? "bg-violet-50 text-plum border-violet-200"
            : "bg-slate-50 text-muted border-slate-200";
  return (
    <span className={clsx("inline-flex rounded border px-2 py-1 text-xs font-semibold", tone)}>
      {value.replaceAll("_", " ")}
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
      <div className="rounded-lg border border-line bg-panel p-4">
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
            className="flex items-center gap-2 rounded-md bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-black disabled:opacity-50"
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

      <div className="overflow-x-auto rounded-lg border border-line bg-panel">
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
                      s.last_sync_status === "ok" && "bg-emerald-50 text-emerald-700",
                      s.last_sync_status === "error" && "bg-red-50 text-danger",
                      s.last_sync_status === "running" && "bg-amber-50 text-amber-700",
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
  ["rel", "rel", "Rel"]
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
  ["source_domain", "Source domain"]
];

function pct(n: number, total: number) {
  if (!total) return "0%";
  return `${Math.round((n / total) * 100)}%`;
}

function AnalyticsDesk({ token }: { token: string | null }) {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [groupBy, setGroupBy] = useState("user");

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
      <div className="rounded-lg border border-line bg-panel p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">Analytics</h2>
          {Object.keys(filters).length ? (
            <button onClick={() => setFilters({})} className="text-xs font-medium text-ocean hover:underline">
              Clear filters
            </button>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {ANALYTICS_FACETS.map(([dim, key, label]) => {
            const opts = q.data?.facets?.[dim] || [];
            return (
              <select
                key={dim}
                className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
      <div className="rounded-lg border border-line bg-panel">
        <div className="flex items-center justify-between border-b border-line p-3">
          <h3 className="text-sm font-semibold text-ink">Breakdown</h3>
          <select
            className="h-9 rounded-md border border-line bg-white px-3 text-sm"
            value={groupBy}
            onChange={(e) => setGroupBy(e.target.value)}
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
                return (
                  <tr key={i} className="hover:bg-field/60">
                    <Td><span className="font-medium text-ink">{name || "—"}</span></Td>
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
      </div>
    </section>
  );
}

function IndexBadge({ value }: { value: string }) {
  const map: Record<string, string> = {
    indexed: "bg-emerald-100 text-emerald-700",
    not_indexed: "bg-red-100 text-danger",
    uncertain: "bg-amber-100 text-amber-700"
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

function toneClass(tone: "ink" | "ocean" | "ember" | "danger" | "plum") {
  return {
    ink: "text-ink",
    ocean: "text-ocean",
    ember: "text-ember",
    danger: "text-danger",
    plum: "text-plum"
  }[tone];
}

function severityClass(value: string) {
  return {
    CRITICAL: "bg-red-100 text-danger",
    HIGH: "bg-amber-100 text-ember",
    MEDIUM: "bg-yellow-100 text-yellow-800",
    LOW: "bg-slate-100 text-muted",
    INFO: "bg-teal-100 text-ocean"
  }[value] || "bg-slate-100 text-muted";
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
      <section className="rounded-lg border border-line bg-panel">
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
      <section className="rounded-lg border border-line bg-panel">
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
              className="h-10 w-full rounded-md border border-line bg-white px-3 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ocean/20"
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
            className="flex h-9 items-center justify-center gap-2 rounded-md bg-ink px-4 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {invite.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            Invite member
          </button>
        </div>
      </section>

      <section className="rounded-lg border border-line bg-panel">
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
                      className="h-9 rounded-md border border-line bg-white px-2 text-sm"
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
                          ? "border-teal-200 bg-teal-50 text-ocean"
                          : "border-slate-200 bg-slate-50 text-muted"
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
                        className="grid h-8 w-8 place-items-center rounded-md border border-line text-danger hover:bg-red-50"
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
