"""
tests/test_loader.py — Unit tests for job_sources.loader.load_plugins().

Covers:
  - Happy path: valid plugin is discovered and returned
  - File-level skips: missing plugin.py, missing source.json
  - Parse errors: invalid JSON in source.json
  - Schema validation: missing required keys (source_key, display_name, etc.)
  - Class-count checks: 0 subclasses, 2+ subclasses
  - Import errors in plugin.py
  - Non-directory entries ignored
  - Non-existent plugins_dir returns {}
  - _plugin_schema attribute attached to loaded class
  - settings_schema() shim correctness
  - Underscore-prefix folders skipped
  - Alphabetical ordering of results
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from job_sources.loader import load_plugins

# ---------------------------------------------------------------------------
# Minimal valid plugin.py content — implements all JobSource abstract methods
# so the ABC constraint is satisfied without instantiation.
# ---------------------------------------------------------------------------

_VALID_PLUGIN_PY = """\
from job_sources.base import JobSource

class TestSource(JobSource):
    def fetch_page(self, page):
        return []
    def total_pages(self):
        return 1
    def normalise(self, raw):
        return {}
    @classmethod
    def settings_schema(cls):
        return {"display_name": "Test", "fields": []}
"""

_VALID_SOURCE_JSON_TEMPLATE = """\
{{
    "source_key": "{source_key}",
    "display_name": "Test Source",
    "description": "A test job source",
    "home_url": "https://example.com",
    "fields": []
}}
"""


def _make_plugin(
    base_dir: Path,
    name: str,
    source_key: str | None = None,
    fields: list | None = None,
    *,
    class_count: int = 1,
    bad_json: bool = False,
    import_error: bool = False,
    omit_plugin_py: bool = False,
    omit_source_json: bool = False,
    extra_schema_keys: dict | None = None,
    missing_schema_keys: list[str] | None = None,
) -> Path:
    """Create a plugin folder under *base_dir/name*.

    Args:
        base_dir:            Parent directory to create the plugin folder in.
        name:                Sub-folder name.
        source_key:          Value for ``source_key`` in source.json (defaults to *name*).
        fields:              ``fields`` list written into source.json.
        class_count:         Number of JobSource subclasses to define in plugin.py (0, 1, or 2).
        bad_json:            Write malformed JSON to source.json.
        import_error:        Write plugin.py that raises on import.
        omit_plugin_py:      Don't write plugin.py at all.
        omit_source_json:    Don't write source.json at all.
        extra_schema_keys:   Additional keys merged into source.json.
        missing_schema_keys: List of required keys to omit from source.json.

    Returns:
        Path to the created plugin folder.
    """
    folder = base_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    # --- plugin.py ---
    if not omit_plugin_py:
        if import_error:
            py_content = "raise RuntimeError('intentional import error')\n"
        elif class_count == 0:
            py_content = "# no subclasses here\nx = 1\n"
        elif class_count == 1:
            py_content = _VALID_PLUGIN_PY
        else:
            # Generate `class_count` distinct subclasses.
            lines = ["from job_sources.base import JobSource\n"]
            for i in range(class_count):
                lines.append(f"""\
class TestSource{i}(JobSource):
    def fetch_page(self, page): return []
    def total_pages(self): return 1
    def normalise(self, raw): return {{}}
    @classmethod
    def settings_schema(cls): return {{"display_name": "T{i}", "fields": []}}
