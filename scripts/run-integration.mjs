#!/usr/bin/env node
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { preparePerformance, enableMeasurementLimits, captureDatabase, startResourceSampling } from "./performance/integration.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const composeFile = join(root, "compose.integration.yml");
const fixturePath = join(root, "apps", "api", "tests", "integration", "fixture.json");
const u00FixturePath = join(root, "apps", "api", "tests", "integration", "u00_filter_fixture.json");
const supportedSuites = new Set(["api", "live", "concurrency", "performance"]);
const requestedArgs = process.argv.slice(2);
let interrupted = false;
const activeChildren = new Set();

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    interrupted = true;
    for (const child of activeChildren) {
      child.kill("SIGTERM");
      const killEscalation = setTimeout(() => child.kill("SIGKILL"), 5_000);
      child.once("close", () => clearTimeout(killEscalation));
    }
    process.exitCode = 1;
  });
}

function usage(message) {
  if (message) console.error(`Error: ${message}`);
  console.error("Usage: node scripts/run-integration.mjs --suite api|live|concurrency|performance [--scenario functional|representative|snapshot|c01-data-modes|u00-filters] [--snapshot-dir DISPOSABLE_COPY] [--profile desktop|mobile] [--smoke] [--keep-on-failure]");
  process.exitCode = 2;
}

function parseArgs(argv) {
  const options = { keepOnFailure: false, assertFailure: false, isolationCheck: false, child: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--suite" || argument === "--scenario" || argument === "--profile" || argument === "--snapshot-dir") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[argument === "--snapshot-dir" ? "snapshotDir" : argument.slice(2)] = value;
      index += 1;
    } else if (argument === "--keep-on-failure") options.keepOnFailure = true;
    else if (argument === "--assert-failure") options.assertFailure = true;
    else if (argument === "--isolation-check") options.isolationCheck = true;
    else if (argument === "--smoke") options.smoke = true;
    else if (argument === "--child") options.child = true;
    else throw new Error(`Unknown option ${argument}`);
  }
  if (!options.suite) throw new Error("--suite is required");
  if (!supportedSuites.has(options.suite)) {
    throw new Error(`Suite '${options.suite}' is not implemented by T01`);
  }
  if (options.suite === "performance") {
    options.scenario ??= options.snapshotDir ? "snapshot" : "representative";
    options.profile ??= "desktop";
    if (!["functional", "representative", "snapshot"].includes(options.scenario)) throw new Error("Performance scenario must be functional, representative or snapshot");
    if ((options.scenario === "snapshot") !== !!options.snapshotDir) throw new Error("Snapshot scenario requires --snapshot-dir; other scenarios forbid it");
    if (!["desktop", "mobile"].includes(options.profile)) throw new Error("Performance profile must be desktop or mobile");
  } else {
    if (options.profile || options.smoke || options.snapshotDir) throw new Error("Performance options require --suite performance");
    if (options.scenario && !["c01-data-modes", "u00-filters"].includes(options.scenario)) throw new Error(`Scenario '${options.scenario}' is not implemented`);
    if (options.scenario === "c01-data-modes" && (options.suite !== "api" || options.assertFailure || options.isolationCheck || options.child)) {
      throw new Error("--scenario c01-data-modes requires the top-level api suite without assertion or isolation flags");
    }
    if (options.scenario === "u00-filters" && (options.suite !== "live" || options.assertFailure || options.isolationCheck || options.child)) {
      throw new Error("--scenario u00-filters requires the top-level live suite without assertion or isolation flags");
    }
  }
  if (options.assertFailure && options.suite !== "api") {
    throw new Error("--assert-failure is only supported with --suite api");
  }
  if (options.isolationCheck && (options.suite !== "api" || options.child)) {
    throw new Error("--isolation-check is only supported with the top-level api suite");
  }
  return options;
}

