import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const WEB = "http://localhost:3000";
const API = "http://127.0.0.1:8000";
const ADMIN_SECRET = process.env.ADMIN_API_SECRET ?? "dev-admin-secret-change-me";
const REVIEW_DIR = path.resolve("../../.impeccable/review/next");
const SAMPLE_PDF = path.resolve("../../backend/tests/sample_networks.pdf");

async function createAccessKey() {
  const userResponse = await fetch(`${API}/api/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Secret": ADMIN_SECRET },
    body: JSON.stringify({ display_name: "Design Review" }),
  });
  if (!userResponse.ok) throw new Error(`create user failed: ${userResponse.status}`);
  const user = await userResponse.json();

  const keyResponse = await fetch(`${API}/api/admin/users/${user.id}/keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Secret": ADMIN_SECRET },
    body: "{}",
  });
  if (!keyResponse.ok) throw new Error(`issue key failed: ${keyResponse.status}`);
  return (await keyResponse.json()).key;
}

async function main() {
  await fs.mkdir(REVIEW_DIR, { recursive: true });
  const key = process.env.STUDBUD_KEY ?? (await createAccessKey());
  const useBundledBrowser = process.env.PLAYWRIGHT_CHANNEL === "bundled";
  const browser = await chromium.launch(
    useBundledBrowser ? { headless: true } : { channel: "chrome", headless: true },
  );
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: "light",
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  async function shot(name, fullPage = true) {
    await page.screenshot({ path: path.join(REVIEW_DIR, `${name}.png`), fullPage });
    console.log(name);
  }

  await page.goto(`${WEB}/sign-in`, { waitUntil: "networkidle" });
  await page.waitForSelector("#access-key");
  await shot("signin-light");
  await page.click('button[aria-label="Switch to dark mode"]');
  await page.waitForTimeout(250);
  await shot("signin-dark");
  await page.click('button[aria-label="Switch to light mode"]');

  await page.fill("#access-key", key);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => url.pathname === "/");
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), {
    timeout: 30_000,
  });
  await page.waitForSelector(".doc-row, .empty");

  if ((await page.locator(".empty").count()) > 0) {
    await page.setInputFiles('input[type="file"]', SAMPLE_PDF);
    await page.waitForSelector(".status--ready", { timeout: 90_000 });
    await page.waitForTimeout(500);
  }

  await shot("library-light");

  await page.click('button[aria-label="Switch to dark mode"]');
  await page.waitForTimeout(250);
  await shot("library-dark");
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForSelector(".doc-row, .empty");
  const persistedTheme = await page.evaluate(() => document.documentElement.dataset.theme);
  if (persistedTheme !== "dark") throw new Error("Dark theme did not persist after reload");
  await page.click('button[aria-label="Switch to light mode"]');
  await page.waitForTimeout(250);

  await page.fill("#library-search", "tcp handshake");
  await page.click(".search__submit");
  await page.waitForURL(/\/search\?/);
  await page.waitForFunction(() => !document.querySelector('[aria-busy="true"]'), {
    timeout: 30_000,
  });
  await page.waitForSelector("a.result-row, .empty, .state");
  await shot("results-light");

  const resultLink = page.locator("a.result-row").first();
  const href = await resultLink.getAttribute("href");
  if (!href) throw new Error("No search result link found");
  const match = href.match(/documents\/([^/]+)\/chunks\/([^?]+)/);
  if (!match) throw new Error(`Unexpected result link: ${href}`);
  const [, documentId, chunkId] = match;
  const documentName =
    (await resultLink.locator(".result-doc span").innerText()).trim() || "Computer Networks.pdf";
  const sectionTitle =
    (await resultLink.locator(".result-heading").innerText()).trim() ||
    "TCP Three-Way Handshake";

  const mockExplanation = {
    explanation_id: "00000000-0000-4000-8000-000000000001",
    document_id: documentId,
    document_name: documentName,
    section_title: sectionTitle,
    page_start: 2,
    page_end: 2,
    answer: `TCP opens a connection with a three-step handshake so both computers agree they are ready to exchange data and agree on starting sequence numbers.

**The three steps**
- **SYN** — the client sends a synchronize segment with its starting sequence number.
- **SYN-ACK** — the server acknowledges that number and sends its own starting sequence number.
- **ACK** — the client acknowledges the server's number.

After the third step, both sides have synchronized sequence numbers and the connection is established. The handshake confirms reachability in both directions and initializes the state each endpoint needs for reliable delivery.

**Why three steps, not two?** Each side needs both to send its own starting number and to hear the other side's number acknowledged. Two messages would leave one of those confirmations missing.`,
    citations: [
      {
        chunk_id: chunkId,
        document_id: documentId,
        document_name: documentName,
        page_start: 2,
        page_end: 2,
        excerpt:
          "TCP establishes a connection using a three-step handshake. The client sends a SYN segment with its initial sequence number. The server replies with a SYN-ACK segment…",
      },
    ],
    insufficient_context: false,
    model: "openai/gpt-oss-120b",
  };

  await page.route("**/api/explanations", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(mockExplanation),
      });
      return;
    }
    await route.continue();
  });

  await page.goto(`${WEB}${href}`, { waitUntil: "networkidle" });
  await page.waitForSelector(".answer");
  await page
    .waitForFunction(() => {
      const image = document.querySelector<HTMLImageElement>(".page-preview img");
      return Boolean(image && image.complete && image.naturalWidth > 0);
    }, { timeout: 20_000 })
    .catch(() => undefined);
  await shot("explanation-light");

  await page.click('button[aria-label="Switch to dark mode"]');
  await page.waitForTimeout(250);
  await shot("explanation-dark");
  await page.click('button[aria-label="Switch to light mode"]');

  const pdfHref = await page.locator(".pdf-button").getAttribute("href");
  if (pdfHref) {
    await page.goto(`${WEB}${pdfHref}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);
    await shot("viewer", false);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${WEB}/`, { waitUntil: "networkidle" });
  await page.waitForSelector(".doc-list, .empty");
  await shot("library-mobile");

  await page.goto(`${WEB}${href}`, { waitUntil: "networkidle" });
  await page.waitForSelector(".answer");
  await shot("explanation-mobile");

  await browser.close();

  if (errors.length) {
    console.log("BROWSER ERRORS:");
    for (const error of errors) console.log(`- ${error}`);
  } else {
    console.log("No browser console or page errors.");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
