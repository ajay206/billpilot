export type Role = "customer" | "csr" | "ops";

export type SessionUser = {
  username: string;
  displayName: string;
  role: Role;
  customerNumber: string | null;
  csrCode: string | null;
  expiresAt: string;
  csrfToken: string;
};

export type DemoAccount = {
  username: string;
  displayName: string;
  role: Role;
  password: string;
  scope: string;
  demoOnly: boolean;
};

let csrfMemory = "";

export function rememberCsrf(token: string) {
  if (token) csrfMemory = token;
}

export function clearCsrf() {
  csrfMemory = "";
}

export function csrfToken(): string {
  if (csrfMemory) return csrfMemory;
  const match = document.cookie.match(/(?:^|; )bp_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

export function roleHome(role: Role): string {
  return `/${role}`;
}

export function roleLabel(role: Role): string {
  if (role === "csr") return "CSR";
  if (role === "ops") return "Ops";
  return "Customer";
}

export function screenFromPath(path: string): Role | null {
  const head = path.split("/").filter(Boolean)[0];
  if (head === "customer" || head === "csr" || head === "ops") return head;
  return null;
}

export const NAV: Record<Role, { id: string; label: string }[]> = {
  customer: [
    { id: "overview", label: "Overview" },
    { id: "bills", label: "Bills" },
    { id: "usage", label: "Usage" },
    { id: "payments", label: "Payments" },
    { id: "disputes", label: "Disputes" },
  ],
  csr: [{ id: "account", label: "Account 360" }],
  ops: [
    { id: "queue", label: "Approval queue" },
    { id: "failures", label: "Failures" },
    { id: "reports", label: "Reports" },
    { id: "findings", label: "Findings" },
    { id: "runs", label: "Agent runs" },
    { id: "audit", label: "Audit log" },
  ],
};

export function opsSectionFromPath(path: string): string {
  const parts = path.split("/").filter(Boolean);
  if (parts[0] !== "ops") return "queue";
  const id = parts[1] ?? "queue";
  return NAV.ops.some((item) => item.id === id) ? id : "queue";
}

export function opsPath(section: string): string {
  return section === "queue" ? "/ops" : `/ops/${section}`;
}

export function defaultSection(role: Role): string {
  return NAV[role][0].id;
}

export function sectionLabel(role: Role, section: string): string {
  return NAV[role].find((item) => item.id === section)?.label ?? section;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string };
    if (body.message) return body.message;
  } catch {
    /* not JSON */
  }
  return `Request failed (${response.status}).`;
}

export async function currentUser(): Promise<SessionUser | null> {
  const response = await fetch("/auth/me", { credentials: "same-origin" });
  if (response.status === 401) return null;
  if (!response.ok) return null;
  const body = (await response.json()) as SessionUser;
  rememberCsrf(body.csrfToken);
  return body;
}

export async function login(username: string, password: string): Promise<SessionUser> {
  const response = await fetch("/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = (await response.json()) as SessionUser;
  rememberCsrf(body.csrfToken);
  return body;
}

export async function logout(): Promise<void> {
  await fetch("/auth/logout", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken() },
  });
  clearCsrf();
}

export async function demoAccounts(): Promise<DemoAccount[]> {
  const response = await fetch("/auth/demo-accounts", { credentials: "same-origin" });
  if (!response.ok) return [];
  return (await response.json()) as DemoAccount[];
}
