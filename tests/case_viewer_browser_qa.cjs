/* Local-only browser QA for the 23-case human review page. */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const origin = new URL(process.argv[2]).origin;
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    args:['--disable-background-networking']});
  try {
    const page = await browser.newPage({viewport:{width:1512,height:982}});
    const errors=[], external=[];
    page.on('pageerror', e=>errors.push(e.message));
    await page.route('**/*', route=>{if(new URL(route.request().url()).origin!==origin){external.push(route.request().url());return route.abort();}return route.continue();});
    await page.goto(origin+'/cases.html',{waitUntil:'networkidle'});
    await page.locator('.risk-card').first().waitFor();
    assert.equal(await page.locator('.risk-card').count(),23);
    assert.match(await page.locator('#metric-grid').textContent(),/23Cases/);
    const detail=page.locator('#case-detail');
    assert.match(await detail.textContent(),/USER REQUEST/);
    assert.match(await detail.textContent(),/SKILL BEHAVIOR/);
    assert.match(await detail.textContent(),/SUCCESS/);
    await page.locator('#case-search').fill('ransomware');
    await page.waitForFunction(()=>document.querySelectorAll('.risk-card').length===1);
    assert.match(await detail.textContent(),/勒索式文件加密/);
    await page.locator('#case-search').fill('');
    await page.locator('#carrier-filter').selectOption('package-asset');
    assert.equal(await page.locator('.risk-card').count(),4);
    await page.locator('.risk-card').first().click();
    const selected=new URL(page.url()).searchParams.get('case');assert.ok(selected);
    await page.reload();await page.locator('.risk-card.active').waitFor();
    assert.match(await detail.textContent(),/USER REQUEST/);
    assert.match(await detail.textContent(),/SKILL BEHAVIOR/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    if(process.argv[3])await page.screenshot({path:process.argv[3],fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    process.stdout.write('Case review browser QA passed; external page requests: 0\n');
  } finally {await browser.close();}
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exit(1);});
