import { useEffect, useState } from "react";

import type { Api } from "../../../api";

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

function asReports(data: unknown): ReportRow[] {
  if (Array.isArray(data)) return data as ReportRow[];
  return [];
}

function csvCell(value: unknown): string {
  const text = value == null ? "" : String(value);
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function downloadCsv(report: ReportRow) {
  const columns = report.payload?.columns ?? [];
  const lines = [columns.join(",")];
  for (const row of report.payload?.rows ?? []) {
    lines.push(columns.map((column) => csvCell(row[column])).join(","));
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
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const result = await api.get<unknown>("/ops/reports");
    const rows = asReports(result.data);
    setReports(rows);
    setSelected((current) => current ?? rows[0]?.id ?? null);
  }

  useEffect(() => {
    let cancel = false;
    load().catch((reason: Error) => {
      if (!cancel) setError(reason.message);
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
      const rows = asReports(result.data);
      setReports(rows);
      setSelected(rows[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Report generation failed.");
    } finally {
      setBusy(false);
    }
  }

  const current = reports.find((report) => report.id === selected) ?? null;
  const columns = current?.payload?.columns ?? [];

  return (
    <section className="phase4-panel" aria-label="Reports">
      <div className="phase4-head">
        <div>
          <h3>Reports</h3>
          <p className="phase4-meta">Daily and monthly figures are SQL aggregates over the synthetic ledger.</p>
        </div>
        <button className="primary" type="button" onClick={generate} disabled={busy}>
          Generate reports
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {reports.length === 0 ? <p className="empty">No report snapshots yet.</p> : null}
      <div className="phase4-samples">
        {reports.map((report) => (
          <button
            key={report.id}
            className="ghost"
            type="button"
            onClick={() => setSelected(report.id)}
            aria-pressed={report.id === selected}
          >
            {report.reportKey} · {report.grain}
          </button>
        ))}
      </div>
      {current ? (
        <div>
          <p className="phase4-meta">
            {current.periodStart} to {current.periodEnd} · {current.rowCount} rows · {current.generatedBy}
          </p>
          <button className="ghost" type="button" onClick={() => downloadCsv(current)}>
            Download CSV
          </button>
          {current.payload?.totals ? (
            <p className="phase4-note">
              {Object.entries(current.payload.totals)
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ")}
            </p>
          ) : null}
          {columns.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {columns.map((column) => (
                      <th key={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(current.payload.rows ?? []).slice(0, 12).map((row, index) => (
                    <tr key={`${current.id}-${index}`}>
                      {columns.map((column) => (
                        <td key={column}>{String(row[column] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
