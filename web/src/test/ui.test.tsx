import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Api } from "../api";
import { App } from "../App";
import { AnswerText, Placeholder, ProposalCard, StatusBadge } from "../components";
import { OpsDashboard } from "../views/OpsDashboard";

function ok(body: unknown, total: string | null = null): Response {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (total != null) headers.set("X-Total-Count", total);
  return new Response(JSON.stringify(body), { status: 200, headers });
}

describe("persona UI", () => {
  it("shows the demo-mode banner and switches to the ops placeholders", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.endsWith("/health")) {
          return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
        }
        if (url.includes("/ops/agentRuns") || url.includes("/ops/auditLog")) return ok([], "0");
        if (url.includes("customerBillDispute")) return ok([], "2");
        if (url.includes("billAdjustment")) return ok([], "0");
        if (url.includes("fraudFlag")) return ok([], "3");
        if (url.includes("billingAccount")) return ok([], "0");
        return ok([]);
      }),
    );
    render(<App />);
    expect(await screen.findByRole("status")).toHaveTextContent(/demo mode/i);
    expect(screen.getByRole("heading", { name: "Ask about this bill" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /ops/i }));
    expect(window.location.pathname).toBe("/ops");
    expect(screen.getByRole("heading", { name: "Approvals, runs, and the audit log" })).toBeInTheDocument();
    expect(screen.getByText(/no customer chat/i)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /failure dashboard, phase 4/i })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /reports, phase 4/i })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Unbars" }));
    expect(screen.getByText(/no unbar proposals/i)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /csr/i }));
    expect(window.location.pathname).toBe("/csr");
    expect(screen.getByRole("region", { name: /csr troubleshooting ai, phase 4/i })).toBeInTheDocument();
  });

  it("opens the ops view from /ops", async () => {
    window.history.pushState({}, "", "/ops");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.endsWith("/health")) {
          return ok({ status: "ok", demoMode: true, llmBackend: "fake", tracing: false });
        }
        return ok([], "0");
      }),
    );
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Approvals, runs, and the audit log" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /ops/i })).toHaveAttribute("aria-checked", "true");
  });

  it("renders a citation as a button and a credit as pending approval", async () => {
    const user = userEvent.setup();
    const onCite = vi.fn();
    render(
      <>
        <AnswerText text="Roaming is rated at the plan rate. [roaming.md § When roaming charges apply]" onCite={onCite} />
        <ProposalCard item={{ type: "credit", id: "adj-1", status: "pending_approval", amount: "18.00" }} />
        <StatusBadge status="pending_approval" />
      </>,
    );
    await user.click(screen.getByRole("button", { name: /roaming.md/i }));
    expect(onCite).toHaveBeenCalledWith("roaming.md", "When roaming charges apply");
    expect(screen.getAllByText("Pending approval").length).toBeGreaterThan(0);
    expect(screen.getByText("Status: pending_approval")).toBeInTheDocument();
    expect(screen.getByText("₹18.00")).toBeInTheDocument();
  });

  it("approves a credit through the existing endpoint", async () => {
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
        if (path.includes("billAdjustment")) return { data: pending as T, total: 1 };
        return { data: [] as T, total: 0 };
      },
      async post<T>(path: string, body: unknown) {
        posts.push({ path, body });
        return { data: applied as T, total: null };
      },
    };
    render(<OpsDashboard api={api} />);
    await user.click(await screen.findByRole("button", { name: "Approve" }));
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
