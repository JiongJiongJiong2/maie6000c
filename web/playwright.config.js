import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 20000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.WEB_BASE_URL || "http://127.0.0.1:8765",
    headless: true,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 1040 },
  },
  webServer: process.env.WEB_BASE_URL
    ? undefined
    : {
        command: "python -m http.server 8765 --bind 127.0.0.1 --directory ..",
        url: "http://127.0.0.1:8765/web/",
        reuseExistingServer: false,
      },
});
