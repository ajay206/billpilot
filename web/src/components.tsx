import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import type { Api } from "./api";
import { inr } from "./format";
import type { PolicySection, Proposed } from "./types";

const CITATION = /\[([A-Za-z0-9._-]+\.md) § ([^\]\n]+?)\]/g;

export function AnswerText({
  text,
  onCite,
}: {
  text: string;
  onCite: (doc: string, section: string) => void;
}) {
  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    const doc = match[1];
    const section = match[2];
    parts.push(
      <button key={`${doc}-${section}-${index}`} type="button" className="cite" onClick={() => onCite(doc, section)}>
        {doc} · {section}
      </button>,
    );
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <p className="answer-text">{parts}</p>;
}

export function StatusBadge({ status }: { status: string }) {
  const pending = status === "pending_approval";
  const rejected = status === "rejected";
  const applied = status === "applied";
  const tone = pending ? "pending" : rejected ? "bad" : applied ? "good" : "neutral";
  return <span className={`badge ${tone}`}>{pending ? "Pending approval" : status.replaceAll("_", " ")}</span>;
}

export function ProposalCard({ item }: { item: Proposed }) {
  const status = item.status || "pending_approval";
  const label = item.type === "credit" ? "Credit" : item.type === "dispute" ? "Dispute" : item.type || "Proposal";
  return (
    <article className="proposal">
      <div className="proposal-top">
        <strong>{label}</strong>
        <StatusBadge status={status} />
      </div>
      {item.amount ? <p className="proposal-amount">{inr(item.amount)}</p> : null}
      <p className="proposal-status">Status: {status}</p>
    </article>
  );
}

export function PolicyDrawer({
  api,
  doc,
  section,
  onClose,
}: {
  api: Api;
  doc: string;
  section: string;
  onClose: () => void;
}) {
  const [page, setPage] = useState<PolicySection | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    setPage(null);
    setError(null);
    const path = `/knowledge/section?doc=${encodeURIComponent(doc)}&section=${encodeURIComponent(section)}`;
    api
      .get<PolicySection>(path)
      .then((result) => {
        if (!cancel) setPage(result.data);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    return () => {
      cancel = true;
    };
  }, [api, doc, section]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label="Cited policy section" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <p className="eyebrow">Cited policy</p>
          <button type="button" className="text-button" onClick={onClose}>
            Close
          </button>
        </header>
        {error ? <p className="error">{error}</p> : null}
        {!page && !error ? <p className="muted">Opening the section…</p> : null}
        {page ? (
          <>
            <h2>{page.section}</h2>
            <p className="muted">
              {page.title} · {page.doc}
            </p>
            <div className="policy-body">{page.body}</div>
          </>
        ) : null}
      </aside>
    </div>
  );
}

export function Placeholder({ phase, title, children }: { phase: string; title: string; children: string }) {
  return (
    <section className="placeholder" aria-label={`${title}, ${phase}`}>
      <span className="placeholder-flag">{phase}</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </section>
  );
}

export function Metric({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <article className="metric">
      <p className="metric-label">{label}</p>
      <p className="metric-value">{value}</p>
      {hint ? <p className="muted">{hint}</p> : null}
    </article>
  );
}

export function DataTable<T extends { id: string }>({
  columns,
  rows,
  empty,
}: {
  columns: { key: string; label: string; render: (row: T) => ReactNode }[];
  rows: T[];
  empty: string;
}) {
  if (!rows.length) return <p className="empty">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
