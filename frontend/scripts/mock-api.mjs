import http from "node:http";
import { randomUUID } from "node:crypto";

const port = Number(process.env.MOCK_API_PORT || 8000);

const now = () => new Date().toISOString();

const projects = [
  {
    id: "proj_demo",
    name: "Acme Backlinks",
    client_name: "Acme Co",
    target_domain: "acme.test",
    status: "ACTIVE",
    schedule_interval: "daily",
    created_at: now()
  }
];

const backlinks = [
  row("PASS", 96, "https://example.com/best-seo-tools", "https://acme.test/seo", 200, "dofollow", null),
  row("WARNING", 72, "https://publisher.test/acme-review", "https://acme.test/pricing", 200, "nofollow", "NOFOLLOW"),
  row("FAIL", 24, "https://old-blog.test/resources", "https://acme.test/seo", 404, null, "SOURCE_404"),
  row("NEEDS_MANUAL_REVIEW", 61, "https://waf.test/partner", "https://acme.test/demo", 403, null, "BOT_PROTECTION"),
  row("PENDING", null, "https://new-site.test/article", "https://acme.test/seo", null, null, null)
];

const alertRules = [
  {
    id: "alert_demo",
    name: "Critical backlink regressions",
    project_id: "proj_demo",
    event_types: [],
    min_severity: "HIGH",
    score_drop_threshold: null,
    channels: ["in_app"],
    dedup_window_minutes: 60,
    digest_mode: false,
    is_active: true
  }
];

const reports = [
  {
    id: "report_demo",
    project_id: "proj_demo",
    report_type: "monthly_qa",
    format: "pdf",
    status: "completed",
    title: "Monthly QA report",
    row_count: backlinks.length,
    file_size: 128000,
    error: null,
    created_at: now(),
    completed_at: now()
  }
];

function row(status, score, source, target, httpStatus, rel, issue) {
  return {
    id: randomUUID(),
    project_id: "proj_demo",
    source_page_url: source,
    target_url: target,
    status,
    override_status: null,
    score,
    link_found: status !== "FAIL" && status !== "PENDING",
    current_rel: rel,
    current_anchor_text: rel ? "Acme SEO" : null,
    http_status: httpStatus,
    indexability: status === "FAIL" ? "not_indexable" : "indexable",
    canonical_status: "ok",
    robots_status: "allowed",
    issue_count: issue ? 1 : 0,
    top_issue_label: issue,
    last_checked_at: status === "PENDING" ? null : now(),
    next_check_at: now(),
    assigned_user_id: null,
    tags: ["demo"]
  };
}

