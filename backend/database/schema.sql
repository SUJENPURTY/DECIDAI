-- DECIDAI Phase 3: run this manually in the Supabase SQL Editor.
-- The FastAPI backend uses the service-role key. Never put that key in browser code.
create extension if not exists pgcrypto;

create table if not exists decision_cases (
  id uuid primary key default gen_random_uuid(),
  case_id text not null unique,
  title text not null,
  category text not null,
  amount numeric not null,
  requester_name text not null,
  department text not null,
  description text not null,
  supporting_document_name text,
  created_at timestamptz not null default now(),
  status text not null default 'PENDING_HUMAN_REVIEW',
  constraint decision_cases_status_check check (status in ('PENDING_HUMAN_REVIEW', 'APPROVED', 'REJECTED'))
);

create table if not exists ai_analyses (
  id uuid primary key default gen_random_uuid(),
  decision_case_id uuid not null references decision_cases(id) on delete cascade,
  recommendation text not null,
  confidence integer not null,
  summary text not null,
  reasoning text not null,
  evidence jsonb not null default '[]'::jsonb,
  risk_flags jsonb not null default '[]'::jsonb,
  missing_information jsonb not null default '[]'::jsonb,
  human_review_focus jsonb not null default '[]'::jsonb,
  analysis_notice text,
  model_name text not null,
  created_at timestamptz not null default now(),
  constraint ai_analyses_recommendation_check check (recommendation in ('APPROVE', 'REJECT', 'NEEDS_REVIEW')),
  constraint ai_analyses_confidence_check check (confidence between 0 and 100)
);

create table if not exists human_decisions (
  id uuid primary key default gen_random_uuid(),
  decision_case_id uuid not null unique references decision_cases(id) on delete cascade,
  ai_analysis_id uuid not null references ai_analyses(id),
  final_decision text not null,
  decision_reason text not null,
  reviewer_name text not null,
  is_override boolean not null default false,
  created_at timestamptz not null default now(),
  constraint human_decisions_final_decision_check check (final_decision in ('APPROVED', 'REJECTED')),
  constraint human_decisions_reason_check check (length(trim(decision_reason)) > 0),
  constraint human_decisions_reviewer_check check (length(trim(reviewer_name)) > 0)
);

create table if not exists audit_logs (
  id uuid primary key default gen_random_uuid(),
  decision_case_id uuid not null references decision_cases(id) on delete cascade,
  event_type text not null,
  actor_type text not null,
  actor_name text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint audit_logs_event_type_check check (event_type in ('CASE_CREATED', 'AI_ANALYSIS_COMPLETED', 'HUMAN_DECISION_SUBMITTED', 'HUMAN_OVERRIDE')),
  constraint audit_logs_actor_type_check check (actor_type in ('SYSTEM', 'AI', 'HUMAN'))
);

create index if not exists decision_cases_created_at_idx on decision_cases (created_at desc);
create index if not exists decision_cases_status_idx on decision_cases (status);
create index if not exists ai_analyses_case_created_idx on ai_analyses (decision_case_id, created_at desc);
create index if not exists audit_logs_case_created_idx on audit_logs (decision_case_id, created_at asc);
