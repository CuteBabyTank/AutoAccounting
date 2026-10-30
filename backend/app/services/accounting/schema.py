"""Additive column migrations for existing aa_* tables (idempotent; run at startup after create_all).

New databases get these columns from the models via create_all; existing ones get them here.
"""


def column_statements() -> list[str]:
    return [
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
        "ALTER TABLE aa_assets ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
        "ALTER TABLE aa_employees ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ",
        "ALTER TABLE aa_contacts ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS handler_id UUID REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE aa_tasks ADD COLUMN IF NOT EXISTS completed_by UUID REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE aa_tasks ADD COLUMN IF NOT EXISTS assigned_auto BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_work_items ADD COLUMN IF NOT EXISTS assigned_auto BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_firm_settings ADD COLUMN IF NOT EXISTS auto_assign BOOLEAN NOT NULL DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar BYTEA",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_accepted_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS privacy_policy_version VARCHAR(20)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS terms_version VARCHAR(20)",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS seller_branch VARCHAR(5) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS buyer_branch VARCHAR(5) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS operations_start_year INTEGER",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS facts_updated_at TIMESTAMPTZ",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS filed_output_id UUID "
        "REFERENCES aa_outputs(id) ON DELETE SET NULL",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS contact_number VARCHAR(20) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS email VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS taxpayer_classification VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS filed_forms JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_kept JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_start DATE",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory VARCHAR(120) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory_title VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_updated_at TIMESTAMPTZ",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_on DATE",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_via VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS payment_ref VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_document_id UUID "
        "REFERENCES aa_documents(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_settles_document_id ON aa_documents (settles_document_id)",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_source VARCHAR(5) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS counterparty_name VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS not_duplicate_of JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_assets ALTER COLUMN document_id DROP NOT NULL",  # opening assets have no document
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS has_compensation_income BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS payroll_mapping JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS review_notes JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS owner_names JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_audit_events ADD COLUMN IF NOT EXISTS label VARCHAR(200) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_accounts ADD COLUMN IF NOT EXISTS bank_account_no VARCHAR(40) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS review_flags JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS cwt_2307 JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_audit_events ALTER COLUMN company_id DROP NOT NULL",  # firm-level events (settings, tasks)
        "ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS is_adjusting BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_notes TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_files JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE aa_accounts ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS recurring_id UUID "
        "REFERENCES aa_recurring_entries(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_journal_entries_recurring_id ON aa_journal_entries (recurring_id)",
        "ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS writeoff_items JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_bank_lines ADD COLUMN IF NOT EXISTS page INTEGER",
        "ALTER TABLE aa_journal_entries ADD COLUMN IF NOT EXISTS import_batch_id UUID "
        "REFERENCES aa_import_batches(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_journal_entries_import_batch_id ON aa_journal_entries (import_batch_id)",
        "ALTER TABLE aa_opening_items ADD COLUMN IF NOT EXISTS import_batch_id UUID "
        "REFERENCES aa_import_batches(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_opening_items_import_batch_id ON aa_opening_items (import_batch_id)",
    ] + search_index_statements()


# Global search (routers/accounting_search.py): equality lookups on amount / TIN / date, and trigram GIN indexes for
# ILIKE '%text%' when pg_trgm is installed or may be created. Without it (or without USAGE on its schema) the same
# queries still run (slower); each trigram index is guarded so a failure never aborts startup.
_TRGM_INDEXES = (
    ("ix_aa_documents_number_trgm", "aa_documents", "doc_number"),
    ("ix_aa_documents_seller_trgm", "aa_documents", "seller_name"),
    ("ix_aa_documents_buyer_trgm", "aa_documents", "buyer_name"),
    ("ix_aa_contacts_name_trgm", "aa_contacts", "registered_name"),
    ("ix_aa_bank_lines_narration_trgm", "aa_bank_lines", "narration"),
    ("ix_aa_journal_entries_particulars_trgm", "aa_journal_entries", "particulars"),
    ("ix_aa_tasks_title_trgm", "aa_tasks", "title"),
    ("ix_aa_companies_name_trgm", "aa_companies", "registered_name"),
)


def search_index_statements() -> list[str]:
    trgm = "\n".join(
        f"    BEGIN\n      EXECUTE 'CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin ({column} ' || "
        f"quote_ident(s) || '.gin_trgm_ops)';\n    EXCEPTION WHEN OTHERS THEN\n"
        f"      RAISE NOTICE 'trigram index {name} skipped: %', SQLERRM;\n    END;"
        for name, table, column in _TRGM_INDEXES
    )
    return [
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_ent_gross ON aa_documents (enterprise_id, gross_amount)",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_ent_seller_tin ON aa_documents (enterprise_id, seller_tin)",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_ent_buyer_tin ON aa_documents (enterprise_id, buyer_tin)",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_ent_date ON aa_documents (enterprise_id, doc_date)",
        "CREATE INDEX IF NOT EXISTS ix_aa_bank_lines_ent_amount ON aa_bank_lines (enterprise_id, amount)",
        "CREATE INDEX IF NOT EXISTS ix_aa_contacts_ent_tin ON aa_contacts (enterprise_id, tin)",
        "DO $$\nDECLARE s text;\nBEGIN\n"
        "  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN\n"
        "    BEGIN\n      CREATE EXTENSION IF NOT EXISTS pg_trgm;\n"
        "    EXCEPTION WHEN OTHERS THEN\n      RAISE NOTICE 'pg_trgm unavailable: search uses plain indexes';\n"
        "    END;\n  END IF;\n"
        "  SELECT n.nspname INTO s FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
        "WHERE e.extname = 'pg_trgm';\n"
        f"  IF s IS NOT NULL THEN\n{trgm}\n  END IF;\nEND $$",
    ]
