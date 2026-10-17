// Rasterize the existing project SVG; PNG-compressed ICO entries need no image library.
import fs from 'node:fs';
import {chromium} from '@playwright/test';
fs.mkdirSync('assets',{recursive:true});
const browser=await chromium.launch(process.env.CLIGRID_CHROMIUM?{executablePath:process.env.CLIGRID_CHROMIUM}:{});
try {
  const svg=fs.readFileSync('../icons/cligrid.svg','utf8');
  fs.writeFileSync('assets/icon.svg',svg);
  const images=[];
  for(const size of [32,48,256]) {
    const page=await browser.newPage({viewport:{width:size,height:size},deviceScaleFactor:1});
    await page.setContent(`<style>body{margin:0}svg{width:100vw;height:100vh;display:block}</style>${svg}`);
    const png=await page.screenshot({omitBackground:true});images.push({size,png});
    if(size===256)fs.writeFileSync('assets/icon.png',png);
    await page.close();
  }
  const header=Buffer.alloc(6+16*images.length);header.writeUInt16LE(1,2);header.writeUInt16LE(images.length,4);
  let offset=header.length;
  images.forEach(({size,png},i)=>{const n=6+16*i;header[n]=size%256;header[n+1]=size%256;header.writeUInt16LE(1,n+4);header.writeUInt16LE(32,n+6);header.writeUInt32LE(png.length,n+8);header.writeUInt32LE(offset,n+12);offset+=png.length;});
  fs.writeFileSync('assets/icon.ico',Buffer.concat([header,...images.map(i=>i.png)]));
} finally {await browser.close();}
