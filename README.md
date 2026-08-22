# DECIDAI

DECIDAI is a Human-in-the-Loop AI decision copilot: **AI Advises. Human Decides.**

## Frontend

```bash
npm install
npm run dev
```

Set the local API address in `.env` (copy from `.env.example`):

```env
VITE_API_BASE_URL=http://localhost:8000
```

## Backend

From the `backend` directory, create and activate a virtual environment, then install dependencies:

```bash
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env` and add your Gemini credentials:

```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=your_gemini_model_here
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
```

Run the API from `backend`:

```bash
uvicorn main:app --reload
```

The API listens on `http://localhost:8000`; the FastAPI health check is at `/health`.

## Notes

- Gemini credentials live only in `backend/.env`; they are never sent to the browser.
- The supporting-document upload accepts PDF, DOCX, and TXT files up to 10 MB.
- Human final decisions are stored by the backend in Supabase. A final decision requires an explicit reviewer name and reason; AI recommendations never create a final decision.

## Supabase Setup

1. Create a Supabase project.
2. Open its SQL Editor and run `backend/database/schema.sql`.
3. In Supabase Project Settings, copy the Project URL and the **service role** key.
4. Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to `backend/.env`.
5. Restart FastAPI.

Never expose the service-role key in frontend code, Vite variables, browser requests, or source control. DECIDAI sends all database writes through FastAPI.
