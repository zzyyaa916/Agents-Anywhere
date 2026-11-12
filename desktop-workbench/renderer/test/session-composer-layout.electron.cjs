// Run with Electron after building the renderer; measures real Chromium layout.
const { app, BrowserWindow } = require('electron');
app.disableHardwareAcceleration();
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/components/session-detail.tsx'), 'utf8');
const ast = ts.createSourceFile('session-detail.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function slotClass(slot) {
  let found;
  function visit(node) {
    if (ts.isJsxOpeningElement(node)) {
      const attrs = node.attributes.properties;
      const attribute = name => attrs.find(a => ts.isJsxAttribute(a) && a.name.getText(ast) === name)?.initializer;
      if (attribute('data-slot')?.text === slot) found = attribute('className')?.text;
    }
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(found, `Missing production slot ${slot}`);
  return found;
}
const cssRoot = path.join(root, 'out/_next/static');
function cssFiles(dir) { return fs.readdirSync(dir, {withFileTypes:true}).flatMap(e => e.isDirectory() ? cssFiles(path.join(dir,e.name)) : e.name.endsWith('.css') ? [path.join(dir,e.name)] : []); }
const css = cssFiles(cssRoot).map(p => fs.readFileSync(p,'utf8')).join('\n');
const follow = ts.transpileModule(fs.readFileSync(path.join(root,'src/components/session/timeline-scroll-follow.ts'),'utf8'), {compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText.replace('export function', 'function');
setTimeout(() => { console.error('Layout browser test timed out'); app.exit(1); }, 30_000).unref();
app.whenReady().then(async () => {
  const window = new BrowserWindow({show:false, width:1100, height:800, webPreferences:{contextIsolation:true,backgroundThrottling:false}});
  await window.loadURL('about:blank');
  const result = await window.webContents.executeJavaScript(`(async () => {
    document.head.innerHTML = '<style>' + ${JSON.stringify(css)} + '</style>';
    document.body.style.margin = '0';
    document.body.innerHTML = '<main style="height:720px;display:flex;flex-direction:column;position:relative;overflow:hidden"><section id="timeline" class="${slotClass('session-timeline')}"><div id="viewport" style="height:100%;overflow:auto"><div id="content"><div style="height:2500px">older replies</div><div id="reply" style="height:80px">Latest AI response</div></div></div></section><footer id="composer" class="${slotClass('session-composer-stack')}"><div id="queue" style="height:0px">Pending commands</div><div style="height:140px">Message input</div></footer></main>';
    ${follow}
    const viewport=document.getElementById('viewport'), content=document.getElementById('content');
    const queue=document.getElementById('queue'), composer=document.getElementById('composer'), timeline=document.getElementById('timeline');
    const controller=createTimelineScrollFollow(viewport,content,()=>{},()=>{});
    const settle=async()=>{for(let i=0;i<5;i++)await new Promise(requestAnimationFrame)};
    const check=()=>{
      if(timeline.getBoundingClientRect().bottom>composer.getBoundingClientRect().top+1)throw Error('Pending commands overlap the reply viewport');
      if(document.getElementById('reply').getBoundingClientRect().bottom>viewport.getBoundingClientRect().bottom+1)throw Error('Latest reply requires manual scrolling after queue resize');
    };
    controller.resume();await settle();check();
    for(const height of [80,192,0,192]){queue.style.height=height+'px';await settle();check()}
    controller.pause();viewport.scrollTop=800;const top=viewport.scrollTop;
    queue.style.height='80px';await settle();
    if(Math.abs(viewport.scrollTop-top)>1)throw Error('Queue resize moved the reader away from older messages');
    if(timeline.getBoundingClientRect().bottom>composer.getBoundingClientRect().top+1)throw Error('Older messages overlap pending commands');
    controller.dispose();return 'Queue expand/shrink, latest response visibility and history reading passed';
  })()`);
  console.log(result);
  window.destroy();app.quit();
}).catch(error=>{console.error(error);app.exit(1)});
