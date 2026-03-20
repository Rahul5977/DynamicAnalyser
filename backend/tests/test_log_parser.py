import pytest

from app.services.log_parser import (
    parse_log_line,
    parse_logs,
    parse_timestamp,
    _extract_step_name_from_header,
)
from app.core.exceptions import LogParseError, LogFormatError


class TestParseTimestamp:
    def test_valid_timestamp(self):
        ts = parse_timestamp("2024-03-19T10:32:01.456789Z")
        assert ts.year == 2024
        assert ts.month == 3
        assert ts.day == 19
        assert ts.hour == 10
        assert ts.minute == 32
        assert ts.second == 1

    def test_variable_fractional_seconds(self):
        ts = parse_timestamp("2024-03-19T10:32:01.4567890Z")
        assert ts.second == 1

    def test_short_fractional_seconds(self):
        ts = parse_timestamp("2024-03-19T10:32:01.4Z")
        assert ts.second == 1

    def test_invalid_timestamp_raises(self):
        with pytest.raises(LogFormatError):
            parse_timestamp("not-a-timestamp")


class TestParseLogLine:
    def test_regular_line(self):
        line = "2024-03-19T10:32:01.456789Z Installing dependencies..."
        result = parse_log_line(line)
        assert result is not None
        assert result.message == "Installing dependencies..."
        assert result.annotation is None

    def test_group_annotation(self):
        line = "2024-03-19T10:32:01.456789Z ##[group]Run npm install"
        result = parse_log_line(line)
        assert result is not None
        assert result.annotation == "group"
        assert result.message == "Run npm install"

    def test_endgroup_annotation(self):
        line = "2024-03-19T10:32:05.456789Z ##[endgroup]"
        result = parse_log_line(line)
        assert result is not None
        assert result.annotation == "endgroup"

    def test_error_annotation(self):
        line = "2024-03-19T10:32:01.456789Z ##[error]Process exited with code 1"
        result = parse_log_line(line)
        assert result is not None
        assert result.annotation == "error"
        assert result.message == "Process exited with code 1"

    def test_warning_annotation(self):
        line = "2024-03-19T10:32:01.456789Z ##[warning]Node 16 is deprecated"
        result = parse_log_line(line)
        assert result is not None
        assert result.annotation == "warning"

    def test_empty_line_returns_none(self):
        assert parse_log_line("") is None
        assert parse_log_line("   ") is None

    def test_no_timestamp_returns_none(self):
        assert parse_log_line("Just some random text") is None


class TestExtractStepName:
    def test_numbered_step(self):
        name, num = _extract_step_name_from_header("build/2_Run npm install.txt")
        assert name == "Run npm install"
        assert num == 2

    def test_nested_path(self):
        name, num = _extract_step_name_from_header("job/3_Deploy to staging.txt")
        assert name == "Deploy to staging"
        assert num == 3

    def test_no_number(self):
        name, num = _extract_step_name_from_header("build/Setup.txt")
        assert name == "Setup"
        assert num == 0


class TestParseLogs:
    def test_empty_log_raises(self):
        with pytest.raises(LogParseError, match="Empty log input"):
            parse_logs("")

    def test_whitespace_only_raises(self):
        with pytest.raises(LogParseError, match="Empty log input"):
            parse_logs("   \n  \n  ")

    def test_no_steps_found_raises(self):
        with pytest.raises(LogParseError, match="No steps found"):
            parse_logs("Just some text with no timestamps")

    def test_archive_format(self):
        log = """=== build/1_Set up job.txt ===
2024-03-19T10:32:01.000000Z Setting up runner...
2024-03-19T10:32:02.500000Z Runner ready
=== build/2_Run npm install.txt ===
2024-03-19T10:32:03.000000Z ##[group]Run npm install
2024-03-19T10:32:03.100000Z npm install
2024-03-19T10:32:08.000000Z added 1234 packages
2024-03-19T10:32:08.100000Z ##[endgroup]
=== build/3_Run tests.txt ===
2024-03-19T10:32:09.000000Z ##[group]Run npm test
2024-03-19T10:32:09.500000Z PASS src/app.test.ts
2024-03-19T10:32:12.000000Z All tests passed
"""
        steps = parse_logs(log)
        assert len(steps) == 3

        assert steps[0].step_name == "Set up job"
        assert steps[0].step_number == 1
        assert steps[0].duration_ms == 1500  # 2.5 - 1.0 = 1.5s

        assert steps[1].step_name == "Run npm install"
        assert steps[1].step_number == 2
        assert steps[1].duration_ms == 5100  # 8.1 - 3.0 = 5.1s

        assert steps[2].step_name == "Run tests"
        assert steps[2].step_number == 3
        assert steps[2].duration_ms == 3000  # 12.0 - 9.0 = 3.0s

    def test_group_format(self):
        log = """2024-03-19T10:32:01.000000Z ##[group]Run npm install
2024-03-19T10:32:01.100000Z npm install
2024-03-19T10:32:06.000000Z added 500 packages
2024-03-19T10:32:06.100000Z ##[endgroup]
2024-03-19T10:32:07.000000Z ##[group]Run npm test
2024-03-19T10:32:07.100000Z running tests...
2024-03-19T10:32:10.000000Z ##[endgroup]
"""
        steps = parse_logs(log)
        assert len(steps) == 2
        assert steps[0].step_name == "Run npm install"
        assert steps[0].duration_ms == 5100
        assert steps[1].step_name == "Run npm test"
        assert steps[1].duration_ms == 3000

    def test_error_step_marked_failure(self):
        log = """2024-03-19T10:32:01.000000Z ##[group]Run npm test
2024-03-19T10:32:01.100000Z running tests...
2024-03-19T10:32:05.000000Z ##[error]Test failed: app.test.ts
2024-03-19T10:32:05.100000Z ##[endgroup]
"""
        steps = parse_logs(log)
        assert len(steps) == 1
        assert steps[0].status == "failure"
        assert steps[0].annotation == "error"

    def test_steps_sorted_correctly(self):
        log = """=== build/1_Checkout.txt ===
2024-03-19T10:32:01.000000Z Checking out repo
2024-03-19T10:32:01.500000Z Done
=== build/2_Install.txt ===
2024-03-19T10:32:02.000000Z Installing...
2024-03-19T10:32:10.000000Z Done
=== build/3_Test.txt ===
2024-03-19T10:32:11.000000Z Testing...
2024-03-19T10:32:14.000000Z Done
"""
        steps = parse_logs(log)
        assert steps[0].step_number < steps[1].step_number < steps[2].step_number

    def test_log_excerpt_truncation(self):
        long_line = "x" * 3000
        log = f"""=== build/1_Long step.txt ===
2024-03-19T10:32:01.000000Z {long_line}
2024-03-19T10:32:02.000000Z Done
"""
        steps = parse_logs(log)
        assert "truncated" in steps[0].log_excerpt

    def test_implicit_setup_step(self):
        log = """2024-03-19T10:32:01.000000Z Preparing environment
2024-03-19T10:32:02.000000Z Environment ready
"""
        steps = parse_logs(log)
        assert len(steps) == 1
        assert steps[0].step_name == "Setup"
