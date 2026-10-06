import { useEffect, useState } from "react";

import { ApiError } from "../../api";
import type { Api } from "../../api";
import { DataTable } from "../../components";
import { formatINR } from "../../format";

type Summary = {
  source?: { records?: number; balanceTotal?: string; customers?: number; services?: number; balances?: number };
  target?: { customers?: number; services?: number; balances?: number; balanceTotal?: string };
  acceptedBalanceTotal?: string;
  balanceMatched?: boolean;
  rejected?: number;
  skipped?: number;
  writes?: number;
  idempotent?: boolean;
  byReason?: Record<string, number>;
  mappingSuggestions?: Suggestion[];
  restored?: boolean;
  alreadyRolledBack?: boolean;
};

type Suggestion = {
  legacyCode: string;
  legacyName?: string | null;
  targetCode: string | null;
  rationale: string;
  recordCount: number;
};

type BatchRow = {
  id: string;
  batchCode: string;
  status: string;
  sourceName: string;
  mappingVersion: string;
  balanceMatched: boolean | null;
  summary: Summary;
};

type RecordRow = {
  id: string;
  sourceKey: string;
  recordKind: string;
  status: string;
  reason: string | null;
  legacyPlan: string | null;
  targetPlan: string | null;
  msisdn: string | null;
  sourceBalance: string | null;
};

type BatchDetail = BatchRow & {
  records: RecordRow[];
  mappingSuggestions: Suggestion[];
  csv: string;
  signedOffBy: string | null;
};

