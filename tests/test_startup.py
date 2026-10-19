import os

from simax.__main__ import load_environment, main


def test_dotenv_loads_before_app_and_preserves_literal_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIMAX_SECRET_STARTUP", raising=False)
    monkeypatch.delenv("SIMAX_DATA_DIR", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "0")
    (tmp_path / ".env").write_text(
        "SIMAX_SECRET_STARTUP='literal-${NOT_A_VARIABLE}-#-value'\nSIMAX_DATA_DIR=custom-data\n",
        encoding="utf-8-sig")
    monkeypatch.setattr("sys.argv", ["simax"])
    sentinel = object()

    def create(directory):
        assert os.environ["SIMAX_SECRET_STARTUP"] == "literal-${NOT_A_VARIABLE}-#-value"
        assert os.environ["SIMAX_DATA_DIR"] == "custom-data"
        return sentinel

    def serve(app, **kwargs):
        assert app is sentinel
        assert kwargs["host"] == "127.0.0.1"

    monkeypatch.setattr("simax.__main__.create_app", create)
    monkeypatch.setattr("simax.__main__.uvicorn.run", serve)
    main()


def test_dotenv_respects_existing_process_values(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMAX_SECRET_STARTUP", "process-value")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "0")
    env_file = tmp_path / "private.env"
    env_file.write_text("SIMAX_SECRET_STARTUP=file-value\n", encoding="utf-8")
    load_environment(env_file)
    assert os.environ["SIMAX_SECRET_STARTUP"] == "process-value"


def test_missing_default_env_does_not_search_parent(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMAX_SECRET_PARENT", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "0")
    (tmp_path / ".env").write_text("SIMAX_SECRET_PARENT=unrelated\n", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    assert not load_environment()
    assert "SIMAX_SECRET_PARENT" not in os.environ
