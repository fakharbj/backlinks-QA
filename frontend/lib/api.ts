export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export type Project = {
  id: string;
  name: string;
  client_name: string | null;
  target_domain: string | null;
  status: string;
  schedule_interval: string;
  created_at: string;
};

export type ConflictMember = {
  backlink_id: string;
  project_id: string | null;
  project_name: string | null;
  source_page_url: string;
  target_url: string;
  status: string | null;
  score: number | null;
  assigned_user_label: string | null;
  link_type: string | null;
  // ── Enriched comparison fields (0034) ──
  source_domain?: string | null;
  current_anchor_text?: string | null;
  expected_anchor_text?: string | null;
  current_rel?: string | null;
  expected_rel?: string | null;
  target_url_normalized?: string | null;
  target_domain?: string | null;
  index_status?: string | null;
  duplicate_status?: string | null;
  is_duplicate?: boolean | null;
  placement_date?: string | null;
  created_at?: string | null;
  last_checked_at?: string | null;
  override_status?: string | null;
};

export type ConflictGroup = {
  id: string;
  canonical_url: string | null;
  fingerprint: string | null;
  project_id: string | null;
  scope: string;
  resolution_status: string;
  member_count: number;
  detected_at: string | null;
  created_at: string | null;
  // ── Enterprise facts (0034) ──
  reason?: string | null;
  similarity?: number | null;
  first_member_id?: string | null;
  distinct_projects?: number | null;
  distinct_users?: number | null;
  distinct_targets?: number | null;
  members: ConflictMember[];
};

export type ConflictFieldMatrixRow = {
  field: string;
  all_same: boolean;
  distinct: number;
  values: Array<unknown>;
  cells?: Array<unknown>; // each member's actual value, aligned to members order
};

export type ConflictAction = {
  id: string;
  action: string;
  payload: Record<string, unknown>;
  actor_user_id: string | null;
  note: string | null;
  created_at: string | null;
};

export type ConflictDetail = ConflictGroup & {
  field_matrix: ConflictFieldMatrixRow[];
  suggested_keep: string | null;
  actions: ConflictAction[];
  total_members: number;
  members_truncated: boolean;
};

export type ConflictSummary = {
  total: number;
  open: number;
  resolved: number;
  by_scope: Record<string, number>;
  by_status?: Record<string, number>;
  avg_similarity?: number | null;
  total_duplicate_links?: number;
  weekly?: Array<{ week: string; new_groups: number }>;
};

export type ProjectDomain = {
  id: string;
  domain: string;
  is_primary: boolean;
};

export type ProjectSettings = {
  project_id: string;
  scoring_profile: string;
  index_expected: boolean;
  treat_sponsored_as_follow: boolean;
  status_thresholds: Record<string, number>;
  domains: ProjectDomain[];
};

export type AppUser = {
  id: string;
  name: string | null;
  email: string;
};

export type EmployeeCode = {
  id: string;
  code: string;
  display_name: string | null;
  user_id: string | null;
  user_name: string | null;
  is_active: boolean;
};

export type EmployeeMapping = {
  id: string;
  sheet_user_label: string;
  user_id: string | null;
  user_name: string | null;
  employee_code_id: string | null;
  backlink_count: number;
  is_active?: boolean; // false = laid off (hidden from pickers; history kept)
  canonical_label?: string | null; // set = this label is an ALIAS rolled up into canonical_label
};

export type EmployeeOverview = {
  codes: EmployeeCode[];
  mappings: EmployeeMapping[];
  app_users: AppUser[];
};

export type LabelSuggestionMember = { label: string; backlink_count: number };
export type LabelSuggestionCluster = {
  key: string;
  canonical: string; // suggested keeper (highest-count spelling)
  score: number; // 0..1 fuzzy confidence
  members: LabelSuggestionMember[];
};
export type LabelSuggestions = { clusters: LabelSuggestionCluster[] };

export type LinkType = {
  id: string;
  name: string;
  slug: string;
  color: string | null;
  description: string | null;
  is_active: boolean;
  backlink_count: number;
};

export type ScoringParameter = {
  key: string;
  display_name: string;
  description: string | null;
  category: string;
  value_kind: string;
  outcomes: Array<{ key: string; label: string }>;
  default_points: Record<string, number>;
  sort_order: number;
};

export type ScoringConfig = {
  scope: string;
  scope_ref_id: string | null;
  link_type_id?: string | null;
  version: number;
  version_id: string | null;
  rules: Record<string, Record<string, number>>;
  bands: { fail_below: number; warn_below: number };
  inherited_rules: Record<string, Record<string, number>>;
  inherited_bands: { fail_below: number; warn_below: number };
  note: string | null;
  parameters: ScoringParameter[];
};