export function MigrationDesk({ api }: { api: Api }) {
  const [batches, setBatches] = useState<BatchRow[]>([]);
  const [detail, setDetail] = useState<BatchDetail | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh(selectId?: string) {
    const listed = await api.get<BatchRow[]>("/ops/migration/batches?limit=20");
    setBatches(listed.data);
    const id = selectId || detail?.id;
    if (id) {
      const next = await api.get<BatchDetail>(`/ops/migration/batches/${id}`);
      setDetail(next.data);
    }
  }

  useEffect(() => {
    let cancel = false;
    api
      .get<BatchRow[]>("/ops/migration/batches?limit=20")
      .then((result) => {
        if (!cancel) setBatches(result.data);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    return () => {
      cancel = true;
    };
  }, [api]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "The migration request failed.");
    } finally {
      setBusy(false);
    }
  }

  function remember(body: BatchDetail, message: string) {
    setDetail(body);
    setNotice(message);
    return refresh(body.id);
  }

  async function useSample() {
    await run(async () => {
      const created = await api.post<BatchDetail>("/ops/migration/batches", { source: "sample" });
      await remember(created.data, `Loaded ${created.data.batchCode}. Nothing was written to the ledger.`);
    });
  }

  async function upload(file: File) {
    const text = await file.text();
    const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : "json";
    await run(async () => {
      const created = await api.post<BatchDetail>("/ops/migration/batches", {
        source: format,
        name: file.name,
        body: text,
      });
      await remember(created.data, `Loaded ${file.name}. Review the dry run before sign-off.`);
    });
  }

  async function act(path: string, body: unknown, message: string) {
    if (!detail) return;
    await run(async () => {
      const result = await api.post<BatchDetail>(`/ops/migration/batches/${detail.id}/${path}`, body);
      await remember(result.data, message);
    });
  }

  function download() {
    if (!detail?.csv) return;
    const blob = new Blob([detail.csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${detail.batchCode}-reconciliation.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const summary = detail?.summary;
  const suggestions = detail?.mappingSuggestions || summary?.mappingSuggestions || [];
  const status = detail?.status;

  return (
    <section className="phase5" aria-label="Migration">
      <p className="eyebrow">Migration</p>
      <h3>Migration desk</h3>
      <p className="muted">
        Ops only. Load a synthetic legacy file, dry-run it, approve the plan mapping, then commit. A second commit does
        not duplicate rows. Rollback restores the ledger. The APIs stay up while the batch runs in one transaction.
      </p>
      <div className="phase5-actions">
        <button type="button" className="primary" disabled={busy} onClick={() => void useSample()}>
          Use synthetic sample
        </button>
        <label className="ghost file-label">
          Upload CSV or JSON
          <input
            type="file"
            accept=".csv,.json,text/csv,application/json"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) void upload(file);
            }}
          />
        </label>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="notice">{notice}</p> : null}
      {batches.length ? (
        <ul className="batch-list">
          {batches.map((batch) => (
            <li key={batch.id}>
              <button
                type="button"
                className={detail?.id === batch.id ? "account selected" : "account"}
                onClick={() =>
                  void run(async () => {
                    const next = await api.get<BatchDetail>(`/ops/migration/batches/${batch.id}`);
                    setDetail(next.data);
                  })
                }
              >
                <strong>{batch.batchCode}</strong>
                <span>
                  {batch.status} · {batch.sourceName}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">No migration batches yet.</p>
      )}
      {detail && summary ? (
        <>
          <div className="metrics slim-metrics">
            <article className="metric">
              <p className="metric-label">Records in</p>
              <p className="metric-value">{summary.source?.records ?? "—"}</p>
            </article>
            <article className="metric">
              <p className="metric-label">Migrated customers</p>
              <p className="metric-value">{summary.target?.customers ?? "—"}</p>
            </article>
            <article className="metric">
              <p className="metric-label">Rejected</p>
              <p className="metric-value">{summary.rejected ?? "—"}</p>
            </article>
          </div>
          <p>
            Source balance {formatINR(summary.source?.balanceTotal)} · accepted {formatINR(summary.acceptedBalanceTotal)} · target{" "}
            {formatINR(summary.target?.balanceTotal)} ·{" "}
            {summary.balanceMatched ? "balance totals match" : "balance totals do not match"}
          </p>
          <p className="muted">
            Status {status} · mapping {detail.mappingVersion}
            {detail.signedOffBy ? ` · signed off by ${detail.signedOffBy}` : ""}
            {summary.idempotent ? " · last commit was a no-op" : ""}
            {summary.restored ? " · prior state restored" : ""}
          </p>
          <h4>Plan mapping</h4>
          <ul>
            {suggestions.map((row) => (
              <li key={row.legacyCode}>
                <strong>{row.legacyCode}</strong>
                {row.targetCode ? ` → ${row.targetCode}` : " → no current plan"}
                . {row.rationale}
              </li>
            ))}
          </ul>
          <div className="phase5-actions">
            <button type="button" className="ghost" disabled={busy || status === "committed"} onClick={() => void act("dry-run", {}, "Dry run finished. No billing rows were written.")}>
              Dry run
            </button>
            <button
              type="button"
              className="ghost"
              disabled={busy || status !== "dry_run"}
              onClick={() => void act("sign-off", { approveMapping: true }, "Mapping signed off.")}
            >
              Approve mapping
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || (status !== "signed_off" && status !== "committed")}
              onClick={() => void act("commit", {}, "Commit finished.")}
            >
              Commit batch
            </button>
            <button
              type="button"
              className="ghost"
              disabled={busy || (status !== "committed" && status !== "rolled_back")}
              onClick={() => void act("rollback", {}, "Batch rolled back.")}
            >
              Roll back
            </button>
            <button type="button" className="ghost" onClick={download}>
              Download reconciliation
            </button>
          </div>
          <h4>Rejects by reason</h4>
          {summary.byReason && Object.keys(summary.byReason).length ? (
            <ul>
              {Object.entries(summary.byReason).map(([reason, count]) => (
                <li key={reason}>
                  {reason}: {count}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">No rejected rows.</p>
          )}
          <DataTable
            rows={detail.records.filter((row) => row.status === "rejected" || row.status === "skipped")}
            empty="No rejected or skipped rows."
            columns={[
              { key: "kind", label: "Kind", render: (row) => row.recordKind },
              { key: "status", label: "Status", render: (row) => row.status },
              { key: "reason", label: "Reason", render: (row) => row.reason || "—" },
              { key: "plan", label: "Plan", render: (row) => row.legacyPlan || "—" },
              { key: "msisdn", label: "MSISDN", render: (row) => row.msisdn || "—" },
              { key: "balance", label: "Balance", render: (row) => (row.sourceBalance ? formatINR(row.sourceBalance) : "—"), numeric: true },
            ]}
          />
        </>
      ) : null}
    </section>
  );
}
