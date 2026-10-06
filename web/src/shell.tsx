import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import type { Api } from "./api";
import { qs } from "./api";
import { NAV, demoAccounts, login, roleLabel } from "./auth";
import type { DemoAccount, Role, SessionUser } from "./auth";
import { partyName } from "./format";
import type { Account } from "./types";

export function LoginScreen({
  expired,
  demoMode,
  onSuccess,
}: {
  expired: boolean;
  demoMode: boolean;
  onSuccess: (user: SessionUser) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancel = false;
    demoAccounts()
      .then((rows) => {
        if (!cancel) setAccounts(rows);
      })
      .catch(() => {
        if (!cancel) setAccounts([]);
      });
    return () => {
      cancel = true;
    };
  }, []);

  async function submit(nextUser: string, nextPassword: string) {
    setBusy(true);
    setError(null);
    try {
      const user = await login(nextUser, nextPassword);
      onSuccess(user);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-screen">
      <section className="login-brand">
        <p className="mark" aria-hidden="true">
          Bp
        </p>
        <h1>BillPilot</h1>
        <p>A billing copilot for synthetic telecom accounts. Money and service changes stay proposals until ops approves them.</p>
        <p className="env-badge">Demo - synthetic data</p>
      </section>
      <section className="login-panel" aria-label="Sign in">
        <h2>Sign in</h2>
        <p className="muted">Use a demo account below. These passwords exist only for this portfolio.</p>
        {demoMode ? (
          <p className="banner" role="status">
            Demo mode. The copilot is using the scripted model, so this session needs no model key.
          </p>
        ) : null}
        {expired ? (
          <p className="error" role="alert">
            Your session expired. Sign in again.
          </p>
        ) : null}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submit(username, password);
          }}
        >
          <label htmlFor="username">Username</label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {error ? (
            <p className="error" role="alert">
              {error}
            </p>
          ) : null}
          <button type="submit" className="primary" disabled={busy || !username.trim() || !password}>
            Sign in
          </button>
        </form>
        <section className="demo-accounts" aria-label="Demo accounts">
          <h3>Demo accounts</h3>
          <ul>
            {accounts.map((account) => (
              <li key={account.username}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setUsername(account.username);
                    setPassword(account.password);
                    void submit(account.username, account.password);
                  }}
                >
                  <strong>Sign in as {account.displayName}</strong>
                  <span>
                    {roleLabel(account.role)} · {account.scope} · password {account.password}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {accounts.length === 0 ? <p className="empty">Demo accounts are loading.</p> : null}
        </section>
      </section>
    </div>
  );
}

export function Forbidden({ role, onHome }: { role: Role; onHome: () => void }) {
  return (
    <section className="panel forbidden" role="alert" aria-label="Access denied">
      <p className="eyebrow">403</p>
      <h1>This screen is outside your role</h1>
      <p>Signed in as {roleLabel(role)}. The server refuses this path, and this navigation is not shown for your role.</p>
      <button type="button" className="primary" onClick={onHome}>
        Go to your screen
      </button>
    </section>
  );
}

function AccountSearch({ api, onPick }: { api: Api; onPick: (account: Account) => void }) {
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<Account[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancel = false;
    const handle = window.setTimeout(() => {
      api
        .get<Account[]>(qs("/tmf-api/accountManagement/v4/billingAccount", { q: query || undefined, limit: 8 }))
        .then((result) => {
          if (!cancel) setRows(result.data);
        })
        .catch(() => {
          if (!cancel) setRows([]);
        });
    }, 200);
    return () => {
      cancel = true;
      window.clearTimeout(handle);
    };
  }, [api, query]);

  return (
    <div className="search">
      <label htmlFor="account-search">Search accounts</label>
      <input
        id="account-search"
        role="searchbox"
        value={query}
        placeholder="Name, customer number, account"
        autoComplete="off"
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {open && query.trim() && rows.length > 0 ? (
        <ul className="search-results" role="listbox" aria-label="Matching accounts">
          {rows.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                onClick={() => {
                  onPick(row);
                  setOpen(false);
                }}
              >
                <strong>{partyName(row.relatedParty)}</strong>
                <span>
                  {row.customerNumber} · {row.name}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {open && query.trim() && rows.length === 0 ? <p className="search-empty">No account matches.</p> : null}
    </div>
  );
}

function UserMenu({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onDoc(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);
  const scope = user.role === "customer" ? user.customerNumber : user.role === "csr" ? user.csrCode : "All accounts";
  return (
    <div className="user-menu" ref={ref}>
      <button type="button" className="user-button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="avatar" aria-hidden="true">
          {user.displayName.slice(0, 1)}
        </span>
        <span className="user-copy">
          <span className="user-name">{user.displayName}</span>
          <span className="user-role">{roleLabel(user.role)}</span>
        </span>
      </button>
      {open ? (
        <div className="menu" role="menu" aria-label="Account menu">
          <p className="menu-meta">
            {user.username} · {scope}
          </p>
          <button type="button" role="menuitem" onClick={onLogout}>
            Log out
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function AppShell({
  user,
  demoMode,
  section,
  onSection,
  breadcrumbs,
  api,
  onPickAccount,
  onLogout,
  children,
}: {
  user: SessionUser;
  demoMode: boolean;
  section: string;
  onSection: (id: string) => void;
  breadcrumbs: string[];
  api: Api;
  onPickAccount: (account: Account) => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  const items = NAV[user.role];
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = useCallback(() => setSidebarOpen(false), []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setSidebarOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="shell">
      <a className="skip" href="#content">
        Skip to content
      </a>
      {sidebarOpen ? <div className="sidebar-backdrop" aria-hidden="true" onClick={closeSidebar} /> : null}
      <aside className={sidebarOpen ? "sidebar open" : "sidebar"} aria-label="Navigation">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            Bp
          </span>
          <div>
            <p className="wordmark">BillPilot</p>
            <p className="tag">Billing copilot</p>
          </div>
        </div>
        <nav aria-label="Primary">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className={section === item.id ? "nav-item current" : "nav-item"}
              aria-current={section === item.id ? "page" : undefined}
              onClick={() => { onSection(item.id); setSidebarOpen(false); }}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <p className="sidebar-note">Synthetic data only. Not a certified TM Forum implementation.</p>
      </aside>
      <div className="main-col">
        <header className="topbar">
          <button
            type="button"
            className="sidebar-toggle"
            aria-label={sidebarOpen ? "Close menu" : "Open menu"}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((v) => !v)}
          >
            {sidebarOpen ? "✕" : "☰"}
          </button>
          <nav className="crumbs" aria-label="Breadcrumb">
            <ol>
              {breadcrumbs.map((crumb) => (
                <li key={crumb}>{crumb}</li>
              ))}
            </ol>
          </nav>
          {user.role === "customer" ? <div className="search-spacer" /> : <AccountSearch api={api} onPick={onPickAccount} />}
          <p className="env-badge">Demo - synthetic data</p>
          <UserMenu user={user} onLogout={onLogout} />
        </header>
        {demoMode ? (
          <div className="banner" role="status">
            Demo mode. The copilot is using the scripted model, so this session needs no model key. Set LLM_BACKEND=api and
            LLM_API_KEY on the server to use a hosted model.
          </div>
        ) : null}
        <main id="content">{children}</main>
      </div>
    </div>
  );
}

export function ToastRegion({ toasts }: { toasts: { id: string; text: string; tone: "ok" | "err" }[] }) {
  if (!toasts.length) return null;
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((toast) => (
        <p key={toast.id} className={`toast ${toast.tone}`} role="status">
          {toast.text}
        </p>
      ))}
    </div>
  );
}
