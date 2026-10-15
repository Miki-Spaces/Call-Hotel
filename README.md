# Hotel Booking API — merged FastAPI + Supabase Auth

This project combines the original hotel booking API with email/password authentication routes in a single `app.py`.

## Routes in `app.py`

- `POST /api/auth/register` — accepts `email`, `phone`, and `password`; creates a Supabase Auth user and stores the phone in `public.profiles`.
- `POST /api/auth/login` — accepts `email` and `password`; returns the Supabase Auth session tokens.
- `GET /api/rooms` — returns room types, prices, physical room counts, and available counts. Optionally pass `check_in` and `check_out` query params.
- `POST /api/check-availability` — checks availability of a room type for a date range.
- `POST /api/bookings` — creates a booking and assigns a physical room using a PostgreSQL function.
- `GET /api/bookings?phone=...` — looks up bookings by phone.
- `POST /api/bookings/cancel` — cancels a booking when booking ID and phone match.
- `GET /api/admin/me` — verifies an Admin access token.
- `GET /api/admin/bookings` — lists all bookings (Admin only; supports `limit` and `offset`).
- `GET /api/admin/rooms` — lists all physical rooms (Admin only).
- `GET /api/admin/room-types` — lists all room types and prices (Admin only).
- `GET /api/admin/profiles` — lists profile IDs, phones, and roles (Admin only; supports `limit` and `offset`).
- `GET /api/admin/users` — lists Supabase Auth account basics (Admin only; paginated).
- `GET /health` — health check.

## 1. Prepare Supabase SQL

Run these in Supabase Dashboard → SQL Editor in this order:

1. `sql/schema.sql` — creates the original hotel tables and seeds initial room data.
2. `sql/auth_profiles.sql` — creates `public.profiles` and a trigger to link signup metadata to a unique phone number.
3. `sql/admin_roles.sql` — adds the `role` column to `public.profiles` (safe to run more than once).
4. `sql/booking_functions.sql` — creates database functions for atomic booking creation and cancellation.
5. `sql/secure_policies.sql` — drops the broad public policies from the original schema.

Important:
- The original `schema.sql` includes a legacy `public.users` table and a seeded admin PIN. Auth routes in this project use Supabase Auth and `public.profiles`; they do not use `public.users.pin`. Do not use the sample PIN as production authentication.
- Review policies and grants before using real customer data. The FastAPI server uses the Supabase secret key, which bypasses RLS; keep it server-side only.
- Ordinary accounts default to `profiles.role = 'user'`. The public register endpoint does not accept or assign roles.
- To promote your own, already-registered account, replace the email in the UPDATE below and run it in SQL Editor as the project owner. Never expose an endpoint that lets a user change their own role:

  ```sql
  update public.profiles p
  set role = 'admin'
  from auth.users u
  where p.id = u.id
    and lower(u.email) = lower('admin@example.com')
  returning p.id, p.phone, p.role;
  ```
- Admin endpoints verify `Authorization: Bearer <access_token>` with Supabase Auth, then read the role from `public.profiles`. They do not trust a role sent by the browser or stored in user-editable metadata.
- The booking lookup and cancellation routes in this prototype still use the phone number in the request instead of a login token because they are intended to fit the current Voice Bot API contract. Do not expose those routes to the public internet in production without adding a trusted Voice Bot API key or customer JWT/ownership checks.
- The phone field must be unique. Signup with an existing phone may fail due to the database trigger constraint.

## 2. Configure environment on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_KEY
SUPABASE_SECRET_KEY=sb_secret_YOUR_KEY
```

Use the URL and keys from your own Supabase project. Never commit `.env` or expose `SUPABASE_SECRET_KEY` in frontend code or GitHub.

## 3. Run locally

```powershell
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000/docs` to test the routes.

## 4. Register request example

`POST /api/auth/register`

```json
{
  "email": "guest@example.com",
  "phone": "0812345678",
  "password": "ExamplePass123!"
}
```

## 5. Login request example

`POST /api/auth/login`

```json
{
  "email": "guest@example.com",
  "password": "ExamplePass123!"
}
```

On successful login, `session.access_token` is returned. To call an Admin endpoint, pass it as `Authorization: Bearer <access_token>` and first promote that account to `role = 'admin'` using SQL. In Swagger `/docs`, click `Authorize` and paste the access token.

## Notes

- If email confirmation is enabled in Supabase Auth, users must confirm their email before they can log in; signup may return a `null` session.
- This project has been syntax-checked, but must still be tested against your own Supabase project and keys.
- Add CORS middleware with only your frontend's real origin before deploying the frontend and API separately.
