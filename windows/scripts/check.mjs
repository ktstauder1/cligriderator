import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
for(const dir of ['src','scripts','test','e2e']) {
  for(const file of fs.readdirSync(dir).filter(name=>/\.(?:js|mjs|cjs)$/.test(name))) {
    const result=spawnSync(process.execPath,['--check',`${dir}/${file}`],{stdio:'inherit'});
    if(result.status!==0)process.exit(1);
  }
}
console.log('JavaScript syntax checks passed.');
