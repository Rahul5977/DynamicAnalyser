import os
import pytest

from app.services.ast_parser import ASTParser, CodeIndexer, CodeIndexData
from app.core.exceptions import ASTParseError


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename)) as f:
        return f.read()


@pytest.fixture
def parser():
    return ASTParser()


@pytest.fixture
def python_source():
    return _read_fixture("sample_python.py")


@pytest.fixture
def js_source():
    return _read_fixture("sample_javascript.js")


class TestPythonParsing:
    def test_extract_functions(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        func_names = [f.name for f in functions]
        assert "deploy_app" in func_names
        assert "run_migrations" in func_names
        assert "execute_sql" in func_names

    def test_qualified_names_for_methods(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        method_funcs = [f for f in functions if f.qualified_name and "." in f.qualified_name]
        qualified_names = [f.qualified_name for f in method_funcs]
        assert "DatabaseManager.connect" in qualified_names
        assert "DatabaseManager.disconnect" in qualified_names

    def test_function_line_numbers(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        deploy = next(f for f in functions if f.name == "deploy_app")
        assert deploy.line_number > 0
        assert deploy.end_line_number >= deploy.line_number

    def test_call_graph_edges(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        deploy = next(f for f in functions if f.name == "deploy_app")
        assert "run_migrations" in deploy.calls
        assert "start_server" in deploy.calls

    def test_log_call_extraction(self, parser, python_source):
        _, log_calls = parser.parse_file(python_source, "app/deploy.py")
        log_strings = [lc.log_string for lc in log_calls]
        assert "Starting deployment" in log_strings
        assert "Running database migrations" in log_strings
        assert "Executing SQL statements" in log_strings

    def test_log_call_enclosing_function(self, parser, python_source):
        _, log_calls = parser.parse_file(python_source, "app/deploy.py")
        deploy_log = next(
            lc for lc in log_calls if lc.log_string == "Starting deployment"
        )
        assert deploy_log.function_name == "deploy_app"

    def test_log_call_level(self, parser, python_source):
        _, log_calls = parser.parse_file(python_source, "app/deploy.py")
        warning_log = next(
            lc for lc in log_calls
            if lc.log_string == "Running database migrations"
        )
        assert warning_log.log_level == "warning"

    def test_print_calls_extracted(self, parser, python_source):
        _, log_calls = parser.parse_file(python_source, "app/deploy.py")
        log_strings = [lc.log_string for lc in log_calls]
        assert "SQL execution complete" in log_strings


class TestJavaScriptParsing:
    def test_extract_functions(self, parser, js_source):
        functions, _ = parser.parse_file(js_source, "src/build.js")
        func_names = [f.name for f in functions]
        assert "installDependencies" in func_names
        assert "validatePackageJson" in func_names
        assert "runTests" in func_names

    def test_console_log_extraction(self, parser, js_source):
        _, log_calls = parser.parse_file(js_source, "src/build.js")
        log_strings = [lc.log_string for lc in log_calls]
        assert "Installing npm packages" in log_strings
        assert "Running test suite" in log_strings

    def test_console_warn_extraction(self, parser, js_source):
        _, log_calls = parser.parse_file(js_source, "src/build.js")
        warn_logs = [lc for lc in log_calls if lc.log_level == "warn"]
        assert len(warn_logs) >= 1
        assert any("Validating" in lc.log_string for lc in warn_logs)

    def test_method_in_class(self, parser, js_source):
        functions, _ = parser.parse_file(js_source, "src/build.js")
        build_method = next(
            (f for f in functions if f.name == "build"), None
        )
        assert build_method is not None
        assert "BuildManager" in (build_method.qualified_name or "")


class TestUnsupportedAndEdgeCases:
    def test_unsupported_extension_returns_empty(self, parser):
        functions, log_calls = parser.parse_file("some content", "file.txt")
        assert functions == []
        assert log_calls == []

    def test_empty_file(self, parser):
        functions, log_calls = parser.parse_file("", "empty.py")
        assert functions == []
        assert log_calls == []

    def test_syntax_still_parses(self, parser):
        # tree-sitter is error-tolerant; broken syntax still produces a tree
        bad_python = "def foo(\n    print('hello'"
        functions, log_calls = parser.parse_file(bad_python, "broken.py")
        # Should not raise, may find partial results
        assert isinstance(functions, list)


class TestCodeIndexerGraphs:
    def test_build_call_graph(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        graph = CodeIndexer._build_call_graph(functions)
        assert "run_migrations" in graph.get("deploy_app", [])

    def test_build_reverse_graph(self, parser, python_source):
        functions, _ = parser.parse_file(python_source, "app/deploy.py")
        graph = CodeIndexer._build_call_graph(functions)
        reverse = CodeIndexer._build_reverse_graph(graph)
        assert "deploy_app" in reverse.get("run_migrations", [])

    def test_build_log_line_map(self, parser, python_source):
        functions, log_calls = parser.parse_file(python_source, "app/deploy.py")
        log_map = CodeIndexer._build_log_line_map(log_calls, functions)
        assert "Starting deployment" in log_map
        loc = log_map["Starting deployment"]
        assert loc.function_name == "deploy_app"
        assert loc.file_path == "app/deploy.py"

    def test_code_index_data_get_callers(self, parser, python_source):
        functions, log_calls = parser.parse_file(python_source, "app/deploy.py")
        graph = CodeIndexer._build_call_graph(functions)
        reverse = CodeIndexer._build_reverse_graph(graph)
        log_map = CodeIndexer._build_log_line_map(log_calls, functions)

        index = CodeIndexData(
            repo_full_name="test/repo",
            commit_sha="abc123",
            functions=functions,
            log_calls=log_calls,
            call_graph=graph,
            reverse_call_graph=reverse,
            log_line_map=log_map,
        )

        callers = index.get_callers("execute_sql")
        caller_names = [c.function_name for c in callers]
        assert "run_migrations" in caller_names
