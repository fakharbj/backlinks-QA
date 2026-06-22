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
  last_checked_at: string | null;
  next_check_at: string | null;
  assigned_user_id: string | null;
  tags: string[];
  extra?: { moz?: MozMetrics } | null;
};

export type MozMetrics = {
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

export type IssueOut = {
  code: string;
  label: string;
  category: string;
  severity: string;
  message: string;
  recommendation: string | null;
  evidence: Record<string, unknown>;
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
  latest_result: CrawlResultOut | null;
  history: HistoryEventOut[];
};

export type Report = {
  id: string;
  project_id: string | null;
  report_type: string;
  format: string;
  status: string;
  title: string;
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

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {}
): Promise<T> {
  const { token, headers, ...rest } = options;
  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      ...(rest.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers
    }
  });

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
