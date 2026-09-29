/* Optional local visual acceptance. Never calls Genius or a model provider.
 * npm run viewer, then node tests/viewer_real_trace_qa.cjs [base URL] [output dir]
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");
(async () => {
  const base = process.argv[2] || "http://127.0.0.1:4070";
  const output = process.argv[3] || "logs/viewer-qa";
  assert.equal(new URL(base).hostname, "127.0.0.1");
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath:
      process.env.CHROME_PATH ||
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1512, height: 982 },
    });
    const external = [],
      errors = [];
    page.on("request", (r) => {
      if (new URL(r.url()).origin !== new URL(base).origin)
        external.push(r.url());
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page.locator(".event").first().waitFor();
    const data = await page.evaluate(async () =>
      (await fetch("/api/index")).json(),
    );
    const approval = data.events.find(
      (e) => e.run_id === "live-smoke" && e.kind === "approval_terminal_result",
    );
    const tool = data.events.find(
      (e) =>
        e.run_id === "live-smoke" && e.tool_name === "project_create_with_team",
    );
    const reply = data.events
      .filter((e) => e.raw?.summary?.raw?.reply)
      .sort((a, b) => b.text.length - a.text.length)[0];
    assert.ok(
      approval && tool && reply,
      "Real approval, tool-call and reply records are required",
    );
    const link = (e) =>
      `${base}/?${new URLSearchParams({ run_id: e.run_id, session_id: e.session_id || "", event_id: e.event_id })}`;
    await page.goto(link(tool));
    await page.locator(".event.active").waitFor();
    await page.locator(".event.tool").first().locator("summary").click();
    await page.waitForFunction(() => document.querySelector(".tool pre"));
    await page.screenshot({ animations: "disabled",
      path: path.join(output, "after-tool-desktop.png"),
    });
    await page.goto(link(approval));
    await page.locator(".event.active").waitFor();
    assert.match(
      await page.locator(".event.active").textContent(),
      /策略判定 · denied/,
    );
    assert.match(
      await page.locator(".event.active").textContent(),
      /策略判定 · approved/,
    );
    assert.match(
      await page.locator(".event.active").textContent(),
      /completed_after_approval/,
    );
    await page.screenshot({ animations: "disabled",
      path: path.join(output, "after-approval-desktop.png"),
    });
    await page.reload();
    await page.locator(".event.active").waitFor();
    assert.match(
      await page.locator("#details-body").textContent(),
      /approval_terminal_result/,
    );
    await page.locator(".event.active").focus();
    await page.keyboard.press("ArrowDown");
    assert.notEqual(
      new URL(page.url()).searchParams.get("event_id"),
      approval.event_id,
    );
    await page.goto(link(reply));
    await page.locator(".event.active").waitFor();
    // Place the reply at the top of the reading column for the comparison image.
    await page
      .locator(".event.active")
      .evaluate((n) => n.scrollIntoView({ block: "start" }));
    await page.screenshot({ animations: "disabled", path: path.join(output, "after-desktop.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page
      .locator(".event.active")
      .evaluate((n) => n.scrollIntoView({ block: "start" }));
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await page.screenshot({ animations: "disabled", path: path.join(output, "after-mobile.png") });
    await page.setViewportSize({ width: 1512, height: 982 });
    await page.locator("#theme-toggle").click();
    await page.screenshot({ animations: "disabled", path: path.join(output, "after-dark.png") });
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    fs.writeFileSync(
      path.join(output, "acceptance.json"),
      JSON.stringify(
        {
          date: new Date().toISOString(),
          eventCount: data.events.length,
          approvalEvent: approval.event_id,
          toolEvent: tool.event_id,
          replyEvent: reply.event_id,
          replyURL: link(reply),
          approvalURL: link(approval),
          externalRequests: external,
          browserErrors: errors,
          checks: [
            "real tool input/result",
            "real approval denied then approved",
            "real Markdown reply",
            "event reload",
            "keyboard navigation",
            "390px no horizontal overflow",
            "dark theme",
          ],
        },
        null,
        2,
      ),
    );
    console.log(`Visual acceptance passed. Screenshots: ${output}`);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
