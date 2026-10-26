# Orbitly — Source Handoff

Orbitly is a cinematic study-abroad AI advisor experience. The project includes the original landing page, the advisor chat workspace, and matching login and sign-up pages using one shared visual system.

## Preview routes

- `/` — Orbitly landing page
- `/chat` — Vera advisor workspace
- `/login` — Login page
- `/signup` — Account creation page

## Design system

Orbitly uses a typography-led, editorial interface inspired by signal maps and global movement:

- **Dark theme:** ink navy, charcoal, warm white, signal coral, and acid-lime status accents.
- **Light theme:** warm ivory, deep blue-black, softened coral, and muted green signal accents.
- **Typography:** DM Mono for display and interface labels, Space Grotesk for readable supporting copy.
- **Signature motifs:** orbital rings, route lines, signal dots, coordinate labels, and small editorial status labels.
- **Motion:** subtle floating nodes, orbiting match indicators, hover lifts, animated reveals, and responsive transitions.

The theme preference is stored in `localStorage` under `orbitly-theme` and is shared across the landing page, chat workspace, login, and sign-up routes.

## Source map

| File | Purpose |
| --- | --- |
| `index.html` | Main Orbitly landing page |
| `chat.html` | Study-abroad advisor chat workspace |
| `login.html` | Login experience |
| `signup.html` | Sign-up experience |
| `styles.css` | Shared theme variables, layout, responsive styles, chat UI, and auth UI |
| `app.js` | Theme toggle, matching preview, suggestion chips, chat composer, and auth form interactions |
| `server.mjs` | Lightweight Node static server and route handling |
| `package.json` | Project metadata and start/build scripts |
| `app.config.ts` | Project logo metadata |
| `public/manus-routes.json` | Page route manifest |
| `TODO.md` | Product outcome notes |

## Run locally

Requirements: Node.js 18 or newer.

```bash
npm start
```

Then open `http://localhost:3000`.

The server listens on `0.0.0.0` and respects the `PORT` environment variable:

```bash
PORT=3000 npm start
```

## Build check

This project is intentionally lightweight and serves static files directly. The build script is a validation placeholder suitable for the managed preview workflow:

```bash
npm run build
```

## Notes

The hero backgrounds are served through the project’s managed storage paths and referenced directly from `styles.css`. The front-end auth forms are styled and interactive but do not include a real authentication backend yet. The chat composer and suggestion chips are currently front-end interaction previews ready to connect to a real advisor service.

## Checkpoint

Latest saved checkpoint: `9f5c63d` — `Extend Orbitly styling to chat and auth`