const server = http.createServer(async (req, res) => {
  setCors(res);
  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url || "/", `http://${req.headers.host}`);
  const path = url.pathname.replace(/^\/api\/v1/, "");

  try {
    if (req.method === "POST" && (path === "/auth/login" || path === "/auth/register")) {
      return json(res, tokenPair());
    }

    if (req.method === "GET" && path === "/projects") {
      return json(res, projects);
    }

    if (req.method === "POST" && path === "/projects") {
      const body = await readJson(req);
      const project = {
        id: randomUUID(),
        name: body.name || "Untitled Project",
        client_name: body.client_name || null,
        target_domain: body.target_domain || null,
        status: "ACTIVE",
        schedule_interval: "daily",
        created_at: now()
      };
      projects.unshift(project);
      return json(res, project, 201);
    }

    if (req.method === "GET" && path === "/dashboard") {
      return json(res, dashboard());
    }

    if (req.method === "GET" && path === "/backlinks") {
      const status = url.searchParams.get("status");
      const items = status ? backlinks.filter((item) => item.status === status) : backlinks;
      return json(res, { items, next_cursor: null, has_more: false, total: items.length });
    }

    if (req.method === "POST" && path === "/backlinks/recheck") {
      return json(res, { job_id: randomUUID(), queued: backlinks.length });
    }

    if (req.method === "POST" && path === "/imports/paste") {
      const imported = row("PENDING", null, "https://imported.example/new-link", "https://acme.test/seo", null, null, null);
      backlinks.unshift(imported);
      return json(res, { id: randomUUID(), status: "queued" }, 201);
    }

    if (req.method === "GET" && path === "/alert-rules") {
      return json(res, alertRules);
    }

    if (req.method === "POST" && path === "/alert-rules") {
      const body = await readJson(req);
      const rule = {
        id: randomUUID(),
        name: body.name || "New alert rule",
        project_id: body.project_id || null,
        event_types: body.event_types || [],
        min_severity: body.min_severity || "HIGH",
        score_drop_threshold: body.score_drop_threshold || null,
        channels: body.channels || ["in_app"],
        dedup_window_minutes: body.dedup_window_minutes || 60,
        digest_mode: Boolean(body.digest_mode),
        is_active: true
      };
      alertRules.unshift(rule);
      return json(res, rule, 201);
    }

    if (req.method === "GET" && path === "/reports") {
      return json(res, reports);
    }

    if (req.method === "POST" && path === "/reports") {
      const body = await readJson(req);
      const report = {
        id: randomUUID(),
        project_id: body.project_id || null,
        report_type: body.report_type || "monthly_qa",
        format: body.format || "pdf",
        status: "completed",
        title: body.title || "QA report",
        row_count: backlinks.length,
        file_size: 64000,
        error: null,
        created_at: now(),
        completed_at: now()
      };
      reports.unshift(report);
      return json(res, report, 201);
    }

    const downloadMatch = path.match(/^\/reports\/([^/]+)\/download$/);
    if (req.method === "GET" && downloadMatch) {
      return json(res, { url: "data:text/plain,LinkSentinel%20mock%20report" });
    }

    return json(res, { error: { message: `No mock route for ${req.method} ${path}` } }, 404);
  } catch (error) {
    return json(res, { error: { message: error.message || "Mock server error" } }, 500);
  }
});

server.listen(port, () => {
  console.log(`Mock API running at http://localhost:${port}/api/v1`);
});

function dashboard() {
  const count = (status) => backlinks.filter((item) => item.status === status).length;
  return {
    totals: {
      total: backlinks.length,
      pass_count: count("PASS"),
      warning_count: count("WARNING"),
      fail_count: count("FAIL"),
      unknown_count: count("UNKNOWN"),
      review_count: count("NEEDS_MANUAL_REVIEW"),
      pending_count: count("PENDING"),
      avg_score: Math.round(
        backlinks.filter((item) => typeof item.score === "number").reduce((sum, item) => sum + item.score, 0) /
          backlinks.filter((item) => typeof item.score === "number").length
      )
    },
    issues: {
      nofollow_count: backlinks.filter((item) => item.top_issue_label === "NOFOLLOW").length,
      noindex_count: 0,
      robots_blocked_count: 0,
      canonical_issue_count: 0,
      broken_count: backlinks.filter((item) => item.top_issue_label === "SOURCE_404").length,
      link_missing_count: 1
    },
    lost: { today: 1, week: 2, month: 4 },
    top_failing_domains: [
      { source_domain: "old-blog.test", total: 1, fail_count: 1, failure_rate: 1 }
    ],
    top_vendors_by_failure: [
      { vendor_id: "vendor_demo", vendor_name: "EditorialHub", total: backlinks.length, fail_count: count("FAIL"), failure_rate: 0.2, avg_score: 72 }
    ],
    recent_changes: backlinks.slice(0, 4).map((item) => ({
      backlink_id: item.id,
      source_page_url: item.source_page_url,
      event_type: item.status === "FAIL" ? "lost" : "checked",
      severity: item.status === "FAIL" ? "HIGH" : "INFO",
      created_at: now()
    }))
  };
}

function tokenPair() {
  return {
    access_token: "mock-access-token",
    refresh_token: "mock-refresh-token",
    token_type: "bearer",
    expires_in: 3600
  };
}

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS");
}

function json(res, body, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (chunk) => {
      data += chunk;
    });
    req.on("end", () => {
      if (!data) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(data));
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}
