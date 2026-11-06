CREATE TABLE customers (id integer PRIMARY KEY, name varchar(100) NOT NULL UNIQUE) ENGINE=InnoDB;
CREATE TABLE orders (
    id bigint AUTO_INCREMENT PRIMARY KEY,
    customer_id integer,
    label text NOT NULL,
    amount decimal(12,2) NOT NULL CHECK (amount >= 0),
    doubled decimal(12,2) GENERATED ALWAYS AS (amount * 2) STORED,
    payload longblob,
    metadata json,
    optional text,
    state enum('new','paid') DEFAULT 'new',
    created timestamp DEFAULT '2026-01-02 03:04:05',
    FOREIGN KEY (customer_id) REFERENCES customers(id)
) ENGINE=InnoDB;
CREATE INDEX orders_label ON orders(label(32));
CREATE TABLE audit (order_id bigint, action varchar(20)) ENGINE=InnoDB;
CREATE TABLE `résumé` (`名前` text) ENGINE=InnoDB;
INSERT INTO `résumé` VALUES ('こんにちは 🌏');
DELIMITER $$
CREATE FUNCTION double_amount(n decimal(12,2)) RETURNS decimal(12,2) DETERMINISTIC NO SQL
BEGIN RETURN n * 2; END$$
CREATE TRIGGER order_insert AFTER INSERT ON orders FOR EACH ROW
BEGIN INSERT INTO audit VALUES (NEW.id, 'INSERT'); END$$
CREATE PROCEDURE mark_paid(IN n bigint)
BEGIN UPDATE orders SET state = 'paid' WHERE id = n; END$$
CREATE EVENT dormant_event ON SCHEDULE EVERY 1 DAY DISABLE DO
BEGIN INSERT INTO audit VALUES (0, 'EVENT'); END$$
DELIMITER ;
CREATE VIEW order_summary AS SELECT id, label, double_amount(amount) AS total FROM orders;
INSERT INTO customers VALUES (1, 'SimaX Jakarta');
INSERT INTO orders(customer_id, label, amount, payload, metadata, optional) VALUES
    (1, 'café 日本 🌏 quote\' slash\\ tab\t line\nend', 123.45, X'0001ff005c27', '{"unicode":"日本","nested":[1,true,null]}', NULL),
    (1, '', 0.00, X'', '{}', '');
