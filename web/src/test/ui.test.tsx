import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Api } from "../api";
import { App } from "../App";
import { AnswerText, DataTable, Placeholder, ProposalCard, StatusBadge } from "../components";
import { OpsDashboard } from "../views/OpsDashboard";

function ok(body: unknown, total: string | null = null): Response {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (total != null) headers.set("X-Total-Count", total);
  return new Response(JSON.stringify(body), { status: 200, headers });
}

const demo = [
  {
    username: "priya.sharma",
    displayName: "Priya Sharma",
    role: "customer",
    password: "demo-priya",
    scope: "CUST-000001 only",
    demoOnly: true,
  },
  {
    username: "ananya.rao",
    displayName: "Ananya Rao",
    role: "csr",
    password: "demo-ananya",
    scope: "Accounts assigned to CSR-A",
    demoOnly: true,
  },
  {
    username: "meera.kapoor",
    displayName: "Meera Kapoor",
    role: "ops",
    password: "demo-meera",
    scope: "All accounts, approvals, and audit",
    demoOnly: true,
  },
];

function session(role: "customer" | "csr" | "ops", name: string) {
  return {
    username: name.toLowerCase().replace(" ", "."),
    displayName: name,
    role,
    customerNumber: role === "customer" ? "CUST-000001" : null,
    csrCode: role === "csr" ? "CSR-A" : null,
    expiresAt: "2026-10-05T00:00:00Z",
    csrfToken: "csrf-test",
  };
}

const account = {
  id: "acc-1",
  name: "ACC-000001",
  customerNumber: "CUST-000001",
  state: "active",
  treatment: null,
  exemption: null,
  relatedParty: [{ id: "c1", role: "customer", name: "Asha Rao" }],
};

function installFetch(handler: (url: string, init?: RequestInit) => Response | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const hit = handler(url, init);
      if (hit) return hit;
      if (url.includes("/ops/agentRuns") || url.includes("/ops/auditLog")) return ok([], "0");
      if (url.includes("/billingAccount?") || url.endsWith("/billingAccount")) return ok([account], "1");
      return ok([], "0");
    }),
  );
}

