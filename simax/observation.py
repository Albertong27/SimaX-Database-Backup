"""Read-only table snapshots. No source objects or replication slots are installed."""

import hashlib
import json
import tempfile


def literal(value, postgres):
    encoded = value.encode("utf-8").hex()
    return f"convert_from(decode('{encoded}','hex'),'UTF8')" if postgres else f"CONVERT(0x{encoded} USING utf8mb4)"


def quote(value, postgres):
    delimiter = '"' if postgres else '`'
    return delimiter + value.replace(delimiter, delimiter * 2) + delimiter


def fingerprint(adapter, source, selected, scratch, stopped=lambda: False):
    pg = source["engine"] == "postgresql"
    if pg:
        inventory_sql = "SELECT json_build_array(schemaname,tablename) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY schemaname,tablename"
    else:
        inventory_sql = "SELECT JSON_ARRAY(TABLE_SCHEMA,TABLE_NAME) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
    inventory = [json.loads(line) for line in adapter.query(source, inventory_sql).splitlines()]
    names = [(f"{schema}.{name}" if pg else name, schema, name) for schema, name in inventory]
    if selected:
        if not set(selected).issubset({label for label, _, _ in names}):
            raise ValueError("A watched table is missing or not visible. Check selection and SELECT privileges.")
        names = [entry for entry in names if entry[0] in selected]
    if len(names) > 100 or len({label for label, _, _ in names}) != len(names):
        raise ValueError("Change observation supports at most 100 unambiguously named tables per policy.")
    checksum = hashlib.sha256()
    for label, schema, name in names:
        if stopped():
            raise ValueError("Change observation stopped; continuity is not guaranteed.")
        condition = f"table_schema={literal(schema, pg)} AND table_name={literal(name, pg)}"
        if pg:
            columns = adapter.query(source, f"SELECT row_to_json(c) FROM information_schema.columns c WHERE {condition} ORDER BY ordinal_position")
            row_expression = "encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),'hex')"
        else:
            columns = adapter.query(source, f"SELECT JSON_ARRAY(COLUMN_NAME,ORDINAL_POSITION,COLUMN_TYPE,IS_NULLABLE,COLUMN_DEFAULT,EXTRA,GENERATION_EXPRESSION,CHARACTER_SET_NAME,COLLATION_NAME) FROM information_schema.COLUMNS WHERE {condition} ORDER BY ORDINAL_POSITION")
            column_names = [json.loads(line)[0] for line in columns.splitlines()]
            if not column_names:
                raise ValueError("Column metadata is unavailable; check observation privileges.")
            row_expression = "SHA2(CAST(JSON_ARRAY(" + ",".join(f"HEX(CAST({quote(col, False)} AS BINARY))" for col in column_names) + ") AS CHAR),256)"
        checksum.update(json.dumps([label, columns], ensure_ascii=True).encode())
        table = f"{quote(schema, pg)}.{quote(name, pg)}"
        sql = f"SELECT {row_expression} FROM {table} t ORDER BY 1"
        args, env = adapter.command(source)
        if pg:
            args += ["--quiet"]
            sql = "BEGIN READ ONLY; SET LOCAL statement_timeout='30s'; SET LOCAL row_security=off; SET LOCAL TIME ZONE 'UTC'; " + sql + "; COMMIT"
        else:
            args += ["--database=" + source["database"]]
            sql = "SET SESSION time_zone='+00:00'; START TRANSACTION READ ONLY; " + sql + "; COMMIT"
        # Only ordered row hashes reach this short-lived private file, never row values.
        with tempfile.TemporaryFile(dir=scratch) as output:
            adapter.invoke(args, env, output=output, input_data=(sql + ";\n").encode(), timeout=35)
            output.seek(0)
            checksum.update(hashlib.file_digest(output, "sha256").digest())
    return checksum.hexdigest()
