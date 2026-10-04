/**
 * Screenshot the three persona views against a running BillPilot.
 * Usage: node scripts/capture.mjs [baseUrl]
 * The API must already be up, seeded, and on the fake model.
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const base = process.argv[2] || "http://127.0.0.1:8000";
const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/screenshots");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(90000);

await page.goto(base, { waitUntil: "networkidle" });
await page.getByRole("status").waitFor();

await page.evaluate(async () => {
  const headers = { "X-API-Key": "dev-customer-key" };
  const accounts = await fetch("/tmf-api/accountManagement/v4/billingAccount?limit=1", { headers }).then((response) =>
    response.json(),
  );
  const account = accounts[0];
  if (!account) return;
  const bills = await fetch(
    `/tmf-api/customerBillManagement/v4/customerBill?billingAccount.id=${account.id}&limit=1`,
    { headers },
  ).then((response) => response.json());
  const bill = bills[0];
  if (!bill) return;
  const proposed = await fetch("/tmf-api/customerBillManagement/v4/billAdjustment", {
    method: "POST",
    headers: { "X-API-Key": "dev-csr-key", "Content-Type": "application/json" },
    body: JSON.stringify({
      billingAccount: { id: account.id },
      customerBill: { id: bill.id },
      adjustmentType: "credit",
      amount: { unit: "INR", value: "10.00" },
      reason: "Screenshot demo: proposed credit, still pending approval.",
    }),
  });
  if (!proposed.ok) {
    throw new Error(`Could not propose a credit (${proposed.status}).`);
  }
});

await page.reload({ waitUntil: "networkidle" });
await page.getByText("Pending approval").first().waitFor();
await page.getByRole("button", { name: /roaming rules/i }).click();
await page.getByRole("button", { name: /roaming\.md/i }).first().waitFor();
await mkdir(outDir, { recursive: true });
await page.screenshot({ path: path.join(outDir, "customer.png"), fullPage: true });

await page.getByRole("radio", { name: /csr/i }).click();
await page.getByLabel("Search accounts").fill("CUST-000001");
await page.getByRole("button", { name: /CUST-000001/ }).click();
await page.getByLabel("Ask the copilot").fill("Explain the latest bill line by line against the tariff.");
await page.getByRole("button", { name: "Ask" }).click();
await page.getByRole("button", { name: /tool call/i }).waitFor();
await page.screenshot({ path: path.join(outDir, "csr.png"), fullPage: true });

await page.getByRole("radio", { name: /ops/i }).click();
await page.getByRole("button", { name: "Approve" }).first().waitFor();
await page.getByRole("region", { name: /failure dashboard, phase 4/i }).waitFor();
await page.screenshot({ path: path.join(outDir, "ops.png"), fullPage: true });

await browser.close();
console.log(`Wrote screenshots to ${outDir}`);
