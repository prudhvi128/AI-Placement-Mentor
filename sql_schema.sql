-- ============================================================================
-- AI Placement Mentor — Complete Supabase Schema
-- ============================================================================
-- Paste this entire file into the Supabase SQL Editor and run it once.
-- It is idempotent (safe to re-run).
-- ============================================================================

-- --------------------------------------------------------------------------
-- 0. EXTENSIONS
-- --------------------------------------------------------------------------
create extension if not exists "pgcrypto";

-- ==========================================================================
-- 1. TABLES
-- ==========================================================================

-- 1a. profiles — stores user metadata synced from auth.users
create table if not exists public.profiles (
    user_id    uuid primary key references auth.users(id) on delete cascade,
    email      text not null default '',
    full_name  text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 1b. conversations — a chat session
create table if not exists public.conversations (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null references auth.users(id) on delete cascade,
    title      text not null default 'New Chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    pinned     boolean not null default false
);

-- 1c. messages — individual turns inside a conversation
create table if not exists public.messages (
    id              bigint generated always as identity primary key,
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id         uuid not null references auth.users(id) on delete cascade,
    role            text not null check (role in ('user', 'assistant', 'system')),
    content         text not null,
    timestamp       text not null default '',        -- formatted by Python: "Jun 28, 02:30 PM"
    metadata        jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

alter table public.messages
    add column if not exists metadata jsonb not null default '{}'::jsonb;

-- 1d. user_settings — per-user preferences
create table if not exists public.user_settings (
    user_id    uuid primary key references auth.users(id) on delete cascade,
    theme      text not null default 'dark' check (theme in ('dark', 'light')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 1e. uploaded_files — resume / document uploads
create table if not exists public.uploaded_files (
    id             bigint generated always as identity primary key,
    user_id        uuid not null references auth.users(id) on delete cascade,
    filename       text not null,
    file_type      text not null default '',
    file_size      bigint not null default 0,
    extracted_text text,
    analysis       text,         -- AI-generated analysis / feedback
    created_at     timestamptz not null default now()
);

-- 1f. interview_history — records of mock interview sessions
create table if not exists public.interview_history (
    id             bigint generated always as identity primary key,
    user_id        uuid not null references auth.users(id) on delete cascade,
    question       text not null default '',
    answer         text not null default '',
    feedback       text not null default '',
    score          text not null default '',
    session_id     text not null default '',
    created_at     timestamptz not null default now()
);

-- 1g. interview_reports — structured reports for completed interviews
create table if not exists public.interview_reports (
    id                      bigint generated always as identity primary key,
    user_id                 uuid not null references auth.users(id) on delete cascade,
    session_id              text not null default '',
    overall_score           numeric(4,1) not null default 0,
    technical_score         numeric(4,1) not null default 0,
    communication_score     numeric(4,1) not null default 0,
    confidence_score        numeric(4,1) not null default 0,
    strengths               text not null default '',
    weaknesses              text not null default '',
    improvement_suggestions text not null default '',
    recommended_topics      text not null default '',
    hiring_recommendation   text not null default '',
    report_text             text not null default '',
    created_at              timestamptz not null default now()
);

-- 1h. saved_jobs — bookmarked job postings
create table if not exists public.saved_jobs (
    id         bigint generated always as identity primary key,
    user_id    uuid not null references auth.users(id) on delete cascade,
    job_title  text not null default '',
    company    text not null default '',
    job_url    text not null default '',
    notes      text not null default '',
    status     text not null default 'saved'
               check (status in ('saved', 'applied', 'interviewing', 'offered', 'rejected')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ==========================================================================
-- 2. INDEXES
-- ==========================================================================

-- conversations
create index if not exists idx_conversations_user_id
    on public.conversations(user_id);
create index if not exists idx_conversations_updated_at
    on public.conversations(updated_at desc);
create index if not exists idx_conversations_pinned
    on public.conversations(pinned) where pinned = true;

-- messages
create index if not exists idx_messages_conversation_id
    on public.messages(conversation_id);
create index if not exists idx_messages_user_id
    on public.messages(user_id);
create index if not exists idx_messages_created_at
    on public.messages(created_at);

-- uploaded_files
create index if not exists idx_uploaded_files_user_id
    on public.uploaded_files(user_id);

-- interview_history
create index if not exists idx_interview_history_user_id
    on public.interview_history(user_id);
create index if not exists idx_interview_history_created_at
    on public.interview_history(created_at desc);

-- interview_reports
create index if not exists idx_interview_reports_user_id
    on public.interview_reports(user_id);
create index if not exists idx_interview_reports_created_at
    on public.interview_reports(created_at desc);

-- saved_jobs
create index if not exists idx_saved_jobs_user_id
    on public.saved_jobs(user_id);
create index if not exists idx_saved_jobs_status
    on public.saved_jobs(status);

-- user_memory
create index if not exists idx_user_memory_user_id
    on public.user_memory(user_id);

-- 1i. career_recommendations — standalone career advice results
create table if not exists public.career_recommendations (
    id                      bigint generated always as identity primary key,
    user_id                 uuid not null references auth.users(id) on delete cascade,
    skills                  text not null default '',
    experience_level        text not null default '',
    interests               text not null default '',
    recommendation_markdown text not null default '',
    created_at              timestamptz not null default now()
);

-- 1j. user_weaknesses — tracked weaknesses from interview reports
create table if not exists public.user_weaknesses (
    id                      bigint generated always as identity primary key,
    user_id                 uuid not null references auth.users(id) on delete cascade,
    weakness_text           text not null default '',
    category                text not null default '',
    status                  text not null default 'active',  -- active | improving | resolved
    detected_count          integer not null default 1,
    last_detected_at        timestamptz not null default now(),
    created_at              timestamptz not null default now()
);

-- 1k. learning_roadmaps — personalized learning plans from weaknesses
create table if not exists public.learning_roadmaps (
    id                      bigint generated always as identity primary key,
    user_id                 uuid not null references auth.users(id) on delete cascade,
    weaknesses_input        text not null default '',
    roadmap_markdown        text not null default '',
    created_at              timestamptz not null default now()
);

-- 1l. user_memory — persistent user-scoped key-value memory (survives across chats)
create table if not exists public.user_memory (
    id          bigint generated always as identity primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    key         text not null,
    value       text not null default '',
    updated_at  timestamptz not null default now(),
    created_at  timestamptz not null default now(),
    unique (user_id, key)
);

-- ==========================================================================
-- 3. TRIGGERS
-- ==========================================================================

-- 3a. Auto-update updated_at on row change
create or replace function public.set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

do $$
begin
    if not exists (select 1 from pg_trigger where tgname = 'set_profiles_updated_at') then
        create trigger set_profiles_updated_at
            before update on public.profiles
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'set_conversations_updated_at') then
        create trigger set_conversations_updated_at
            before update on public.conversations
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'set_user_settings_updated_at') then
        create trigger set_user_settings_updated_at
            before update on public.user_settings
            for each row execute function public.set_updated_at();
    end if;
    if not exists (select 1 from pg_trigger where tgname = 'set_saved_jobs_updated_at') then
        create trigger set_saved_jobs_updated_at
            before update on public.saved_jobs
            for each row execute function public.set_updated_at();
    end if;
end;
$$;

-- 3b. Auto-create profile + default settings when a user signs up
create or replace function public.handle_new_user()
returns trigger as $$
begin
    insert into public.profiles (user_id, email)
    values (new.id, new.email);
    insert into public.user_settings (user_id, theme)
    values (new.id, 'dark');
    return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row execute function public.handle_new_user();

-- ==========================================================================
-- 4. ROW LEVEL SECURITY
-- ==========================================================================

-- 4a. Enable RLS on all tables
alter table public.profiles           enable row level security;
alter table public.conversations      enable row level security;
alter table public.messages           enable row level security;
alter table public.user_settings      enable row level security;
alter table public.uploaded_files     enable row level security;
alter table public.interview_history  enable row level security;
alter table public.interview_reports  enable row level security;
alter table public.saved_jobs         enable row level security;
alter table public.career_recommendations enable row level security;
alter table public.user_weaknesses     enable row level security;
alter table public.learning_roadmaps  enable row level security;
alter table public.user_memory        enable row level security;

-- 4b. Helper: is the current user the owner of this row?
create or replace function public.is_owner(owner_id uuid)
returns boolean
language plpgsql stable
as $$
begin
    return auth.uid() = owner_id;
end;
$$;

-- ── profiles ──
create policy "profiles_select_own" on public.profiles
    for select using (is_owner(user_id));
create policy "profiles_insert_own" on public.profiles
    for insert with check (is_owner(user_id));
create policy "profiles_update_own" on public.profiles
    for update using (is_owner(user_id));

-- ── conversations ──
create policy "conversations_select_own" on public.conversations
    for select using (is_owner(user_id));
create policy "conversations_insert_own" on public.conversations
    for insert with check (is_owner(user_id));
create policy "conversations_update_own" on public.conversations
    for update using (is_owner(user_id));
create policy "conversations_delete_own" on public.conversations
    for delete using (is_owner(user_id));

-- ── messages ──
create policy "messages_select_own" on public.messages
    for select using (is_owner(user_id));
create policy "messages_insert_own" on public.messages
    for insert with check (is_owner(user_id));
create policy "messages_delete_own" on public.messages
    for delete using (is_owner(user_id));

-- ── user_settings ──
create policy "user_settings_select_own" on public.user_settings
    for select using (is_owner(user_id));
create policy "user_settings_insert_own" on public.user_settings
    for insert with check (is_owner(user_id));
create policy "user_settings_update_own" on public.user_settings
    for update using (is_owner(user_id));

-- ── uploaded_files ──
create policy "uploaded_files_select_own" on public.uploaded_files
    for select using (is_owner(user_id));
create policy "uploaded_files_insert_own" on public.uploaded_files
    for insert with check (is_owner(user_id));
create policy "uploaded_files_update_own" on public.uploaded_files
    for update using (is_owner(user_id));
create policy "uploaded_files_delete_own" on public.uploaded_files
    for delete using (is_owner(user_id));

-- ── interview_history ──
create policy "interview_history_select_own" on public.interview_history
    for select using (is_owner(user_id));
create policy "interview_history_insert_own" on public.interview_history
    for insert with check (is_owner(user_id));
create policy "interview_history_delete_own" on public.interview_history
    for delete using (is_owner(user_id));

-- ── interview_reports ──
create policy "interview_reports_select_own" on public.interview_reports
    for select using (is_owner(user_id));
create policy "interview_reports_insert_own" on public.interview_reports
    for insert with check (is_owner(user_id));
create policy "interview_reports_delete_own" on public.interview_reports
    for delete using (is_owner(user_id));

-- ── saved_jobs ──
create policy "saved_jobs_select_own" on public.saved_jobs
    for select using (is_owner(user_id));
create policy "saved_jobs_insert_own" on public.saved_jobs
    for insert with check (is_owner(user_id));
create policy "saved_jobs_update_own" on public.saved_jobs
    for update using (is_owner(user_id));
create policy "saved_jobs_delete_own" on public.saved_jobs
    for delete using (is_owner(user_id));

-- ── career_recommendations ──
create policy "career_recommendations_select_own" on public.career_recommendations
    for select using (is_owner(user_id));
create policy "career_recommendations_insert_own" on public.career_recommendations
    for insert with check (is_owner(user_id));
create policy "career_recommendations_delete_own" on public.career_recommendations
    for delete using (is_owner(user_id));

-- ── user_weaknesses ──
create policy "user_weaknesses_select_own" on public.user_weaknesses
    for select using (is_owner(user_id));
create policy "user_weaknesses_insert_own" on public.user_weaknesses
    for insert with check (is_owner(user_id));
create policy "user_weaknesses_update_own" on public.user_weaknesses
    for update using (is_owner(user_id));
create policy "user_weaknesses_delete_own" on public.user_weaknesses
    for delete using (is_owner(user_id));

-- ── learning_roadmaps ──
create policy "learning_roadmaps_select_own" on public.learning_roadmaps
    for select using (is_owner(user_id));
create policy "learning_roadmaps_insert_own" on public.learning_roadmaps
    for insert with check (is_owner(user_id));
create policy "learning_roadmaps_delete_own" on public.learning_roadmaps
    for delete using (is_owner(user_id));

-- ── user_memory ──
create policy "user_memory_select_own" on public.user_memory
    for select using (is_owner(user_id));
create policy "user_memory_insert_own" on public.user_memory
    for insert with check (is_owner(user_id));
create policy "user_memory_update_own" on public.user_memory
    for update using (is_owner(user_id));
create policy "user_memory_delete_own" on public.user_memory
    for delete using (is_owner(user_id));

-- ==========================================================================
-- 5. SERVICE-ROLE PERMISSIONS (used by the anon key in the app)
-- ==========================================================================
-- The Streamlit app connects with the anon key and relies on RLS above.
-- Service-role can be used for admin tasks via the Supabase dashboard.
-- No additional grants are needed — the anon key has full access to
-- authenticated-user-owned rows through the RLS policies.
