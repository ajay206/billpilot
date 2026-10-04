import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import type { Api } from "./api";
import { inr } from "./format";
import type { PolicySection, Proposed } from "./types";

const CITATION = /\[([A-Za-z0-9._-]+\.md) § ([^\]\n]+?)\]/g;

export type CitationRef = { doc: string; section: string };

export function AnswerText({
  text,
  onCite,
}: {
  text: string;
  onCite: (doc: string, section: string) => void;
}) {
  const parts: ReactNode[] = [];
  const seen = new Set<string>();
  let last = 0;
  for (const match of text.matchAll(CITATION)) {
    const index = match.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    const doc = match[1];
    const section = match[2];
    const key = `${doc}\u0000${section}`;
    if (!seen.has(key)) {
      seen.add(key);
      parts.push(
        <button key={`${doc}-${section}-${index}`} type="button" className="cite" onClick={() => onCite(doc, section)}>
          {doc} · {section}
        </button>,
      );
    }
    last = index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <p className="answer-text">{parts}</p>;
}

/** Chips for citations that are not already drawn inside the answer text. */
export function extraCitations(items: CitationRef[] | undefined, answer: string): CitationRef[] {
  const seen = new Set<string>();
  const extra: CitationRef[] = [];
  for (const item of items ?? []) {
    const key = `${item.doc}\u0000${item.section}`;
    if (seen.has(key)) continue;
    seen.add(key);
    if (answer.includes(`[${item.doc} § ${item.section}]`)) continue;
    extra.push(item);
  }
  return extra;
}

export function SeverityBadge({ severity }: { severity?: string | null }) {
  const value = (severity || "unknown").toLowerCase();
  const tone = value === "critical" || value === "high" ? "bad" : value === "medium" ? "pending" : value === "low" ? "good" : "neutral";
  return <span className={`badge ${tone}`}>{value}</span>;
}

export function StatusBadge({ status }: { status?: string | null }) {
  const value = status || "unknown";
  const pending = value === "pending_approval";
  const rejected = value === "rejected";
  const applied = value === "applied" || value === "settled" || value === "done" || value === "active";
  const tone = pending ? "pending" : rejected ? "bad" : applied ? "good" : "neutral";
  const label = pending ? "Pending approval" : value.replaceAll("_", " ");
  return <span className={`badge ${tone}`}>{label}</span>;
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
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

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

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") closeRef.current();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Cited policy section" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <p className="eyebrow">Cited policy</p>
          <button type="button" className="text-button" onClick={onClose}>
            Close
          </button>
        </header>
        {error ? <p className="error">{error}</p> : null}
        {!page && !error ? <Skeleton rows={4} label="Opening the section" /> : null}
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

export function Skeleton({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div className="skeleton" aria-busy="true" aria-live="polite" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton-row" />
      ))}
    </div>
  );
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;

  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[data-cancel]")?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        cancelRef.current();
        return;
      }
      if (event.key !== "Tab" || !ref.current) return;
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>("button:not(:disabled)"));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="drawer-backdrop" onClick={onCancel}>
      <div
        ref={ref}
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-title">{title}</h2>
        <p>{body}</p>
        <div className="dialog-actions">
          <button type="button" className="ghost" data-cancel onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="primary" onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

type Column<T> = {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  value?: (row: T) => string | number;
};

export function DataTable<T extends { id: string }>({
  columns,
  rows,
  empty,
  loading = false,
  pageSize = 8,
  label = "Data",
}: {
  columns: Column<T>[];
  rows: T[];
  empty: string;
  loading?: boolean;
  pageSize?: number;
  label?: string;
}) {
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    let next = rows;
    if (needle) {
      next = rows.filter((row) =>
        columns.some((column) => String(column.value ? column.value(row) : "").toLowerCase().includes(needle)),
      );
    }
    if (sortKey) {
      const column = columns.find((item) => item.key === sortKey);
      if (column?.value) {
        next = [...next].sort((left, right) => {
          const a = column.value?.(left) ?? "";
          const b = column.value?.(right) ?? "";
          const order = a < b ? -1 : a > b ? 1 : 0;
          return sortDir === "asc" ? order : -order;
        });
      }
    }
    return next;
  }, [columns, filter, rows, sortDir, sortKey]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pages - 1);
  const visible = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    setPage(0);
  }

  if (loading) return <Skeleton rows={4} label={`Loading ${label}`} />;
  if (!rows.length) return <p className="empty">{empty}</p>;

  return (
    <div className="table-block">
      <div className="table-tools">
        <label className="filter">
          <span className="sr-only">Filter {label}</span>
          <input
            type="search"
            value={filter}
            placeholder={`Filter ${label.toLowerCase()}`}
            aria-label={`Filter ${label}`}
            onChange={(event) => {
              setFilter(event.target.value);
              setPage(0);
            }}
          />
        </label>
        <p className="muted table-count">
          {filtered.length} row{filtered.length === 1 ? "" : "s"}
        </p>
      </div>
      {filtered.length === 0 ? <p className="empty">No rows match this filter.</p> : null}
      {filtered.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {columns.map((column) => {
                  const active = sortKey === column.key;
                  const ariaSort = !column.value ? undefined : active ? (sortDir === "asc" ? "ascending" : "descending") : "none";
                  return (
                    <th key={column.key} aria-sort={ariaSort}>
                      {column.value ? (
                        <button type="button" className="sort" onClick={() => toggleSort(column.key)}>
                          {column.label}
                          {active ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                        </button>
                      ) : (
                        column.label
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.id}>
                  {columns.map((column) => (
                    <td key={column.key}>{column.render(row)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {pages > 1 ? (
        <nav className="pager" aria-label={`${label} pages`}>
          <button type="button" className="ghost" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
            Previous
          </button>
          <span>
            Page {safePage + 1} of {pages}
          </span>
          <button type="button" className="ghost" disabled={safePage >= pages - 1} onClick={() => setPage(safePage + 1)}>
            Next
          </button>
        </nav>
      ) : null}
    </div>
  );
}
