# BusX Premium Buyer Chat (React Web)

This folder contains the **React.js web client** for the BusX Premium Buyer Chat.

## Why this exists
The original UI in `app/static/` is a vanilla HTML/JS prototype. This React app:

- keeps the **FastAPI backend** as the single “brain”
- provides a clean component architecture for **web**
- is designed so you can later share logic with a **React Native (Expo)** mobile app

## Quick start (dev)

1) Install Node.js 18+.

2) From this folder:

```bash
npm install
npm run dev
```

3) By default it calls the API at `/buyer/chat`.
If you run the React dev server on a different port/host than FastAPI, either:

- set a proxy in `vite.config.ts`, or
- set `VITE_BUYER_ENDPOINT` in `.env`.

Example `.env`:

```bash
VITE_BUYER_ENDPOINT=http://localhost:8000/buyer/chat
```

## Build (production)

```bash
npm run build
```

Outputs to `dist/`.

### Serving in production
Recommended: **Nginx** serves the static `dist/` and proxies `/buyer/*` to FastAPI.

Optional: FastAPI can serve the built files if you copy `dist/` into a directory
and mount it with `StaticFiles`.

## Notes
This first React refactor focuses on:

- message list
- send box
- “typing” indicator (dots-only)
- quick actions for date (Today/Tomorrow/Other date)
- passenger details card (Title Mr/Ms first, all required, auto gender)

Seat map is scaffolded for SVG rendering in a follow-up step.