export type RescoreResult = {
  scope: string;
  applied: boolean;
  total: number;
  changed: number;
  avg_score_delta: number;
  transitions: Record<string, number>;
};

export type Batch = {
  id: string;
  seq: number;
  kind: string;
  status: string;
  label: string | null;
  project_id: string | null;
  started_by: string | null;
  totals: Record<string, number>;
  counters: Record<string, number>;
  meta: Record<string, unknown>;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  // Review batches only: items still awaiting a decision.
  review_pending?: number | null;
};

// One staged row of a review batch (link or domain) — QA verdicts / metrics
// live in payload only until the item is approved.
export type BatchItemQA = {
  status?: string | null;
  score?: number | null;
  link_found?: boolean | null;
  rendered?: boolean | null;
  http_status?: number | null;
  final_url?: string | null;
  anchor?: string | null;
  rel?: string | null;
  matched_href?: string | null;
  is_followable?: boolean | null;
  indexability?: string | null;
  robots_status?: string | null;
  canonical_status?: string | null;
  top_issue?: string | null;
  issues?: Array<{ code?: string | null; label?: string | null; severity?: string | null; message?: string | null }>;
  word_count?: number | null;
};

export type BatchItemMetrics = {
  da?: number | null;
  pa?: number | null;
  spam_score?: number | null;
  semrush_as?: number | null;
  semrush_traffic?: number | null;
  semrush_keywords?: number | null;
  domain_age_days?: number | null;
  domain_created_on?: string | null;
  metrics_updated_at?: string | null;
};

export type BatchItem = {
  id: string;
  kind: string;
  label: string;
  presence: string;
  state: string;
  error: string | null;
  payload: {
    mapped?: Record<string, string>;
    source_domain?: string;
    row?: number;
    qa?: BatchItemQA;
    metrics?: BatchItemMetrics;
  };
  checked_at: string | null;
  approved_at: string | null;
  created_at: string | null;
};

export type BatchItemsPage = {
  items: BatchItem[];
  counts: { total: number; by_state: Record<string, number>; by_presence: Record<string, number> };
};

export type BatchLog = {
  level: string;
  message: string;
  row_ref: string | null;
  data: Record<string, unknown>;
  created_at: string;
};

export type ImportRowError = { row_number: number; error: string; raw: Record<string, string> };

export type CompetitorSheet = {
  id: string;
  name: string;
  competitor_url?: string | null;
  source_kind: string;
  status: string;
  total_rows: number;
  domain_count: number;
  new_domains: number;
  existing_domains: number;
  created_at: string;
};

export type CompetitorParent = {
  competitor: string;
  display_name: string;
  competitor_url: string | null;
  uploads: number;
  total_rows: number;
  new_domains: number;
  existing_domains: number;
  first_upload_at: string | null;
  last_upload_at: string | null;
  sheet_ids: string[];
};

export type CompetitorDomain = {
  id: string;
  domain_key: string;
  url_count: number;
  category: string;
  our_link_count: number;
  our_indexed_pct: number | null;
  is_new: boolean;
  da: number | null;
  pa: number | null;
  decision: string;
  decision_reason: string | null;
  has_guest_post: boolean;
};

export type CompetitorSummary = {
  domains: number;
  new_opportunities: number;
  existing: number;
  dismissed: number;
  competitor_links: number;
  avg_da?: number | null;
  avg_as?: number | null;
};

export type SourceDomain = {
  id: string;
  domain_key: string;
  grouping: string;
  backlink_count: number;
  indexed_count: number;
  not_indexed_count: number;
  uncertain_count: number;
  unchecked_count: number;
  indexed_pct: number;
  not_indexed_pct: number;
  dofollow_count: number;
  nofollow_count: number;
  dofollow_pct: number;
  duplicate_count: number;
  qualified_count: number;
  not_qualified_count: number;
  qualified_pct: number;
  not_qualified_pct: number;
  referring_domains_count: number;
  avg_score: number | null;
  project_count: number;
  user_count: number;
  link_type_distribution: Record<string, number>;
  last_recomputed_at: string | null;
  origin: string;
  da: number | null;
  pa: number | null;
  spam_score: number | null;
  semrush_as: number | null;
  semrush_traffic: number | null;
  semrush_keywords: number | null;
  domain_age_days: number | null;
  metrics_updated_at: string | null;
};

