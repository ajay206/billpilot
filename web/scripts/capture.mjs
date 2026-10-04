/**
 * Screenshot the login page and each role's main screen against a running BillPilot.
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

await page.goto(`${base}/login`, { waitUntil: "networkidle" });
await page.getByRole("heading", { name: "Sign in" }).waitFor();
await page.getByRole("button", { name: /sign in as priya sharma/i }).waitFor();

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
      reason: `Duplicate caller tune charge on ${bill.billNo}.`,
    }),
  });
  if (!proposed.ok) {
    throw new Error(`Could not propose a credit (${proposed.status}).`);
  }
});

await mkdir(outDir, { recursive: true });
await page.screenshot({ path: path.join(outDir, "login.png"), fullPage: true });

await page.getByRole("button", { name: /sign in as priya sharma/i }).click();
await page.getByRole("heading", { name: "Your account" }).waitFor();
await page.getByText("Pending approval").first().waitFor();
await page.getByRole("button", { name: /roaming rules/i }).click();
await page.getByRole("button", { name: /roaming\.md/i }).first().waitFor();
await page.screenshot({ path: path.join(outDir, "customer.png"), fullPage: true });

await page.getByRole("button", { name: /priya sharma/i }).click();
await page.getByRole("menuitem", { name: "Log out" }).click();
await page.getByRole("button", { name: /sign in as ananya rao/i }).click();
await page.getByLabel("Search accounts").waitFor();
await page.getByLabel("Search accounts").fill("CUST-000001");
await page.getByRole("option", { name: /CUST-000001/ }).click();
await page.getByLabel("Ask the copilot").fill("Explain the latest bill line by line against the tariff.");
await page.getByRole("button", { name: "Ask" }).click();
await page.getByRole("button", { name: /tool call/i }).waitFor();
await page.screenshot({ path: path.join(outDir, "csr.png"), fullPage: true });

const trouble = page.getByRole("region", { name: /csr troubleshooting/i });
await trouble.getByLabel("Error or symptom").fill(
  "Troubleshooting: a payment failed with token PAYMENT_DECLINED. Follow the failed payment runbook.",
);
await trouble.getByRole("button", { name: "Run troubleshooting" }).click();
await trouble.getByText(/failed payment/i).waitFor();
await trouble.screenshot({ path: path.join(outDir, "troubleshoot.png") });

await page.getByRole("button", { name: /ananya rao/i }).click();
await page.getByRole("menuitem", { name: "Log out" }).click();
await page.getByRole("button", { name: /sign in as meera kapoor/i }).click();
await page.getByRole("button", { name: "Approve" }).first().waitFor();
const failures = page.getByRole("region", { name: /failure dashboard/i });
await failures.getByRole("button", { name: "Simulate failures" }).click();
await failures.getByText(/payment failed|dead-letter|bill run/i).first().waitFor();
await failures.screenshot({ path: path.join(outDir, "failures.png") });

const reports = page.getByRole("region", { name: /^reports$/i });
await reports.getByRole("button", { name: "Generate reports" }).click();
await reports.getByRole("button", { name: "billing · daily" }).waitFor();
await reports.screenshot({ path: path.join(outDir, "reports.png") });

const findings = page.getByRole("region", { name: /fraud and revenue findings/i });
await findings.getByRole("button", { name: "Run checks" }).click();
await findings.getByRole("button", { name: "Open case" }).first().waitFor();
await findings.screenshot({ path: path.join(outDir, "findings.png") });

await page.screenshot({ path: path.join(outDir, "ops.png"), fullPage: true });

await browser.close();
console.log(`Wrote screenshots to ${outDir}`);
