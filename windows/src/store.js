import fs from 'node:fs';
import path from 'node:path';
import { createState, validateState } from './model.js';

export function loadState(file) {
  if (!fs.existsSync(file)) return createState();
  if (fs.statSync(file).size > 2*1024*1024) throw new Error('Settings file is too large');
  return validateState(JSON.parse(fs.readFileSync(file,'utf8')));
}
export function saveState(file, state) {
  validateState(state);
  fs.mkdirSync(path.dirname(file),{recursive:true});
  const temp=file+'.tmp';
  fs.writeFileSync(temp,JSON.stringify(state,null,2),{mode:0o600});
  fs.renameSync(temp,file);
}
