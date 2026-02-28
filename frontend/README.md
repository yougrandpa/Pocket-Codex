# Pocket Codex Frontend

Mobile-first Next.js dashboard for monitoring and controlling Pocket Codex tasks.

## Features in this scaffold

- Dashboard page with task creation form and task list.
- Task detail page (`/tasks/[id]`) with status and metadata.
- Typed API client targeting backend `/api/v1` endpoints.
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
- `components/task-creator.tsx`: create-task form (client component).
- `components/task-list.tsx`: task list rendering.
- `components/task-detail.tsx`: task metadata display.
- `lib/api.ts`: typed fetch wrappers for `/api/v1`.
