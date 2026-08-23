-- DECIDAI Phase 4: durable invitation usage only.
-- Other usage totals are derived from existing organization-scoped tables.

begin;

create table if not exists public.organization_usage_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  event_type text not null check (event_type = 'INVITATION_SENT'),
  source_invitation_id uuid unique references public.organization_invitations(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists organization_usage_events_organization_event_created_idx
  on public.organization_usage_events (organization_id, event_type, created_at desc);

create or replace function public.record_organization_invitation_usage()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.organization_usage_events (
    organization_id, event_type, source_invitation_id, created_at
  ) values (
    new.organization_id, 'INVITATION_SENT', new.id, new.created_at
  ) on conflict (source_invitation_id) do nothing;
  return new;
end;
$$;

drop trigger if exists organization_invitations_track_usage on public.organization_invitations;
create trigger organization_invitations_track_usage
after insert on public.organization_invitations
for each row execute function public.record_organization_invitation_usage();

-- Count invitations which still exist when this migration is first applied.
insert into public.organization_usage_events (
  organization_id, event_type, source_invitation_id, created_at
)
select organization_id, 'INVITATION_SENT', id, created_at
from public.organization_invitations
on conflict (source_invitation_id) do nothing;

alter table public.organization_usage_events enable row level security;

revoke all on public.organization_usage_events from anon, authenticated;
revoke all on function public.record_organization_invitation_usage() from public;

commit;