// Paginated list envelope for the Source-Domains desk.
export type SourceDomainList = {
  items: SourceDomain[];
  total: number;
};

// Set-based aggregate over the filtered source-domain population (/source-domains/stats).
export type SourceDomainStats = {
  total_domains: number;
  total_backlinks: number;
  total_qualified: number;
  overall_qualified_pct: number;
  overall_indexed_pct: number;
  avg_da: number | null;
  avg_pa: number | null;
  avg_spam: number | null;
  avg_as: number | null;
  count_da_ge_50: number;
  count_spam_le_5: number;
  count_indexed: number;
};

// Rules engine — a whitelisted condition ({field, op, value(s)}) matched all/any.
export type SourceDomainRuleCondition = {
  field: string;
  op: string;
  value?: number | null;
  value2?: number | null;
  value_str?: string | null;
};

export type SourceDomainRuleDefinition = {
  match: string; // "all" | "any"
  conditions: SourceDomainRuleCondition[];
};

export type SourceDomainRule = {
  id: string;
  workspace_id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  definition: SourceDomainRuleDefinition;
  is_shared: boolean;
  created_by: string | null;
  updated_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  match_count: number | null;
};

// A named, reusable filter set stored per workspace.
export type SourceDomainSavedFilter = {
  name: string;
  params: Record<string, string>;
};

export type SourceDomainBacklink = {
  id: string;
  project_name: string | null;
  source_page_url: string;
  target_url: string;
  status: string | null;
  score: number | null;
  link_type: string | null;
  index_status: string | null;
  assigned_user_label: string | null;
};

export type SourceDomainDetail = SourceDomain & {
  backlinks: SourceDomainBacklink[];
};

export type Dashboard = {
  totals: {
    total: number;
    pass_count: number;
    warning_count: number;
    fail_count: number;
    unknown_count: number;
    review_count: number;
    pending_count: number;
    avg_score: number | null;
  };
  issues: {
    nofollow_count: number;
    noindex_count: number;
    robots_blocked_count: number;
    canonical_issue_count: number;
    broken_count: number;
    link_missing_count: number;
  };
  lost: { today: number; week: number; month: number };
  top_failing_domains: Array<{
    source_domain: string;
    total: number;
    fail_count: number;
    failure_rate: number | null;
  }>;
  top_vendors_by_failure: Array<{
    vendor_id: string;
    vendor_name: string | null;
    total: number;
    fail_count: number;
    failure_rate: number | null;
    avg_score: number | null;
  }>;
  recent_changes: Array<{
    backlink_id: string;
    source_page_url: string;
    event_type: string;
    severity: string | null;
    created_at: string;
  }>;
  // Company-view entity totals (empty for a project dashboard).
  counts?: Record<string, number>;
  // Headline KPI boxes (HTTP buckets / index / qualified / spam / duplicate /
  // orphaned) — one aggregate pass, project + RBAC scoped. All optional numbers.
  kpi?: {
    http_200?: number;
    http_301?: number;
    http_302?: number;
    http_404?: number;
    broken?: number;
    indexed?: number;
    not_indexed?: number;
    qualified?: number;
    non_qualified?: number;
    duplicate?: number;
    spam?: number;
    orphaned?: number;
    [key: string]: number | undefined;
  };
  // Project-dashboard-only sections (empty for the company view).
  is_project: boolean;
  link_type_breakdown: Array<{
    link_type: string;
    total: number;
    pass_count: number;
    fail_count: number;
    avg_score: number | null;
  }>;
  trends: Array<{ date: string; added: number; removed: number; score_changed: number }>;
  top_source_domains: Array<{
    source_domain: string;
    total: number;
    pass_count: number;
    fail_count: number;
    indexed_pct: number | null;
  }>;
  recent_regressions: Array<{
    backlink_id: string;
    source_page_url: string;
    event_type: string;
    severity: string | null;
    field: string | null;
    old_value: string | null;
    new_value: string | null;
    created_at: string;
  }>;
  assigned_user_stats: Array<{
    assigned_user_label: string;
    total: number;
    pass_count: number;
    fail_count: number;
    avg_score: number | null;
  }>;
};

