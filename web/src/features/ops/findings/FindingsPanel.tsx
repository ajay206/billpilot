import { useEffect, useMemo, useState } from "react";

import type { Api } from "../../../api";
import { BarChart, DataTable, SeverityBadge, Skeleton, StatusBadge } from "../../../components";
import { formatINR, formatIST } from "../../../format";
import type { Account } from "../../../types";

type EvidenceField = { label: string; value: string | number; kind: string };

type Finding = {
  id: string;
  name: string;
  detector: string;
  anomalyType: string;
  family: string;
  severity: string;
  status: string;
  summary: string;
  accountId: string;
  holderName: string | null;
  customerNumber: string | null;
  evidence: Record<string, unknown>;
  evidenceFields: EvidenceField[];
  ticketNumber: string | null;
  ticketStatus: string | null;
  adjustmentStatus: string | null;
  adjustmentAmount: string | null;
};

const FAMILIES: { id: string; label: string }[] = [
  { id: "fraud", label: "Fraud" },
  { id: "revenue", label: "Revenue" },
  { id: "payments", label: "Payments" },
  { id: "treatment", label: "Treatment" },
  { id: "entitlement", label: "Entitlements" },
];

const SEVERITIES = ["critical", "high", "medium", "low"];

function asFindings(data: unknown): Finding[] {
  const rows = Array.isArray(data)
    ? data
    : data && typeof data === "object" && Array.isArray((data as { rows?: unknown }).rows)
      ? (data as { rows: Finding[] }).rows
      : [];
  return rows.map((row) => ({
    ...row,
    evidenceFields: Array.isArray(row.evidenceFields) ? row.evidenceFields : [],
    holderName: row.holderName ?? null,
    customerNumber: row.customerNumber ?? null,
    ticketNumber: row.ticketNumber ?? null,
    ticketStatus: row.ticketStatus ?? null,
    adjustmentStatus: row.adjustmentStatus ?? null,
    adjustmentAmount: row.adjustmentAmount ?? null,
  }));
}

function hasAmount(evidence: Record<string, unknown>): boolean {
  const raw = evidence.pre_tax_amount ?? evidence.preTaxAmount;
  if (raw == null || raw === "") return false;
  const amount = Number(raw);
  return Number.isFinite(amount) && amount > 0;
}

function fieldText(field: EvidenceField): string {
  if (field.kind === "money") return formatINR(String(field.value));
  if (field.kind === "date") return formatIST(String(field.value));
  return String(field.value);
}

function titleCase(value: string): string {
  return value.replaceAll("_", " ");
}

function replaceFinding(current: Finding[], next: Finding): Finding[] {
  const [normalized] = asFindings([next]);
  if (!normalized) return current;
  return current.map((row) => (row.id === normalized.id ? normalized : row));
}

