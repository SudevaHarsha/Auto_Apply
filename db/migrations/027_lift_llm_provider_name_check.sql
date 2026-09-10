-- File: migrations/027_lift_llm_provider_name_check.sql
-- S4/D19: llm_providers.name no longer restricted to the four launch adapters;
-- the set of valid names is the provider registry (backend/app/llm/registry.py).
-- The DB keeps a lowercase invariant (the app normalises on write); registry
-- membership is enforced at the application layer (see test 8d/8e).

ALTER TABLE llm_providers DROP CONSTRAINT llm_providers_name_check;
ALTER TABLE llm_providers ADD CONSTRAINT llm_providers_name_lowercase CHECK (name = lower(name));
