CREATE TABLE IF NOT EXISTS rfqs (
  rfq_id TEXT PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  client_id TEXT,
  instrument_id TEXT NOT NULL,
  product_type TEXT NOT NULL,
  request JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('RECEIVED', 'QUOTED', 'CONVERTED', 'EXPIRED', 'CANCELLED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quotes (
  quote_id TEXT PRIMARY KEY,
  rfq_id TEXT NOT NULL REFERENCES rfqs(rfq_id),
  quote_version INTEGER NOT NULL CHECK (quote_version > 0),
  pricing_request JSONB NOT NULL,
  quote JSONB NOT NULL,
  pv_amount NUMERIC,
  pv_currency TEXT,
  price_pct_of_notional NUMERIC,
  status TEXT NOT NULL CHECK (status IN ('DRAFT', 'VALID', 'ACCEPTED', 'REJECTED', 'EXPIRED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  quoted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  trade_id TEXT,
  UNIQUE (rfq_id, quote_version)
);

CREATE TABLE IF NOT EXISTS trades (
  trade_id TEXT PRIMARY KEY,
  rfq_id TEXT REFERENCES rfqs(rfq_id),
  accepted_quote_id TEXT REFERENCES quotes(quote_id),
  instrument_id TEXT NOT NULL,
  product_type TEXT NOT NULL,
  terms JSONB NOT NULL DEFAULT '{}'::jsonb,
  notional NUMERIC NOT NULL CHECK (notional > 0),
  currency TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('QUOTED', 'LIVE', 'AMENDED', 'CANCELLED', 'MATURED', 'TERMINATED')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ;
UPDATE rfqs SET created_at = COALESCE(created_at, received_at, now()), updated_at = COALESCE(updated_at, received_at, now()), received_at = COALESCE(received_at, created_at, now()) WHERE created_at IS NULL OR updated_at IS NULL OR received_at IS NULL;
ALTER TABLE rfqs ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE rfqs ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE rfqs ALTER COLUMN received_at SET DEFAULT now();
ALTER TABLE rfqs ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE rfqs ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE rfqs ALTER COLUMN received_at SET NOT NULL;

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS quoted_at TIMESTAMPTZ;
ALTER TABLE quotes ADD COLUMN IF NOT EXISTS trade_id TEXT;
UPDATE quotes SET created_at = COALESCE(created_at, quoted_at, now()), updated_at = COALESCE(updated_at, quoted_at, now()), quoted_at = COALESCE(quoted_at, created_at, now()) WHERE created_at IS NULL OR updated_at IS NULL OR quoted_at IS NULL;
ALTER TABLE quotes ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE quotes ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE quotes ALTER COLUMN quoted_at SET DEFAULT now();
ALTER TABLE quotes ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE quotes ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE quotes ALTER COLUMN quoted_at SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'quotes_trade_id_fk') THEN
    ALTER TABLE quotes ADD CONSTRAINT quotes_trade_id_fk FOREIGN KEY (trade_id) REFERENCES trades(trade_id) NOT VALID;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS trade_lifecycle_events (
  event_id TEXT PRIMARY KEY,
  trade_id TEXT NOT NULL REFERENCES trades(trade_id),
  event_type TEXT NOT NULL,
  reason TEXT,
  before_state JSONB,
  after_state JSONB NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE trade_lifecycle_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;
ALTER TABLE trade_lifecycle_events ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE trade_lifecycle_events ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;
UPDATE trade_lifecycle_events SET created_at = COALESCE(created_at, occurred_at, now()), updated_at = COALESCE(updated_at, occurred_at, now()), occurred_at = COALESCE(occurred_at, created_at, now()) WHERE created_at IS NULL OR updated_at IS NULL OR occurred_at IS NULL;
ALTER TABLE trade_lifecycle_events ALTER COLUMN created_at SET DEFAULT now();
ALTER TABLE trade_lifecycle_events ALTER COLUMN updated_at SET DEFAULT now();
ALTER TABLE trade_lifecycle_events ALTER COLUMN occurred_at SET DEFAULT now();
ALTER TABLE trade_lifecycle_events ALTER COLUMN created_at SET NOT NULL;
ALTER TABLE trade_lifecycle_events ALTER COLUMN updated_at SET NOT NULL;
ALTER TABLE trade_lifecycle_events ALTER COLUMN occurred_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS rfqs_created_status_idx ON rfqs(created_at, status);
CREATE INDEX IF NOT EXISTS quotes_created_status_idx ON quotes(created_at, status);
CREATE INDEX IF NOT EXISTS trades_created_status_idx ON trades(created_at, status);
CREATE INDEX IF NOT EXISTS lifecycle_created_type_idx ON trade_lifecycle_events(created_at, event_type);
CREATE INDEX IF NOT EXISTS rfqs_status_received_idx ON rfqs(status, received_at);
CREATE INDEX IF NOT EXISTS quotes_rfq_version_idx ON quotes(rfq_id, quote_version DESC);
CREATE INDEX IF NOT EXISTS trades_status_updated_idx ON trades(status, updated_at);
CREATE INDEX IF NOT EXISTS lifecycle_trade_time_idx ON trade_lifecycle_events(trade_id, occurred_at);
