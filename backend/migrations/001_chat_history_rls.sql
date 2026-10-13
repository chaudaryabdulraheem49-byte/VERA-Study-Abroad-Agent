-- Chat history for signed-in students.
--
-- Run against the Supabase project that holds this app's auth users, either
-- through the SQL editor or `supabase db push`. Idempotent, so re-running it
-- is safe.
--
-- Two tables rather than one: a thread is what the sidebar lists and what gets
-- a title, while messages are append-only and far more numerous. Keeping them
-- apart means listing somebody's conversations never reads their message
-- bodies.
--
-- Note on isolation: every policy below is an RLS policy, which the service
-- role bypasses by design. The backend therefore verifies the JWT itself and
-- filters by user_id in its own queries - see backend/app/chat_history.py. RLS
-- is the guarantee for anything reaching Postgres with a user's own token
-- (the browser client), not a substitute for checking on the server.

create extension if not exists "pgcrypto";

-- --------------------------------------------------------------------------
-- Tables
-- --------------------------------------------------------------------------

create table if not exists public.chat_threads (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users (id) on delete cascade,
    title       text not null default 'New conversation',
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create table if not exists public.chat_messages (
    id          uuid primary key default gen_random_uuid(),
    thread_id   uuid not null references public.chat_threads (id) on delete cascade,
    -- Denormalised from the thread on purpose: the RLS policy below can then
    -- check ownership without a join, which it is evaluated for on every row.
    user_id     uuid not null references auth.users (id) on delete cascade,
    sender      text not null check (sender in ('user', 'assistant', 'system')),
    content     text not null,
    created_at  timestamptz not null default now()
);

-- The sidebar's query: this user's threads, most recently active first.
create index if not exists chat_threads_user_updated_idx
    on public.chat_threads (user_id, updated_at desc);

-- Replaying one conversation, oldest first.
create index if not exists chat_messages_thread_created_idx
    on public.chat_messages (thread_id, created_at);

-- --------------------------------------------------------------------------
-- Row Level Security
--
-- Enabled before any policy exists, so a window where the tables are readable
-- never opens. With RLS on and no policy, the default is deny.
-- --------------------------------------------------------------------------

alter table public.chat_threads  enable row level security;
alter table public.chat_messages enable row level security;

-- Separate policies per command rather than one `for all`: `with check` governs
-- what may be written and `using` what may be read, and a single combined
-- policy makes it easy to grant one while meaning the other.

drop policy if exists chat_threads_select on public.chat_threads;
create policy chat_threads_select on public.chat_threads
    for select using (auth.uid() = user_id);

drop policy if exists chat_threads_insert on public.chat_threads;
create policy chat_threads_insert on public.chat_threads
    for insert with check (auth.uid() = user_id);

drop policy if exists chat_threads_update on public.chat_threads;
create policy chat_threads_update on public.chat_threads
    for update using (auth.uid() = user_id)
    -- Both clauses: `using` picks the rows that may be updated, `with check`
    -- stops the update reassigning user_id to somebody else.
    with check (auth.uid() = user_id);

drop policy if exists chat_threads_delete on public.chat_threads;
create policy chat_threads_delete on public.chat_threads
    for delete using (auth.uid() = user_id);

drop policy if exists chat_messages_select on public.chat_messages;
create policy chat_messages_select on public.chat_messages
    for select using (auth.uid() = user_id);

drop policy if exists chat_messages_insert on public.chat_messages;
create policy chat_messages_insert on public.chat_messages
    for insert with check (
        auth.uid() = user_id
        -- A message may only be filed under a thread the same person owns.
        -- Without this, a valid user_id would let anyone append to any thread.
        and exists (
            select 1 from public.chat_threads t
            where t.id = thread_id and t.user_id = auth.uid()
        )
    );

drop policy if exists chat_messages_delete on public.chat_messages;
create policy chat_messages_delete on public.chat_messages
    for delete using (auth.uid() = user_id);

-- Deliberately no update policy on chat_messages: a transcript is a record of
-- what was said. Editing it after the fact is not something this app does, and
-- the absence of a policy is what enforces that.

-- --------------------------------------------------------------------------
-- Keep `updated_at` honest, so the sidebar's ordering means something
-- --------------------------------------------------------------------------

create or replace function public.touch_thread_updated_at()
returns trigger
language plpgsql
security definer
-- Pinned: a security definer function with a caller-controlled search_path is
-- the standard way these get hijacked.
set search_path = public, pg_temp
as $$
begin
    update public.chat_threads
       set updated_at = now()
     where id = new.thread_id;
    return new;
end;
$$;

drop trigger if exists chat_messages_touch_thread on public.chat_messages;
create trigger chat_messages_touch_thread
    after insert on public.chat_messages
    for each row execute function public.touch_thread_updated_at();
