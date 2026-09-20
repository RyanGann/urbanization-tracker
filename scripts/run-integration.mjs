#!/usr/bin/env node
import { createHash, randomBytes, randomUUID } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const composeFile = join(root, "compose.integration.yml");
const fixturePath = join(root, "apps", "api", "tests", "integration", "fixture.json");
const supportedSuites = new Set(["api", "live"]);
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
  console.error("Usage: node scripts/run-integration.mjs --suite api|live [--keep-on-failure]");
  process.exitCode = 2;
}

function parseArgs(argv) {
  const options = { keepOnFailure: false, assertFailure: false, isolationCheck: false, child: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--suite" || argument === "--scenario") {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`${argument} requires a value`);
      options[argument.slice(2)] = value;
      index += 1;
    } else if (argument === "--keep-on-failure") options.keepOnFailure = true;
    else if (argument === "--assert-failure") options.assertFailure = true;
    else if (argument === "--isolation-check") options.isolationCheck = true;
    else if (argument === "--child") options.child = true;
    else throw new Error(`Unknown option ${argument}`);
  }
  if (!options.suite) throw new Error("--suite is required");
  if (!supportedSuites.has(options.suite)) {
    throw new Error(`Suite '${options.suite}' is not implemented by T01`);
  }
  if (options.scenario) {
    throw new Error(`Scenario '${options.scenario}' is not implemented by T01`);
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
  if (!authorized.ok || store.backend !== "postgres" || collection?.database_count !== 1) {
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
  const fixture = {
    id: `t01-postgis-${sentinel}`,
    title: `T01 PostGIS Fixture ${sentinel}`
  };
  let apiUrl = "";
  const compose = ["compose", "--project-name", project, "--project-directory", root, "--env-file", envFile, "-f", composeFile];
  let failed = false;
  let failureMessage = null;
  let imageDigests = {};
  let imageIds = {};
  const commitSha = (await run("git", ["rev-parse", "HEAD"], { log })).output.trim();

  await mkdir(artifactDir, { recursive: true });
  await writeFile(envFile, [
    `INTEGRATION_ARTIFACT_DIR=${artifactDir.replaceAll("\\", "/")}`,
    `INTEGRATION_REVIEWER_TOKEN=${reviewerToken}`,
    `INTEGRATION_FIXTURE_TITLE=${fixture.title}`
  ].join("\n") + "\n", { encoding: "utf8", mode: 0o600 });
  await writeFile(cleanupEnv, [
    `INTEGRATION_ARTIFACT_DIR=${artifactDir.replaceAll("\\", "/")}`,
    "INTEGRATION_REVIEWER_TOKEN=",
    "INTEGRATION_FIXTURE_TITLE="
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
      args: ["compose", "--project-name", project, "--project-directory", root, "--env-file", cleanupEnv, "-f", composeFile, "down", "--volumes", "--remove-orphans"]
    },
    instruction: "Inspect every listed resource label before running the exact cleanup arguments."
  }, null, 2) + "\n", "utf8");
  const fixtureHash = createHash("sha256").update(await readFile(fixturePath)).digest("hex");

  try {
    await run("docker", [...compose, "build", "api", ...(options.suite === "live" ? ["web", "browser"] : [])], { log, timeoutMs: 300_000 });
    await run("docker", [...compose, "up", "--detach", "db", "mail"], { log, timeoutMs: 300_000 });
    await waitForDatabase(compose, log);
    await run("docker", [...compose, "run", "--rm", "--no-deps", "api", "alembic", "upgrade", "head"], { log });
    await run("docker", [...compose, "run", "--rm", "--no-deps", "--volume", `${join(root, "apps", "api", "tests", "integration").replaceAll("\\", "/")}:/integration:ro`, "--env", `INTEGRATION_FIXTURE_ID=${fixture.id}`, "--env", `INTEGRATION_FIXTURE_TITLE=${fixture.title}`, "api", "python", "/integration/seed_integration.py"], { log });
    await run("docker", [...compose, "up", "--detach", "api"], { log });
    await run("docker", [...compose, "up", "--detach", "api-gateway"], { log });
    apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
    await waitForHealth(apiUrl);
    await run("docker", [...compose, "exec", "-T", "db", "psql", "-U", "integration", "-d", "integration", "-Atqc", "SELECT PostGIS_Version();"], { log });
    await run("docker", [...compose, "exec", "-T", "api", "alembic", "current"], { log });
    await assertApi(apiUrl, reviewerToken, fixture, options.assertFailure);
    await run("docker", [...compose, "restart", "api"], { log });
    apiUrl = await publishedPort(compose, "api-gateway", 8000, log);
    await waitForHealth(apiUrl);
    await assertApi(apiUrl, reviewerToken, fixture, false);
    if (options.suite === "live") {
      await run("docker", [...compose, "up", "--detach", "web"], { log, timeoutMs: 300_000 });
      await waitForWeb(compose, log);
      await run("docker", [...compose, "run", "--rm", "browser"], { log, timeoutMs: 300_000 });
    }
  } catch (error) {
    failed = true;
    failureMessage = error instanceof Error ? error.message.split("\n", 1)[0] : String(error);
    throw error;
  } finally {
    let artifactError;
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
        imageDigests[name] = digest.output.trim() || null;
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
    try {
      await writeFile(join(artifactDir, "manifest.json"), JSON.stringify({
      run_id: runId,
      project,
      suite: options.suite,
      api_url: apiUrl,
      fixture_sha256: fixtureHash,
      fixture,
      command: `node scripts/run-integration.mjs ${requestedArgs.join(" ")}`,
      options: {
        suite: options.suite,
        keep_on_failure: options.keepOnFailure,
        assert_failure: options.assertFailure,
        isolation_check: options.isolationCheck
      },
      outcome: failed ? "failed" : "passed",
      failure: failureMessage,
      commit_sha: commitSha,
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
