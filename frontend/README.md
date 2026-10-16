# Vindex frontend

React 18 + Vite + TypeScript app for every role: citizens file and track complaints; department, district and super admins work the queues, the map, staff accounts, rules and metrics.

- UI: Tailwind CSS v4, shadcn/ui on Base UI, lucide-react icons
- Forms: react-hook-form + zod; maps: react-leaflet with OpenStreetMap tiles
- Languages: i18next with `src/i18n/en.json`, `ta.json` and `hi.json`
- API: `src/lib/api.ts` talks to `VITE_API_URL` (default `http://localhost:8000`); copy `.env.example` to `.env` to change it

## Commands

```bash
npm install
npm run dev
npm run build
```

`npm run dev` serves the app on http://localhost:5173. Set `VITE_HTTPS=1` to serve over HTTPS with the certificates from `scripts/setup/make_cert.py`, which phones need for the camera and GPS. `npm run build` type-checks and bundles into `dist/`.

## Layout

```
src/pages/        one file per screen (citizen, staff and admin pages)
src/components/   shared parts: camera, location, decision bar, timeline, media, cards; ui/ holds the shadcn components
src/lib/          API client, auth context, formatting, labels, translations set-up
src/i18n/         English, Tamil and Hindi strings
```
