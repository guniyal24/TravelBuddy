# TravelBuddy frontend

React + Vite single-page app. Logged out, it is a marketing site (hero, how it works, destinations,
features, FAQ) with a login / sign-up dialog. Logged in, it is the planner: plan a trip with human
approval at each step, review it as a day-by-day plan, timeline, map and booking checklist, re-plan
mid-trip, share or export it, keep preferences, and ask questions.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (backend on :8000)
npm run build
```

Set `VITE_API_URL` to point at a deployed backend. The backend's `CORS_ORIGINS` must include
the frontend's origin.

## Layout

| Path | What |
|---|---|
| `src/App.jsx` | Landing + auth dialog when logged out; tabbed app shell (bottom nav on phones) when logged in |
| `src/components/Landing.jsx` | Marketing page |
| `src/components/Trip.jsx`, `TripView.jsx` | Planner flow and the trip view (banner, plan cards, timeline, map, checklist, share) |
| `src/data.js` | Static copy: destinations, features, FAQ |
| `src/styles.css` | Design system (CSS variables, light and dark) |
| `public/sw.js`, `manifest.webmanifest` | Offline app shell (production builds only) |

Fonts (Nunito) load from Google Fonts and fall back to system fonts offline. There are no
image assets beyond the logo (`public/logo*.png`, `icon-*.png`, made from `brand/travelbuddy-logo-original.webp`): the skyline and icons are inline SVG.
