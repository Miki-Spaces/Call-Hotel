-- Run this if FastAPI is the only public entry point for this prototype.
-- The FastAPI server uses the Supabase Secret key and returns only the data each route needs.
-- After removing these policies, anonymous/browser clients will not be able to read/write these tables
-- through RLS-protected access. The server secret key bypasses RLS and MUST remain server-side.

drop policy if exists "Public can read room_types" on public.room_types;
drop policy if exists "Public can read rooms" on public.rooms;
drop policy if exists "Public can read and write users" on public.users;
drop policy if exists "Public can read and write bookings" on public.bookings;
