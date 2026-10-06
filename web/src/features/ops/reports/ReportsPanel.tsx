import { useEffect, useState } from "react";

import type { Api } from "../../../api";
import { Metric, Skeleton } from "../../../components";
import { formatINR, formatIST } from "../../../format";

type ReportRow = {
  id: string;
  reportKey: string;
  grain: string;
  periodStart: string;
  periodEnd: string;
  rowCount: number;
  generatedBy: string;
  payload: {
    columns?: string[];
    rows?: Record<string, string | number>[];
    totals?: Record<string, string | number>;
  };
};

const REPORTS: { id: string; label: string }[] = [
  { id: "billing", label: "Billing summary" },
  { id: "collections", label: "Collections and treatment" },
  { id: "disputes", label: "Disputes and credits" },
  { id: "payments", label: "Payments" },
  { id: "agent", label: "Agent usage and cost" },
];

const HEADERS: Record<string, string> = {
  issue_date: "Issue date",
  invoice_count: "Invoices",
  subtotal: "Subtotal",
  tax: "GST",
  total: "Total",
  amount_due: "Amount due",
  section: "Section",
  stage: "Stage",
  status: "Status",
  accounts: "Accounts",
  event_type: "Event",
  events: "Events",
  disputes: "Disputes",
  adjustment_type: "Adjustment",
  adjustments: "Adjustments",
  amount: "Amount",
  payments: "Payments",
  attempts: "Attempts",
  persona: "Persona",
  turns: "Turns",
  prompt_tokens: "Prompt tokens",
  completion_tokens: "Completion tokens",
  estimated_cost_usd: "Estimated cost",
};

const MONEY = new Set(["subtotal", "tax", "total", "amount_due", "amount"]);

function asReports(data: unknown): ReportRow[] {
  if (Array.isArray(data)) return data as ReportRow[];
  return [];
}

function header(key: string): string {
  return HEADERS[key] ?? key.replaceAll("_", " ");
}

function cell(column: string, value: unknown): string {
  if (value == null || value === "") return "—";
  if (MONEY.has(column)) return formatINR(String(value));
  if (column === "estimated_cost_usd") return `$${value}`;
  if (column.endsWith("_date") || column === "issue_date") return formatIST(String(value));
  return String(value);
}

function kpi(key: string, value: string | number): string {
  if (MONEY.has(key) || key.endsWith("_amount")) return formatINR(String(value));
  if (key === "estimated_cost_usd") return `$${value}`;
  return String(value);
}

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function downloadCsv(report: ReportRow) {
  const columns = report.payload?.columns ?? [];
  const lines = [columns.map(header).join(",")];
  for (const row of report.payload?.rows ?? []) {
    lines.push(columns.map((column) => csvCell(cell(column, row[column]))).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${report.reportKey}-${report.grain}-${report.periodStart}.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ReportsPanel({ api }: { api: Api }) {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [grain, setGrain] = useState<"daily" | "monthly">("daily");
  const [reportKey, setReportKey] = useState("billing");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    const result = await api.get<unknown>("/ops/reports");
    setReports(asReports(result.data));
    setLoaded(true);
  }

  useEffect(() => {
    let cancel = false;
    load()
      .then(() => {
        if (!cancel) setLoaded(true);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [api]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<unknown>("/ops/reports/generate", {});
      setReports(asReports(result.data));
      setLoaded(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Report generation failed.");
    } finally {
      setBusy(false);
    }
  }

  const title = REPORTS.find((item) => item.id === reportKey)?.label ?? "Report";
  const current = reports.find((report) => report.reportKey === reportKey && report.grain === grain) ?? null;
  const columns = current?.payload?.columns ?? [];
  const totals = current?.payload?.totals ?? {};

  return (
    <section className="panel" aria-label="Reports">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Reports</h1>
          <p className="muted">Daily and monthly figures are SQL aggregates over the synthetic ledger.</p>
        </div>
        <button className="primary" type="button" onClick={generate} disabled={busy}>
          {busy ? "Generating…" : "Generate reports"}
        </button>
      </header>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {loading ? <Skeleton rows={4} label="Loading reports" /> : null}
      {!loading && loaded && reports.length === 0 ? (
        <p className="empty">No report snapshots yet. Generate reports for the latest invoice day and that month.</p>
      ) : null}
      {!loading && reports.length > 0 ? (
        <>
          <div className="report-picker">
            <div className="tabs" role="tablist" aria-label="Report period">
              {(["daily", "monthly"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  role="tab"
                  aria-selected={grain === item}
                  className={grain === item ? "tab selected" : "tab"}
                  onClick={() => setGrain(item)}
                >
                  {item === "daily" ? "Daily" : "Monthly"}
                </button>
              ))}
            </div>
            <label className="field">
              Report
              <select value={reportKey} aria-label="Report" onChange={(event) => setReportKey(event.target.value)}>
                {REPORTS.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <h2>
            {title}, {grain}
          </h2>
          {!current ? <p className="empty">This report has not been generated for the {grain} window.</p> : null}
          {current ? (
            <>
              <p className="muted">
                {formatIST(current.periodStart)} to {formatIST(current.periodEnd)} · {current.rowCount}{" "}
                {current.rowCount === 1 ? "row" : "rows"} · {current.generatedBy}
              </p>
              <div className="metrics">
                {Object.entries(totals).map(([key, value]) => (
                  <Metric key={key} label={header(key)} value={kpi(key, value)} />
                ))}
              </div>
              <button className="ghost" type="button" onClick={() => downloadCsv(current)}>
                Download CSV
              </button>
              {columns.length === 0 ? <p className="empty">This snapshot has no columns.</p> : null}
              {columns.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {columns.map((column) => (
                          <th key={column}>{header(column)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(current.payload.rows ?? []).length === 0 ? (
                        <tr>
                          <td colSpan={columns.length}>No rows in this window.</td>
                        </tr>
                      ) : null}
                      {(current.payload.rows ?? []).slice(0, 12).map((row, index) => (
                        <tr key={`${current.id}-${index}`}>
                          {columns.map((column) => (
                            <td key={column}>{cell(column, row[column])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