describe("sign-in and role routing", () => {
  it("shows demo accounts and routes a customer away from other roles", async () => {
    const user = userEvent.setup();
    installFetch((url) => {
      if (url.endsWith("/auth/me")) return new Response("{}", { status: 401 });
      if (url.endsWith("/auth/demo-accounts")) return ok(demo);
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
      if (url.endsWith("/auth/login")) return ok(session("customer", "Priya Sharma"));
      return null;
    });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/demo mode/i);
    expect(await screen.findByRole("button", { name: /sign in as priya sharma/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Demo accounts" })).toHaveTextContent("demo-priya");
    await user.click(screen.getByRole("button", { name: /sign in as priya sharma/i }));
    expect(await screen.findByRole("heading", { name: "Your account" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/customer");
    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Approval queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Account 360" })).not.toBeInTheDocument();
    expect(screen.getByText("Demo - synthetic data")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /priya sharma/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bills" }));
    expect(screen.getByRole("heading", { name: "Bills" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Bills");
  });

  it("hides customer navigation for a CSR and shows account search", async () => {
    installFetch((url) => {
      if (url.endsWith("/auth/me")) return ok(session("csr", "Ananya Rao"));
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
      return null;
    });
    window.history.pushState({}, "", "/csr");
    render(<App />);
    expect(await screen.findByLabelText("Search accounts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Account 360" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Overview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approval queue" })).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: /csr troubleshooting ai, phase 4/i })).toBeInTheDocument();
    expect(screen.getByText(/search for an account/i)).toBeInTheDocument();
  });

  it("refuses a customer who opens the ops path", async () => {
    installFetch((url) => {
      if (url.endsWith("/auth/me")) return ok(session("customer", "Priya Sharma"));
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: false, llmBackend: "api", tracing: false });
      return null;
    });
    window.history.pushState({}, "", "/ops");
    render(<App />);
    expect(await screen.findByRole("alert", { name: "Access denied" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Control tower" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approval queue" })).not.toBeInTheDocument();
  });

  it("opens the ops control tower and keeps phase 4 placeholders", async () => {
    const user = userEvent.setup();
    installFetch((url) => {
      if (url.endsWith("/auth/me")) return ok(session("ops", "Meera Kapoor"));
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
      if (url.includes("customerBillDispute")) return ok([], "2");
      if (url.includes("fraudFlag")) return ok([], "3");
      return null;
    });
    window.history.pushState({}, "", "/ops");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Control tower" })).toBeInTheDocument();
    expect(screen.getByText(/no customer chat/i)).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: /failure dashboard, phase 4/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /reports, phase 4/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Overview" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Unbars" }));
    expect(screen.getByText(/no unbar proposals/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Audit log" }));
    expect(screen.getByRole("heading", { name: "Audit log" })).toBeInTheDocument();
  });

  it("says when a previous session has expired", async () => {
    document.cookie = "bp_csrf=stale";
    installFetch((url) => {
      if (url.endsWith("/auth/me")) return new Response("{}", { status: 401 });
      if (url.endsWith("/auth/demo-accounts")) return ok([]);
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
      return null;
    });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/session expired/i);
  });

  it("logs out back to the sign-in screen", async () => {
    const user = userEvent.setup();
    installFetch((url, init) => {
      if (url.endsWith("/auth/me")) return ok(session("ops", "Meera Kapoor"));
      if (url.endsWith("/auth/logout") && init?.method === "POST") return new Response(null, { status: 204 });
      if (url.endsWith("/auth/demo-accounts")) return ok(demo);
      if (url.endsWith("/health")) return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
      return null;
    });
    window.history.pushState({}, "", "/ops");
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /meera kapoor/i }));
    await user.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("shared controls", () => {
  it("renders a citation as a button and a credit as pending approval", async () => {
    const user = userEvent.setup();
    const onCite = vi.fn();
    render(
      <>
        <AnswerText
          text="Roaming is rated at the plan rate. [roaming.md § When roaming charges apply] [roaming.md § When roaming charges apply]"
          onCite={onCite}
        />
        <ProposalCard item={{ type: "credit", id: "adj-1", status: "pending_approval", amount: "18.00" }} />
        <StatusBadge status="pending_approval" />
      </>,
    );
    await user.click(screen.getByRole("button", { name: /roaming.md/i }));
    expect(onCite).toHaveBeenCalledWith("roaming.md", "When roaming charges apply");
    expect(screen.getAllByRole("button", { name: /roaming.md/i })).toHaveLength(1);
    expect(screen.getAllByText("Pending approval").length).toBeGreaterThan(0);
    expect(screen.getByText("Status: pending_approval")).toBeInTheDocument();
    expect(screen.getByText("₹18.00")).toBeInTheDocument();
  });

  it("sorts, filters, and pages a table", async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 10 }, (_, index) => ({
      id: `row-${index}`,
      name: `Item ${String.fromCharCode(65 + index)}`,
    }));
    render(
      <DataTable
        label="Items"
        rows={rows}
        empty="Nothing here."
        pageSize={4}
        columns={[{ key: "name", label: "Name", render: (row) => row.name, value: (row) => row.name }]}
      />,
    );
    expect(screen.getByText("Item A")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(screen.getByRole("columnheader", { name: /name/i })).toHaveAttribute("aria-sort", "ascending");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Filter Items"), "Item A");
    expect(screen.getByText("Item A")).toBeInTheDocument();
    expect(screen.queryByText("Item J")).not.toBeInTheDocument();
  });

  it("shows an empty table state", () => {
    render(<DataTable label="Items" rows={[]} empty="Nothing here." columns={[{ key: "name", label: "Name", render: (row: { id: string }) => row.id }]} />);
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
  });

  it("approves a credit only after confirmation", async () => {
    const user = userEvent.setup();
    const posts: { path: string; body: unknown }[] = [];
    const pending = [
      {
        id: "adj-9",
        adjustmentType: "credit",
        status: "pending_approval",
        reason: "Duplicate line",
        amount: { unit: "INR", value: "10.00" },
        creationDate: "2026-10-01T00:00:00Z",
        proposedBy: "csr:CSR-A",
        billingAccount: { id: "acc-1" },
      },
    ];
    const applied = { ...pending[0], status: "applied", decidedBy: "ops" };
    const api: Api = {
      async get<T>(path: string) {
        if (path.includes("billAdjustment") && posts.length === 0) return { data: pending as T, total: 1 };
        return { data: [] as T, total: 0 };
      },
      async post<T>(path: string, body: unknown) {
        posts.push({ path, body });
        return { data: applied as T, total: null };
      },
    };
    render(<OpsDashboard api={api} section="queue" focus={null} />);
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    expect(posts).toHaveLength(0);
    const dialog = screen.getByRole("dialog", { name: /approve this credit/i });
    await user.click(within(dialog).getByRole("button", { name: "Confirm approval" }));
    expect(posts[0]?.path).toBe("/tmf-api/customerBillManagement/v4/billAdjustment/adj-9/approve");
    expect(posts[0]?.body).toMatchObject({ decision: "approve" });
    expect(await screen.findByText(/approved by ops/i)).toBeInTheDocument();
  });

  it("marks phase 4 panels as placeholders", () => {
    function Harness() {
      const [open, setOpen] = useState(true);
      return open ? (
        <Placeholder phase="Phase 4" title="Failure dashboard">
          Not built yet.
        </Placeholder>
      ) : (
        <button type="button" onClick={() => setOpen(true)}>
          show
        </button>
      );
    }
    render(<Harness />);
    expect(screen.getByRole("region", { name: /failure dashboard, phase 4/i })).toHaveTextContent("Not built yet.");
  });
});
