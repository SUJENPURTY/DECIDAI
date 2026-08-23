-- DECIDAI Phase 1 SaaS tenancy, identity, and RLS migration.
-- Run manually in the Supabase SQL Editor only after schema.sql. Do not run from the app.
-- The FastAPI service role bypasses RLS; it must continue to enforce tenant scope server-side.

begin;

create extension if not exists pgcrypto;

-- Core tenant and membership data. The ALTER statements make this safe for an
-- existing project where an earlier version of this migration was partially run.
create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique,
  created_by uuid references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.organizations add column if not exists name text;
alter table public.organizations add column if not exists slug text;
alter table public.organizations add column if not exists created_by uuid references auth.users(id);
alter table public.organizations add column if not exists created_at timestamptz default now();
alter table public.organizations add column if not exists updated_at timestamptz default now();
alter table public.organizations alter column created_at set default now();
alter table public.organizations alter column updated_at set default now();
create unique index if not exists organizations_slug_key on public.organizations (slug);

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  avatar_url text,
  organization_id uuid references public.organizations(id),
  role text not null default 'requester' check (role in ('admin', 'reviewer', 'requester')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Invitations are created and managed only by trusted server-side code.  The
-- email value is retained for delivery/audit; uniqueness and matching use its
-- normalized form so case and surrounding whitespace cannot create duplicates.
create table if not exists public.organization_invitations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email text not null,
  role text not null default 'requester' check (role in ('admin', 'reviewer', 'requester')),
  invited_by uuid not null references auth.users(id),
  token_hash text not null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.organization_invitations add column if not exists organization_id uuid references public.organizations(id) on delete cascade;
alter table public.organization_invitations add column if not exists email text;
alter table public.organization_invitations add column if not exists role text default 'requester';
alter table public.organization_invitations add column if not exists invited_by uuid references auth.users(id);
alter table public.organization_invitations add column if not exists token_hash text;
alter table public.organization_invitations add column if not exists expires_at timestamptz;
alter table public.organization_invitations add column if not exists accepted_at timestamptz;
alter table public.organization_invitations add column if not exists created_at timestamptz default now();
alter table public.organization_invitations add column if not exists updated_at timestamptz default now();
alter table public.organization_invitations alter column created_at set default now();
alter table public.organization_invitations alter column updated_at set default now();
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.organization_invitations'::regclass
      and conname = 'organization_invitations_role_check'
  ) then
    alter table public.organization_invitations add constraint organization_invitations_role_check
      check (role in ('admin', 'reviewer', 'requester'));
  end if;
end;
$$;

create index if not exists organization_invitations_organization_created_idx
  on public.organization_invitations (organization_id, created_at desc);
create index if not exists organization_invitations_expires_at_idx
  on public.organization_invitations (expires_at);
create unique index if not exists organization_invitations_pending_email_key
  on public.organization_invitations (organization_id, lower(btrim(email)))
  where accepted_at is null;

alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists full_name text;
alter table public.profiles add column if not exists avatar_url text;
alter table public.profiles add column if not exists organization_id uuid references public.organizations(id);
alter table public.profiles add column if not exists role text default 'requester';
alter table public.profiles add column if not exists created_at timestamptz default now();
alter table public.profiles add column if not exists updated_at timestamptz default now();
update public.profiles
set role = 'requester'
where role is null or role not in ('admin', 'reviewer', 'requester');
alter table public.profiles alter column role set default 'requester';
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.profiles'::regclass and conname = 'profiles_role_check'
  ) then
    alter table public.profiles add constraint profiles_role_check
      check (role in ('admin', 'reviewer', 'requester'));
  end if;
end;
$$;

-- Tenant columns for the existing DECIDAI tables. Current backend identity
-- metadata remains in human_decisions.reviewer_name and audit_logs.details.
alter table public.decision_cases add column if not exists organization_id uuid references public.organizations(id);
alter table public.decision_cases add column if not exists created_by uuid references auth.users(id);
alter table public.ai_analyses add column if not exists organization_id uuid references public.organizations(id);
alter table public.human_decisions add column if not exists organization_id uuid references public.organizations(id);
alter table public.audit_logs add column if not exists organization_id uuid references public.organizations(id);

-- Preserve pre-SaaS demo data. Ownership is intentionally left NULL when it
-- cannot be established from an authenticated historical user.
insert into public.organizations (name, slug)
values ('Legacy DECIDAI Workspace', 'legacy-decidai-workspace')
on conflict (slug) do nothing;

update public.decision_cases
set organization_id = (select id from public.organizations where slug = 'legacy-decidai-workspace')
where organization_id is null;

-- Historical profiles without a membership came from the pre-tenant app, so
-- attach them to its only workspace. created_by is deliberately not backfilled.
update public.profiles
set organization_id = (select id from public.organizations where slug = 'legacy-decidai-workspace')
where organization_id is null;

