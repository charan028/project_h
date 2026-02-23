-- 1. Create the Chat Logs Table
CREATE TABLE chat_logs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL
);

-- 2. Create the Search & Analysis Logs Table
CREATE TABLE search_logs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    files_analyzed TEXT,
    flooded_nodes_count INTEGER DEFAULT 0,
    surcharged_conduits_count INTEGER DEFAULT 0
);

-- 3. Security (Optional but good practice: Allow anon inserts if RLS is enabled)
-- If Row Level Security (RLS) is enabled on Supabase, you must allow inserts from the anon key.
-- Alternatively, just leave RLS disabled for these two tables during development.
