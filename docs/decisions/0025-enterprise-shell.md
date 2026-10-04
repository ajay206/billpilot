# Hand-built enterprise shell, no visual kit

## Decision

The three persona screens stay a Vite, React, and TypeScript app served by the API process. The persona switcher is gone. After sign-in the shell is a left navigation for that role only, a top bar (breadcrumb, account search for CSR and ops, the "Demo - synthetic data" badge, and a user menu), and one main screen per role.

Customer is a self-service portal: bill summary, usage, payments, disputes, and the assistant as a side panel. CSR is an account 360 with the copilot panel (citations, tool-call evidence, proposals). Ops is the control tower: KPI cards, the approval queue, agent runs, the audit log, and the Phase 4 placeholders. Approve and reject open a confirm dialog. Tables sort, filter, and page on the rows already loaded. Empty and loading states use the same components.

Spacing, type, and colour are CSS variables in `web/src/styles.css`. Source Sans 3 is the UI face. Fraunces is only the wordmark. There is no component-kit dependency.

## Alternatives

- MUI, Ant Design, or another visual kit. Faster tables and dialogs. A large bundle, and the screens would look like the kit. The free-tier image is one process; the built JS is about 80 KB gzipped without a kit.
- Radix or React Aria for the dialog and menu only. Those primitives are good. The dialog, menu, and table in this app are small enough to do with the platform (focus trap, `Escape`, `aria-modal`, `aria-sort`) without a second dependency to keep patched.
- Keep the warm paper layout from Phase 3. It read as a demo site. The deck's screens are a BSS console: dense tables, a stable shell, status badges.

## Why

[0020](0020-react-vite-ui.md) chose a static build and no kit so one container could serve the UI. That constraint is unchanged. The new shell is the same build, with role navigation and the controls a billing console actually uses. Keyboard focus, contrast, and a layout that holds together at a laptop width are part of the CSS, not a library default.