export type BacklinkRow = {
  id: string;
  project_id: string;
  source_page_url: string;
  target_url: string;
  status: string;
  override_status: string | null;
  score: number | null;
  link_found: boolean | null;
  current_rel: string | null;
  current_anchor_text: string | null;
  http_status: number | null;
  indexability: string | null;
  canonical_status: string | null;
  robots_status: string | null;
  issue_count: number;
  top_issue_label: string | null;
  created_at?: string | null;
  updated_at?: string | null; // last modified in our DB
  sheet_created_date?: string | null; // the sheet's own link-building date
  placement_date?: string | null; // when the link was placed live
  discovered_at?: string | null; // first time we saw/crawled it
  first_qa_at?: string | null; // first QA check
  qa_completed_at?: string | null; // QA reached a terminal verdict
  assigned_at?: string | null; // assigned to a user
  index_checked_at?: string | null; // last index check
  last_checked_at: string | null;
  next_check_at: string | null;
  targets_on_source?: number | null; // distinct targets this source page links to
  assigned_user_id: string | null;
  assigned_user_label?: string | null;
  employee_code?: string | null;
  link_type?: string | null;
  is_duplicate?: boolean;
  duplicate_status?: string | null;
  index_status?: string | null;
  domain_da?: number | null;
  domain_pa?: number | null;
  domain_as?: number | null;
  domain_spam?: number | null;
  tags: string[];
  extra?: { metrics?: SiteMetrics } | null;
};

export type AssignmentEvent = {
  old_user_label: string | null;
  new_user_label: string | null;
  source: string;
  changed_at: string;
};

// Headline KPI/summary counts for the analytics filtered set. All optional numbers
// so older/partial backend responses stay type-safe; the index signature keeps the
// existing `s[...]` access pattern working for keys not spelled out here.
export type AnalyticsSummary = {
  total?: number;
  avg_score?: number | null;
  pass?: number;
  warning?: number;
  fail?: number;
  unknown?: number;
  review?: number;
  pending?: number;
  indexed?: number;
  not_indexed?: number;
  index_unchecked?: number;
  nofollow?: number;
  dofollow?: number;
  duplicates?: number;
  link_missing?: number;
  // HTTP-status KPI buckets.
  http_200?: number;
  http_301?: number;
  http_302?: number;
  http_404?: number;
  broken?: number;
  redirects?: number;
  // Source-domain-backed buckets.
  spam?: number;
  orphaned?: number;
  // Plain-English aliases (PASS→qualified, FAIL→non_qualified).
  qualified?: number;
  non_qualified?: number;
  [key: string]: number | null | undefined;
};

export type AnalyticsResponse = {
  summary: AnalyticsSummary;
  facets: Record<string, Array<{ value: string; label?: string; count: number }>>;
  groups: Array<Record<string, number | string>>;
  dimensions: string[];
};

export type SheetSource = {
  id: string;
  project_id: string;
  project_name: string;
  spreadsheet_id: string;
  sheet_tab: string | null;
  source_url: string | null;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
  row_count: number;
  imported_count: number;
  updated_count: number;
  writeback_enabled: boolean;
};

export type SheetConfig = {
  enabled: boolean;
  service_account_email: string | null;
  main_sheet_id: string | null;
};

export type SiteMetrics = {
  provider?: string | null;
  global_rank?: number | null;
  monthly_visits?: number | null;
  category?: string | null;
  da?: number | null;
  pa?: number | null;
  spam_score?: number | null;
  fetched_at?: string | null;
};

export type Page<T> = {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
  total: number | null;
};

// One spam-keyword hit surfaced in issue.evidence.matches (new shape). Older
// rows carry evidence.keywords (string[]) instead — readers tolerate both.
export type SpamMatch = {
  keyword?: string | null;
  category?: string | null;
  region?: string | null;
  snippet?: string | null;
};

export type IssueEvidence = {
  matches?: SpamMatch[];
  keywords?: string[]; // legacy shape
  [key: string]: unknown;
};

export type IssueOut = {
  code: string;
  label: string;
  category: string;
  severity: string;
  message: string;
  recommendation: string | null;
  evidence: IssueEvidence;
};

export type HistoryEventOut = {
  event_type: string;
  severity: string | null;
  field: string | null;
  old_value: string | null;
  new_value: string | null;
  score_delta: number | null;
  created_at: string;
};

export type ScoreStep = {
  code: string;
  severity: string;
  delta: number;
  cap_applied: number | null;
  note: string;
  // ── Explainability metadata (additive; older breakdown rows lack these) ──
  parameter_key?: string | null;
  parameter_label?: string | null;
  outcome_key?: string | null;
  outcome_label?: string | null;
  // where the delta came from: "severity" | "ruleset" | "metric_signal" | "cap"
  source?: string | null;
  configured_points?: number | null;
};

