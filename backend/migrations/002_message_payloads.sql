-- Let a saved conversation carry its diagnostic card and course matches.
--
-- Run after 001. Idempotent, so re-running is safe.
--
-- Replaying a thread used to restore only what was *said*, because rebuilding
-- the diagnostic card from message text would mean re-deriving a student's
-- profile from its own transcript - the guesswork the slot barrier exists to
-- prevent. The answer is not to re-derive it but to keep it: the card and the
-- match list are stored exactly as they were sent, and replayed verbatim.
--
-- A column on chat_messages rather than on chat_threads, so the card appears
-- at the point in the conversation where it was produced, and so a corrected
-- grade leaves both cards in order rather than overwriting the first.

alter table public.chat_messages
    add column if not exists kind text,
    add column if not exists payload jsonb;

-- `kind` labels what `payload` holds; `content` stays human-readable text for
-- every row, so anything that only knows about `content` still works.
alter table public.chat_messages
    drop constraint if exists chat_messages_kind_check;
alter table public.chat_messages
    add constraint chat_messages_kind_check
    check (kind is null or kind in ('diagnostic_card', 'university_matches'));

-- Replay reads the whole thread in order, so no index is needed on `kind`;
-- it exists to be rendered, not to be searched.
