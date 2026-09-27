import { join } from "node:path";
import { performance } from "node:perf_hooks";

// The host deadline includes Compose/container startup. The child receives the
// same deadline; the runner's hard cutoff remains authoritative.
export async function waitForDatabase({ compose, log, run, root, now = Date.now, clock = () => performance.now(), timeoutMs = 180_000 }) {
  const started = clock();
  const deadline = now() + timeoutMs;
  const result = await run("docker", [
    ...compose, "run", "--rm", "--no-deps",
    "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
    "api", "python", "/integration/database_readiness.py", String(deadline / 1000)
  ], { log, allowFailure: true, timeoutMs: Math.max(1, timeoutMs - Math.max(0, clock() - started)), killGraceMs: 0 });
  if (result.code !== 0) throw new Error("database TCP SQL readiness failed; see timestamped probe diagnostics");
}
