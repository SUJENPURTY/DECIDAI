-- DECIDAI Phase 4: organization plan foundation. No payment integration.
begin;

alter table public.organizations add column if not exists plan text;

update public.organizations
set plan = case
  when upper(plan) in ('FREE', 'PRO', 'BUSINESS') then upper(plan)
  else 'FREE'
end;

alter table public.organizations alter column plan set default 'FREE';
alter table public.organizations alter column plan set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.organizations'::regclass
      and conname = 'organizations_plan_check'
  ) then
    alter table public.organizations
      add constraint organizations_plan_check
      check (plan in ('FREE', 'PRO', 'BUSINESS'));
  end if;
end;
$$;

commit;
