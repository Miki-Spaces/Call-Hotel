-- Run in Supabase SQL Editor after the original schema.sql.
-- Supabase Auth stores and verifies passwords in auth.users.
-- This table stores only the phone number associated with each Auth user.

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  phone text not null unique,
  role text not null default 'user' check (role in ('user', 'admin')),
  created_at timestamptz not null default now()
);

-- Ensure existing installations also receive the role column safely.
alter table public.profiles
  add column if not exists role text not null default 'user';

do $do$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'profiles_role_check'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table public.profiles
      add constraint profiles_role_check check (role in ('user', 'admin'));
  end if;
end
$do$;

alter table public.profiles enable row level security;

-- Authenticated users can read only their own profile. Do not expose profile writes.
revoke all on table public.profiles from anon;
revoke all on table public.profiles from authenticated;
grant select on table public.profiles to authenticated;
grant all on table public.profiles to service_role;

drop policy if exists "Users can read own profile" on public.profiles;
create policy "Users can read own profile"
  on public.profiles
  for select
  to authenticated
  using ((select auth.uid()) = id);

-- Automatically create a profile from phone metadata supplied at sign-up.
-- The unique constraint rejects re-use of an already registered phone number.
create or replace function public.handle_new_auth_user_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_phone text;
begin
  v_phone := nullif(pg_catalog.btrim(new.raw_user_meta_data ->> 'phone'), '');

  if v_phone is not null then
    insert into public.profiles (id, phone)
    values (new.id, v_phone);
  end if;

  return new;
end;
$function$;

revoke all on function public.handle_new_auth_user_profile() from public, anon, authenticated;

drop trigger if exists on_auth_user_created_create_profile on auth.users;
create trigger on_auth_user_created_create_profile
after insert on auth.users
for each row execute function public.handle_new_auth_user_profile();
