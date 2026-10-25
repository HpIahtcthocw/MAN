/* Runner for *.playwright.js checks (bare `async (page) => {...}` expression).
 * Reuses the shared playwright install in E:/gitproject/hackathon/solo
 * (v1.62.1, browsers already cached); this repo keeps no playwright dep.
 * Usage: node tools/run_playwright_check.cjs tools/verify-responsive.playwright.js
 */
const fs=require('node:fs');
const path=require('node:path');
const playwright=require('E:/gitproject/hackathon/solo/node_modules/playwright');

(async()=>{
 const scriptPath=path.resolve(process.argv[2]);
 const source=fs.readFileSync(scriptPath,'utf8');
 const check=Function('"use strict";return ('+source+')')();
 const executablePath='C:/Users/ASUS/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe';
 const browser=await playwright.chromium.launch({headless:true,executablePath});
 const page=await browser.newPage();
 try{
  const result=await check(page);
  console.log(JSON.stringify(result,null,2));
  await browser.close();
 }catch(error){
  console.error('CHECK_FAILED',error&&error.message?error.message:error);
  try{await browser.close()}catch(_){}
  process.exitCode=1;
 }
})();
