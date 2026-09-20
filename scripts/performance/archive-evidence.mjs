#!/usr/bin/env node
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const runsRoot = join(root, "tmp", "integration");
const evidenceRoot = join(root, "docs", "evidence", "P01");
const allowedFiles = [
  "manifest.json",
  "fixture.json.manifest.json",
  "database.json",
  "resources.json",
  "resource-policy.json",
  join("performance", "browser.json")
];

function usage(message) {
  if (message) console.error(`Error: ${message}`);
  console.error("Usage: node scripts/performance/archive-evidence.mjs --run <completed-run-dir> --label <safe-label> [--dry-run]");
  process.exitCode = 2;
}

function parseArgs(argv) {
  const options = { dryRun: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--run" || argument === "--label") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[argument.slice(2)] = value;
      index += 1;
    } else if (argument === "--dry-run") options.dryRun = true;
    else throw new Error(`Unknown option ${argument}`);
  }
  if (!options.run || !options.label) throw new Error("--run and --label are required");
  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/.test(options.label)) {
    throw new Error("--label must contain only lowercase letters, numbers, dot, underscore, or hyphen");
  }
  return options;
}

function isWithin(parent, candidate) {
  const path = relative(parent, candidate);
  return path !== "" && !path.startsWith("..") && !isAbsolute(path);
}

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

