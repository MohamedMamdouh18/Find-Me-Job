import json

from src.params_defaults import DEFAULT_PARAMS, ensure_default_params


def test_creates_missing_files(tmp_path):
    created = ensure_default_params(str(tmp_path))
    assert created == list(DEFAULT_PARAMS)
    assert json.loads((tmp_path / "linkedin_searches.txt").read_text())["searches"]


def test_keeps_existing_file_untouched(tmp_path):
    path = tmp_path / "linkedin_searches.txt"
    path.write_text('{"searches": []}')
    assert ensure_default_params(str(tmp_path)) == []
    assert path.read_text() == '{"searches": []}'


def test_creates_params_dir(tmp_path):
    target = tmp_path / "params"
    ensure_default_params(str(target))
    assert (target / "linkedin_searches.txt").is_file()