""")
            py_content = "\n".join(lines)
        (folder / "plugin.py").write_text(py_content, encoding="utf-8")

    # --- source.json ---
    if not omit_source_json:
        if bad_json:
            (folder / "source.json").write_text("{invalid json", encoding="utf-8")
        else:
            import json

            schema: dict = {
                "source_key": source_key or name,
                "display_name": "Test Source",
                "description": "A test job source",
                "home_url": "https://example.com",
                "fields": fields if fields is not None else [],
            }
            if extra_schema_keys:
                schema.update(extra_schema_keys)
            if missing_schema_keys:
                for k in missing_schema_keys:
                    schema.pop(k, None)
            (folder / "source.json").write_text(json.dumps(schema), encoding="utf-8")

    return folder


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadPlugins:
    def test_valid_plugin_discovered(self, tmp_path):
        """A well-formed plugin folder is returned, keyed by its source_key."""
        _make_plugin(tmp_path, "my_source", source_key="my_source")
        result = load_plugins(tmp_path)
        assert "my_source" in result

    def test_missing_plugin_py_skipped(self, tmp_path):
        """A folder with only source.json (no plugin.py) is skipped."""
        _make_plugin(tmp_path, "no_py", omit_plugin_py=True)
        result = load_plugins(tmp_path)
        assert "no_py" not in result

    def test_missing_source_json_skipped(self, tmp_path):
        """A folder with only plugin.py (no source.json) is skipped."""
        _make_plugin(tmp_path, "no_json", omit_source_json=True)
        result = load_plugins(tmp_path)
        assert "no_json" not in result

    def test_missing_plugin_py_does_not_block_other_plugins(self, tmp_path):
        """A bad plugin does not prevent a valid sibling from loading."""
        _make_plugin(tmp_path, "bad_source", omit_plugin_py=True)
        _make_plugin(tmp_path, "good_source", source_key="good_source")
        result = load_plugins(tmp_path)
        assert "good_source" in result

    def test_invalid_json_skipped(self, tmp_path):
        """A folder with malformed source.json is skipped."""
        _make_plugin(tmp_path, "bad_json_source", bad_json=True)
        result = load_plugins(tmp_path)
        assert "bad_json_source" not in result

    def test_missing_source_key_skipped(self, tmp_path):
        """source.json without the source_key field causes the plugin to be skipped."""
        _make_plugin(tmp_path, "no_key", missing_schema_keys=["source_key"])
        result = load_plugins(tmp_path)
        assert not result  # source_key is how we'd look it up anyway

    def test_missing_required_field_skipped(self, tmp_path):
        """source.json missing display_name (a required field) causes a skip."""
        _make_plugin(tmp_path, "no_display", missing_schema_keys=["display_name"])
        result = load_plugins(tmp_path)
        assert "no_display" not in result

    def test_missing_description_skipped(self, tmp_path):
        """source.json missing description causes a skip."""
        _make_plugin(tmp_path, "no_desc", source_key="no_desc", missing_schema_keys=["description"])
        result = load_plugins(tmp_path)
        assert "no_desc" not in result

    def test_missing_home_url_skipped(self, tmp_path):
        """source.json missing home_url causes a skip."""
        _make_plugin(tmp_path, "no_url", source_key="no_url", missing_schema_keys=["home_url"])
        result = load_plugins(tmp_path)
        assert "no_url" not in result

    def test_missing_fields_skipped(self, tmp_path):
        """source.json missing the fields list causes a skip."""
        _make_plugin(tmp_path, "no_fields_key", source_key="no_fields_key", missing_schema_keys=["fields"])
        result = load_plugins(tmp_path)
        assert "no_fields_key" not in result

    def test_zero_subclasses_skipped(self, tmp_path):
        """plugin.py with no JobSource subclass causes a skip."""
        _make_plugin(tmp_path, "zero_classes", source_key="zero_classes", class_count=0)
        result = load_plugins(tmp_path)
        assert "zero_classes" not in result

    def test_multiple_subclasses_skipped(self, tmp_path):
        """plugin.py with 2 JobSource subclasses causes a skip (ambiguous)."""
        _make_plugin(tmp_path, "two_classes", source_key="two_classes", class_count=2)
        result = load_plugins(tmp_path)
        assert "two_classes" not in result

    def test_import_error_skipped(self, tmp_path):
        """plugin.py that raises on import is skipped; other plugins still load."""
        _make_plugin(tmp_path, "bad_import", source_key="bad_import", import_error=True)
        _make_plugin(tmp_path, "good_source", source_key="good_source")
        result = load_plugins(tmp_path)
        assert "bad_import" not in result
        assert "good_source" in result

    def test_non_directory_entries_ignored(self, tmp_path):
        """Loose files directly inside plugins_dir are ignored."""
        (tmp_path / "some_file.txt").write_text("not a plugin", encoding="utf-8")
        _make_plugin(tmp_path, "real_source", source_key="real_source")
        result = load_plugins(tmp_path)
        assert "real_source" in result
        assert len(result) == 1  # the file was not interpreted as a plugin

    def test_nonexistent_dir_returns_empty(self):
        """A non-existent plugins_dir returns an empty dict instead of raising."""
        result = load_plugins(Path("/nonexistent/path/that/does/not/exist"))
        assert result == {}

    def test_empty_dir_returns_empty(self, tmp_path):
        """An empty plugins_dir returns an empty dict."""
        result = load_plugins(tmp_path)
        assert result == {}

    def test_plugin_has_schema_attribute(self, tmp_path):
        """The loaded class has _plugin_schema equal to the parsed source.json content."""
        import json

        folder = _make_plugin(tmp_path, "schema_test", source_key="schema_test")
        expected = json.loads((folder / "source.json").read_text(encoding="utf-8"))

        result = load_plugins(tmp_path)
        cls = result["schema_test"]
        assert hasattr(cls, "_plugin_schema")
        assert cls._plugin_schema == expected

    def test_settings_schema_shim_returns_correct_dict(self, tmp_path):
        """cls.settings_schema() returns all source.json keys except source_key."""
        import json

        folder = _make_plugin(
            tmp_path,
            "shim_test",
            source_key="shim_test",
            extra_schema_keys={"custom_extra": "hello"},
        )
        schema = json.loads((folder / "source.json").read_text(encoding="utf-8"))

        result = load_plugins(tmp_path)
        cls = result["shim_test"]
        shim_result = cls.settings_schema()

        assert "source_key" not in shim_result
        for key in schema:
            if key != "source_key":
                assert key in shim_result
                assert shim_result[key] == schema[key]

    def test_underscore_prefix_skipped(self, tmp_path):
        """Folders whose name starts with '_' (e.g. _internal) are skipped."""
        _make_plugin(tmp_path, "_internal", source_key="_internal")
        result = load_plugins(tmp_path)
        assert result == {}

    def test_alphabetical_ordering(self, tmp_path):
        """Plugins are processed in alphabetical folder order."""
        # Create two plugins; "alpha_source" should appear before "zeta_source"
        # in results if iteration order is alphabetical.
        _make_plugin(tmp_path, "zeta_folder", source_key="zeta_source")
        _make_plugin(tmp_path, "alpha_folder", source_key="alpha_source")

        result = load_plugins(tmp_path)
        keys = list(result.keys())

        assert set(keys) == {"alpha_source", "zeta_source"}
        assert keys.index("alpha_source") < keys.index("zeta_source")

    def test_default_plugins_dir_used_when_none_given(self, monkeypatch, tmp_path):
        """When plugins_dir is None, the loader uses <repo_root>/plugins/sources/."""
        import job_sources.loader as loader_module

        # Patch Path(__file__).parent.parent to point at tmp_path so the default
        # resolves to tmp_path / "plugins" / "sources".
        plugins_sources = tmp_path / "plugins" / "sources"
        plugins_sources.mkdir(parents=True)
        _make_plugin(plugins_sources, "default_source", source_key="default_source")

        original_file = loader_module.__file__

        # Monkey-patch the loader to think it lives at tmp_path/job_sources/loader.py
        # so the default resolution hits our tmp directory.
        fake_loader_path = tmp_path / "job_sources" / "loader.py"
        monkeypatch.setattr(loader_module, "__file__", str(fake_loader_path))

        result = load_plugins()  # no explicit dir
        assert "default_source" in result

        # Restore
        monkeypatch.setattr(loader_module, "__file__", original_file)

    def test_loaded_class_is_jobsource_subclass(self, tmp_path):
        """The class returned from a valid plugin is a subclass of JobSource."""
        from job_sources.base import JobSource

        _make_plugin(tmp_path, "type_check", source_key="type_check")
        result = load_plugins(tmp_path)
        cls = result["type_check"]
        assert issubclass(cls, JobSource)
