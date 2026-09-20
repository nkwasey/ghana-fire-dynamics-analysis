from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from mv_firms_panels.cli.main import build_parser, main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path("configs/example_project.yaml")


def test_console_entry_point_is_installed_command() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    assert raw["project"]["scripts"] == {"mv-firms-panels": "mv_firms_panels.cli.main:main"}


@pytest.mark.parametrize(
    ("command_args", "command"),
    [
        (["prepare-year", "--sensor", "viirs", "--year", "2024"], "prepare-year"),
        (["aggregate", "--sensor", "viirs"], "aggregate"),
        (["combine"], "combine"),
        (["visualise"], "visualise"),
        (["pipeline", "--dry-run"], "pipeline"),
    ],
)
def test_config_is_accepted_before_and_after_subcommand(command_args: list[str], command: str) -> None:
    parser = build_parser()
    before = parser.parse_args(["--config", str(CONFIG), *command_args])
    after = parser.parse_args([command_args[0], "--config", str(CONFIG), *command_args[1:]])
    assert before.command == command
    assert after.command == command
    assert before.config == CONFIG
    assert after.config == CONFIG


def test_pre_subcommand_common_values_are_not_overwritten_by_subparser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--config", str(CONFIG),
            "--run-id", "pre_value",
            "--log-level", "DEBUG",
            "--skip-existing",
            "combine",
        ]
    )
    assert args.config == CONFIG
    assert args.run_id == "pre_value"
    assert args.log_level == "DEBUG"
    assert args.skip_existing is True


def test_post_subcommand_common_values_override_root_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "combine",
            "--config", str(CONFIG),
            "--run-id", "post_value",
            "--log-level", "WARNING",
            "--force",
        ]
    )
    assert args.config == CONFIG
    assert args.run_id == "post_value"
    assert args.log_level == "WARNING"
    assert args.force is True


def test_missing_config_is_rejected_by_cli(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["combine"])
    assert exc.value.code == 2
    assert "--config is required" in capsys.readouterr().err
