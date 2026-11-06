import os
from simax.__main__ import main


def test_startup_does_not_load_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SIMAX_SECRET_STARTUP", raising=False)
    (tmp_path / ".env").write_text("SIMAX_SECRET_STARTUP=must-not-load\n", encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["simax", "--data-dir", "isolated"])
    sentinel = object()
    def create(directory):
        assert directory == "isolated"
        assert "SIMAX_SECRET_STARTUP" not in os.environ
        return sentinel
    def serve(app, **kwargs):
        assert app is sentinel
        assert kwargs["host"] == "127.0.0.1"
    monkeypatch.setattr("simax.__main__.create_app", create)
    monkeypatch.setattr("simax.__main__.uvicorn.run", serve)
    main()
