#!/usr/bin/env node
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const planDirectory = "docs/implementation/2026-09-readiness";
const allowedStatuses = new Set(["planned", "in_progress", "in_review", "blocked", "complete"]);
const requiredSections = [
  "Problem and intended result", "Code to inspect", "Implementation steps",
  "Acceptance and verification", "Rollout and recovery", "Outside this PR", "Agent handoff"
];

// An optional in-memory manifest lets callers check invalid graphs without changing files.
export function validateReadinessPlan(root = repositoryRoot, manifest) {
  const planDir = join(root, planDirectory);
  const plan = manifest ?? JSON.parse(readFileSync(join(planDir, "plan.json"), "utf8"));
  const errors = [];
  const guides = Array.isArray(plan.guides) ? plan.guides : [];
  const ids = new Map(guides.map((guide) => [guide.id, guide]));
  const sameMembers = (left, right) =>
    JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
  const dependencies = (guide) => Array.isArray(guide.depends_on) ? guide.depends_on : [];
  const localPath = (base, target, label) => {
    if (typeof target !== "string" || !target || isAbsolute(target) || /^[A-Za-z]:/.test(target)) {
      errors.push(`${label}: expected a repository-relative path`);
      return null;
    }
    const resolved = resolve(base, target);
    const fromRoot = relative(root, resolved);
    if (fromRoot === ".." || fromRoot.startsWith(`..${sep}`) || isAbsolute(fromRoot)) {
      errors.push(`${label}: path escapes the repository`);
      return null;
    }
    if (!existsSync(resolved)) {
      errors.push(`${label}: missing ${target}`);
      return null;
    }
    return resolved;
  };

  if (!guides.length) errors.push("No guides in manifest");
  if (ids.size !== guides.length) errors.push("Duplicate guide IDs");
  const visiting = new Set();
  const visited = new Set();
  function visit(id) {
    if (visiting.has(id)) { errors.push(`Dependency cycle at ${id}`); return; }
    if (visited.has(id)) return;
    const guide = ids.get(id);
    if (!guide) { errors.push(`Unknown dependency ${id}`); return; }
    visiting.add(id);
    dependencies(guide).forEach(visit);
    visiting.delete(id);
    visited.add(id);
  }
  guides.forEach((guide) => visit(guide.id));

  const topologicalOrder = Array.isArray(plan.topological_order) ? plan.topological_order : [];
  if (!sameMembers(topologicalOrder, [...ids.keys()])) errors.push("Topological order differs from guide IDs");
  const positions = new Map(topologicalOrder.map((id, index) => [id, index]));
  const indexText = readFileSync(join(planDir, "README.md"), "utf8");
  const indexRows = new Map();
  for (const row of indexText.split(/\r?\n/)) {
    const match = row.match(/^\| \[([A-Z][0-9]{2}):[^\]]+\]\(([^)]+)\) \| ([^|]+) \|/);
    if (match) {
      if (indexRows.has(match[1])) errors.push(`Duplicate index row ${match[1]}`);
      indexRows.set(match[1], { path: match[2], deps: match[3].match(/\b[A-Z][0-9]{2}\b/g) ?? [] });
    }
  }
  if (!sameMembers([...indexRows.keys()], [...ids.keys()])) errors.push("Index guide IDs differ from manifest");

  for (const guide of guides) {
    if (!/^[A-Z][0-9]{2}$/.test(guide.id)) errors.push(`Invalid guide ID ${guide.id}`);
    if (!Array.isArray(guide.depends_on)) errors.push(`${guide.id}: depends_on must be an array`);
    const deps = dependencies(guide);
    if (new Set(deps).size !== deps.length) errors.push(`${guide.id}: duplicate dependencies`);
    if (!allowedStatuses.has(guide.status)) errors.push(`${guide.id}: unknown status ${guide.status}`);
    if (guide.implementation_pr != null && !/^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+$/.test(guide.implementation_pr)) {
      errors.push(`${guide.id}: invalid implementation PR URL`);
    }
    if (guide.evidence != null) {
      const evidenceFile = localPath(planDir, guide.evidence, `${guide.id} evidence`);
      if (evidenceFile && !statSync(evidenceFile).isFile()) errors.push(`${guide.id}: evidence must be a regular file`);
    }
    if (guide.status === "complete") {
      if (!guide.implementation_pr || !guide.evidence) errors.push(`${guide.id}: completion requires PR and evidence`);
      for (const dependency of deps) {
        if (ids.get(dependency)?.status !== "complete") errors.push(`${guide.id}: incomplete prerequisite ${dependency}`);
      }
    }
    if (guide.status === "blocked" && !guide.blocked_reason) errors.push(`${guide.id}: blocked status requires blocked_reason`);
    for (const dependency of deps) {
      if (!(positions.get(dependency) < positions.get(guide.id))) errors.push(`Invalid topological order ${dependency} -> ${guide.id}`);
    }
    const indexRow = indexRows.get(guide.id);
    if (indexRow?.path !== guide.path || !sameMembers(indexRow?.deps ?? [], deps)) errors.push(`${guide.id}: index row mismatch`);
    const file = localPath(planDir, guide.path, `${guide.id} guide`);
    if (!file) continue;
    const body = readFileSync(file, "utf8");
    if (!body.startsWith(`# ${guide.id} `)) errors.push(`${guide.id}: heading mismatch`);
    for (const section of requiredSections) {
      if (!body.includes(`## ${section}`)) errors.push(`${guide.id}: missing section ${section}`);
    }
    const dependencyRow = body.split(/\r?\n/).find((line) => line.startsWith("| Depends on |")) ?? "";
    const rowIds = [...dependencyRow.matchAll(/\[([A-Z][0-9]{2})\]/g)].map((match) => match[1]);
    if (!sameMembers(rowIds, deps)) errors.push(`${guide.id}: guide dependency row mismatch`);
  }

  const ready = guides.filter((guide) => dependencies(guide).length === 0).map((guide) => guide.id).sort();
  if (!sameMembers(ready, plan.initial_ready ?? [])) errors.push("Initial-ready set mismatch");
  const shared = Array.isArray(plan.shared_documents) ? plan.shared_documents : [];
  for (const file of shared) localPath(planDir, file, "Shared document");
  const files = readdirSync(planDir).filter((name) => name.endsWith(".md"));
  const expected = new Set([...guides.map((guide) => guide.path), ...shared]);
  for (const file of files) if (!expected.has(file)) errors.push(`Unindexed markdown file ${file}`);

  let links = 0;
  const documents = [
    ...files.map((name) => join(planDir, name)), join(root, "README.md"),
    ...["next-steps.md", "architecture.md", "follow-up-prompts.md", "implementation-checklist.md"].map((name) => join(root, "docs", name))
  ];
  for (const file of documents) {
    const body = readFileSync(file, "utf8");
    body.split(/\r?\n/).forEach((line, index) => {
      if (/[ \t]+$/.test(line)) errors.push(`${relative(root, file)}:${index + 1}: trailing whitespace`);
    });
    for (const match of body.matchAll(/\[[^\]\n]+\]\(([^)\n]+)\)/g)) {
      let target = match[1].replace(/^<|>$/g, "");
      if (/^(https?:|app:|codex:|mailto:|#)/.test(target)) continue;
      target = target.replace(/:\d+$/, "").split("#")[0];
      if (!target) continue;
      links += 1;
      localPath(dirname(file), target, `Link in ${relative(root, file)}`);
    }
  }
  return {
    guides: guides.length,
    performanceGuides: guides.filter((guide) => guide.track === "Performance").length,
    markdownFiles: files.length,
    localLinksChecked: links,
    initialReady: ready,
    valid: errors.length === 0,
    errors
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = validateReadinessPlan();
    console.log(JSON.stringify(result, null, 2));
    process.exitCode = result.valid ? 0 : 1;
  } catch (error) {
    console.error(`Plan validation failed: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
