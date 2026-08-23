-- DECIDAI Phase 3: persistent in-app notifications.
-- Apply in Supabase SQL Editor after the existing Phase 1/2 schema.

begin;

create table if not exists public.organization_notifications (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  event_type text not null check (event_type in (
    'CASE_CREATED', 'AI_ANALYSIS_COMPLETED', 'HUMAN_DECISION_SUBMITTED',
    'TEAM_INVITE_CREATED', 'TEAM_INVITE_ACCEPTED',
    'TEAM_MEMBER_ROLE_CHANGED', 'TEAM_MEMBER_REMOVED'
  )),
  recipient_user_id uuid references auth.users(id) on delete cascade,
  visible_to_roles text[] not null default '{}'::text[] check (
    visible_to_roles <@ array['admin', 'reviewer', 'requester']::text[]
  ),
  title text not null,
  body text not null,
  decision_case_id uuid references public.decision_cases(id) on delete cascade,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (recipient_user_id is not null or cardinality(visible_to_roles) > 0)
);

create table if not exists public.notification_reads (
  notification_id uuid not null references public.organization_notifications(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  read_at timestamptz not null default now(),
  primary key (notification_id, user_id)
);

create index if not exists organization_notifications_organization_created_idx
  on public.organization_notifications (organization_id, created_at desc);
create index if not exists organization_notifications_recipient_created_idx
  on public.organization_notifications (recipient_user_id, created_at desc)
  where recipient_user_id is not null;
create index if not exists notification_reads_user_idx
  on public.notification_reads (user_id, notification_id);

alter table public.organization_notifications enable row level security;
alter table public.notification_reads enable row level security;

drop policy if exists "decidai_notifications_select_visible" on public.organization_notifications;
create policy "decidai_notifications_select_visible"
on public.organization_notifications for select to authenticated
using (
  organization_id = public.current_user_organization_id()
  and (
    recipient_user_id = auth.uid()
    or public.current_user_role() = any (visible_to_roles)
  )
);

drop policy if exists "decidai_notification_reads_select_own" on public.notification_reads;
create policy "decidai_notification_reads_select_own"
on public.notification_reads for select to authenticated
using (user_id = auth.uid());

drop policy if exists "decidai_notification_reads_insert_own" on public.notification_reads;
create policy "decidai_notification_reads_insert_own"
on public.notification_reads for insert to authenticated
with check (user_id = auth.uid());

revoke all on public.organization_notifications, public.notification_reads from anon;
revoke insert, update, delete on public.organization_notifications from authenticated;
revoke update, delete on public.notification_reads from authenticated;
grant select on public.organization_notifications to authenticated;
grant select, insert on public.notification_reads to authenticated;

commit;
