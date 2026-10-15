-- Run in Supabase Dashboard > SQL Editor after public.profiles exists.
-- Adds a trusted application role. New profiles are ordinary users by default.
-- The role is NOT writable by anon/authenticated clients; change it only from a trusted admin SQL session.

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

revoke insert, update, delete on table public.profiles from anon, authenticated;
grant select on table public.profiles to authenticated;
grant all on table public.profiles to service_role;

-- Promote a user to Admin ONLY after the account has registered successfully.
-- Replace admin@example.com with the email of the account you control, then run separately:
--
-- update public.profiles p
-- set role = 'admin'
-- from auth.users u
-- where p.id = u.id
--   and lower(u.email) = lower('admin@example.com')
-- returning p.id, p.phone, p.role;
--
-- If this returns zero rows, confirm that the user registered and the profile trigger created a profile.
