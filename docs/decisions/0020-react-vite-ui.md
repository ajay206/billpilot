# React, Vite, and TypeScript for the three persona screens

The persona switcher and the demo keys in the bundle are replaced by sign-in. The shell, and the choice to keep building the components here, are [0024](0024-signed-session-cookie.md) and [0025](0025-enterprise-shell.md). React, Vite, and TypeScript still stand.

## Decision

The UI is a Vite app in `web/`, written in React and TypeScript. It builds to static files. The API process serves those files when `web/dist` exists, so one container is the product. Personas are a switcher in the header. The switcher sends the published demo keys (`dev-customer-key`, `dev-csr-key`, `dev-ops-key`). Those strings are in the bundle on purpose. A model key, a database URL, and a Langfuse secret are not.

The components (badge, table, drawer, proposal card) live in this repo. There is no component-kit dependency.

Each view has its own path: `/customer`, `/csr`, and `/ops`. `/` is the customer view. The switcher updates the path, and the browser back button returns to the previous persona. The API serves `index.html` for those paths.

## Alternatives

- Streamlit, which the architecture deck also named. A second Python process, a second port, and a look that is hard to put in a short demo video.
- Next.js. The app is three views over one API. A server framework would add a second runtime next to FastAPI.
- MUI or another kit. Faster to start, heavier in the image, and the demo would look like the kit.

## Why

The deck asks for a customer chat, a CSR console, and an ops dashboard, each with its own scope. A static build keeps the free-tier host to one process and one cold start. TypeScript keeps the TMF payloads honest. The demo keys are already printed in the README. Putting them in the switcher is how a reviewer changes persona without a login form. Real secrets stay in the server environment.
