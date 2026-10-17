import fs from 'node:fs';
import path from 'node:path';
import {build} from 'esbuild';

fs.mkdirSync('dist',{recursive:true});
await build({entryPoints:['src/renderer.js'],bundle:true,outfile:'dist/renderer.js',platform:'browser',target:'chrome140',sourcemap:false});
fs.copyFileSync('node_modules/@xterm/xterm/css/xterm.css','dist/xterm.css');
fs.copyFileSync('../LICENSE','LICENSE');
const packages=['@xterm/xterm','@xterm/addon-fit','@xterm/addon-search','@xterm/addon-web-links','node-pty','node-addon-api'];
const notices=['Third-party components retain their own licenses. The application license does not replace these terms. Electron and Chromium notices are also included alongside the executable.\n'];
function licenses(dir) {
  const result=[];
  for(const entry of fs.readdirSync(dir,{withFileTypes:true})) {
    if(entry.name==='node_modules')continue;
    const file=path.join(dir,entry.name);
    if(entry.isDirectory())result.push(...licenses(file));
    else if(/^licen[cs]e(?:\.|$)/i.test(entry.name))result.push(file);
  }
  return result;
}
for(const name of packages) {
  const dir=path.join('node_modules',name),files=licenses(dir);
  if(!files.length)throw new Error(`Missing license for ${name}`);
  for(const file of files)notices.push(`\n--- ${file} ---\n${fs.readFileSync(file,'utf8')}`);
}
fs.writeFileSync('THIRD-PARTY-NOTICES.txt',notices.join('\n'));