export function FindingsPanel({
  api,
  onOpenAccount,
}: {
  api: Api;
  onOpenAccount?: (account: Account) => void;
}) {
  const [rows, setRows] = useState<Finding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [family, setFamily] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [detector, setDetector] = useState("all");

  async function load() {
    const result = await api.get<unknown>("/ops/findings");
    setRows(asFindings(result.data));
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

  async function openAccount(accountId: string) {
    setError(null);
    try {
      const result = await api.get<Account>(`/tmf-api/accountManagement/v4/billingAccount/${accountId}`);
      onOpenAccount?.(result.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account lookup failed.");
    }
  }

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const result = await api.post<unknown>("/ops/assurance/run", {});
      setRows(asFindings(result.data));
      setLoaded(true);
      setNotice("Checks finished. Figures come from the ledger, not from a model.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The checks failed.");
    } finally {
      setRunning(false);
    }
  }

  async function openCase(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const result = await api.post<{ ticketNumber: string; duplicate: boolean; finding: Finding }>(
        `/ops/findings/${id}/case`,
        {},
      );
      setRows((current) => replaceFinding(current, result.data.finding));
      setNotice(
        result.data.duplicate
          ? `Case ${result.data.ticketNumber} is already open. No second ticket was created.`
          : `Opened case ${result.data.ticketNumber}. The bill did not change.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open a case.");
    } finally {
      setBusyId(null);
    }
  }

  async function propose(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const result = await api.post<{ status: string; amount: string; duplicate: boolean; finding: Finding }>(
        `/ops/findings/${id}/adjustment`,
        {},
      );
      setRows((current) => replaceFinding(current, result.data.finding));
      setNotice(
        result.data.duplicate
          ? `Credit ${formatINR(result.data.amount)} is already ${result.data.status.replaceAll("_", " ")}.`
          : `Credit ${formatINR(result.data.amount)} is ${result.data.status.replaceAll("_", " ")}. You proposed it, so you cannot approve it.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not propose a credit.");
    } finally {
      setBusyId(null);
    }
  }

  const familyCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(row.family, (counts.get(row.family) ?? 0) + 1);
    return counts;
  }, [rows]);

  const FAMILY_COLORS: Record<string, string> = {
    fraud: "#8d2f2f",
    revenue: "#0f5c56",
    payments: "#3b6fa0",
    treatment: "#7a4e0d",
    entitlement: "#14663d",
  };

  const familyBars = useMemo(
    () =>
      FAMILIES.map((f) => ({
        label: f.label,
        value: familyCounts.get(f.id) ?? 0,
        color: FAMILY_COLORS[f.id] ?? "var(--accent)",
      })).filter((d) => d.value > 0),
    [familyCounts],
  );

  const visible = rows.filter((row) => {
    if (family !== "all" && row.family !== family) return false;
    if (severity !== "all" && row.severity !== severity) return false;
    if (detector !== "all" && row.detector !== detector) return false;
    return true;
  });

  const detectors = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (family !== "all" && row.family !== family) continue;
      counts.set(row.detector, (counts.get(row.detector) ?? 0) + 1);
    }
    return [...counts.entries()].sort((left, right) => left[0].localeCompare(right[0]));
  }, [family, rows]);

  return (
    <section className="panel" aria-label="Fraud and revenue findings">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Revenue assurance</p>
          <h1>Findings</h1>
          <p className="muted">Rule checks over the synthetic ledger. Evidence is the query row, not a model judgement.</p>
        </div>
        <button className="primary" type="button" onClick={run} disabled={running}>
          {running ? "Running checks…" : "Run checks"}
        </button>
      </header>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status">
          {notice}
        </p>
      ) : null}
      {loading ? <Skeleton rows={4} label="Loading findings" /> : null}
      {!loading && loaded && rows.length === 0 ? (
        <p className="empty">No findings yet. Run checks to score the synthetic ledger.</p>
      ) : null}
      {!loading && familyBars.length > 0 ? (
        <div className="chart-card" style={{ marginTop: "var(--space-4)" }}>
          <h3>Findings by category</h3>
          <BarChart data={familyBars} height={140} />
        </div>
      ) : null}
      {!loading && rows.length > 0 ? (
        <>
          <div className="tabs" role="tablist" aria-label="Finding category">
            <button type="button" role="tab" aria-selected={family === "all"} className={family === "all" ? "tab selected" : "tab"} onClick={() => setFamily("all")}>
              All {rows.length}
            </button>
            {FAMILIES.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={family === item.id}
                className={family === item.id ? "tab selected" : "tab"}
                onClick={() => {
                  setFamily(item.id);
                  setDetector("all");
                }}
              >
                {item.label} {familyCounts.get(item.id) ?? 0}
              </button>
            ))}
          </div>
          <div className="tabs" role="tablist" aria-label="Finding severity">
            <button type="button" role="tab" aria-selected={severity === "all"} className={severity === "all" ? "tab selected" : "tab"} onClick={() => setSeverity("all")}>
              Any severity
            </button>
            {SEVERITIES.map((item) => (
              <button
                key={item}
                type="button"
                role="tab"
                aria-selected={severity === item}
                className={severity === item ? "tab selected" : "tab"}
                onClick={() => setSeverity(item)}
              >
                {item} {rows.filter((row) => row.severity === item && (family === "all" || row.family === family)).length}
              </button>
            ))}
          </div>
          <label className="field detector-field">
            Detector
            <select value={detector} onChange={(event) => setDetector(event.target.value)}>
              <option value="all">All detectors ({rows.filter((row) => family === "all" || row.family === family).length})</option>
              {detectors.map(([id, count]) => (
                <option key={id} value={id}>
                  {titleCase(id)} ({count})
                </option>
              ))}
            </select>
          </label>
          <DataTable
            label="Findings"
            rows={visible}
            empty="No findings match these filters."
            pageSize={8}
            columns={[
              { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} />, value: (row) => row.severity },
              { key: "name", label: "Detector", render: (row) => row.name, value: (row) => row.name },
              {
                key: "account",
                label: "Account",
                render: (row) => (
                  <button type="button" className="text-button account-link" onClick={() => void openAccount(row.accountId)}>
                    <span>{row.holderName || "Open account"}</span>
                    <span className="muted">{row.customerNumber}</span>
                  </button>
                ),
                value: (row) => `${row.holderName ?? ""} ${row.customerNumber ?? ""}`,
              },
              {
                key: "evidence",
                label: "Evidence",
                render: (row) =>
                  row.evidenceFields.length === 0 ? (
                    <span className="muted">No extra evidence.</span>
                  ) : (
                    <dl className="evidence-fields">
                      {row.evidenceFields.map((field) => (
                        <div key={field.label}>
                          <dt>{field.label}</dt>
                          <dd>{fieldText(field)}</dd>
                        </div>
                      ))}
                    </dl>
                  ),
                value: (row) => row.evidenceFields.map((field) => fieldText(field)).join(" "),
              },
              {
                key: "state",
                label: "State",
                render: (row) => (
                  <div className="row-actions">
                    <StatusBadge status={row.status} />
                    {row.ticketNumber ? (
                      <p className="muted">
                        Case {row.ticketNumber} · {row.ticketStatus}
                      </p>
                    ) : (
                      <button className="primary" type="button" onClick={() => void openCase(row.id)} disabled={busyId === row.id}>
                        {busyId === row.id ? "Opening…" : "Open case"}
                      </button>
                    )}
                    {row.adjustmentStatus ? (
                      <p>
                        Credit {formatINR(row.adjustmentAmount)} · <StatusBadge status={row.adjustmentStatus} />
                      </p>
                    ) : hasAmount(row.evidence) ? (
                      <button className="ghost" type="button" onClick={() => void propose(row.id)} disabled={busyId === row.id}>
                        {busyId === row.id ? "Proposing…" : "Propose adjustment"}
                      </button>
                    ) : (
                      <p className="muted">No credit amount on this finding, so an adjustment is not offered.</p>
                    )}
                  </div>
                ),
                value: (row) => row.status,
              },
            ]}
          />
        </>
      ) : null}
    </section>
  );
}