export type CrawlResultOut = {
  id: string;
  crawled_at: string;
  crawl_mode: string;
  http_status: number | null;
  final_url: string | null;
  content_type: string | null;
  redirect_chain: Array<{ url: string; status: number; location?: string | null }>;
  meta_robots: string | null;
  x_robots_tag: string | null;
  canonical_url: string | null;
  anchor_text: string | null;
  rel_values: string[];
  status: string;
  score: number;
  is_followable: boolean | null;
  is_indexable: string | null;
  score_breakdown: ScoreStep[];
  word_count: number | null;
  outbound_link_count: number | null;
  published_date: string | null;
  modified_date: string | null;
  date_source: string | null;
  raw_html_key: string | null;
  rendered_html_key: string | null;
  matched_href?: string | null; // the exact href we matched on the page
  scoring_rule_version_id?: string | null; // which rule set produced this verdict (if exposed)
};

export type BacklinkDetail = BacklinkRow & {
  expected_target_url: string | null;
  expected_anchor_text: string | null;
  expected_rel: string;
  final_url: string | null;
  source_domain: string;
  target_domain: string | null;
  override_note: string | null;
  notes: string | null;
  issues: IssueOut[];
  recommendations: string[];
  score_breakdown: ScoreStep[];
  scoring_rule_version_id?: string | null; // which rule set scored this link (if exposed)
  latest_result: CrawlResultOut | null;
  history: HistoryEventOut[];
};

export type Report = {
  id: string;
  project_id: string | null;
  project_name?: string | null;
  report_type: string;
  format: string;
  status: string;
  title: string;
  version?: number;
  is_latest?: boolean;
  filters?: Record<string, unknown>;
  row_count: number | null;
  file_size: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type AlertRule = {
  id: string;
  name: string;
  project_id: string | null;
  event_types: string[];
  min_severity: string;
  score_drop_threshold: number | null;
  channels: string[];
  dedup_window_minutes: number;
  digest_mode: boolean;
  is_active: boolean;
};

export type Role = "admin" | "manager" | "qa" | "viewer";

export type TeamMember = {
  user_id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  member_since: string;
};

export type Me = {
  user: { id: string; email: string; full_name: string; is_active: boolean };
  workspaces: Array<{ id: string; name: string; slug: string; role: string | null }>;
  active_workspace_id: string | null;
  role: Role | null;
};

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(status: number, message: string, details: unknown = null) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

// ── Durable session: token manager + transparent refresh ───────────────────
let _access: string | null = null;
let _refresh: string | null = null;
let _refreshing: Promise<boolean> | null = null;

export function loadTokens(): string | null {
  if (typeof window !== "undefined") {
    _access = localStorage.getItem("ls_access");
    _refresh = localStorage.getItem("ls_refresh");
  }
  return _access;
}

export function setTokens(t: TokenPair) {
  _access = t.access_token;
  _refresh = t.refresh_token;
  if (typeof window !== "undefined") {
    localStorage.setItem("ls_access", t.access_token);
    localStorage.setItem("ls_refresh", t.refresh_token);
  }
}

export function clearTokens() {
  _access = null;
  _refresh = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem("ls_access");
    localStorage.removeItem("ls_refresh");
  }
}

export function getAccessToken(): string | null {
  return _access;
}

/** Exchange the refresh token for a fresh pair (single-flight). */
export async function refreshAccess(): Promise<boolean> {
  if (!_refresh) return false;
  if (!_refreshing) {
    _refreshing = (async () => {
      try {
        const resp = await fetch(`${API_BASE}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: _refresh })
        });
        if (!resp.ok) return false;
        setTokens((await resp.json()) as TokenPair);
        return true;
      } catch {
        return false;
      } finally {
        _refreshing = null;
      }
    })();
  }
  return _refreshing;
}

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token, headers, ...rest } = options;
  // Always use the managed access token (kept fresh by refresh); the passed token
  // is only a fallback before tokens are loaded.
  const authHeader = (): Record<string, string> => {
    const tok = _access ?? token ?? null;
    return tok ? { Authorization: `Bearer ${tok}` } : {};
  };
  const doFetch = () =>
    fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: {
        ...(rest.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...authHeader(),
        ...headers
      }
    });

  let response = await doFetch();

  // Access token expired → refresh once and retry transparently.
  if (response.status === 401 && _refresh && !path.startsWith("/auth/")) {
    if (await refreshAccess()) {
      response = await doFetch();
    } else {
      clearTokens();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event("ls-auth-expired"));
      }
    }
  }

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    let details: unknown = null;
    try {
      const body = await response.json();
      message = body?.error?.message || message;
      details = body?.error?.details || body;
    } catch {
      // response was not JSON
    }
    throw new ApiError(response.status, message, details);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
