-- DECIDAI Phase 3 workspace-member management. Run in Supabase SQL Editor.
begin;

create table if not exists public.organization_member_audit_logs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  event_type text not null check (event_type in ('TEAM_MEMBER_ROLE_CHANGED', 'TEAM_MEMBER_REMOVED')),
  actor_user_id uuid not null references auth.users(id),
  target_user_id uuid not null references auth.users(id),
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists organization_member_audit_logs_organization_created_idx
  on public.organization_member_audit_logs (organization_id, created_at desc);

alter table public.organization_member_audit_logs enable row level security;

drop policy if exists "decidai_organization_member_audit_select_admin"
  on public.organization_member_audit_logs;
create policy "decidai_organization_member_audit_select_admin"
on public.organization_member_audit_logs for select to authenticated
using (
  organization_id = public.current_user_organization_id()
  and public.current_user_role() = 'admin'
);

revoke all on public.organization_member_audit_logs from anon;
revoke insert, update, delete on public.organization_member_audit_logs from authenticated;
grant select on public.organization_member_audit_logs to authenticated;

create or replace function public.manage_organization_member(
  p_actor_user_id uuid,
  p_target_user_id uuid,
  p_action text,
  p_new_role text default null
)
returns table (id uuid, organization_id uuid, old_role text, new_role text, removed boolean)
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  actor_profile public.profiles%rowtype;
  target_profile public.profiles%rowtype;
  admin_count integer;
begin
  select profile.* into actor_profile
  from public.profiles profile
  where profile.id = p_actor_user_id
    and profile.role = 'admin';
  if not found then
    raise exception using errcode = '42501', message = 'Only workspace administrators can manage members.';
  end if;

  select profile.* into target_profile
  from public.profiles profile
  where profile.id = p_target_user_id
    and profile.organization_id = actor_profile.organization_id
  for update;
  if not found then
    raise exception using errcode = 'P0001', message = 'The requested workspace member could not be found.';
  end if;

  if p_action = 'change_role' then
    if p_new_role is null or p_new_role not in ('admin', 'reviewer', 'requester') then
      raise exception using errcode = 'P0001', message = 'The member role is invalid.';
    end if;
    if target_profile.role = p_new_role then
      return query select target_profile.id, actor_profile.organization_id, target_profile.role, target_profile.role, false;
      return;
    end if;
    if target_profile.role = 'admin' and p_new_role <> 'admin' then
      perform 1 from public.profiles profile
      where profile.organization_id = actor_profile.organization_id and profile.role = 'admin'
      for update;
      select count(*) into admin_count from public.profiles profile
      where profile.organization_id = actor_profile.organization_id and profile.role = 'admin';
      if admin_count <= 1 then
        raise exception using errcode = 'P0001', message = 'The last workspace admin cannot be demoted.';
      end if;
    end if;
    update public.profiles set role = p_new_role where id = target_profile.id;
    insert into public.organization_member_audit_logs (
      organization_id, event_type, actor_user_id, target_user_id, details
    ) values (
      actor_profile.organization_id, 'TEAM_MEMBER_ROLE_CHANGED', p_actor_user_id, target_profile.id,
      jsonb_build_object('target_user_id', target_profile.id, 'old_role', target_profile.role,
        'new_role', p_new_role, 'acting_admin_user_id', p_actor_user_id)
    );
    return query select target_profile.id, actor_profile.organization_id, target_profile.role, p_new_role, false;
    return;
  end if;

  if p_action = 'remove' then
    if target_profile.role = 'admin' then
      perform 1 from public.profiles profile
      where profile.organization_id = actor_profile.organization_id and profile.role = 'admin'
      for update;
      select count(*) into admin_count from public.profiles profile
      where profile.organization_id = actor_profile.organization_id and profile.role = 'admin';
      if admin_count <= 1 then
        raise exception using errcode = 'P0001', message = 'The last workspace admin cannot be removed.';
      end if;
    end if;
    update public.profiles
    set organization_id = null, role = 'requester'
    where id = target_profile.id;
    insert into public.organization_member_audit_logs (
      organization_id, event_type, actor_user_id, target_user_id, details
    ) values (
      actor_profile.organization_id, 'TEAM_MEMBER_REMOVED', p_actor_user_id, target_profile.id,
      jsonb_build_object('target_user_id', target_profile.id, 'old_role', target_profile.role,
        'acting_admin_user_id', p_actor_user_id)
    );
    return query select target_profile.id, actor_profile.organization_id, target_profile.role, null::text, true;
    return;
  end if;

  raise exception using errcode = 'P0001', message = 'The member management action is invalid.';
end;
$$;

revoke all on function public.manage_organization_member(uuid, uuid, text, text) from public;
grant execute on function public.manage_organization_member(uuid, uuid, text, text) to service_role;

commit;
