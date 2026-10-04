-- Schéma de la plateforme Fiduce.
-- Multi-tenant : chaque table métier porte une colonne tenant_id.
-- Les utilisateurs de démonstration sont amorcés par le service auth au démarrage.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     TEXT NOT NULL REFERENCES tenants(id),
    username      TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    roles         TEXT[] NOT NULL DEFAULT '{user}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, username)
);

CREATE TABLE IF NOT EXISTS accounts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    code        TEXT NOT NULL,
    name        TEXT NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'EUR',
    UNIQUE (tenant_id, code)
);

CREATE TABLE IF NOT EXISTS entries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    account_id   UUID NOT NULL REFERENCES accounts(id),
    amount_cents BIGINT NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'EUR',
    side         TEXT NOT NULL CHECK (side IN ('debit', 'credit')),
    reference    TEXT,
    external_ref TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'matched', 'unmatched')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entries_tenant_account ON entries (tenant_id, account_id);
CREATE INDEX IF NOT EXISTS idx_entries_tenant_status ON entries (tenant_id, status);

CREATE TABLE IF NOT EXISTS reconciliation_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    matched_count   INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reports (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL REFERENCES tenants(id),
    type         TEXT NOT NULL,
    period       TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'processing', 'ready', 'failed')),
    result       JSONB,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Données de référence (non sensibles).
INSERT INTO tenants (id, name) VALUES
    ('acme', 'ACME Corp'),
    ('globex', 'Globex SA')
ON CONFLICT (id) DO NOTHING;

INSERT INTO accounts (tenant_id, code, name, currency) VALUES
    ('acme', '1000', 'Banque principale', 'EUR'),
    ('acme', '4000', 'Clients', 'EUR'),
    ('globex', '1000', 'Banque principale', 'EUR'),
    ('globex', '4000', 'Clients', 'EUR')
ON CONFLICT (tenant_id, code) DO NOTHING;

-- Quelques écritures d'exemple pour rendre la réconciliation et les rapports
-- immédiatement parlants (la moitié avec référence externe -> "matched").
INSERT INTO entries (tenant_id, account_id, amount_cents, currency, side, reference, external_ref)
SELECT 'acme', a.id, v.amount, 'EUR', v.side, v.ref, v.ext
FROM accounts a
JOIN (VALUES
        ('1000', 150000, 'debit',  'FAC-2024-001', 'BANK-779001'),
        ('1000',  85000, 'debit',  'FAC-2024-002', NULL),
        ('4000', 150000, 'credit', 'FAC-2024-001', 'BANK-779001'),
        ('4000',  42000, 'credit', 'FAC-2024-003', NULL)
     ) AS v(code, amount, side, ref, ext) ON a.code = v.code
WHERE a.tenant_id = 'acme'
ON CONFLICT DO NOTHING;
