import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import * as jsxRuntime from "react/jsx-runtime";

// Execute the component's hooks without a browser; only the HTTP boundary is replaced.
function historyHarness(auditEvents) {
  const slots = [], effects = [];
  let cursor = 0;
  const react = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = initial;
      return [slots[i], (next) => { slots[i] = typeof next === "function" ? next(slots[i]) : next; }];
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!slots[i] || deps.some((value, n) => value !== slots[i].deps[n])) {
        slots[i]?.cleanup?.();
        slots[i] = { deps };
        effects.push(() => { slots[i].cleanup = effect(); });
      }
    },
  };
  const sandbox = {
    exports: {},
    require(name) {
      if (name === "react") return react;
      if (name === "react/jsx-runtime") return jsxRuntime;
      if (name === "@/lib/accounting-api") return { accountingApi: { auditEvents } };
      if (name === "@/lib/accounting-format") return { apiErrorMessage: () => "Request failed" };
      if (name === "@/components/work/ui") return { BTN: "" };
      if (name === "@/components/accounting/AuditTrail") return { default: () => null };
      throw new Error(`Unexpected import: ${name}`);
    },
  };
  const filename = fileURLToPath(new URL("../src/components/work/TaskHistory.tsx", import.meta.url));
  const source = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(source, sandbox, { filename });
  return async () => {
    const render = () => {
      cursor = 0;
      const tree = sandbox.exports.default({ taskId: "task", people: [] });
      while (effects.length) effects.shift()();
      return tree;
    };
    render();
    await new Promise(setImmediate);
    return render();
  };
}

function olderButton(tree) {
  return tree.props.children.find((child) => child?.type === "button");
}

test("failed history pagination retries the missing page without skipping events", async () => {
  const offsets = [];
  const render = historyHarness(async ({ offset }) => {
    offsets.push(offset);
    if (offsets.length === 2) throw new Error("Temporary network failure");
    return { events: Array.from({ length: 20 }, (_, n) => ({ id: `${offset + n}`, before: {}, after: {} })), total: 60 };
  });
  let tree = await render();
  olderButton(tree).props.onClick();
  tree = await render();
  olderButton(tree).props.onClick();
  tree = await render();
  assert.deepEqual(offsets, [0, 20, 20]);
  const trail = tree.props.children.find((child) => child?.props?.events);
  assert.equal(trail.props.events.length, 40);
  assert.equal(new Set(trail.props.events.map((event) => event.id)).size, 40);
});
