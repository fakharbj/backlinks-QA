import { WorkspaceApp } from "@/components/workspace-app";

// Render per-request instead of a fully-static prerender. A static prerender is
// served with a year-long `s-maxage` cache header, which pins the app shell in
// browsers/proxies so new deploys (new content-hashed chunks) don't appear until
// a hard refresh. Dynamic rendering serves the shell with a no-store header, so
// every load fetches the current shell → the latest JS/CSS. The shell is a thin
// client component, so the per-request cost is negligible. Hashed assets under
// /_next/static keep their own immutable caching.
export const dynamic = "force-dynamic";

export default function Page() {
  return <WorkspaceApp />;
}
