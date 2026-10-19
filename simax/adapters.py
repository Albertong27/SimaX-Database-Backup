"""Native logical SQL adapters. No shell execution or passwords in command arguments."""

import os
import re
import shutil
import subprocess
from pathlib import Path


class AdapterError(ValueError):
    pass


class NativeAdapter:
    tools = {"postgresql": ("psql", "pg_dump"), "mysql": ("mysql", "mysqldump")}

    def availability(self):
        return {engine: {tool: bool(shutil.which(tool)) for tool in tools}
                for engine, tools in self.tools.items()}

    def command(self, source, export=False):
        if source["engine"] not in self.tools:
            raise AdapterError("This engine is planned; execution is not available in this release.")
        tool = self.tools[source["engine"]][int(export)]
        executable = shutil.which(tool)
        if not executable:
            raise AdapterError(f"Install {tool} on the runtime host and add it to PATH, then restart SimaX.")
        password = os.environ.get(source["password_env"])
        if password is None:
            raise AdapterError(f"Set {source['password_env']} on the runtime host, then restart SimaX.")
        # Strip inherited client overrides; connection identity always comes from the saved source.
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PG", "MYSQL", "SIMAX_SECRET_"))}
        if source["engine"] == "postgresql":
            env.update(PGPASSWORD=password, PGSSLMODE=source["tls"], PGCONNECT_TIMEOUT="10",
                       PGCLIENTENCODING="UTF8")
            if os.environ.get("SIMAX_PG_SSL_ROOT_CERT"):
                env["PGSSLROOTCERT"] = os.environ["SIMAX_PG_SSL_ROOT_CERT"]
            args = [executable, "--no-password", "--host", source["host"], "--port", str(source["port"]),
                    "--username", source["username"], "--dbname", source["database"]]
            if not export:
                args += ["-X", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-A", "-t"]
        else:
            env["MYSQL_PWD"] = password
            args = [executable, "--no-defaults", "--host=" + source["host"],
                    "--port=" + str(source["port"]), "--user=" + source["username"],
                    "--protocol=TCP", "--default-character-set=utf8mb4",
                    "--ssl-mode=" + ("DISABLED" if source["tls"] == "disable" else "VERIFY_IDENTITY")]
            if os.environ.get("SIMAX_MYSQL_SSL_CA"):
                args += ["--ssl-ca=" + os.environ["SIMAX_MYSQL_SSL_CA"]]
            if not export:
                args += ["--batch", "--skip-column-names", "--binary-mode", "--raw"]
        return args, env

    def invoke(self, args, env, *, output=None, input_file=None, input_data=None, timeout=30):
        try:
            result = subprocess.run(args, env=env,
                                    stdin=None if input_data is not None else input_file or subprocess.DEVNULL,
                                    input=input_data,
                                    stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=timeout, shell=False, check=False)
        except subprocess.TimeoutExpired:
            raise AdapterError("Native tool timed out. Check connectivity or workload size; inspect the target before retrying a restore.") from None
        except OSError:
            raise AdapterError("Native tool could not start. Check installation and runtime permissions.") from None
        if result.returncode:
            # Native errors can contain data, SQL, connection details or passwords. Never persist them.
            raise AdapterError(f"Native tool exited with code {result.returncode}. Check connectivity, TLS, privileges and tool compatibility. Raw output is withheld to protect data.")
        return (result.stdout or b"").decode("utf-8", errors="replace").strip()

    def query(self, source, sql):
        args, env = self.command(source)
        if source["engine"] == "mysql":
            args += ["--database=" + source["database"]]
        # Windows native argv uses the active code page. Feed SQL bytes directly so
        # Unicode identifiers/data survive regardless of the host console locale.
        return self.invoke(args, env, input_data=(sql + ";\n").encode("utf-8"))

    def inspect(self, source):
        version = self.query(source, "SELECT version()")
        if "MariaDB" in version:
            raise AdapterError("MariaDB is not yet validated by this MySQL adapter.")
        match = re.search(r"(?:PostgreSQL\s+)?(\d+)\.(\d+)", version)
        if not match:
            raise AdapterError("Could not identify the database server version.")
        major = int(match[1])
        if source["engine"] == "postgresql":
            if major < 14:
                raise AdapterError("This preview requires PostgreSQL 14 or later.")
            sql = "SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1"
        else:
            if major != 8:
                raise AdapterError("This preview requires MySQL 8.x.")
            sql = "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
            nontransactional = self.query(source, "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' AND ENGINE <> 'InnoDB'")
            if nontransactional != "0":
                raise AdapterError("Consistent MySQL exports require all selected tables to use InnoDB.")
        tables = self.query(source, sql).splitlines()
        # Preflight checks both tools, without claiming all export privileges were tested.
        args, env = self.command(source, export=True)
        tool_version = self.invoke([args[0], "--version"], env)
        if source["engine"] == "postgresql":
            tool_major = re.search(r"(\d+)\.", tool_version)
            if not tool_major or int(tool_major[1]) != major:
                raise AdapterError("Use a pg_dump client matching the server major version for this preview.")
        return {"version": version[:160], "major": major, "tables": tables,
                "tool_version": tool_version[:160]}

    def ensure_empty(self, source):
        if source["engine"] == "postgresql":
            sql = """SELECT
                (SELECT COUNT(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                 AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')) +
                (SELECT COUNT(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                 WHERE n.nspname NOT IN ('pg_catalog','information_schema')) +
                (SELECT COUNT(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
                 WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                 AND n.nspname NOT LIKE 'pg_toast%') +
                (SELECT COUNT(*) FROM pg_namespace WHERE nspname NOT IN ('public','information_schema')
                 AND nspname NOT LIKE 'pg_%') +
                (SELECT COUNT(*) FROM pg_extension WHERE extname <> 'plpgsql')"""
        else:
            sql = """SELECT (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()) + (SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE()) + (SELECT COUNT(*) FROM information_schema.EVENTS WHERE EVENT_SCHEMA=DATABASE())"""
        if self.query(source, sql) != "0":
            raise AdapterError("Target must be an empty, dedicated database. Existing objects will not be replaced.")

    def export(self, source, path: Path):
        args, env = self.command(source, export=True)
        if source["engine"] == "postgresql":
            args += ["--format=plain", "--no-owner", "--no-privileges"]
        else:
            args += ["--single-transaction", "--quick", "--routines", "--events", "--triggers",
                     "--hex-blob", "--no-tablespaces", "--set-gtid-purged=OFF",
                     "--skip-add-drop-table", source["database"]]
        with path.open("xb") as output:
            self.invoke(args, env, output=output, timeout=3600)
            output.flush()
            os.fsync(output.fileno())
        if path.stat().st_size == 0:
            raise AdapterError("Export produced an empty file; no recovery point was created.")

    def restore(self, target, path: Path):
        args, env = self.command(target)
        if target["engine"] == "postgresql":
            args += ["--single-transaction"]
        else:
            args += ["--database=" + target["database"]]
        with path.open("rb") as input_file:
            self.invoke(args, env, input_file=input_file, timeout=3600)
