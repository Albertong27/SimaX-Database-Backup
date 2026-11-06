CREATE SCHEMA app;
CREATE TYPE app.order_state AS ENUM ('new', 'paid');
CREATE TABLE app.customers (id integer PRIMARY KEY, name text NOT NULL UNIQUE);
CREATE TABLE app.orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id integer REFERENCES app.customers(id),
    label text NOT NULL,
    amount numeric(12,2) NOT NULL CHECK (amount >= 0),
    doubled numeric(12,2) GENERATED ALWAYS AS (amount * 2) STORED,
    payload bytea,
    metadata jsonb,
    optional text,
    state app.order_state DEFAULT 'new',
    created timestamptz DEFAULT '2026-01-02 03:04:05+00'
);
CREATE INDEX orders_label ON app.orders(label);
CREATE TABLE app.audit (order_id bigint, action text);
CREATE TABLE public."résumé" ("名前" text);
INSERT INTO public."résumé" VALUES ('こんにちは 🌏');
CREATE FUNCTION app.double_amount(n numeric) RETURNS numeric LANGUAGE sql IMMUTABLE AS $$ SELECT n * 2 $$;
CREATE FUNCTION app.record_order() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO app.audit VALUES (NEW.id, TG_OP);
    RETURN NEW;
END $$;
CREATE TRIGGER order_insert AFTER INSERT ON app.orders FOR EACH ROW EXECUTE FUNCTION app.record_order();
CREATE PROCEDURE app.mark_paid(n bigint) LANGUAGE plpgsql AS $$
BEGIN UPDATE app.orders SET state = 'paid' WHERE id = n; END $$;
CREATE VIEW app.order_summary AS SELECT id, label, app.double_amount(amount) AS total FROM app.orders;
INSERT INTO app.customers VALUES (1, 'SimaX Jakarta');
INSERT INTO app.orders(customer_id, label, amount, payload, metadata, optional) VALUES
    (1, E'café 日本 🌏 quote'' slash\\ tab\t line\nend', 123.45, decode('0001ff005c27','hex'), '{"unicode":"日本","nested":[1,true,null]}', NULL),
    (1, '', 0.00, decode('','hex'), '{}', '');
CREATE MATERIALIZED VIEW app.order_count AS SELECT COUNT(*) AS total FROM app.orders;
