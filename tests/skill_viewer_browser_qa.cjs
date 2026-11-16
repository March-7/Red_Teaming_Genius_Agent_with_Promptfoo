/* Only local fixture data; all non-local page requests are blocked. */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const origin = new URL(process.argv[2]).origin;
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args:['--disable-background-networking']});
  try {
    const page = await browser.newPage({viewport:{width:1512,height:982}});
    const errors = [], external = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin !== origin) {
        external.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    await page.goto(`${origin}/?suite_id=genius-skill-security&case_id=notes-one&variant=normal`);
    await page.locator('.event').first().waitFor();
    await page.locator('#toggle-filters').click();
    assert.equal(await page.locator('[data-filter=suite_id]').inputValue(), 'genius-skill-security');
    assert.equal(await page.locator('[data-filter=variant]').inputValue(), 'normal');
    assert.match(await page.locator('#timeline').textContent(), /正常资料总结/);
    assert.ok(!(await page.locator('#timeline').textContent()).includes('攻击侧记录'));
    await page.locator('.event').last().click();
    const event = new URL(page.url()).searchParams.get('event_id');
    assert.ok(event);
    await page.reload();
    await page.locator('.event.active').waitFor();
    assert.match(await page.locator('#details-body').textContent(), /notes-one/);
    await page.locator('#toggle-filters').click();
    await page.locator('[data-filter=variant]').selectOption('attack');
    await page.waitForFunction(() => document.querySelector('#timeline').textContent.includes('攻击侧记录'));
    assert.ok(!(await page.locator('#timeline').textContent()).includes('正常资料总结'));
    await page.goto(`${origin}/?run_id=notes-skill-run&outcome=not-run`);
    await page.locator('.event').first().waitFor();
    assert.match(await page.locator('#timeline').textContent(), /Judge: not-run/);
    await page.setViewportSize({width:390,height:844});
    await page.locator('#toggle-filters').click();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const hashFilter = page.locator('[data-filter=skill_hash]');
    await hashFilter.scrollIntoViewIfNeeded();
    const visible = await hashFilter.boundingBox();
    const panel = await page.locator('#filter-panel').boundingBox();
    assert.ok(visible.y >= panel.y && visible.y + visible.height <= panel.y + panel.height);
    if (process.argv[3]) await page.screenshot({path:process.argv[3], fullPage:true});
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    process.stdout.write('Skill viewer browser QA passed; external page requests: 0\n');
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exit(1); });
