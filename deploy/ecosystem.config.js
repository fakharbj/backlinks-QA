// PM2 process definitions for the LinkSentinel VPS deploy.
//   pm2 start deploy/ecosystem.config.js   (run from the site root)
//   pm2 save
//
// All four processes set `cwd` explicitly so Python can import `app.*` and load
// `.env`, and run the venv/node binaries directly (interpreter: "none").
// Adjust BASE if your site path differs.

const BASE = "/home/ls_user/htdocs/72.62.81.34.nip.io";
const BACKEND = `${BASE}/backend`;
const FRONTEND = `${BASE}/frontend`;

const CRAWL_QUEUES =
  "default,crawl.http.0,crawl.http.1,crawl.http.2,crawl.http.3," +
  "crawl.render,qa,alerts,reports,sheets.sync,index.check,maintenance";

module.exports = {
  apps: [
    {
      name: "api",
      cwd: BACKEND,
      script: `${BACKEND}/venv/bin/gunicorn`,
      args: "app.main:app -k uvicorn.workers.UvicornWorker -w 3 -b 127.0.0.1:8000",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
    {
      name: "worker",
      cwd: BACKEND,
      script: `${BACKEND}/venv/bin/celery`,
      args: `-A app.workers.celery_app worker -Q ${CRAWL_QUEUES} --concurrency=4 --loglevel=info`,
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
    {
      name: "beat",
      cwd: BACKEND,
      script: `${BACKEND}/venv/bin/celery`,
      args: "-A app.workers.celery_app beat -S redbeat.RedBeatScheduler --loglevel=info",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
    {
      name: "frontend",
      cwd: FRONTEND,
      script: "npm",
      args: "start",
      interpreter: "none",
      autorestart: true,
      max_restarts: 20,
    },
  ],
};
