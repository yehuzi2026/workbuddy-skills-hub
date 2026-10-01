#!/usr/bin/env node
/**
 * Darwin Skill - 高清截图脚本
 *
 * 用法: node scripts/screenshot.mjs [html文件路径] [输出png路径]
 *
 * 特性:
 * - 2x deviceScaleFactor，输出高清图
 * - 只截 .card 元素，无多余背景
 * - 等待字体加载完成
 * - 截完自动用 open 命令打开图片（设 DARWIN_NO_OPEN=1 可跳过，适用于无人值守环境）
 *
 * WorkBuddy 适配说明：
 * - 若 playwright-core 期望的内核版本与本机 ms-playwright 已有内核不一致，
 *   自动复用本机已安装的 Chromium 内核，无需重新下载内核。
 */

import { createRequire } from 'module';
import { execSync } from 'child_process';
import { existsSync, readdirSync } from 'fs';
import path from 'path';
const require = createRequire(import.meta.url);

// 健壮解析 playwright / playwright-core：跨机器、跨平台，不硬编码任何用户路径
function loadPlaywright() {
  // 1) 标准解析（脚本目录或 NODE_PATH 里有的话）
  for (const m of ['playwright', 'playwright-core']) {
    try { return require(m); } catch {}
  }
  // 2) 动态定位全局 node_modules 并尝试候选路径
  const candidates = [];
  try {
    const groot = execSync('npm root -g', { encoding: 'utf8' }).trim();
    candidates.push(path.join(groot, 'playwright-core'));
    candidates.push(path.join(groot, 'playwright'));
    // openclaw 等把 playwright-core 作为嵌套依赖的情况
    candidates.push(path.join(groot, 'openclaw', 'node_modules', 'playwright-core'));
  } catch {}
  for (const c of candidates) {
    if (existsSync(c)) { try { return require(c); } catch {} }
  }
  throw new Error(
    'playwright/playwright-core 未找到。请先安装：npm install -g playwright-core 且 npx playwright install chromium'
  );
}
const pw = loadPlaywright();

// 环境适配：优先用 playwright-core 自带内核；若版本号与本机 ms-playwright 已有内核不匹配，
// 则回退复用本机已安装的内核，避免为此重新下载上百 MB 的浏览器。
async function launchBrowser() {
  try {
    return await pw.chromium.launch();
  } catch (err) {
    const base = process.env.PLAYWRIGHT_BROWSERS_PATH
      || (process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, 'ms-playwright') : null);
    if (!base || !existsSync(base)) throw err;

    const found = [];
    for (const d of readdirSync(base)) {
      const shell = /^chromium_headless_shell-(\d+)$/.exec(d);
      if (shell) {
        found.push([Number.parseInt(shell[1], 10),
          path.join(base, d, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')]);
      }
      const full = /^chromium-(\d+)$/.exec(d);
      if (full) {
        found.push([Number.parseInt(full[1], 10),
          path.join(base, d, 'chrome-win', 'chrome.exe')]);
      }
    }
    found.sort((a, b) => b[0] - a[0]);

    for (const [rev, exe] of found) {
      if (existsSync(exe)) {
        console.log(`提示: 复用本机已有 Chromium 内核 r${rev}`);
        return await pw.chromium.launch({ executablePath: exe });
      }
    }
    throw err;
  }
}

const htmlPath = process.argv[2] || new URL('../templates/result-card.html', import.meta.url).pathname;
const outputPath = process.argv[3] || new URL('../templates/result-card.png', import.meta.url).pathname;

async function screenshot() {
  const browser = await launchBrowser();

  try {
    const context = await browser.newContext({
      viewport: { width: 920, height: 1600 },
      deviceScaleFactor: 2,
    });

    const page = await context.newPage();

    await page.goto(`file://${htmlPath.replace(/\\/g,'/')}`, { waitUntil: 'networkidle' });

    // 等待字体加载
    await page.evaluate(() => document.fonts.ready);
    // 额外等待确保渲染完成
    await page.waitForTimeout(2000);

    // 只截 .card 元素
    const card = await page.locator('.card');
    await card.screenshot({
      path: outputPath,
      type: 'png',
    });

    console.log(`截图完成: ${outputPath}`);

    // 获取图片尺寸信息
    const box = await card.boundingBox();
    console.log(`卡片尺寸: ${Math.round(box.width)}x${Math.round(box.height)}px (CSS)`);
    console.log(`输出尺寸: ${Math.round(box.width * 2)}x${Math.round(box.height * 2)}px (2x高清)`);

  } finally {
    await browser.close();
  }

  // 无人值守环境（如 WorkBuddy 自动化流程）跳过自动弹窗
  if (process.env.DARWIN_NO_OPEN === '1') {
    console.log(`图片已保存: ${outputPath}`);
    return;
  }

  // 自动打开图片（跨平台）
  try {
    if (process.platform === 'win32') {
      execSync(`start "" "${outputPath}"`);
    } else if (process.platform === 'darwin') {
      execSync(`open "${outputPath}"`);
    } else {
      execSync(`xdg-open "${outputPath}"`);
    }
  } catch {
    // 打不开也无妨，路径已打印
    console.log(`图片已保存: ${outputPath}`);
  }
}

screenshot().catch(err => {
  console.error('截图失败:', err.message);
  process.exit(1);
});
