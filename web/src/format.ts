import type { Money } from "./types";

const INR_FMT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const IST_DATE_FMT = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  dateStyle: "medium",
});

const IST_DATETIME_FMT = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  dateStyle: "medium",
  timeStyle: "short",
});

/** Format a money value as ₹ with en-IN grouping (e.g. ₹1,23,456.00). */
export function formatINR(amount: Money | string | null | undefined): string {
  const raw = typeof amount === "string" ? amount : amount?.value;
  if (!raw) return "—";
  const value = Number(raw);
  if (Number.isNaN(value)) return `₹${raw}`;
  return INR_FMT.format(value);
}

/** Format an ISO date-string as a date in IST (no time). */
export function formatIST(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return IST_DATE_FMT.format(date);
}

/** Format an ISO date-string as a date+time in IST. */
export function formatISTTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 16);
  return IST_DATETIME_FMT.format(date);
}

/** @deprecated Use formatINR */
export function inr(amount: Money | string | null | undefined): string {
  return formatINR(amount);
}

/** @deprecated Use formatIST */
export function when(iso: string | null | undefined): string {
  return formatIST(iso);
}

/** @deprecated Use formatISTTime */
export function whenTime(iso: string | null | undefined): string {
  return formatISTTime(iso);
}

export function age(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const minutes = Math.max(0, Math.round((now - then) / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

export function partyName(parties: { name?: string | null }[] | undefined): string {
  return parties?.find((party) => party.name)?.name || "Account";
}

export function actorLabel(actor: string | null | undefined): string {
  if (!actor) return "unknown";
  const split = actor.indexOf(":");
  if (split === -1) return actor;
  const kind = actor.slice(0, split);
  const rest = actor.slice(split + 1);
  if (kind === "user" || kind === "csr" || kind === "customer" || kind === "ops") return rest || kind;
  return actor;
}

export function characteristic(rows: { name: string; value: string }[] | undefined, name: string): string {
  return rows?.find((row) => row.name === name)?.value ?? "";
}
