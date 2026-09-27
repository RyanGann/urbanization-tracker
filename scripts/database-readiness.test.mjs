import assert from "node:assert/strict";
import test from "node:test";
import { waitForDatabase } from "./database-readiness.mjs";

test("one persistent process receives the host deadline and remaining overhead budget", async () => {
  let calls = 0;
  let tick = 1000;
  await waitForDatabase({ compose: ["compose"], root: "/repo", log: [],
    now: () => 1000,
    clock: () => { const value = tick; tick += 25; return value; },
    run: async (command, args, options) => {
      calls++;
      assert.equal(command, "docker");
      assert.deepEqual(args.slice(-4), ["api", "python", "/integration/database_readiness.py", "181"]);
      assert.equal(options.timeoutMs, 179975);
      assert.equal(options.killGraceMs, 0);
      return { code: 0 };
    } });
  assert.equal(calls, 1);
});

test("backwards wall-clock drift cannot extend the process timeout", async () => {
  await waitForDatabase({ compose: [], root: "/repo", log: [], now: () => -100000,
    clock: () => 1000, run: async (command, args, options) => {
      assert.equal(options.timeoutMs, 180000);
      return { code: 0 };
    } });
});

test("unavailable database refuses without disclosing process output", async () => {
  await assert.rejects(waitForDatabase({ compose: [], root: "/repo", log: [],
    run: async () => ({ code: 1, output: "secret" }) }),
  /database TCP SQL readiness failed/);
});

for (const message of ["process exceeded deadline", "integration run interrupted"]) {
  test(`process ${message} propagates to owning cleanup`, async () => {
    await assert.rejects(waitForDatabase({ compose: [], root: "/repo", log: [],
      run: async () => { throw new Error(message); } }), { message });
  });
}
