# Copyright 2021-2022 NVIDIA Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from __future__ import annotations

import re
from shlex import quote

import pytest
from pytest_mock import MockerFixture

import legate.driver.driver as m
from legate.driver.command import CMD_PARTS
from legate.driver.config import Config
from legate.driver.launcher import RANK_ENV_VARS, Launcher
from legate.util.colors import scrub
from legate.util.shared_args import LAUNCHERS
from legate.util.system import System
from legate.util.types import LauncherType

from ...util import Capsys
from .util import GenConfig

SYSTEM = System()

DARWIN_GDB_WARN_EXPECTED_PAT = """\
WARNING: You must start the debugging session with the following command,
as LLDB no longer forwards the environment to subprocesses for security
reasons:

[(]lldb[)] process launch -v LIB_PATH=(.*) -v PYTHONPATH=(.*)
"""


class TestDriver:
    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_init(self, genconfig: GenConfig, launch: LauncherType) -> None:
        config = genconfig(["--launcher", launch])

        driver = m.Driver(config, SYSTEM)

        assert driver.config is config
        assert driver.system is SYSTEM
        assert driver.launcher == Launcher.create(config, SYSTEM)

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_cmd(self, genconfig: GenConfig, launch: LauncherType) -> None:
        config = genconfig(["--launcher", launch])

        driver = m.Driver(config, SYSTEM)

        parts = (part(config, SYSTEM, driver.launcher) for part in CMD_PARTS)
        expected_cmd = driver.launcher.cmd + sum(parts, ())

        assert driver.cmd == expected_cmd

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_env(self, genconfig: GenConfig, launch: LauncherType) -> None:
        config = genconfig(["--launcher", launch])

        driver = m.Driver(config, SYSTEM)

        assert driver.env == driver.launcher.env

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_custom_env_vars(
        self, genconfig: GenConfig, launch: LauncherType
    ) -> None:
        config = genconfig(["--launcher", launch])

        driver = m.Driver(config, SYSTEM)

        assert driver.custom_env_vars == driver.launcher.custom_env_vars

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_dry_run(
        self, genconfig: GenConfig, mocker: MockerFixture, launch: LauncherType
    ) -> None:
        config = genconfig(["--launcher", launch, "--dry-run"])
        driver = m.Driver(config, SYSTEM)

        mocker.patch.object(m, "process_logs")
        mock_run = mocker.patch.object(m, "run")

        driver.run()

        mock_run.assert_not_called()

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_run(
        self, genconfig: GenConfig, mocker: MockerFixture, launch: LauncherType
    ) -> None:
        config = genconfig(["--launcher", launch])
        driver = m.Driver(config, SYSTEM)

        mocker.patch.object(m, "process_logs")
        mock_run = mocker.patch.object(m, "run")

        driver.run()

        mock_run.assert_called_once_with(driver.cmd, env=driver.env)

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_verbose(
        self,
        capsys: Capsys,
        genconfig: GenConfig,
        launch: LauncherType,
    ) -> None:
        # set --dry-run to avoid needing to mock anything
        config = genconfig(["--launcher", launch, "--verbose", "--dry-run"])
        driver = m.Driver(config, SYSTEM)

        driver.run()

        run_out = scrub(capsys.readouterr()[0]).strip()

        m.print_verbose(driver.system, driver)

        pv_out = scrub(capsys.readouterr()[0]).strip()

        assert pv_out in run_out

    @pytest.mark.parametrize("rank_var", RANK_ENV_VARS)
    def test_verbose_nonero_rank_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: Capsys,
        genconfig: GenConfig,
        rank_var: str,
    ) -> None:
        for name in RANK_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(name, "1")

        # set --dry-run to avoid needing to mock anything
        config = genconfig(
            ["--launcher", "none", "--verbose", "--dry-run"], multi_rank=(2, 2)
        )
        system = System()
        driver = m.Driver(config, system)

        driver.run()

        run_out = scrub(capsys.readouterr()[0]).strip()

        m.print_verbose(driver.system, driver)

        pv_out = scrub(capsys.readouterr()[0]).strip()

        assert pv_out not in run_out

    @pytest.mark.parametrize("launch", LAUNCHERS)
    def test_darwin_gdb_warning(
        self,
        mocker: MockerFixture,
        capsys: Capsys,
        genconfig: GenConfig,
        launch: str,
    ) -> None:
        mocker.patch("platform.system", return_value="Darwin")
        mocker.patch.object(m, "process_logs")

        system = m.System()

        # set --dry-run to avoid needing to mock anything
        config = genconfig(["--launcher", launch, "--gdb", "--dry-run"])
        driver = m.Driver(config, system)

        driver.run()

        out, _ = capsys.readouterr()

        assert re.search(DARWIN_GDB_WARN_EXPECTED_PAT, scrub(out))


class Test_print_verbose:
    def test_system_only(self, capsys: Capsys) -> None:
        system = System()

        m.print_verbose(system)

        out = scrub(capsys.readouterr()[0]).strip()

        assert out.startswith(f"{'--- Legion Python Configuration ':-<80}")
        assert "Legate paths:" in out
        for line in scrub(str(system.legate_paths)).split():
            assert line in out

        assert "Legion paths:" in out
        for line in scrub(str(system.legion_paths)).split():
            assert line in out

    def test_system_and_driver(self, capsys: Capsys) -> None:
        config = Config(["legate", "--no-replicate"])
        system = System()
        driver = m.Driver(config, system)

        m.print_verbose(system, driver)

        out = scrub(capsys.readouterr()[0]).strip()

        assert out.startswith(f"{'--- Legion Python Configuration ':-<80}")
        assert "Legate paths:" in out
        for line in scrub(str(system.legate_paths)).split():
            assert line in out

        assert "Legion paths:" in out
        for line in scrub(str(system.legion_paths)).split():
            assert line in out

        assert "Command:" in out
        assert f"  {' '.join(quote(t) for t in driver.cmd)}" in out

        assert "Customized Environment:" in out
        for k in driver.custom_env_vars:
            assert f"{k}={driver.env[k]}" in out

        assert out.endswith(f"\n{'-':-<80}")
