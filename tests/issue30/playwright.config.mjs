import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
  testDir:'.',
  testMatch:'browser.spec.mjs',
  timeout:25000,
  expect:{timeout:6000},
  retries:0,
  workers:2,
  reporter:[['list']],
  use:{
    baseURL:'http://127.0.0.1:8765',
    browserName:'chromium',
    trace:'retain-on-failure',
    screenshot:'only-on-failure',
    headless:true,
  },
  webServer:{
    command:'python3 -m http.server 8765 --bind 127.0.0.1 --directory .',
    url:'http://127.0.0.1:8765/tests/issue30/browser_fixture.html',
    timeout:15000,
    reuseExistingServer:false,
  },
});
