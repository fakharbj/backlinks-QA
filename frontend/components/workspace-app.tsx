"use client";

import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Filter,
  Gauge,
  Link2,
  Loader2,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  ShieldAlert,
  Trash2,
  Upload,
  UserPlus,
  Users,
  XCircle
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  AlertRule,
  api,
  API_BASE,
  ApiError,
  BacklinkDetail,
  BacklinkRow,
  Dashboard,
  Page,
  Project,
  Report,
  Role,
  TeamMember,
  TokenPair
} from "@/lib/api";

type Tab = "overview" | "backlinks" | "imports" | "alerts" | "reports" | "team";

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
    setToken(localStorage.getItem("ls_access"));
    setRefreshToken(localStorage.getItem("ls_refresh"));
  }, []);

  const authed = Boolean(token);
  const projects = useQuery({
    queryKey: ["projects", token],
    enabled: authed,
    queryFn: () => api<Project[]>("/projects", { token })
  });

  useEffect(() => {
    if (!activeProjectId && projects.data?.length) {
      setActiveProjectId(projects.data[0].id);
    }
  }, [activeProjectId, projects.data]);

  function saveTokens(tokens: TokenPair) {
    localStorage.setItem("ls_access", tokens.access_token);
    localStorage.setItem("ls_refresh", tokens.refresh_token);
    setToken(tokens.access_token);
    setRefreshToken(tokens.refresh_token);
  }

  function logout() {
    localStorage.removeItem("ls_access");
    localStorage.removeItem("ls_refresh");
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
          {tab === "backlinks" ? (
            <Backlinks token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "imports" ? (
            <ImportDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "alerts" ? (
            <AlertsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "reports" ? (
            <ReportsDesk token={token} projectId={activeProjectId} onNotice={setNotice} />
          ) : null}
          {tab === "team" ? <TeamDesk token={token} onNotice={setNotice} /> : null}
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
    ["backlinks", "Backlinks", Link2],
    ["imports", "Imports", Upload],
    ["alerts", "Alerts", Bell],
    ["reports", "Reports", FileSpreadsheet],
    ["team", "Team", Users]
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
        {projects.length === 0 ? <option value="">No projects</option> : null}
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
  const dashboard = useQuery({
    queryKey: ["dashboard", token, projectId],
    enabled: Boolean(token && projectId),
    queryFn: () => api<Dashboard>(`/dashboard?project_id=${projectId}`, { token })
  });

  const stats = dashboard.data;
  return (
    <section className="space-y-5">
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useMemo(() => {
    const params = new URLSearchParams({ project_id: projectId, limit: "50", with_total: "true" });
    if (status) params.set("status", status);
    return params.toString();
  }, [projectId, status]);
  const backlinks = useQuery({
    queryKey: ["backlinks", token, query],
    enabled: Boolean(token && projectId),
    queryFn: () => api<Page<BacklinkRow>>(`/backlinks?${query}`, { token })
  });
  const recheck = useMutation({
    mutationFn: () =>
      api<{ job_id: string; queued: number }>("/backlinks/recheck", {
        token,
        method: "POST",
        body: JSON.stringify({ project_id: projectId, priority: true })
      }),
    onSuccess: (data) => {
      onNotice(`Queued ${data.queued} backlinks`);
      queryClient.invalidateQueries({ queryKey: ["backlinks"] });
    },
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
                <Td><Url value={row.source_page_url} /></Td>
                <Td><Url value={row.target_url} /></Td>
                <Td>{row.http_status ?? "-"}</Td>
                <Td>{row.current_rel ?? "-"}</Td>
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
            </DetailBlock>

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
  const [format, setFormat] = useState("pdf");
  const [type, setType] = useState("monthly_qa");
  const reports = useQuery({
    queryKey: ["reports", token],
    enabled: Boolean(token),
    queryFn: () => api<Report[]>("/reports", { token })
  });
  const create = useMutation({
    mutationFn: () =>
      api<Report>("/reports", {
        token,
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          report_type: type,
          format,
          title: `${type.replace("_", " ")} report`,
          filters: { limit: 50000 }
        })
      }),
    onSuccess: () => {
      onNotice("Report queued");
      queryClient.invalidateQueries({ queryKey: ["reports"] });
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
      link.download = `${report.title || "report"}.${report.format}`.replace(/\s+/g, "_");
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      onNotice(err instanceof Error ? err.message : "Download failed");
    }
  }

  return (
    <section className="rounded-lg border border-line bg-panel">
      <div className="flex flex-col gap-3 border-b border-line p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="text-base font-semibold text-ink">Reports</h2>
          <p className="text-sm text-muted">CSV, XLSX, and PDF exports</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className="h-9 rounded-md border border-line bg-white px-3 text-sm" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="monthly_qa">Monthly QA</option>
            <option value="failed_links">Failed links</option>
            <option value="client">Client</option>
            <option value="campaign">Campaign</option>
            <option value="vendor">Vendor</option>
            <option value="change_history">Change history</option>
          </select>
          <select className="h-9 rounded-md border border-line bg-white px-3 text-sm" value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="pdf">PDF</option>
            <option value="xlsx">XLSX</option>
            <option value="csv">CSV</option>
          </select>
          <button onClick={() => create.mutate()} className="flex h-9 items-center gap-2 rounded-md bg-ink px-3 text-sm font-semibold text-white">
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
            Generate
          </button>
        </div>
      </div>
      <div className="divide-y divide-line">
        {(reports.data || []).map((report) => (
          <div key={report.id} className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="font-medium text-ink">{report.title}</div>
              <div className="mt-1 text-xs text-muted">
                {report.report_type} / {report.format} / {report.row_count ?? "-"} rows
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Status value={report.status.toUpperCase()} />
              <button
                disabled={report.status !== "completed"}
                onClick={() => download(report)}
                className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm font-medium text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Download className="h-4 w-4" />
                Download
              </button>
            </div>
          </div>
        ))}
        {!reports.isLoading && !reports.data?.length ? <Empty label="No reports yet" /> : null}
      </div>
    </section>
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