function run(command, args, { cwd = root, env, log, allowFailure = false, timeoutMs = 120_000, ignoreInterrupt = false } = {}) {
  return new Promise((resolveRun, rejectRun) => {
    if (interrupted && !ignoreInterrupt) {
      rejectRun(new Error("integration run interrupted"));
      return;
    }
    const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, shell: false });
    if (!ignoreInterrupt) activeChildren.add(child);
    let output = "";
    let timedOut = false;
    let killEscalation;
    const timeout = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      killEscalation = setTimeout(() => child.kill("SIGKILL"), 5_000);
    }, timeoutMs);
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", (error) => {
      clearTimeout(timeout);
      clearTimeout(killEscalation);
      activeChildren.delete(child);
      rejectRun(error);
    });
    child.on("close", (code) => {
      clearTimeout(timeout);
      clearTimeout(killEscalation);
      activeChildren.delete(child);
      if (log) log.push(`$ ${command} ${args.join(" ")}\n${output}`);
      if (timedOut) {
        rejectRun(new Error(`${command} exceeded its ${timeoutMs}ms timeout`));
        return;
      }
      if (code === 0 || allowFailure) resolveRun({ code, output });
      else rejectRun(new Error(`${command} exited with ${code}\n${output}`));
    });
  });
}

function redact(text, token) {
  return text.replaceAll(token, "[redacted]");
}

async function waitForHealth(apiUrl, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not attempted";
  while (Date.now() < deadline) {
    if (interrupted) throw new Error("integration run interrupted");
    try {
      const response = await fetch(`${apiUrl}/health`, { signal: AbortSignal.timeout(5_000) });
      if (response.ok) return;
      lastError = `HTTP ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  }
  throw new Error(`API health check timed out: ${lastError}`);
}

async function fetchWithTimeout(url, init = {}) {
  return fetch(url, { ...init, signal: AbortSignal.timeout(10_000) });
}

async function publishedPort(compose, service, containerPort, log) {
  const result = await run("docker", [...compose, "port", service, String(containerPort)], { log });
  const address = result.output.trim().split(/\r?\n/)[0];
  if (!address || address.startsWith("::") || address.startsWith("invalid")) {
    throw new Error(`could not resolve loopback port for ${service}: ${address || "empty output"}`);
  }
  return `http://${address}`;
}

async function waitForDatabase(compose, log, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not attempted";
  let consecutiveSuccesses = 0;
  while (Date.now() < deadline) {
    if (interrupted) throw new Error("integration run interrupted");
    const probe = await run("docker", [...compose, "run", "--rm", "--no-deps", "api", "python", "-c", "from sqlalchemy import text; from app.db import engine; engine.connect().execute(text('SELECT 1'))"], { log, allowFailure: true, timeoutMs: 60_000 });
    if (probe.code === 0) {
      consecutiveSuccesses += 1;
      if (consecutiveSuccesses === 2) return;
    } else {
      consecutiveSuccesses = 0;
      lastError = probe.output.trim();
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 2_000));
  }
  throw new Error(`database SQL readiness probe timed out: ${lastError}`);
}

async function waitForWeb(compose, log, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not attempted";
  while (Date.now() < deadline) {
    if (interrupted) throw new Error("integration run interrupted");
    const probe = await run("docker", [...compose, "exec", "-T", "web", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"], {
      log,
      allowFailure: true,
      timeoutMs: 10_000
    });
    if (probe.code === 0) return;
    lastError = probe.output.trim();
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 500));
  }
  throw new Error(`web readiness probe timed out: ${lastError}`);
}

async function updateComposeEnvironment(envFile, updates) {
  const values = new Map(
    (await readFile(envFile, "utf8"))
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        const separator = line.indexOf("=");
        return [line.slice(0, separator), line.slice(separator + 1)];
      })
  );
  for (const [key, value] of Object.entries(updates)) values.set(key, value);
  const contents = [...values].map(([key, value]) => `${key}=${value}`).join("\n");
  await writeFile(envFile, `${contents}\n`, { encoding: "utf8", mode: 0o600 });
}

async function assertApi(apiUrl, reviewerToken, fixture, assertFailure) {
  const health = await fetchWithTimeout(`${apiUrl}/health`);
  if (!health.ok) throw new Error(`health request returned ${health.status}`);

  const records = await fetchWithTimeout(`${apiUrl}/api/development-records`);
  const payload = await records.json();
  const record = payload.records?.find((item) => item.public_id === fixture.id);
  if (!record || record.title !== fixture.title) {
    throw new Error("real API did not return the deterministic Postgres fixture");
  }
  if (assertFailure) throw new Error("deliberate HTTP assertion failure");

  const denied = await fetchWithTimeout(`${apiUrl}/api/reviewer/processed-store`);
  if (denied.status !== 401) throw new Error(`unauthenticated reviewer request returned ${denied.status}`);
  const authorized = await fetchWithTimeout(`${apiUrl}/api/reviewer/processed-store`, {
    headers: { Authorization: `Bearer ${reviewerToken}` }
  });
  const store = await authorized.json();
  const collection = store.collections?.find((item) => item.name === "development_records");
  if (!authorized.ok || store.backend !== "postgres" || collection?.database_count !== (fixture.count ?? 1)) {
    throw new Error("reviewer request did not observe the Postgres processed-store fixture");
  }
}