update public.ai_analyses analysis
set organization_id = decision_case.organization_id
from public.decision_cases decision_case
where analysis.decision_case_id = decision_case.id
  and analysis.organization_id is null;

update public.human_decisions decision
set organization_id = decision_case.organization_id
from public.decision_cases decision_case
where decision.decision_case_id = decision_case.id
  and decision.organization_id is null;

update public.audit_logs audit_log
set organization_id = decision_case.organization_id
from public.decision_cases decision_case
where audit_log.decision_case_id = decision_case.id
  and audit_log.organization_id is null;

create index if not exists profiles_organization_id_idx on public.profiles (organization_id);
create index if not exists decision_cases_organization_created_idx on public.decision_cases (organization_id, created_at desc);
create index if not exists decision_cases_organization_created_by_idx on public.decision_cases (organization_id, created_by);
create index if not exists ai_analyses_organization_case_idx on public.ai_analyses (organization_id, decision_case_id);
create index if not exists human_decisions_organization_case_idx on public.human_decisions (organization_id, decision_case_id);
create index if not exists audit_logs_organization_case_created_idx on public.audit_logs (organization_id, decision_case_id, created_at asc);

-- SECURITY DEFINER helpers read the caller's own profile without triggering
-- recursive profiles RLS. They expose only the caller's tenant/role.
create or replace function public.current_user_organization_id()
returns uuid
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select profile.organization_id
  from public.profiles profile
  where profile.id = auth.uid()
$$;

create or replace function public.current_user_role()
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select profile.role
  from public.profiles profile
  where profile.id = auth.uid()
$$;

-- Related-record policies use this helper instead of querying through an RLS
-- policy, avoiding recursion while preserving requester ownership rules.
create or replace function public.can_read_decision_case(target_case_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select auth.uid() is not null and exists (
    select 1
    from public.decision_cases decision_case
    where decision_case.id = target_case_id
      and decision_case.organization_id = public.current_user_organization_id()
      and (
        public.current_user_role() in ('admin', 'reviewer')
        or decision_case.created_by = auth.uid()
      )
  )
$$;

revoke all on function public.current_user_organization_id() from public;
revoke all on function public.current_user_role() from public;
revoke all on function public.can_read_decision_case(uuid) from public;
grant execute on function public.current_user_organization_id() to authenticated;
grant execute on function public.current_user_role() to authenticated;
grant execute on function public.can_read_decision_case(uuid) to authenticated;

-- Keep updated_at correct for the two mutable tenant tables.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists organizations_set_updated_at on public.organizations;
create trigger organizations_set_updated_at
before update on public.organizations
for each row execute function public.set_updated_at();

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists organization_invitations_set_updated_at on public.organization_invitations;
create trigger organization_invitations_set_updated_at
before update on public.organization_invitations
for each row execute function public.set_updated_at();

-- Sign-up is idempotent: an existing profile is left intact. A new auth user
-- receives a dedicated workspace and is its initial administrator.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  organization_id uuid;
  organization_name text;
  organization_slug text;
  matching_invitation public.organization_invitations%rowtype;
begin
  if exists (select 1 from public.profiles profile where profile.id = new.id) then
    return new;
  end if;

  -- A pending, unexpired invitation takes precedence over self-service
  -- provisioning only when the caller proves possession of its token. Lock it
  -- so it cannot be consumed concurrently. Trusted invite creation must store
  -- token_hash as encode(digest(raw_token, 'sha256'), 'hex').
  select invitation.*
  into matching_invitation
  from public.organization_invitations invitation
  where lower(btrim(invitation.email)) = lower(btrim(coalesce(new.email, '')))
    and invitation.accepted_at is null
    and invitation.expires_at > now()
    and nullif(new.raw_user_meta_data ->> 'invite_token', '') is not null
    and invitation.token_hash = encode(
      digest(new.raw_user_meta_data ->> 'invite_token', 'sha256'),
      'hex'
    )
  order by invitation.created_at desc
  limit 1
  for update;

  if found then
    insert into public.profiles (id, email, full_name, avatar_url, organization_id, role)
    values (
      new.id,
      new.email,
      nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''),
      nullif(trim(new.raw_user_meta_data ->> 'avatar_url'), ''),
      matching_invitation.organization_id,
      matching_invitation.role
    );

    update public.organization_invitations
    set accepted_at = now()
    where id = matching_invitation.id
      and accepted_at is null
      and expires_at > now();

    return new;
  end if;

  organization_name := coalesce(
    nullif(trim(new.raw_user_meta_data ->> 'organization_name'), ''),
    'My DECIDAI Workspace'
  );
  organization_slug := coalesce(
    nullif(trim(both '-' from lower(regexp_replace(organization_name, '[^a-zA-Z0-9]+', '-', 'g'))), ''),
    'decidai-workspace'
  ) || '-' || replace(new.id::text, '-', '');

  insert into public.organizations (name, slug, created_by)
  values (organization_name, organization_slug, new.id)
  returning id into organization_id;

  insert into public.profiles (id, email, full_name, avatar_url, organization_id, role)
  values (
    new.id,
    new.email,
    nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''),
    nullif(trim(new.raw_user_meta_data ->> 'avatar_url'), ''),
    organization_id,
    'admin'
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

