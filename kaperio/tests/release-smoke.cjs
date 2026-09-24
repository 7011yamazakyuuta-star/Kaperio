// Optional browser acceptance test; only synthetic documents are used.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {spawn, execFileSync} = require('node:child_process');
const {chromium} = require(require.resolve('playwright', {paths: [process.env.KAPERIO_NODE_MODULES || process.cwd()]}));
const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const data = path.join(root, '.test-data', 'release-browser-' + process.pid);
fs.mkdirSync(data, {recursive: true});
const source = path.join(data, 'Sample.pdf');
execFileSync(python, ['-c', "import sys; from pathlib import Path; sys.path.insert(0,'tests'); from test_core import make_pdf; make_pdf(Path(sys.argv[1]),'Test42')", source], {cwd: root, windowsHide: true});
const child = spawn(python, ['app.py', '--port', '0', '--data', data, '--no-browser'], {cwd: root, windowsHide: true, stdio: 'ignore'});
const exited = new Promise(resolve => child.once('exit', resolve));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  let browser, context, base;
  try {
    for (let i = 0; i < 100 && !fs.existsSync(path.join(data, 'launch.json')); i++) {
      if (child.exitCode !== null) throw Error('Server exited before launch');
      await delay(100);
    }
    const launch = JSON.parse(fs.readFileSync(path.join(data, 'launch.json'), 'utf8'));
    base = new URL(launch.url).origin;
    browser = await chromium.launch({channel: process.env.KAPERIO_BROWSER || 'msedge', headless: true});
    context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(launch.url);
    await page.locator('#settings-open').click();
    assert.equal(await page.locator('#hashcat-path').inputValue(), '');
    assert.equal(await page.locator('#zip2john-path').inputValue(), '');
    const licenses = await context.request.get(base + '/api/licenses');
    assert.equal(licenses.status(), 200);
    assert.match(await licenses.text(), /Lucide Icons/);
    await page.locator('#settings-form button[type=submit]').click();
    await page.locator('#settings-close').click();
    await page.locator('#files').setInputFiles(source);
    await page.locator('#document-name').filter({hasText: 'Sample.pdf'}).waitFor();
    await page.locator('#password').fill('wrong');
    await page.locator('#known-form button[type=submit]').click();
    await page.locator('#toast').filter({hasText: '一致しません'}).waitFor();
    await page.locator('#password').fill('Test42');
    await page.locator('#known-form button[type=submit]').click();
    await page.locator('#ready-state').waitFor();
    await page.waitForFunction(() => document.getElementById('page-image').naturalWidth > 0);
    await page.locator('#tab-export').click();
    await page.locator('#export-kind').selectOption('image_pdf');
    await page.locator('#export-form button[type=submit]').click();
    await page.locator('#outputs a').nth(1).waitFor();
    await page.screenshot({path: path.join(data, 'desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await page.locator('#settings-open').click();
    const bounds = await page.locator('#settings-dialog').boundingBox();
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
    await page.screenshot({path: path.join(data, 'mobile-settings.png'), fullPage: true});
    await page.locator('#settings-close').click();
    await page.locator('#remove-file').click();
    await page.locator('#remove-confirm').click();
    await page.locator('#empty').waitFor();
    assert.ok(fs.existsSync(source));
    const second = execFileSync(python, ['app.py', '--data', data, '--no-browser'], {cwd: root, windowsHide: true, encoding: 'utf8'});
    assert.match(second, /already running/);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: true, checks: ['fresh-no-engine', 'licenses', 'unlock', 'preview', 'export', 'mobile', 'delete', 'single-instance'], screenshots: data}));
  } finally {
    if (context && base) await context.request.post(base + '/api/shutdown', {headers: {'X-Kaperio': '1'}, data: {}}).catch(() => {});
    if (browser) await browser.close();
    await Promise.race([exited, delay(3000)]);
    if (child.exitCode === null) child.kill();
    await exited;
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
