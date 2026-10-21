/* Optional browser checks: npm install --no-save playwright-core
 * Run the server first, then CHROMIUM_PATH=/path/to/chromium node tests/browser.cjs
 * BASE_URL defaults to http://localhost:8000. No production dependencies.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    headless: true,
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.BASE_URL || 'http://localhost:8000');
    await page.locator('#order').fill('Решить 10 задач по эконометрике');
    await page.locator('#daily-checks input').first().check();
    await page.reload();
    assert.equal(await page.locator('#order').inputValue(), 'Решить 10 задач по эконометрике');
    assert.equal(await page.locator('#readiness').innerText(), '17');
    await page.locator('[data-page=plan]').click();
    assert.equal(await page.locator('.day-cell').count(), 70);
    await page.locator('.day-cell').last().click();
    assert.match(await page.locator('#selected-day').innerText(), /31 дек/);
    await page.locator('[data-page=settings]').click();
    await page.locator('[name=theme]').selectOption('light');
    await page.locator('[name=goal]').fill('500');
    await page.locator('#settings-form button').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
    await page.locator('[data-page=journal]').click();
    await page.locator('#report').fill('Решены 10 задач, разобраны ошибки.');
    await page.locator('#manual-minutes').fill('60');
    await page.locator('#add-time').click();
    assert.match(await page.locator('#journal-list').innerText(), /60 мин/);
    await page.locator('[data-page=dashboard]').click();
    await page.locator('#timer-start').click();
    await page.waitForTimeout(1100);
    await page.locator('#timer-start').click();
    const paused = await page.locator('#timer').innerText();
    await page.reload();
    assert.equal(await page.locator('#timer').innerText(), paused);
    await page.evaluate(() => {
      const state = JSON.parse(localStorage.getItem('genshtab-web-v1'));
      Object.assign(state.timer, { running: true, end: Date.now() - 100, duration: 300, remaining: 0 });
      localStorage.setItem('genshtab-web-v1', JSON.stringify(state));
    });
    await page.reload();
    await page.waitForTimeout(700);
    assert.equal(await page.locator('#today-focus').innerText(), '65 мин');
    await page.reload();
    assert.equal(await page.locator('#today-focus').innerText(), '65 мин');
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      for (const name of ['dashboard', 'plan', 'soldier', 'journal', 'settings']) {
        await page.locator(`[data-page=${name}]`).click();
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
          false, `Horizontal overflow: ${name} / ${width}`);
      }
    }
    // Imports are validated; report/order text is never inserted as HTML.
    await page.locator('#import').setInputFiles({
      name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{"schema":99}'),
    });
    await page.waitForTimeout(150);
    assert.match(await page.locator('#toast').innerText(), /Импорт отклонён/);
    await page.locator('[data-page=dashboard]').click();
    assert.equal(await page.locator('#order').inputValue(), 'Решить 10 задач по эконометрике');
    assert.deepEqual(errors, []);
    console.log('PASS: persistence, 70 dates, settings, manual focus, timer, invalid import, 25 responsive layouts.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
