import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("goose_studio_install", ROOT / "scripts" / "install.py")
assert SPEC and SPEC.loader
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class InstallSecurityTest(unittest.TestCase):
    def test_bootstrap_progress_is_forwarded_to_setup_details(self):
        class FakeProcess:
            stdout = iter(("[bootstrap] Downloading model\n", "10%\r20%\n"))

            def poll(self):
                return 0

            def wait(self):
                return 0

        with mock.patch.object(INSTALL, "MODAL_CLI", Path("C:/Goose/modal-cli.exe")):
            with mock.patch.object(INSTALL.subprocess, "Popen", return_value=FakeProcess()):
                with mock.patch("builtins.print") as print_output:
                    INSTALL.run_bootstrap_with_progress()

        output = "\n".join(str(call.args[0]) for call in print_output.call_args_list)
        self.assertIn("[bootstrap] Downloading model", output)
        self.assertIn("10%", output)
        self.assertIn("20%", output)
        self.assertIn("Model download still running", output)

    def test_commands_decode_modal_output_as_utf8(self):
        with mock.patch.object(INSTALL.subprocess, "run") as run:
            run.return_value.stdout = "deployed ✓"
            result = INSTALL.run("modal", "deploy", capture=True)

        self.assertEqual("deployed ✓", result)
        self.assertEqual("utf-8", run.call_args.kwargs["encoding"])
        self.assertEqual("replace", run.call_args.kwargs["errors"])

    def test_streaming_commands_forward_deploy_output_immediately(self):
        class FakeProcess:
            stdout = iter(("Deploying app ✓\n", "Creating function\rReady\n"))

            def poll(self):
                return 0

            def wait(self):
                return 0

        with mock.patch.object(INSTALL.subprocess, "Popen", return_value=FakeProcess()) as popen:
            with mock.patch("builtins.print") as print_output:
                result = INSTALL.run_streaming(["modal", "deploy"], "Modal deployment")

        output = "\n".join(str(call.args[0]) for call in print_output.call_args_list)
        self.assertEqual("Deploying app ✓\nCreating function\rReady", result)
        self.assertIn("Deploying app ✓", output)
        self.assertIn("Creating function", output)
        self.assertIn("Ready", output)
        self.assertEqual("utf-8", popen.call_args.kwargs["encoding"])
        self.assertEqual("replace", popen.call_args.kwargs["errors"])
        self.assertIs(INSTALL.subprocess.STDOUT, popen.call_args.kwargs["stderr"])

    def test_environment_uses_workspace_default(self):
        with mock.patch.dict(INSTALL.os.environ, {"MODAL_ENVIRONMENT": ""}, clear=False):
            with mock.patch.object(INSTALL, "run_modal", return_value='{"default_environment":"preview"}') as run_modal:
                self.assertEqual("preview", INSTALL.resolve_modal_environment())
        run_modal.assert_called_once_with("workspace", "settings", "list", "--json", capture=True)

    def test_environment_falls_back_to_main(self):
        with mock.patch.dict(INSTALL.os.environ, {"MODAL_ENVIRONMENT": ""}, clear=False):
            with mock.patch.object(
                INSTALL,
                "run_modal",
                side_effect=INSTALL.subprocess.CalledProcessError(1, ("modal", "workspace", "settings")),
            ):
                self.assertEqual("main", INSTALL.resolve_modal_environment())

    def test_application_key_uses_temporary_json_not_command_line(self):
        observed = {}

        def inspect_command(*args, **_kwargs):
            path = Path(args[-1])
            observed["args"] = args
            observed["path"] = path
            observed["payload"] = json.loads(path.read_text(encoding="utf-8"))

        with mock.patch.object(INSTALL, "run_modal", side_effect=inspect_command):
            INSTALL.create_application_secret("goose-studio-api-key", "private-test-value")

        self.assertEqual(
            {"GOOSE_STUDIO_API_KEY": "private-test-value"},
            observed["payload"],
        )
        self.assertNotIn("private-test-value", " ".join(observed["args"]))
        self.assertFalse(observed["path"].exists())

    def test_endpoint_check_authenticates_before_setup_succeeds(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"status":"ok"}'

        with mock.patch.object(INSTALL.urllib.request, "urlopen", return_value=response) as urlopen:
            INSTALL.check_endpoint("https://example.modal.run/", "private-test-value", attempts=1)

        request = urlopen.call_args.args[0]
        self.assertIsInstance(request, INSTALL.urllib.request.Request)
        self.assertEqual("https://example.modal.run/auth-check", request.full_url)
        self.assertEqual("Bearer private-test-value", request.get_header("Authorization"))

    def test_endpoint_check_reports_rejected_application_key(self):
        error = INSTALL.urllib.error.HTTPError(
            "https://example.modal.run/auth-check",
            401,
            "Unauthorized",
            {},
            io.BytesIO(),
        )

        with mock.patch.object(INSTALL.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(INSTALL.InvalidApplicationApiKeyError):
                INSTALL.check_endpoint("https://example.modal.run", "stale-key", attempts=1)

    def test_deploy_repairs_a_rejected_saved_key(self):
        with mock.patch.object(INSTALL, "deploy", side_effect=["https://old.modal.run", "https://new.modal.run"]):
            with mock.patch.object(
                INSTALL,
                "check_endpoint",
                side_effect=[INSTALL.InvalidApplicationApiKeyError("stale key"), None],
            ) as check_endpoint:
                with mock.patch.object(INSTALL, "create_application_secret") as create_secret:
                    with mock.patch.object(INSTALL.secrets, "token_urlsafe", return_value="fresh-key"):
                        endpoint, api_key = INSTALL.deploy_and_verify("goose-studio", "stale-key", "stale-key")

        self.assertEqual(("https://new.modal.run", "fresh-key"), (endpoint, api_key))
        create_secret.assert_called_once_with("goose-studio-api-key", "fresh-key")
        self.assertEqual(
            [mock.call("https://old.modal.run", "stale-key"), mock.call("https://new.modal.run", "fresh-key")],
            check_endpoint.call_args_list,
        )

    def test_bundled_modal_cli_path_is_used(self):
        with mock.patch.object(INSTALL, "MODAL_CLI", Path("C:/Goose/modal-cli.exe")):
            with mock.patch.object(INSTALL, "run", return_value="ok") as run:
                result = INSTALL.run_modal("app", "list", capture=True)

        self.assertEqual("ok", result)
        run.assert_called_once_with(str(Path("C:/Goose/modal-cli.exe")), "app", "list", capture=True)

    def test_modal_command_failure_preserves_cli_details(self):
        error = INSTALL.subprocess.CalledProcessError(
            1,
            ("modal-cli.exe", "deploy"),
            output="Deploying app",
            stderr="Error: runtime image could not be resolved",
        )

        self.assertIn("Modal command failed with exit code 1", INSTALL._failure_summary(error))
        self.assertIn("runtime image could not be resolved", INSTALL._command_details(error))


if __name__ == "__main__":
    unittest.main()
