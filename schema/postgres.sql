CREATE TABLE IF NOT EXISTS rfqs (
  rfq_id TEXT PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  client_id TEXT,
  instrument_id TEXT NOT NULL,
  product_type TEXT NOT NULL,
  request JSONB NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('RECEIVED', 'QUOTED', 'CONVERTED', 'EXPIRED', 'CANCELLED')),
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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
  quoted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
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

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS trade_id TEXT REFERENCES trades(trade_id);

CREATE TABLE IF NOT EXISTS trade_lifecycle_events (
  event_id TEXT PRIMARY KEY,
  trade_id TEXT NOT NULL REFERENCES trades(trade_id),
  event_type TEXT NOT NULL,
  reason TEXT,
  before_state JSONB,
  after_state JSONB NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rfqs_status_received_idx ON rfqs(status, received_at);
CREATE INDEX IF NOT EXISTS quotes_rfq_version_idx ON quotes(rfq_id, quote_version DESC);
CREATE INDEX IF NOT EXISTS trades_status_updated_idx ON trades(status, updated_at);
CREATE INDEX IF NOT EXISTS lifecycle_trade_time_idx ON trade_lifecycle_events(trade_id, occurred_at);
