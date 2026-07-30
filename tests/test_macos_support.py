from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "BIN" / "_app"
SERVER = APP / "gameserver" / "opeternal_listener.py"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MacOSPathTests(unittest.TestCase):
    def test_darwin_paths(self):
        code = (
            "import sys;"
            "sys.platform='darwin';"
            f"sys.path.insert(0,{str(APP)!r});"
            "from app import paths;"
            "print(paths.RPCS3_EXE);"
            "print(paths.rpcs3_log_path())"
        )
        output = subprocess.check_output(
            [sys.executable, "-c", code],
            text=True,
        ).splitlines()
        self.assertTrue(
            output[0].endswith("RPCS3/RPCS3.app/Contents/MacOS/rpcs3"),
            output[0],
        )
        self.assertTrue(
            output[1].endswith("Library/Caches/rpcs3/RPCS3.log"),
            output[1],
        )


class MacOSConfigTests(unittest.TestCase):
    def test_darwin_gpu_and_log_defaults(self):
        sys.path.insert(0, str(APP))
        from modules import config

        source = (
            "Core:\n"
            "  Accurate RSX reservation access: false\n"
            "Log:\n"
            "Video:\n"
            "  Driver Wake-Up Delay: 1\n"
            "Net:\n"
            "  Internet enabled: Disconnected\n"
            "  PSN status: Disconnected\n"
            "  IP swap list: \"\"\n"
            "  UPNP Enabled: false\n"
            "  Bind address: 0.0.0.0\n"
            "  Frame limit: Off\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yml"
            path.write_text(source, encoding="utf-8")
            with mock.patch.object(config.sys, "platform", "darwin"):
                config.patch_game_config(str(path), "192.0.2.4")
            result = path.read_text(encoding="utf-8")

        self.assertIn("Accurate RSX reservation access: true", result)
        self.assertIn("Driver Wake-Up Delay: 200", result)
        self.assertIn("Log:\n  sceNp: Error", result)


@unittest.skipUnless(sys.platform == "darwin", "macOS only")
class MacOSPrivilegeTests(unittest.TestCase):
    def test_privileged_server_uses_launchctl_job(self):
        sys.path.insert(0, str(APP))
        from modules import processes

        with mock.patch.object(
            processes.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as run:
            result = processes.launch_macos_privileged(
                "/tmp/python3",
                ["/tmp/server.py", "--bind-ip", "127.0.0.1"],
                "/tmp",
                1234,
            )

        self.assertTrue(result)
        command = run.call_args.args[0][-1]
        self.assertIn("/bin/launchctl submit", command)
        self.assertIn("--watch-pid 1234", command)
        self.assertNotIn("nohup", command)


class GameServerLifecycleTests(unittest.TestCase):
    def test_watch_pid_stops_server(self):
        port = free_port()
        watcher = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.5)"]
        )
        with tempfile.TemporaryDirectory() as log_dir:
            env = os.environ.copy()
            env["OEL_LOG_DIR"] = log_dir
            server = subprocess.Popen(
                [
                    sys.executable,
                    str(SERVER),
                    "--bind-ip", "127.0.0.1",
                    "--http-port", str(port),
                    "--no-https",
                    "--forward", "127.0.0.1",
                    "--watch-pid", str(watcher.pid),
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        break
                    try:
                        with socket.create_connection(("127.0.0.1", port), 0.1):
                            break
                    except OSError:
                        time.sleep(0.05)
                watcher.wait(timeout=3)
                server.wait(timeout=4)
                self.assertEqual(server.returncode, 0)
            finally:
                if watcher.poll() is None:
                    watcher.terminate()
                    watcher.wait(timeout=2)
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
