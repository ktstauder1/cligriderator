import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'e2e',workers:1,timeout:30000,use:{headless:true,viewport:{width:1440,height:900},launchOptions:process.env.CLIGRID_CHROMIUM?{executablePath:process.env.CLIGRID_CHROMIUM}:{}},reporter:'list'});