async function assertOwnedResources(project, log, ignoreInterrupt = false) {
  const containers = await run("docker", ["ps", "-aq", "--filter", `label=com.docker.compose.project=${project}`], { log, ignoreInterrupt });
  const volumes = await run("docker", ["volume", "ls", "-q", "--filter", `label=com.docker.compose.project=${project}`], { log, ignoreInterrupt });
  for (const id of [...containers.output.split(/\s+/), ...volumes.output.split(/\s+/)].filter(Boolean)) {
    const target = containers.output.includes(id) ? ["inspect", id, "--format", "{{ index .Config.Labels \"com.docker.compose.project\" }}"] : ["volume", "inspect", id, "--format", "{{ index .Labels \"com.docker.compose.project\" }}"];
    const inspected = await run("docker", target, { log, ignoreInterrupt });
    if (inspected.output.trim() !== project) throw new Error(`refusing to clean resource ${id}: project label did not match`);
  }
}

async function inspectComposeImages(compose, log) {
  const result = await run("docker", [...compose, "images", "--format", "json"], {
    log,
    allowFailure: true,
    ignoreInterrupt: true
  });
  if (result.code !== 0 || !result.output.trim()) return {};
  try {
    const parsed = JSON.parse(result.output);
    const images = Array.isArray(parsed) ? parsed : [parsed];
    return Object.fromEntries(images.map((image) => [image.Service ?? image.ContainerName ?? image.Repository, image.ID]));
  } catch {
    return Object.fromEntries(result.output.trim().split(/\r?\n/).flatMap((line) => {
      try {
        const image = JSON.parse(line);
        return [[image.Service ?? image.ContainerName ?? image.Repository, image.ID]];
      } catch {
        return [];
      }
    }));
  }
}

async function runIsolationCheck() {
  const outcomes = await Promise.allSettled([runSuite({ suite: "api", child: true }), runSuite({ suite: "api", child: true })]);
  const failure = outcomes.find((outcome) => outcome.status === "rejected");
  if (failure) throw failure.reason;
  const summaries = outcomes.map((outcome) => outcome.value);
  if (new Set(summaries.map((summary) => summary.project)).size !== 2) {
    throw new Error("isolation check generated duplicate Compose project IDs");
  }
  if (new Set(summaries.map((summary) => summary.fixture.id)).size !== 2) {
    throw new Error("isolation check generated duplicate fixture sentinels");
  }
}

