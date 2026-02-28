# Pocket Codex Frontend

Mobile-first Next.js dashboard for monitoring and controlling Pocket Codex tasks.

## Features in this scaffold

- JWT login + refresh flow (single-user auth).
- Dashboard page with task creation form, live task list, and in-app notifications.
- Task detail page (`/tasks/[id]`) with realtime events, control actions, and message append.
- Typed API client targeting backend `/api/v1` endpoints and SSE stream.
- Responsive UI tuned for mobile first and iOS Safari usage.

## Environment

Create `.env.local` under `frontend/`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

If omitted, the app defaults to `http://localhost:8000`.

## Run locally

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Pages and components

- `app/page.tsx`: home dashboard.
- `app/tasks/[id]/page.tsx`: task detail screen.
- `components/login-panel.tsx`: sign-in form.
- `components/task-dashboard.tsx`: dashboard state, SSE subscription, notification feed.
- `components/task-creator.tsx`: create-task form (client component).
- `components/task-list.tsx`: task list rendering.
- `components/task-detail-live.tsx`: detail page realtime controls and logs.
- `components/notification-center.tsx`: in-app notification list.
- `lib/api.ts`: typed fetch wrappers for `/api/v1` + session helpers.
