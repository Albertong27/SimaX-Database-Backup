"""Run isolated native database round trips without Docker or system services."""

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
HIDDEN = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, timeout=180, **HIDDEN, **kwargs)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("postgresql", "mysql", "all"), default="all")
    args = parser.parse_args()
    engines = ("postgresql", "mysql") if args.engine == "all" else (args.engine,)
    required = {"postgresql": ("initdb", "pg_ctl", "psql", "pg_dump"),
                "mysql": ("mysqld", "mysql", "mysqldump", "mysqladmin")}
    for engine in engines:
        for binary in required[engine]:
            if not shutil.which(binary):
                parser.error(f"Add {binary} to this process's PATH before running live tests.")
    root = ROOT / "build" / ("live-" + uuid.uuid4().hex[:12])
    root.mkdir(parents=True)
    root.chmod(0o700)
    print(f"Private test workspace: {root}", flush=True)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PG", "MYSQL", "SIMAX_"))}
    password = secrets.token_hex(24)
    env["SIMAX_SECRET_LIVE"] = password
    env["PYTHONUTF8"] = "1"
    status = 0
    for engine in engines:
        with ExitStack() as cleanup:
            ports = []
            for role in ("source", "target"):
                home = root / f"{engine}-{role}"
                home.mkdir()
                data = home / "data"
                port = free_port()
                while port in ports:
                    port = free_port()
                ports.append(port)
                log = home / "server.log"
                if engine == "postgresql":
                    pwfile = home / "password"
                    pwfile.write_text(password, encoding="utf-8")
                    pwfile.chmod(0o600)
                    try:
                        with (home / "init.log").open("wb") as output:
                            run(["initdb", "-D", data, "-U", "postgres", "--encoding=UTF8",
                                 "--locale=C", "--auth=scram-sha-256", "--pwfile", pwfile],
                                env=env, stdout=output, stderr=subprocess.STDOUT)
                    finally:
                        pwfile.unlink(missing_ok=True)
                    with (data / "postgresql.conf").open("a", encoding="utf-8") as config:
                        config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\nunix_socket_directories = ''\n")
                    def stop_pg(data=data):
                        if (data / "postmaster.pid").exists():
                            run(["pg_ctl", "-D", data, "-m", "fast", "-w", "stop"], env=env)
                    cleanup.callback(stop_pg)
                    run(["pg_ctl", "-D", data, "-l", log, "-w", "start"], env=env)
                    client_env = {**env, "PGPASSWORD": password, "PGCLIENTENCODING": "UTF8"}
                    run(["psql", "-X", "-h", "127.0.0.1", "-p", port, "-U", "postgres",
                         "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "CREATE DATABASE simax_fixture"], env=client_env)
                else:
                    basedir = Path(shutil.which("mysqld")).resolve().parent.parent
                    base = ["mysqld", "--no-defaults", f"--basedir={basedir}", f"--datadir={data}"]
                    with (home / "init.log").open("wb") as output:
                        run(base + ["--initialize-insecure"], env=env, stdout=output, stderr=subprocess.STDOUT)
                    output = cleanup.enter_context(log.open("wb"))
                    initfile = home / "init.sql"
                    initfile.write_text(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{password}';\nCREATE DATABASE simax_fixture CHARACTER SET utf8mb4;\n", encoding="utf-8")
                    initfile.chmod(0o600)
                    cleanup.callback(lambda path=initfile: path.unlink(missing_ok=True))
                    server_args = base + [f"--port={port}", "--bind-address=127.0.0.1",
                        "--mysqlx=OFF", "--event-scheduler=OFF", "--log-bin-trust-function-creators=ON",
                        f"--init-file={initfile}", "--socket=mysql.sock"]
                    if os.name == "nt":
                        server_args += ["--console"]
                    process = subprocess.Popen(server_args, cwd=home,
                        env=env, stdout=output, stderr=subprocess.STDOUT, **HIDDEN)
                    client_env = {**env, "MYSQL_PWD": password}
                    client = ["mysql", "--no-defaults", "--protocol=TCP", "--host=127.0.0.1",
                              f"--port={port}", "--user=root", "--connect-timeout=2"]
                    def stop_mysql(process=process, port=port, client_env=client_env):
                        if process.poll() is None:
                            try:
                                subprocess.run(["mysqladmin", "--no-defaults", "--protocol=TCP",
                                    "--host=127.0.0.1", f"--port={port}", "--user=root", "shutdown"],
                                    env=client_env, timeout=20, **HIDDEN)
                                process.wait(timeout=20)
                            except subprocess.TimeoutExpired:
                                process.terminate()
                                process.wait(timeout=10)
                    cleanup.callback(stop_mysql)
                    deadline = time.monotonic() + 120
                    while True:
                        result = subprocess.run(client + ["-Nse", "SELECT 1"], env=client_env,
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                timeout=5, **HIDDEN)
                        if result.returncode == 0:
                            break
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(f"MySQL failed to start; inspect {log}")
                        time.sleep(0.5)
                    initfile.unlink()
            test_env = {**env, "SIMAX_LIVE_ENGINE": engine,
                        "SIMAX_LIVE_SOURCE_PORT": str(ports[0]),
                        "SIMAX_LIVE_TARGET_PORT": str(ports[1])}
            print(f"Testing {engine}: private loopback ports {ports}", flush=True)
            result = subprocess.run([sys.executable, "-m", "pytest", "tests/live", "-v", "-s",
                "--tb=short", "--basetemp", str(root / f"pytest-{engine}"),
                "--junitxml", str(root / f"{engine}.xml")], cwd=ROOT, env=test_env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, **HIDDEN)
            (root / f"{engine}-tests.log").write_bytes(result.stdout)
            print(result.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n"), flush=True)
            status = status or result.returncode
    print(f"Owned servers stopped. Synthetic artifacts and reports retained in {root}", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
