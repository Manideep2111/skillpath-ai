# SkillPath AI — Frontend Application (Stage 9A)

Modern React + Vite + TypeScript web interface for the SkillPath AI personalized learning recommendation platform.

---

## 1. Prerequisites

- **Node.js**: `v18.0.0` or higher (`v24.22.1` verified)
- **Package Manager**: `npm` (`v11.19.1` verified)
- **Backend API**: FastAPI backend running on `http://localhost:8000`

---

## 2. Directory Structure

```
frontend/
├── dist/                      # Compiled production distribution build
├── node_modules/              # Installed npm dependencies
├── public/                    # Static assets
├── src/
│   ├── components/
│   │   ├── dashboard/
│   │   │   └── DashboardPlaceholder.tsx  # Interactive engine probe & Recharts visualizer
│   │   └── layout/
│   │       ├── AppShell.tsx              # Main desktop/laptop responsive layout shell
│   │       ├── Header.tsx                # Topbar with live backend health indicator
│   │       └── Sidebar.tsx               # Fixed navigation sidebar with SRS branding
│   ├── services/
│   │   └── api/
│   │       ├── apiClient.ts              # Typed fetch client with error decoding
│   │       └── types.ts                  # TypeScript mirrors of backend Pydantic models
│   ├── App.tsx                           # Root application component
│   ├── index.css                         # Global CSS custom properties and responsive rules
│   ├── main.tsx                          # React 18 DOM mount point
│   └── vite-env.d.ts                     # Vite environment type declarations
├── .env                              # Active environment configuration
├── .env.example                      # Reference environment template
├── index.html                        # Application HTML entry point
├── package.json                      # Project dependencies and script definitions
├── tsconfig.json                     # TypeScript compiler configuration
└── vite.config.ts                    # Vite build and dev server configuration
```

---

## 3. Configuration

The frontend connects to the backend using the `VITE_API_BASE_URL` environment variable defined in `.env`:

```env
# Default local development endpoint
VITE_API_BASE_URL=http://localhost:8000
```

---

## 4. Available Scripts

From within the `frontend/` directory:

| Command | Action |
|---|---|
| `npm install` | Install all dependencies |
| `npm run dev` | Start the local Vite development server on `http://localhost:5173` |
| `npm run lint` | Run TypeScript compiler type-check (`tsc --noEmit`) |
| `npm run build` | Compile TypeScript and produce production bundle in `dist/` |
| `npm run preview` | Locally preview the production build in `dist/` |

---

## 5. Starting the Backend and Frontend on Windows

### Terminal 1: Start FastAPI Backend
```powershell
# In project root D:\SkillPathAI
& ".\.venv\Scripts\Activate.ps1"
uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
```
- Interactive Swagger docs will be live at `http://localhost:8000/docs`.
- Health check available at `http://localhost:8000/health`.

### Terminal 2: Start React Frontend
```powershell
# In project root D:\SkillPathAI
cd frontend
npm run dev
```
- Open `http://localhost:5173` in your browser.