export function redactLocalPaths(value) {
  if (Array.isArray(value)) return value.map(redactLocalPaths);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redactLocalPaths(item)]));
  }
  if (typeof value !== "string") return value;
  return value
    .replace(/(^|[\s("'=])([A-Za-z]:[\\/][^\s"']+)/g, "$1[local-path]")
    .replace(/\/(?:Users|home|tmp)\/[A-Za-z0-9._/-]+/g, "[local-path]");
}

function sanitizeResources(value) {
  const sanitized = redactLocalPaths(value);
  if (sanitized && typeof sanitized === "object" && !Array.isArray(sanitized)) {
    delete sanitized.running_container_names;
  }
  return sanitized;
}

function workloadSummary(browser) {
  const cold = browser.cold ?? [];
  const interactions = browser.interactions ?? [];
  const api = browser.api ?? [];
  const apiRequested = api.reduce((total, item) => total + (item.requested ?? 0), 0);
  const apiCompleted = api.reduce((total, item) => total + (item.completed ?? 0), 0);
  const apiUnrun = api.reduce((total, item) => total + (item.unrun ?? 0), 0);
  return {
    cold: {
      requested: cold.length + (browser.cold_unrun ?? 0),
      completed: cold.length,
      unrun: browser.cold_unrun ?? 0,
      failed: cold.filter((item) => item.ok === false).length
    },
    interactions: {
      requested: interactions.length + (browser.interactions_unrun ?? 0),
      completed: interactions.length,
      unrun: browser.interactions_unrun ?? 0,
      failed: interactions.filter((item) => item.ok === false).length
    },
    api: { requested: apiRequested, completed: apiCompleted, unrun: apiUnrun },
    totals: {
      requested: cold.length + (browser.cold_unrun ?? 0) + interactions.length + (browser.interactions_unrun ?? 0) + apiRequested,
      completed: cold.length + interactions.length + apiCompleted,
      unrun: (browser.cold_unrun ?? 0) + (browser.interactions_unrun ?? 0) + apiUnrun
    }
  };
}

function resourceSummary(resources) {
  const containers = resources.containers ?? {};
  return Object.fromEntries(Object.entries(containers).map(([name, value]) => [name, {
    oom_killed: value.state?.OOMKilled ?? null,
    exit_code: value.state?.ExitCode ?? null,
    memory_limit_bytes: value.memory_limit_bytes ?? null,
    memory_swap_limit_bytes: value.memory_swap_limit_bytes ?? null,
    nano_cpus: value.nano_cpus ?? null,
    cgroup_memory_peak_bytes: value.cgroup_memory_peak_bytes ?? null
  }]));
}

async function archive(options) {
  const canonicalRunsRoot = await realpath(runsRoot);
  const suppliedRun = resolve(root, options.run);
  if (!isWithin(canonicalRunsRoot, suppliedRun)) {
    throw new Error("--run must be a directory inside tmp/integration");
  }
  const run = await realpath(suppliedRun);
  if (!isWithin(canonicalRunsRoot, run)) throw new Error("--run resolves outside tmp/integration");

  const manifest = await readJson(join(run, "manifest.json"));
  const fixtureManifest = await readJson(join(run, "fixture.json.manifest.json"));
  const browser = await readJson(join(run, "performance", "browser.json"));
  const resources = await readJson(join(run, "resources.json"));
  const cleanup = await readJson(join(run, "cleanup-result.json"));
  const resourcePolicyPath = join(run, "resource-policy.json");
  const resourcePolicy = existsSync(resourcePolicyPath) ? await readJson(resourcePolicyPath) : null;
  if (manifest.suite !== "performance" || manifest.performance?.fixture?.source_coverage?.synthetic !== true) {
    throw new Error("--run must be a completed synthetic performance run");
  }
  const fixtureProfile = manifest.performance?.fixture?.profile;
  if (!["A", "B"].includes(fixtureProfile) || fixtureManifest.profile !== fixtureProfile || browser.fixture_profile !== fixtureProfile) {
    throw new Error("--run must declare synthetic fixture profile A or B");
  }
  if (manifest.fixture_sha256 !== fixtureManifest.sha256 || browser.fixture_sha256 !== fixtureManifest.sha256) {
    throw new Error("fixture hashes do not agree across the run artifacts");
  }
  if (!new Set(["passed", "success", "failed"]).has(manifest.outcome)) {
    throw new Error("manifest outcome must be passed, success, or failed");
  }
  if (cleanup.result !== "removed" || manifest.cleanup_result !== "removed") {
    throw new Error("--run is not a completed cleanup-removed run");
  }
  if (fixtureProfile === "local_snapshot" || fixtureManifest.profile === "local_snapshot" || browser.fixture_profile === "local_snapshot") {
    throw new Error("local_snapshot runs cannot be archived");
  }

  const destination = resolve(evidenceRoot, options.label);
  if (!isWithin(evidenceRoot, destination)) throw new Error("--label resolved outside docs/evidence/P01");
  if (existsSync(destination)) throw new Error(`archive destination already exists: ${options.label}`);

  const summary = redactLocalPaths({
    schema_version: 1,
    source: {
      run_id: manifest.run_id,
      commit_sha: manifest.commit_sha,
      working_tree_dirty: manifest.working_tree_dirty,
      profile: manifest.performance.profile,
      fixture_profile: fixtureProfile,
      fixture_sha256: manifest.fixture_sha256
    },
    result: {
      outcome: manifest.outcome,
      failure: manifest.failure ?? null,
      cleanup_result: cleanup.result ?? manifest.cleanup_result ?? null,
      cleanup_failure: manifest.cleanup_failure ?? null,
      complete: browser.complete ?? null,
      functional_pass: browser.functional_pass ?? null,
      errors: browser.errors ?? []
    },
    workload: workloadSummary(browser),
    resources: {
      configured_limits: manifest.performance.resource_limits ?? {},
      policy: resourcePolicy ? redactLocalPaths(resourcePolicy) : null,
      containers: resourceSummary(resources)
    }
  });

  if (options.dryRun) {
    console.log(JSON.stringify({ destination: join("docs", "evidence", "P01", options.label), files: [...allowedFiles.filter((path) => existsSync(join(run, path))), "cleanup-result.json", "summary.json"], summary }, null, 2));
    return;
  }

  await mkdir(evidenceRoot, { recursive: true });
  await mkdir(destination, { recursive: false });
  try {
    for (const relativePath of allowedFiles) {
      const source = join(run, relativePath);
      const target = join(destination, relativePath);
      if (!existsSync(source)) continue;
      await mkdir(dirname(target), { recursive: true });
      const json = relativePath.startsWith("resources")
        ? sanitizeResources(await readJson(source))
        : redactLocalPaths(await readJson(source));
      await writeFile(target, `${JSON.stringify(json, null, 2)}\n`, "utf8");
    }
    await writeFile(join(destination, "cleanup-result.json"), `${JSON.stringify(redactLocalPaths(cleanup), null, 2)}\n`, "utf8");
    await writeFile(join(destination, "summary.json"), `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  } catch (error) {
    throw new Error(`archive creation failed; remove the incomplete destination manually: ${error instanceof Error ? error.message : String(error)}`);
  }
  console.log(JSON.stringify({ destination: join("docs", "evidence", "P01", options.label), outcome: summary.result.outcome }, null, 2));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    await archive(parseArgs(process.argv.slice(2)));
  } catch (error) {
    usage(error instanceof Error ? error.message : String(error));
  }
}
