--
-- PostgreSQL database dump
--

\restrict tNojhZBpWYBkStkPQiZAzaszFlnZF8pyqEWIz22jPBySg8PSUtpi94KixZ6NfuE

-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: anonymize_audit_logs(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.anonymize_audit_logs(p_user_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE audit_logs
    SET
        user_id = '00000000-0000-0000-0000-000000000000'::uuid,
        details = details - 'name' - 'email' - 'ip_address',
        ip_address = NULL
    WHERE user_id = p_user_id;
END;
$$;


--
-- Name: anonymize_error_logs(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.anonymize_error_logs(p_user_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE error_logs
    SET
        user_id = '00000000-0000-0000-0000-000000000000'::uuid,
        message = REGEXP_REPLACE(message, '\S+@\S+', '[REDACTED]', 'g'),
        stack_trace = NULL
    WHERE user_id = p_user_id;
END;
$$;


--
-- Name: apply_freshness_fsm(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.apply_freshness_fsm() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.freshness_state = 'fresh' AND OLD.freshness_state <> 'fresh' THEN
        NEW.freshness_state = 'fresh';
    END IF;
    RETURN NEW;
END;
$$;


--
-- Name: auth_user_by_email(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.auth_user_by_email(p_email text) RETURNS TABLE(id uuid, email text, password_hash text, name text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    SELECT id, email, password_hash, name
    FROM users
    WHERE email = p_email
    LIMIT 1;
$$;


--
-- Name: delete_user_account(uuid); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.delete_user_account(p_user_id uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Step 1: Anonymize audit logs (keep for legal, remove PII)
    PERFORM anonymize_audit_logs(p_user_id);

    -- Step 2: Anonymize error logs (keep for legal, remove PII)
    PERFORM anonymize_error_logs(p_user_id);

    -- Step 3: Cascade delete all user data (logs stay anonymized)
    DELETE FROM users WHERE id = p_user_id;
END;
$$;


--
-- Name: prevent_audit_log_modification(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_audit_log_modification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Allow anonymization: setting user_id to anonymous UUID
    IF OLD.user_id = NEW.user_id THEN
        RAISE EXCEPTION 'audit_logs are immutable — UPDATE and DELETE are not allowed';
    END IF;
    -- Allow anonymization: setting user_id to anonymous UUID
    IF NEW.user_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_logs are immutable — UPDATE and DELETE are not allowed';
END;
$$;


--
-- Name: prevent_error_log_modification(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_error_log_modification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- Allow anonymization: setting user_id to anonymous UUID
    IF OLD.user_id = NEW.user_id THEN
        RAISE EXCEPTION 'error_logs are immutable — UPDATE and DELETE are not allowed';
    END IF;
    -- Allow anonymization: setting user_id to anonymous UUID
    IF NEW.user_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'error_logs are immutable — UPDATE and DELETE are not allowed';
END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    key_hash text NOT NULL,
    name text NOT NULL,
    prefix text NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.api_keys FORCE ROW LEVEL SECURITY;


--
-- Name: applications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.applications (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    job_id uuid NOT NULL,
    profile_id uuid NOT NULL,
    optimized_resume jsonb NOT NULL,
    cover_letter text,
    pdf_url text NOT NULL,
    field_mappings jsonb NOT NULL,
    required_fields jsonb DEFAULT '[]'::jsonb,
    fill_details jsonb DEFAULT '[]'::jsonb,
    status text DEFAULT 'created'::text NOT NULL,
    skip_reason text,
    screenshot_url text,
    filled_at timestamp with time zone,
    submitted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    snapshot_id uuid,
    CONSTRAINT applications_status_check CHECK ((status = ANY (ARRAY['created'::text, 'filling'::text, 'filled'::text, 'submitted'::text, 'skipped'::text, 'failed'::text])))
);

ALTER TABLE ONLY public.applications FORCE ROW LEVEL SECURITY;


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id uuid,
    details jsonb DEFAULT '{}'::jsonb,
    ip_address inet,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.audit_logs FORCE ROW LEVEL SECURITY;


--
-- Name: auth_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_sessions (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    jti_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.auth_sessions FORCE ROW LEVEL SECURITY;


--
-- Name: checkpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.checkpoints (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    job_id uuid NOT NULL,
    pipeline_state jsonb DEFAULT '{}'::jsonb NOT NULL,
    step text NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT checkpoints_step_check CHECK ((step = ANY (ARRAY['jd_extraction'::text, 'rubric_generation'::text, 'scoring'::text, 'optimization'::text, 'package_generation'::text])))
);

ALTER TABLE ONLY public.checkpoints FORCE ROW LEVEL SECURITY;


--
-- Name: discord_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_connections (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    bot_token text NOT NULL,
    bot_username text,
    status text DEFAULT 'active'::text,
    chat_mode text DEFAULT 'bot'::text,
    notifications_enabled boolean DEFAULT true,
    notification_events text[] DEFAULT '{job_discovered,pipeline_completed,pipeline_failed,application_submitted}'::text[],
    servers jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT discord_connections_chat_mode_check CHECK ((chat_mode = ANY (ARRAY['bot'::text, 'agent'::text]))),
    CONSTRAINT discord_connections_status_check CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text, 'error'::text])))
);

ALTER TABLE ONLY public.discord_connections FORCE ROW LEVEL SECURITY;


--
-- Name: discord_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_messages (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    server_id bigint,
    server_name text,
    channel_id bigint NOT NULL,
    channel_name text,
    message_id bigint NOT NULL,
    author_id bigint NOT NULL,
    is_dm boolean DEFAULT false,
    direction text NOT NULL,
    text text,
    urls_found text[] DEFAULT '{}'::text[],
    job_created boolean DEFAULT false,
    job_id uuid,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT discord_messages_direction_check CHECK ((direction = ANY (ARRAY['inbound'::text, 'outbound'::text])))
);

ALTER TABLE ONLY public.discord_messages FORCE ROW LEVEL SECURITY;


--
-- Name: error_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.error_logs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    component text NOT NULL,
    error_type text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    context jsonb,
    provider text,
    job_id uuid,
    retry_count integer DEFAULT 0 NOT NULL,
    next_action text,
    stack_trace text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT error_logs_severity_check CHECK ((severity = ANY (ARRAY['CRITICAL'::text, 'HIGH'::text, 'MEDIUM'::text, 'LOW'::text, 'INFO'::text])))
);

ALTER TABLE ONLY public.error_logs FORCE ROW LEVEL SECURITY;


--
-- Name: evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evidence (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    application_id uuid,
    user_id uuid NOT NULL,
    type text NOT NULL,
    file_url text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT evidence_type_check CHECK ((type = ANY (ARRAY['screenshot'::text, 'pdf'::text, 'dom_snapshot'::text, 'profile_diff'::text, 'jd_raw'::text, 'message_raw'::text])))
);

ALTER TABLE ONLY public.evidence FORCE ROW LEVEL SECURITY;


--
-- Name: job_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_snapshots (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    content_hash text NOT NULL,
    payload jsonb NOT NULL,
    captured_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jobs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    title text NOT NULL,
    company text NOT NULL,
    url text NOT NULL,
    platform text NOT NULL,
    source text NOT NULL,
    status text DEFAULT 'discovered'::text NOT NULL,
    score integer,
    raw_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    freshness_state text DEFAULT 'fresh'::text NOT NULL,
    content_hash text,
    current_snapshot_id uuid,
    last_fetched_at timestamp with time zone,
    CONSTRAINT jobs_freshness_state_check CHECK ((freshness_state = ANY (ARRAY['fresh'::text, 'stale'::text, 'expired'::text]))),
    CONSTRAINT jobs_platform_check CHECK ((platform = ANY (ARRAY['greenhouse'::text, 'lever'::text, 'linkedin'::text, 'indeed'::text, 'workday'::text, 'generic'::text]))),
    CONSTRAINT jobs_score_check CHECK (((score >= 0) AND (score <= 100))),
    CONSTRAINT jobs_source_check CHECK ((source = ANY (ARRAY['telegram'::text, 'discord'::text, 'manual'::text]))),
    CONSTRAINT jobs_status_check CHECK ((status = ANY (ARRAY['discovered'::text, 'scored'::text, 'approved'::text, 'applying'::text, 'applied'::text, 'rejected'::text, 'skipped'::text, 'failed'::text])))
);

ALTER TABLE ONLY public.jobs FORCE ROW LEVEL SECURITY;


--
-- Name: llm_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.llm_providers (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    base_url text NOT NULL,
    api_key_encrypted text,
    model text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    priority integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT llm_providers_name_check CHECK ((name = ANY (ARRAY['gemini'::text, 'ollama'::text, 'groq'::text, 'openrouter'::text])))
);

ALTER TABLE ONLY public.llm_providers FORCE ROW LEVEL SECURITY;


--
-- Name: pipeline_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pipeline_runs (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    job_id uuid NOT NULL,
    status text DEFAULT 'running'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone,
    steps_run text[] DEFAULT '{}'::text[] NOT NULL,
    total_time_ms integer,
    error_message text,
    trigger text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pipeline_runs_status_check CHECK ((status = ANY (ARRAY['running'::text, 'completed'::text, 'failed'::text, 'paused'::text]))),
    CONSTRAINT pipeline_runs_trigger_check CHECK ((trigger = ANY (ARRAY['manual'::text, 'auto'::text])))
);

ALTER TABLE ONLY public.pipeline_runs FORCE ROW LEVEL SECURITY;


--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.profiles (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    original_pdf_url text NOT NULL,
    json_resume jsonb NOT NULL,
    last_scored_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.profiles FORCE ROW LEVEL SECURITY;


--
-- Name: provider_usage; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provider_usage (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    provider_id uuid NOT NULL,
    job_id uuid,
    prompt_tokens integer DEFAULT 0 NOT NULL,
    completion_tokens integer DEFAULT 0 NOT NULL,
    latency_ms integer NOT NULL,
    success boolean NOT NULL,
    error_type text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.provider_usage FORCE ROW LEVEL SECURITY;


--
-- Name: rate_limit_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rate_limit_state (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    provider_name text NOT NULL,
    user_id uuid NOT NULL,
    state text DEFAULT 'CLOSED'::text NOT NULL,
    failure_count integer DEFAULT 0 NOT NULL,
    last_failure_at timestamp with time zone,
    cooldown_expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT rate_limit_state_state_check CHECK ((state = ANY (ARRAY['OPEN'::text, 'CLOSED'::text, 'HALF_OPEN'::text])))
);

ALTER TABLE ONLY public.rate_limit_state FORCE ROW LEVEL SECURITY;


--
-- Name: settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.settings (
    user_id uuid NOT NULL,
    key text NOT NULL,
    value jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.settings FORCE ROW LEVEL SECURITY;


--
-- Name: telegram_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.telegram_connections (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    bot_token text NOT NULL,
    bot_username text NOT NULL,
    status text DEFAULT 'disconnected'::text NOT NULL,
    groups jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT telegram_connections_status_check CHECK ((status = ANY (ARRAY['connected'::text, 'disconnected'::text, 'error'::text])))
);

ALTER TABLE ONLY public.telegram_connections FORCE ROW LEVEL SECURITY;


--
-- Name: telegram_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.telegram_messages (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    chat_id bigint NOT NULL,
    chat_title text,
    message_id bigint NOT NULL,
    text text,
    urls_found text[] DEFAULT '{}'::text[] NOT NULL,
    job_created boolean DEFAULT false NOT NULL,
    job_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.telegram_messages FORCE ROW LEVEL SECURITY;


--
-- Name: user_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_profiles (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    user_id uuid NOT NULL,
    phone text,
    linkedin_url text,
    github_url text,
    website_url text,
    address text,
    city text,
    state text,
    country text,
    postal_code text,
    date_of_birth date,
    gender text,
    ethnicity text,
    veteran_status text,
    disability_status text,
    work_authorization text,
    custom_fields jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.user_profiles FORCE ROW LEVEL SECURITY;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT public.uuid_generate_v4() NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.users FORCE ROW LEVEL SECURITY;


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: auth_sessions auth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_pkey PRIMARY KEY (id);


--
-- Name: checkpoints checkpoints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkpoints
    ADD CONSTRAINT checkpoints_pkey PRIMARY KEY (id);


--
-- Name: discord_connections discord_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_connections
    ADD CONSTRAINT discord_connections_pkey PRIMARY KEY (id);


--
-- Name: discord_messages discord_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_messages
    ADD CONSTRAINT discord_messages_pkey PRIMARY KEY (id);


--
-- Name: discord_messages discord_messages_user_id_channel_id_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_messages
    ADD CONSTRAINT discord_messages_user_id_channel_id_message_id_key UNIQUE (user_id, channel_id, message_id);


--
-- Name: error_logs error_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.error_logs
    ADD CONSTRAINT error_logs_pkey PRIMARY KEY (id);


--
-- Name: evidence evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_pkey PRIMARY KEY (id);


--
-- Name: job_snapshots job_snapshots_content_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_snapshots
    ADD CONSTRAINT job_snapshots_content_hash_key UNIQUE (content_hash);


--
-- Name: job_snapshots job_snapshots_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_snapshots
    ADD CONSTRAINT job_snapshots_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (id);


--
-- Name: jobs jobs_user_id_url_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_user_id_url_key UNIQUE (user_id, url);


--
-- Name: llm_providers llm_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_pkey PRIMARY KEY (id);


--
-- Name: pipeline_runs pipeline_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_pkey PRIMARY KEY (id);


--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);


--
-- Name: provider_usage provider_usage_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_usage
    ADD CONSTRAINT provider_usage_pkey PRIMARY KEY (id);


--
-- Name: rate_limit_state rate_limit_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rate_limit_state
    ADD CONSTRAINT rate_limit_state_pkey PRIMARY KEY (id);


--
-- Name: rate_limit_state rate_limit_state_provider_name_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rate_limit_state
    ADD CONSTRAINT rate_limit_state_provider_name_user_id_key UNIQUE (provider_name, user_id);


--
-- Name: settings settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_pkey PRIMARY KEY (user_id, key);


--
-- Name: telegram_connections telegram_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_connections
    ADD CONSTRAINT telegram_connections_pkey PRIMARY KEY (id);


--
-- Name: telegram_messages telegram_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_messages
    ADD CONSTRAINT telegram_messages_pkey PRIMARY KEY (id);


--
-- Name: telegram_messages telegram_messages_user_id_chat_id_message_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_messages
    ADD CONSTRAINT telegram_messages_user_id_chat_id_message_id_key UNIQUE (user_id, chat_id, message_id);


--
-- Name: user_profiles user_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (id);


--
-- Name: user_profiles user_profiles_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_user_id_key UNIQUE (user_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_api_keys_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_keys_prefix ON public.api_keys USING btree (prefix);


--
-- Name: idx_api_keys_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_keys_user_id ON public.api_keys USING btree (user_id);


--
-- Name: idx_applications_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_applications_job_id ON public.applications USING btree (job_id);


--
-- Name: idx_applications_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_applications_status ON public.applications USING btree (user_id, status);


--
-- Name: idx_applications_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_applications_user_id ON public.applications USING btree (user_id);


--
-- Name: idx_audit_logs_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_action ON public.audit_logs USING btree (user_id, action);


--
-- Name: idx_audit_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_logs_user_id ON public.audit_logs USING btree (user_id);


--
-- Name: idx_auth_sessions_jti_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_sessions_jti_hash ON public.auth_sessions USING btree (jti_hash);


--
-- Name: idx_auth_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_auth_sessions_user_id ON public.auth_sessions USING btree (user_id);


--
-- Name: idx_checkpoints_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_checkpoints_job_id ON public.checkpoints USING btree (job_id);


--
-- Name: idx_checkpoints_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_checkpoints_user_id ON public.checkpoints USING btree (user_id);


--
-- Name: idx_discord_connections_uid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_connections_uid ON public.discord_connections USING btree (user_id);


--
-- Name: idx_discord_messages_dm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_dm ON public.discord_messages USING btree (user_id, is_dm) WHERE (is_dm = true);


--
-- Name: idx_discord_messages_server; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_server ON public.discord_messages USING btree (user_id, server_id);


--
-- Name: idx_discord_messages_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_user_id ON public.discord_messages USING btree (user_id);


--
-- Name: idx_error_logs_component; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_error_logs_component ON public.error_logs USING btree (component);


--
-- Name: idx_error_logs_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_error_logs_created_at ON public.error_logs USING btree (created_at);


--
-- Name: idx_error_logs_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_error_logs_job_id ON public.error_logs USING btree (job_id);


--
-- Name: idx_error_logs_severity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_error_logs_severity ON public.error_logs USING btree (severity);


--
-- Name: idx_error_logs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_error_logs_user_id ON public.error_logs USING btree (user_id);


--
-- Name: idx_evidence_application_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evidence_application_id ON public.evidence USING btree (application_id);


--
-- Name: idx_evidence_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_evidence_user_id ON public.evidence USING btree (user_id);


--
-- Name: idx_jobs_freshness; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_freshness ON public.jobs USING btree (user_id, freshness_state);


--
-- Name: idx_jobs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_status ON public.jobs USING btree (user_id, status);


--
-- Name: idx_jobs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_jobs_user_id ON public.jobs USING btree (user_id);


--
-- Name: idx_llm_providers_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_providers_priority ON public.llm_providers USING btree (user_id, priority);


--
-- Name: idx_llm_providers_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_llm_providers_user_id ON public.llm_providers USING btree (user_id);


--
-- Name: idx_pipeline_runs_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pipeline_runs_job_id ON public.pipeline_runs USING btree (job_id);


--
-- Name: idx_pipeline_runs_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_pipeline_runs_user_id ON public.pipeline_runs USING btree (user_id);


--
-- Name: idx_profiles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_profiles_user_id ON public.profiles USING btree (user_id);


--
-- Name: idx_provider_usage_job_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_usage_job_id ON public.provider_usage USING btree (job_id);


--
-- Name: idx_provider_usage_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_usage_provider_id ON public.provider_usage USING btree (provider_id);


--
-- Name: idx_provider_usage_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_provider_usage_user_id ON public.provider_usage USING btree (user_id);


--
-- Name: idx_rate_limit_provider_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_rate_limit_provider_user ON public.rate_limit_state USING btree (provider_name, user_id);


--
-- Name: idx_telegram_connections_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telegram_connections_user_id ON public.telegram_connections USING btree (user_id);


--
-- Name: idx_telegram_messages_chat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telegram_messages_chat ON public.telegram_messages USING btree (user_id, chat_id);


--
-- Name: idx_telegram_messages_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_telegram_messages_user_id ON public.telegram_messages USING btree (user_id);


--
-- Name: idx_user_profiles_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_profiles_user_id ON public.user_profiles USING btree (user_id);


--
-- Name: idx_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_users_email ON public.users USING btree (email);


--
-- Name: audit_logs audit_logs_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_logs_immutable BEFORE DELETE OR UPDATE ON public.audit_logs FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_log_modification();


--
-- Name: error_logs error_logs_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER error_logs_immutable BEFORE DELETE OR UPDATE ON public.error_logs FOR EACH ROW EXECUTE FUNCTION public.prevent_error_log_modification();


--
-- Name: checkpoints update_checkpoints_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_checkpoints_updated_at BEFORE UPDATE ON public.checkpoints FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: jobs update_jobs_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_jobs_updated_at BEFORE UPDATE ON public.jobs FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: llm_providers update_llm_providers_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_llm_providers_updated_at BEFORE UPDATE ON public.llm_providers FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: rate_limit_state update_rate_limit_state_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_rate_limit_state_updated_at BEFORE UPDATE ON public.rate_limit_state FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: settings update_settings_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_settings_updated_at BEFORE UPDATE ON public.settings FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: users update_users_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: applications applications_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: applications applications_profile_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.profiles(id) ON DELETE CASCADE;


--
-- Name: applications applications_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.job_snapshots(id) ON DELETE SET NULL;


--
-- Name: applications applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: audit_logs audit_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: auth_sessions auth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: checkpoints checkpoints_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkpoints
    ADD CONSTRAINT checkpoints_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: checkpoints checkpoints_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkpoints
    ADD CONSTRAINT checkpoints_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: discord_connections discord_connections_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_connections
    ADD CONSTRAINT discord_connections_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: discord_messages discord_messages_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_messages
    ADD CONSTRAINT discord_messages_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: discord_messages discord_messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_messages
    ADD CONSTRAINT discord_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: error_logs error_logs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.error_logs
    ADD CONSTRAINT error_logs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: error_logs error_logs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.error_logs
    ADD CONSTRAINT error_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: evidence evidence_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: evidence evidence_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence
    ADD CONSTRAINT evidence_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: jobs fk_jobs_snapshot; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT fk_jobs_snapshot FOREIGN KEY (current_snapshot_id) REFERENCES public.job_snapshots(id) ON DELETE SET NULL;


--
-- Name: jobs jobs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jobs
    ADD CONSTRAINT jobs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: llm_providers llm_providers_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.llm_providers
    ADD CONSTRAINT llm_providers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: pipeline_runs pipeline_runs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE CASCADE;


--
-- Name: pipeline_runs pipeline_runs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pipeline_runs
    ADD CONSTRAINT pipeline_runs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: profiles profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: provider_usage provider_usage_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_usage
    ADD CONSTRAINT provider_usage_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: provider_usage provider_usage_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_usage
    ADD CONSTRAINT provider_usage_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.llm_providers(id) ON DELETE CASCADE;


--
-- Name: provider_usage provider_usage_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provider_usage
    ADD CONSTRAINT provider_usage_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: rate_limit_state rate_limit_state_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rate_limit_state
    ADD CONSTRAINT rate_limit_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: settings settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.settings
    ADD CONSTRAINT settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: telegram_connections telegram_connections_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_connections
    ADD CONSTRAINT telegram_connections_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: telegram_messages telegram_messages_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_messages
    ADD CONSTRAINT telegram_messages_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE SET NULL;


--
-- Name: telegram_messages telegram_messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.telegram_messages
    ADD CONSTRAINT telegram_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_profiles user_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: api_keys; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: applications; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.applications ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: auth_sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: checkpoints; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.checkpoints ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_connections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_connections discord_connections_isolated; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY discord_connections_isolated ON public.discord_connections USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: discord_messages; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_messages discord_messages_isolated; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY discord_messages_isolated ON public.discord_messages USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: error_logs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.error_logs ENABLE ROW LEVEL SECURITY;

--
-- Name: evidence; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.evidence ENABLE ROW LEVEL SECURITY;

--
-- Name: jobs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;

--
-- Name: llm_providers; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.llm_providers ENABLE ROW LEVEL SECURITY;

--
-- Name: pipeline_runs; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.pipeline_runs ENABLE ROW LEVEL SECURITY;

--
-- Name: profiles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: provider_usage; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.provider_usage ENABLE ROW LEVEL SECURITY;

--
-- Name: rate_limit_state; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.rate_limit_state ENABLE ROW LEVEL SECURITY;

--
-- Name: settings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.settings ENABLE ROW LEVEL SECURITY;

--
-- Name: telegram_connections; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.telegram_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: telegram_messages; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.telegram_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: api_keys user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.api_keys USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: applications user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.applications USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: audit_logs user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.audit_logs USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: auth_sessions user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.auth_sessions USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: checkpoints user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.checkpoints USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: discord_connections user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.discord_connections USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: discord_messages user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.discord_messages USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: error_logs user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.error_logs USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: evidence user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.evidence USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: jobs user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.jobs USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: llm_providers user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.llm_providers USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: pipeline_runs user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.pipeline_runs USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: profiles user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.profiles USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: provider_usage user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.provider_usage USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: rate_limit_state user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.rate_limit_state USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: settings user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.settings USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: telegram_connections user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.telegram_connections USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: telegram_messages user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.telegram_messages USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: user_profiles user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.user_profiles USING ((user_id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: users user_isolation; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY user_isolation ON public.users USING ((id = (current_setting('app.user_id'::text))::uuid));


--
-- Name: user_profiles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: users; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

\unrestrict tNojhZBpWYBkStkPQiZAzaszFlnZF8pyqEWIz22jPBySg8PSUtpi94KixZ6NfuE