async function runSuite(options) {
  const runId = `${new Date().toISOString().replace(/[:.]/g, "-")}-${randomUUID().slice(0, 8)}`;
  const project = `urbanization_t01_${randomBytes(6).toString("hex")}`;
  const artifactDir = join(root, "tmp", "integration", runId);
  const envFile = join(artifactDir, ".compose.env");
  const cleanupEnv = join(artifactDir, "cleanup.env");
  const log = [];
  const reviewerToken = randomBytes(24).toString("base64url");
  const sentinel = randomBytes(6).toString("hex");
  const fixture = options.scenario === "u00-filters"
    ? {
        id: "u00-completed-development",
        title: "U00 Completed Development",
        count: 3
      }
    : {
        id: `t01-postgis-${sentinel}`,
        title: `T01 PostGIS Fixture ${sentinel}`
      };
  const liveSubmissionTitle = `C01 live submission ${sentinel}`;
  const demoSubmissionTitle = `C01 demo submission ${sentinel}`;
  let apiUrl = "";
  const compose = ["compose", "--project-name", project, "--project-directory", root, "--env-file", envFile, "-f", composeFile];
  let failed = false;
  let failureMessage = null;
  let imageDigests = {};
  let imageIds = {};
  const scenarioArtifacts = {};
  const commitSha = (await run("git", ["rev-parse", "HEAD"], { log })).output.trim();
  const workingTreeDirty = !!(await run("git", ["status", "--porcelain"], { log })).output.trim();
  console.log(JSON.stringify({ run_id: runId, project, suite: options.suite, artifact_directory: artifactDir }));

  await mkdir(artifactDir, { recursive: true });
  const performance = options.suite === "performance" ? await preparePerformance({ options, root, artifactDir, run, log }) : null;
  if (performance) {
    compose.push("-f", performance.override);
    Object.assign(fixture, { id: performance.manifest.expected.first_development.public_id, title: performance.manifest.expected.first_development.title, count: performance.manifest.development_records });
  }
  let stopSampling;
  if (options.scenario === "c01-data-modes") {
    // Create the bind-mount source as the host user before Compose starts the API.
    // Otherwise Docker creates it as root and the runner cannot write C01 fixtures on Linux CI.
    await mkdir(join(artifactDir, "c01-data"), { recursive: true });
  }
  if (options.suite === "concurrency") {
    await mkdir(join(artifactDir, "c02-data"), { recursive: true });
  }
  await writeFile(envFile, [
    `INTEGRATION_ARTIFACT_DIR=${artifactDir.replaceAll("\\", "/")}`,
    `INTEGRATION_REVIEWER_TOKEN=${reviewerToken}`,
    `INTEGRATION_FIXTURE_TITLE=${fixture.title}`,
    `P01_PERFORMANCE_MARKS=${!!performance}`,
    `P01_PERFORMANCE_PROFILE=${options.profile ?? "desktop"}`,
    `P01_PERFORMANCE_SCENARIO=${options.scenario ?? "functional"}`,
    `P01_SMOKE=${!!options.smoke}`,
    "P01_OUTPUT=/artifacts/performance/browser.json",
    "INTEGRATION_DATA_MODE=live",
    "INTEGRATION_PHASE3_STORE_BACKEND=postgres",
    "INTEGRATION_PROCESSED_STORE_BACKEND=postgres",
    "INTEGRATION_INGESTION_DATA_DIR=/var/empty-data"

  ].join("\n") + "\n", { encoding: "utf8", mode: 0o600 });
  await writeFile(cleanupEnv, [
    `INTEGRATION_ARTIFACT_DIR=${artifactDir.replaceAll("\\", "/")}`,
    "INTEGRATION_REVIEWER_TOKEN=",
    "INTEGRATION_FIXTURE_TITLE=",
    "INTEGRATION_DATA_MODE=live",
    "INTEGRATION_PHASE3_STORE_BACKEND=postgres",
    "INTEGRATION_PROCESSED_STORE_BACKEND=postgres",
    "INTEGRATION_INGESTION_DATA_DIR=/var/empty-data"
  ].join("\n") + "\n", { encoding: "utf8", mode: 0o600 });
  await writeFile(join(artifactDir, "recovery.json"), JSON.stringify({
    run_id: runId,
    project,
    repository_root: root,
    artifact_directory: artifactDir,
    compose_file: composeFile,
    cleanup_env_file: cleanupEnv,
    inspect: [
      { command: "docker", args: ["ps", "-aq", "--filter", `label=com.docker.compose.project=${project}`] },
      { command: "docker", args: ["volume", "ls", "-q", "--filter", `label=com.docker.compose.project=${project}`] }
    ],
    cleanup: {
      command: "docker",
      args: ["compose", "--project-name", project, "--project-directory", root, "--env-file", cleanupEnv, "-f", composeFile, ...(performance ? ["-f", performance.override] : []), "down", "--volumes", "--remove-orphans"]
    },
    instruction: "Inspect every listed resource label before running the exact cleanup arguments."
  }, null, 2) + "\n", "utf8");
  const selectedFixturePath = options.scenario === "u00-filters" ? u00FixturePath : fixturePath;
  const fixtureHash = performance?.manifest.sha256 ?? createHash("sha256").update(await readFile(selectedFixturePath)).digest("hex");

  const runC01HttpAssertions = async (phase) => {
    const resultPath = `/c01-data/results/${phase}.json`;
    await run("docker", [
      ...compose,
      "run", "--rm", "--no-deps",
      "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
      "api", "python", "/integration/c01_data_modes.py",
      "--api-url", "http://api-gateway:8000",
      "--phase", phase,
      "--fixture-id", fixture.id,
      "--reviewer-token", reviewerToken,
      "--live-submission-title", liveSubmissionTitle,
      "--demo-submission-title", demoSubmissionTitle,
      "--result", resultPath
    ], { log });
  };

  const runC01BrowserAssertions = async (phase) => {
    await run("docker", [
      ...compose,
      "run", "--rm", "--env", `C01_BROWSER_PHASE=${phase}`,
      "browser", "--grep", "C01 data modes"
    ], { log, timeoutMs: 300_000 });
  };

  const runU00HttpAssertions = async (phase) => {
    const resultPath = `/results/u00-filters-${phase}.json`;
    await run("docker", [
      ...compose,
      "run", "--rm", "--no-deps",
      "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
      "--volume", `${artifactDir.replaceAll("\\", "/")}:/results`,
      "api", "python", "/integration/u00_filters.py",
      "--api-url", "http://api-gateway:8000",
      "--result", resultPath
    ], { log });
    scenarioArtifacts[phase] = resultPath;
  };

  const runU00BrowserAssertions = async () => {
    await run("docker", [...compose, "run", "--rm", "browser", "--grep", "U00 filters"], {
      log,
      timeoutMs: 300_000
    });
  };

  const reconfigureC01Api = async (updates) => {
    await updateComposeEnvironment(envFile, updates);
    await run("docker", [...compose, "up", "--detach", "--force-recreate", "api"], { log });
    apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
    await waitForHealth(apiUrl);
  };

  const runC01DataModes = async () => {
    const c01DataDirectory = join(artifactDir, "c01-data");
    const emptyArtifact = join(c01DataDirectory, "empty", "processed", "development_records.json");
    const corruptArtifact = join(c01DataDirectory, "corrupt", "processed", "development_records.json");
    await mkdir(dirname(emptyArtifact), { recursive: true });
    await mkdir(dirname(corruptArtifact), { recursive: true });
    await writeFile(emptyArtifact, "[]\n", "utf8");
    await writeFile(corruptArtifact, "{}\n", "utf8");
    scenarioArtifacts.empty_development_records_sha256 = createHash("sha256").update(await readFile(emptyArtifact)).digest("hex");
    scenarioArtifacts.corrupt_development_records_sha256 = createHash("sha256").update(await readFile(corruptArtifact)).digest("hex");

    await runC01HttpAssertions("postgres-empty");
    await run("docker", [...compose, "up", "--detach", "web"], { log, timeoutMs: 300_000 });
    await waitForWeb(compose, log);
    await runC01BrowserAssertions("empty");

    await run("docker", [
      ...compose,
      "run", "--rm", "--no-deps",
      "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
      "--env", `INTEGRATION_FIXTURE_ID=${fixture.id}`,
      "--env", `INTEGRATION_FIXTURE_TITLE=${fixture.title}`,
      "api", "python", "/integration/seed_integration.py"
    ], { log });
    await runC01HttpAssertions("postgres-seeded");

    await run("docker", [...compose, "stop", "db"], { log });
    await runC01HttpAssertions("postgres-stopped");
    await run("docker", [...compose, "start", "db"], { log });
    await waitForDatabase(compose, log);
    apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
    await waitForHealth(apiUrl);
    await runC01HttpAssertions("postgres-recovered");

    await runC01HttpAssertions("live-phase3-seeded");
    await reconfigureC01Api({
      INTEGRATION_DATA_MODE: "demo",
      INTEGRATION_PHASE3_STORE_BACKEND: "postgres",
      INTEGRATION_PROCESSED_STORE_BACKEND: "postgres",
      INTEGRATION_INGESTION_DATA_DIR: "/var/empty-data"
    });
    await runC01HttpAssertions("demo-phase3-isolated");
    await runC01BrowserAssertions("demo");
    await reconfigureC01Api({
      INTEGRATION_DATA_MODE: "live",
      INTEGRATION_PHASE3_STORE_BACKEND: "postgres",
      INTEGRATION_PROCESSED_STORE_BACKEND: "postgres",
      INTEGRATION_INGESTION_DATA_DIR: "/var/empty-data"
    });
    await runC01HttpAssertions("live-phase3-restored");

    await reconfigureC01Api({
      INTEGRATION_DATA_MODE: "live",
      INTEGRATION_PHASE3_STORE_BACKEND: "artifact",
      INTEGRATION_PROCESSED_STORE_BACKEND: "artifact",
      INTEGRATION_INGESTION_DATA_DIR: "/c01-data/missing"
    });
    await runC01HttpAssertions("artifact-missing");
    await runC01BrowserAssertions("unavailable");

    await reconfigureC01Api({ INTEGRATION_INGESTION_DATA_DIR: "/c01-data/empty" });
    await runC01HttpAssertions("artifact-empty");
    await runC01BrowserAssertions("empty");

    await reconfigureC01Api({ INTEGRATION_INGESTION_DATA_DIR: "/c01-data/corrupt" });
    await runC01HttpAssertions("artifact-corrupt");

  };

  const runC02Transactions = async (phase) => {
    await run("docker", [
      ...compose,
      "run", "--rm", "--no-deps",
      "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
      "api", "python", "/integration/c02_transactions.py",
      "--api-url", "http://api-gateway:8000",
      "--reviewer-token", reviewerToken,
      "--fixture-id", fixture.id,
      "--result", "/c02-data/results.json",
      "--phase", phase
    ], { log, timeoutMs: 90_000 });
  };

  try {
    const requiresBrowser = options.suite === "live" || performance || options.scenario === "c01-data-modes";
    await run("docker", [...compose, "build", "api", ...(requiresBrowser ? ["web", "browser"] : [])], { log, timeoutMs: 300_000 });
    await run("docker", [...compose, "up", "--detach", "db", "mail"], { log, timeoutMs: 300_000 });
    await waitForDatabase(compose, log);
    await run("docker", [...compose, "run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"], { log });
    if (options.scenario === "u00-filters") {
      await run("docker", [
        ...compose,
        "run", "--rm", "--no-deps",
        "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`,
        "api", "python", "/integration/seed_u00_filters.py"
      ], { log, timeoutMs: 600_000 });
    } else if (options.scenario !== "c01-data-modes") {
      await run("docker", [...compose, "run", "--rm", "--no-deps", "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`, "--env", `INTEGRATION_FIXTURE_ID=${fixture.id}`, "--env", `INTEGRATION_FIXTURE_TITLE=${fixture.title}`, ...(performance ? ["--volume", `${artifactDir.replaceAll("\\", "/")}:/performance:ro`, "--env", "INTEGRATION_FIXTURE_PATH=/performance/fixture.json", "--env", "INTEGRATION_PRESERVE_IDS=1", "--env", "P01_VALIDATE_GEOMETRY=1"] : []), "api", "python", "/integration/seed_integration.py"], { log, timeoutMs: 600_000 });
    }
    if (performance) await enableMeasurementLimits(performance);

    await run("docker", [...compose, "up", "--detach", "api"], { log });
    await run("docker", [...compose, "up", "--detach", "api-gateway"], { log });
    apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
    await waitForHealth(apiUrl);
    await run("docker", [...compose, "exec", "-T", "db", "psql", "-U", "integration", "-d", "integration", "-Atqc", "SELECT PostGIS_Version();"], { log });
    await run("docker", [...compose, "exec", "-T", "api", "alembic", "current"], { log });
    if (options.scenario === "c01-data-modes") {
      await runC01DataModes();
    } else if (options.scenario === "u00-filters") {
      await runU00HttpAssertions("before-restart");
      await run("docker", [...compose, "restart", "api"], { log });
      apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
      await waitForHealth(apiUrl);
      await runU00HttpAssertions("after-restart");
    } else {
      await assertApi(apiUrl, reviewerToken, fixture, options.assertFailure);
      if (options.suite === "concurrency") await runC02Transactions("create");
      await run("docker", [...compose, "restart", "api"], { log });
      apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
      await waitForHealth(apiUrl);
      await assertApi(apiUrl, reviewerToken, fixture, false);
      if (performance) {
        await captureDatabase({ compose, run, log, artifactDir });
        stopSampling = await startResourceSampling({ compose, run, log, artifactDir });
      }
      if (options.suite === "concurrency") {
        await runC02Transactions("verify");
        scenarioArtifacts.c02_results_sha256 = createHash("sha256")
          .update(await readFile(join(artifactDir, "c02-data", "results.json")))
          .digest("hex");
      }
    }
    if (options.suite === "live" || performance) {
      await run("docker", [...compose, "up", "--detach", "web"], { log, timeoutMs: 300_000 });
      await waitForWeb(compose, log);
      if (options.scenario === "u00-filters") {
        await runU00BrowserAssertions();
      } else {
        await run("docker", [...compose, "run", "--rm", ...(performance ? ["--entrypoint", "node"] : []), "browser", ...(performance ? ["e2e/performance-baseline.mjs"] : [])], { log, timeoutMs: performance ? 14_400_000 : 300_000 });
      }
    }
  } catch (error) {
    failed = true;
    failureMessage = error instanceof Error ? error.message.split("\n", 1)[0] : String(error);
    throw error;
  } finally {
    let artifactError;
    if (stopSampling) { try { await stopSampling(); } catch (error) { artifactError = error; } }
    let cleanupError;
    let cleanupResult = "not_attempted";
    let cleanupFailure = null;
    const cleanup = async () => {
      if (failed && options.keepOnFailure) {
        await rm(envFile, { force: true });
        cleanupResult = "retained";
        console.error(`Resources retained. Cleanup: docker compose --project-name ${project} --project-directory . --env-file ${cleanupEnv} -f compose.integration.yml down --volumes`);
      } else {
        await assertOwnedResources(project, log, true);
        await run("docker", [...compose, "down", "--volumes", "--remove-orphans"], { log, ignoreInterrupt: true });
        await rm(envFile, { force: true });
        cleanupResult = "removed";
      }
    };
    try {
      const logs = await run("docker", [...compose, "logs", "--no-color"], { log, allowFailure: true, ignoreInterrupt: true });
      await writeFile(join(artifactDir, "service.log"), redact(logs.output, reviewerToken), "utf8");
      await writeFile(join(artifactDir, "commands.log"), redact(log.join("\n"), reviewerToken), "utf8");
      for (const [name, image] of Object.entries({
        database: "postgis/postgis:16-3.4",
        mail: "axllent/mailpit:v1.27.1",
        browser: "mcr.microsoft.com/playwright:v1.60.0-noble"
      })) {
        const digest = await run("docker", ["image", "inspect", image, "--format", "{{join .RepoDigests \",\"}}"], { log, allowFailure: true, ignoreInterrupt: true });
        imageDigests[name] = digest.code === 0 ? digest.output.trim() || null : null;
      }
      imageIds = await inspectComposeImages(compose, log);
    } catch (error) {
      artifactError = error;
    }
    try {
      await cleanup();
    } catch (error) {
      cleanupError = error;
      cleanupFailure = error instanceof Error ? error.message.split("\n", 1)[0] : String(error);
    } finally {}
    const finalError = cleanupError ?? artifactError;
    const manifestFailure = failureMessage ?? (
      finalError instanceof Error ? finalError.message.split("\n", 1)[0] : finalError ? String(finalError) : null
    );
    try {
      await writeFile(join(artifactDir, "manifest.json"), JSON.stringify({
      run_id: runId,
      project,
      suite: options.suite,
      performance: performance ? { fixture: performance.manifest, profile: options.profile, smoke: !!options.smoke, resource_limits: { api_cpus: 1, api_memory_gib: 1, db_cpus: 2, db_memory_gib: 2 } } : null,
      scenario: options.scenario ?? null,

      api_url: apiUrl,
      fixture_sha256: fixtureHash,
      fixture,
      scenario_artifacts: scenarioArtifacts,
      command: `node scripts/run-integration.mjs ${requestedArgs.join(" ")}`,
      options: {
        suite: options.suite,
        scenario: options.scenario ?? null,
        keep_on_failure: options.keepOnFailure,
        assert_failure: options.assertFailure,
        isolation_check: options.isolationCheck
      },
      outcome: failed || finalError ? "failed" : "passed",
      failure: manifestFailure,
      commit_sha: commitSha,
      working_tree_dirty: workingTreeDirty,
      images: {
        database: "postgis/postgis:16-3.4",
        mail: "axllent/mailpit:v1.27.1",
        browser: "mcr.microsoft.com/playwright:v1.60.0-noble"
      },
      image_digests: imageDigests,
      image_ids: imageIds,
      retained: cleanupResult === "retained",
      cleanup_result: cleanupResult,
      cleanup_failure: cleanupFailure
    }, null, 2) + "\n", "utf8");
      await writeFile(join(artifactDir, "cleanup-result.json"), JSON.stringify({
      project,
      result: cleanupResult
    }, null, 2) + "\n", "utf8");
    } catch (error) {
      artifactError ??= error;
    }
    if (cleanupError) throw cleanupError;
    if (artifactError) throw artifactError;
  }
  return { project, artifactDir, fixture };
}

try {
  const options = parseArgs(process.argv.slice(2));
  if (options.isolationCheck) await runIsolationCheck();
  else await runSuite(options);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
