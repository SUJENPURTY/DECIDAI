-- DECIDAI Phase 4: provider-neutral subscription foundation. Do not add provider keys here.
begin;

create table if not exists public.organization_subscriptions (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null unique references public.organizations(id) on delete cascade,
  plan text not null default 'FREE' check (plan in ('FREE', 'PRO', 'BUSINESS')),
  billing_status text not null default 'free' check (billing_status in ('free', 'pending', 'active', 'past_due', 'canceled')),
  provider text not null default 'none',
  provider_customer_id text,
  provider_subscription_id text,
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists organization_subscriptions_provider_customer_idx
  on public.organization_subscriptions (provider, provider_customer_id)
  where provider_customer_id is not null;

insert into public.organization_subscriptions (organization_id, plan, billing_status, provider)
select id, plan, 'free', 'none'
from public.organizations
on conflict (organization_id) do nothing;

drop trigger if exists organization_subscriptions_set_updated_at on public.organization_subscriptions;
create trigger organization_subscriptions_set_updated_at
before update on public.organization_subscriptions
for each row execute function public.set_updated_at();

alter table public.organization_subscriptions enable row level security;
revoke all on public.organization_subscriptions from anon, authenticated;

commit;
