import { useEffect, useMemo, useRef, useState } from "react";

import { createApi } from "./api";
import {
  clearCsrf,
  currentUser,
  defaultSection,
  logout,
  opsPath,
  opsSectionFromPath,
  roleHome,
  roleLabel,
  screenFromPath,
  sectionLabel,
} from "./auth";
import type { Role, SessionUser } from "./auth";
import { AppShell, Forbidden, LoginScreen, ToastRegion } from "./shell";
import type { Account, Health } from "./types";
import { CsrConsole } from "./views/CsrConsole";
import { CustomerPortal } from "./views/CustomerChat";
import { OpsDashboard } from "./views/OpsDashboard";

type Toast = { id: string; text: string; tone: "ok" | "err" };

export function App() {
  const [path, setPath] = useState(() => window.location.pathname);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [booting, setBooting] = useState(true);
  const [expired, setExpired] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [section, setSection] = useState("overview");
  const [picked, setPicked] = useState<Account | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const expireRef = useRef<() => void>(() => {});

  function navigate(next: string) {
    if (window.location.pathname !== next) window.history.pushState({}, "", next);
    setPath(next);
  }

  expireRef.current = () => {
    clearCsrf();
    setUser(null);
    setExpired(true);
    setPicked(null);
    navigate("/login");
  };

  const api = useMemo(() => createApi(() => expireRef.current()), []);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    let cancel = false;
    const hadCookie = document.cookie.includes("bp_csrf=");
    Promise.all([
      currentUser(),
      fetch("/health")
        .then((response) => response.json() as Promise<Health>)
        .catch(() => null),
    ])
      .then(([me, nextHealth]) => {
        if (cancel) return;
        setHealth(nextHealth);
        if (me) {
          setUser(me);
          setSection(me.role === "ops" ? opsSectionFromPath(window.location.pathname) : defaultSection(me.role));
        } else {
          setExpired(hadCookie);
        }
      })
      .finally(() => {
        if (!cancel) setBooting(false);
      });
    return () => {
      cancel = true;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    if (!screenFromPath(path)) {
      navigate(roleHome(user.role));
      return;
    }
    if (user.role === "ops") setSection(opsSectionFromPath(path));
  }, [user, path]);

  function pushToast(text: string, tone: "ok" | "err" = "ok") {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts((current) => [...current, { id, text, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 4500);
  }

  function enter(next: SessionUser) {
    setUser(next);
    setExpired(false);
    setPicked(null);
    setSection(defaultSection(next.role));
    navigate(roleHome(next.role));
  }

  async function signOut() {
    await logout();
    setUser(null);
    setPicked(null);
    setExpired(false);
    navigate("/login");
  }

  if (booting) {
    return (
      <div className="boot" aria-busy="true" aria-label="Loading BillPilot">
        <div className="skeleton-row" />
        <div className="skeleton-row" />
      </div>
    );
  }

  if (!user) {
    return <LoginScreen expired={expired} demoMode={Boolean(health?.demoMode)} onSuccess={enter} />;
  }

  const signedIn = user;

  function chooseSection(id: string) {
    if (signedIn.role === "ops") {
      setSection(id);
      navigate(opsPath(id));
      return;
    }
    setSection(id);
  }

  const screen = screenFromPath(path);
  const allowed = screen === signedIn.role;
  const crumbs = !allowed
    ? ["Access denied"]
    : signedIn.role === "csr"
      ? ["Care", picked?.customerNumber ?? "Search", "Account 360"]
      : [roleLabel(signedIn.role), sectionLabel(signedIn.role, section)];

  return (
    <>
      <AppShell
        user={signedIn}
        demoMode={Boolean(health?.demoMode)}
        section={section}
        onSection={chooseSection}
        breadcrumbs={crumbs}
        api={api}
        onPickAccount={setPicked}
        onLogout={() => void signOut()}
      >
        {!allowed ? <Forbidden role={signedIn.role as Role} onHome={() => navigate(roleHome(signedIn.role))} /> : null}
        {allowed && signedIn.role === "customer" ? <CustomerPortal api={api} section={section} /> : null}
        {allowed && signedIn.role === "csr" ? <CsrConsole api={api} account={picked} /> : null}
        {allowed && signedIn.role === "ops" ? (
          <OpsDashboard api={api} section={section} focus={picked} onOpenAccount={setPicked} onToast={pushToast} />
        ) : null}
      </AppShell>
      <ToastRegion toasts={toasts} />
    </>
  );
}
