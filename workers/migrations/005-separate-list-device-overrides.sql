-- Distinguish website/app overrides from device-only overrides.
ALTER TABLE client_overrides ADD COLUMN has_list_override INTEGER NOT NULL DEFAULT 0;

-- Preserve intentional list overrides; rows created only by admin:device remain inherited.
UPDATE client_overrides
SET has_list_override = 1
WHERE COALESCE(updated_by, '') <> 'admin:device';