-- RLS is enabled for all tenant-owned data.
alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.organization_invitations enable row level security;
alter table public.decision_cases enable row level security;
alter table public.ai_analyses enable row level security;
alter table public.human_decisions enable row level security;
alter table public.audit_logs enable row level security;

-- Replace only DECIDAI's named policies so re-running this migration updates
-- them cleanly without weakening unrelated project policies.
drop policy if exists "decidai_organizations_select_own" on public.organizations;
drop policy if exists "decidai_organizations_update_admin" on public.organizations;
drop policy if exists "decidai_profiles_select_own_or_admin" on public.profiles;
drop policy if exists "decidai_organization_invitations_select_admin" on public.organization_invitations;
drop policy if exists "decidai_cases_select_visible" on public.decision_cases;
drop policy if exists "decidai_cases_insert_own_org" on public.decision_cases;
drop policy if exists "decidai_ai_analyses_select_visible_case" on public.ai_analyses;
drop policy if exists "decidai_human_decisions_select_visible_case" on public.human_decisions;
drop policy if exists "decidai_audit_logs_select_visible_case" on public.audit_logs;
drop policy if exists "profiles own organization" on public.profiles;
drop policy if exists "organization visible" on public.organizations;
drop policy if exists "cases read by org" on public.decision_cases;
drop policy if exists "cases create by admin requester" on public.decision_cases;
drop policy if exists "analysis read by org" on public.ai_analyses;
drop policy if exists "decisions read by org" on public.human_decisions;
drop policy if exists "audit read by org" on public.audit_logs;

create policy "decidai_organizations_select_own"
on public.organizations for select to authenticated
using (id = public.current_user_organization_id());

create policy "decidai_organizations_update_admin"
on public.organizations for update to authenticated
using (
  id = public.current_user_organization_id()
  and public.current_user_role() = 'admin'
)
with check (
  id = public.current_user_organization_id()
  and public.current_user_role() = 'admin'
);

create policy "decidai_profiles_select_own_or_admin"
on public.profiles for select to authenticated
using (
  id = auth.uid()
  or (
    organization_id = public.current_user_organization_id()
    and public.current_user_role() = 'admin'
  )
);

create policy "decidai_organization_invitations_select_admin"
on public.organization_invitations for select to authenticated
using (
  organization_id = public.current_user_organization_id()
  and public.current_user_role() = 'admin'
);

create policy "decidai_cases_select_visible"
on public.decision_cases for select to authenticated
using (
  organization_id = public.current_user_organization_id()
  and (
    public.current_user_role() in ('admin', 'reviewer')
    or created_by = auth.uid()
  )
);

create policy "decidai_cases_insert_own_org"
on public.decision_cases for insert to authenticated
with check (
  organization_id = public.current_user_organization_id()
  and created_by = auth.uid()
  and public.current_user_role() in ('admin', 'requester')
);

create policy "decidai_ai_analyses_select_visible_case"
on public.ai_analyses for select to authenticated
using (public.can_read_decision_case(decision_case_id));

create policy "decidai_human_decisions_select_visible_case"
on public.human_decisions for select to authenticated
using (public.can_read_decision_case(decision_case_id));

create policy "decidai_audit_logs_select_visible_case"
on public.audit_logs for select to authenticated
using (public.can_read_decision_case(decision_case_id));

-- Browser clients may read only through the policies above. Direct writes to
-- related records and audit history are intentionally unavailable; FastAPI's
-- service role performs trusted writes after validating the JWT and tenant.
revoke all on public.organizations, public.profiles, public.organization_invitations, public.decision_cases,
  public.ai_analyses, public.human_decisions, public.audit_logs from anon;
revoke insert, update, delete on public.organizations, public.profiles, public.organization_invitations,
  public.decision_cases, public.ai_analyses, public.human_decisions,
  public.audit_logs from authenticated;
grant select on public.organizations, public.profiles, public.organization_invitations, public.decision_cases,
  public.ai_analyses, public.human_decisions, public.audit_logs to authenticated;
grant insert on public.decision_cases to authenticated;
grant update (name, slug) on public.organizations to authenticated;

commit;
