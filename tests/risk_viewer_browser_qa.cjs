/* Local-only browser QA for the dual-gate human review page. */
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
    await page.goto(origin + '/risks.html', {waitUntil:'networkidle'});
    await page.locator('.risk-card').first().waitFor();
    assert.equal(await page.locator('.risk-card').count(), 23);
    assert.match(await page.locator('#metric-grid').textContent(), /23B · 真实可测/);
    assert.match(await page.locator('#risk-detail').textContent(), /五步攻击链/);
    await page.locator('#risk-search').fill('ransomware');
    await page.waitForFunction(() => document.querySelectorAll('.risk-card').length === 1);
    assert.match(await page.locator('#risk-detail').textContent(), /Ransomware|ransomware/i);
    assert.match(await page.locator('#risk-detail').textContent(), /SUCCESS ORACLE/);
    await page.locator('#risk-search').fill('');
    await page.locator('#source-filter').selectOption('skillfortifybench');
    assert.ok(await page.locator('.risk-card').count() > 0);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (process.argv[3]) await page.screenshot({path:process.argv[3], fullPage:true});
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    process.stdout.write('Risk review browser QA passed; external page requests: 0\n');
  } finally { await browser.close(); }
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exit(1); });
