/* Offline browser regression checks. Run against tests.test_viewer fixtures. */
const assert = require("node:assert/strict");
const { chromium } = require("playwright");
(async () => {
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
    const errors = [],
      external = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (new URL(r.url()).origin !== new URL(process.argv[2]).origin)
        external.push(r.url());
    });
    await page.goto(
      `${process.argv[2]}/?run_id=sweep-run&session_id=sweep-session`,
    );
    await page.locator(".event").first().waitFor();
    assert.equal(await page.locator(".event.user").count(), 1);
    assert.equal(
      await page.locator(".event.assistant h2").textContent(),
      "回放标题",
    );
    assert.equal(
      await page.locator(".event.assistant strong").textContent(),
      "重点",
    );
    assert.equal(
      await page
        .locator(
          ".event.assistant img, .event.assistant script, .event.assistant a",
        )
        .count(),
      0,
    );
    assert.match(await page.locator(".event.assistant").textContent(), /<img/);
    const reasoning = page.locator(".event.reasoning").first();
    assert.equal(await reasoning.locator("details").getAttribute("open"), null);
    await reasoning.locator("summary").click();
    await page.waitForFunction(() =>
      document.querySelector(".reasoning details .prose"),
    );
    assert.match(await reasoning.textContent(), /sweep reasoning/);
    const approval = page.locator(".event.approval");
    assert.equal(await approval.count(), 1);
    assert.equal(await approval.locator(".flow li").count(), 4);
    assert.equal(await page.locator(".event.tool").count(), 1);
    await page.locator(".event.tool summary").click();
    await page.waitForFunction(() => document.querySelector(".tool pre"));
    assert.match(await page.locator(".event.tool").textContent(), /team-1/);
    assert.match(
      await page.locator(".event.tool").textContent(),
      /awaiting_user_confirmation/,
    );
    // Every merged event remains individually addressable after refresh.
    await approval.locator(".flow button").last().click();
    const id = new URL(page.url()).searchParams.get("event_id");
    assert.ok(id);
    await page.reload();
    await page.locator(".event.active").waitFor();
    assert.match(
      await page.locator("#details-body").textContent(),
      new RegExp(id),
    );
    assert.equal(
      await page.locator("#raw-json details").getAttribute("open"),
      null,
    );
    await page.locator(".event.active").focus();
    await page.keyboard.press("ArrowDown");
    assert.notEqual(new URL(page.url()).searchParams.get("event_id"), id);
    assert.equal(await page.locator(".event.active").count(), 1);
    // Long sessions render at most one page initially, then remain navigable.
    await page.goto(`${process.argv[2]}/?run_id=sweep-run&view=events`);
    await page.locator("#load-more").waitFor();
    assert.equal(await page.locator(".event").count(), 60);
    await page.locator("#load-more").click();
    assert.equal(await page.locator(".event").count(), 120);
    await page.locator(".event").nth(100).click();
    const lateId = new URL(page.url()).searchParams.get("event_id");
    await page.reload();
    await page.locator(".event.active").waitFor();
    assert.match(
      await page.locator("#details-body").textContent(),
      new RegExp(lateId),
    );
    // Session and request filters survive refresh together, and do not widen.
    await page.goto(
      `${process.argv[2]}/?session_id=sweep-session&request_id=sweep-request&tool_name=team_delete`,
    );
    await page.locator(".event").first().waitFor();
    assert.equal(
      new URL(page.url()).searchParams.get("request_id"),
      "sweep-request",
    );
    assert.equal(await page.locator(".event.tool").count(), 1);
    assert.ok(await page.locator(".event.assistant").count());
    await page.reload();
    await page.locator(".event.tool").waitFor();
    assert.equal(
      new URL(page.url()).searchParams.get("tool_name"),
      "team_delete",
    );
    // Narrow viewport keeps transcript available, with an optional inspector.
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    assert.ok(
      await page.locator("#timeline").evaluate((n) => n.clientHeight > 300),
    );
    await page.locator("#toggle-details").click();
    assert.equal(await page.locator("#inspector").isVisible(), true);
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#inspector").isVisible(), false);
    await page.locator("#theme-toggle").click();
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.reload();
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.locator("[data-filter=q]").fill("not-a-real-event-needle");
    assert.match(await page.locator("#timeline").textContent(), /没有匹配/);
    await page.goBack();
    // Recoverable API error and loading state.
    await page.route("**/api/index", (route) =>
      route.fulfill({ status: 503, body: "unavailable" }),
    );
    await page.reload();
    await page.getByText("暂时无法读取轨迹").waitFor();
    await page.unroute("**/api/index");
    await page.getByRole("button", { name: "重试", exact: true }).click();
    await page.locator(".event").first().waitFor();
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log(
      "Browser QA passed: transcript, Markdown safety, grouped evidence, deep links, keyboard, paging, filters, mobile, theme, error recovery, zero external requests.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
