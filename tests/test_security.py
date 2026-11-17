"""Security regression tests: local files/config rendering only, never deploy."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure_env', ROOT / 'scripts/configure_env.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class EnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '.env'
        config.initialize(self.path)
        self.text, self.values = config.read_env(self.path)

    def test_generated_secrets_are_private_distinct_and_valid(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(config.validate(self.values, {}), '')
        self.assertEqual(len(set(self.values[k] for k in config.SECRET_NAMES)), 8)

    def test_init_never_overwrites_existing_config(self):
        with self.assertRaises(FileExistsError):
            config.initialize(self.path)
        self.assertEqual(self.path.read_text(), self.text)

    def test_each_required_secret_missing_or_empty_blocks(self):
        for key in config.SECRET_NAMES:
            for missing in (True, False):
                values = dict(self.values)
                if missing:
                    del values[key]
                else:
                    values[key] = ''
                with self.subTest(key=key, missing=missing), self.assertRaises(ValueError):
                    config.validate(values, {})

    def test_shell_overrides_are_validated(self):
        for key in config.SECRET_NAMES:
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.validate(self.values, {key: ''})

    def test_placeholder_and_reused_secrets_block(self):
        for value in ['0' * 64, 'your-' + 'secret-' * 6, 'inferencepack-secret-change-me', 'abc']:
            values = dict(self.values, NEXTAUTH_SECRET=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate(values, {})
        with self.assertRaises(ValueError):
            config.validate(dict(self.values, SALT=self.values['NEXTAUTH_SECRET']), {})

    def test_existing_encryption_key_is_preserved(self):
        config.prepare(self.path, self.text, '')
        _, values = config.read_env(self.path)
        self.assertEqual(values['ENCRYPTION_KEY'], self.values['ENCRYPTION_KEY'])
        self.assertEqual(values['SALT'], self.values['SALT'])

    def test_legacy_bootstrap_blocks_without_mutation(self):
        for key in ('LANGFUSE_INIT_USER_PASSWORD', 'LANGFUSE_INIT_USER_EMAIL', 'LANGFUSE_INIT_USER_NAME'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.validate(dict(self.values, **{key: 'legacy-value'}), {})
        self.assertEqual(self.path.read_text(), self.text)

    def test_auth_cannot_be_disabled(self):
        with self.assertRaises(ValueError):
            config.validate(self.values, {'WEBUI_AUTH': 'false'})
        config.validate(self.values, {'WEBUI_AUTH': 'true'})

    def test_signup_values_are_strict(self):
        for key in ('ENABLE_SIGNUP', 'AUTH_DISABLE_SIGNUP'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                config.validate(self.values, {key: 'maybe'})

    def test_pair_keys_and_effective_header(self):
        with self.assertRaises(ValueError):
            config.validate(self.values, {'LANGFUSE_PUBLIC_KEY': 'pk-test'})
        env = {'LANGFUSE_PUBLIC_KEY': 'pk-test', 'LANGFUSE_SECRET_KEY': 'sk-test'}
        expected = 'Authorization=Basic ' + base64.b64encode(b'pk-test:sk-test').decode() + ',x-langfuse-ingestion-version=4'
        self.assertEqual(config.validate(self.values, env), expected)
        with self.assertRaises(ValueError):
            config.validate(self.values, dict(env, **{config.HEADER: 'stale'}))

    def test_prepare_is_idempotent_and_clears_stale_header(self):
        config.prepare(self.path, self.text, 'test-header')
        text, _ = config.read_env(self.path)
        config.prepare(self.path, text, '')
        cleared, values = config.read_env(self.path)
        self.assertEqual(values[config.HEADER], '')
        config.prepare(self.path, cleared, '')
        self.assertEqual(self.path.read_text(), cleared)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_no_expansion_duplicates_or_multiline_syntax(self):
        for suffix in ['\nSALT=duplicate\n', '\nEXTRA=$(touch injected)\n', '\nEXTRA=${HOME}\n', '\nEXTRA="unclosed\n', '\nEXTRA=abc # comment\n']:
            self.path.write_text(self.text + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                config.read_env(self.path)

    def test_public_file_and_symlink_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            config.read_env(self.path)
        link = self.path.parent / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            config.read_env(link)
        with self.assertRaises(FileExistsError):
            config.initialize(link)

    def test_errors_do_not_echo_secrets(self):
        secret = 'PRIVATE+INVALID+VALUE'
        with self.assertRaises(ValueError) as error:
            config.validate(self.values, {'POSTGRES_PASSWORD': secret})
        self.assertNotIn(secret, str(error.exception))


class StartupTests(unittest.TestCase):
    def test_missing_env_stops_before_any_external_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copy(ROOT / 'run.sh', root)
            shutil.copy(ROOT / 'scripts/configure_env.py', root / 'scripts')
            marker = root / 'external-called'
            binpath = root / 'bin'
            binpath.mkdir()
            for command in ('docker', 'sudo', 'curl', 'uv', 'hf'):
                stub = binpath / command
                stub.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
                stub.chmod(0o700)
            result = subprocess.run(['bash', str(root / 'run.sh'), 'vllm'], capture_output=True, text=True,
                                    env={'PATH': f'{binpath}:/usr/bin:/bin'})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists())
            self.assertFalse((root / '.env').exists())

    def test_old_docker_stops_before_install_download_or_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            shutil.copy(ROOT / 'run.sh', root)
            shutil.copy(ROOT / 'scripts/configure_env.py', root / 'scripts')
            config.initialize(root / '.env')
            marker = root / 'side-effect'
            binpath = root / 'bin'
            binpath.mkdir()
            docker = binpath / 'docker'
            docker.write_text('#!/bin/sh\ncase "$1" in\ninfo) exit 0;;\nversion) echo 27.5.1; exit 0;;\nesac\nexit 1\n')
            docker.chmod(0o700)
            for command in ('sudo', 'curl', 'uv', 'hf'):
                stub = binpath / command
                stub.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 1\n')
                stub.chmod(0o700)
            result = subprocess.run(['bash', str(root / 'run.sh'), 'vllm'], capture_output=True, text=True,
                                    env={'PATH': f'{binpath}:/usr/bin:/bin'})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('28+', result.stdout)
            self.assertFalse(marker.exists())

    def test_explicit_env_file_and_version_guard(self):
        script = (ROOT / 'run.sh').read_text()
        for line in script.splitlines():
            if line.strip().startswith('docker compose ') or 'if docker compose ' in line:
                self.assertIn('--env-file "${SCRIPT_DIR}/.env"', line)
        self.assertIn('server_major < 28', script)
        self.assertNotIn('chmod 777', script)


@unittest.skipUnless(os.getenv('COMPOSE_BIN'), 'Set COMPOSE_BIN for actual Docker Compose rendering')
class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.envfile = self.root / '.env'
        config.initialize(self.envfile)
        _, self.values = config.read_env(self.envfile)

    def render(self, name, envfile=None, overrides=None):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(self.root)}
        env.update(overrides or {})
        return subprocess.run([os.environ['COMPOSE_BIN'], '--env-file', str(envfile or self.envfile),
                               '-f', str(ROOT / f'docker-compose.{name}.yml'), 'config', '--format', 'json'],
                              env=env, text=True, capture_output=True)

    def test_all_engines_and_langfuse_render_secure_defaults(self):
        for name in ('vllm', 'sglang', 'tensorrtllm', 'langfuse'):
            with self.subTest(engine=name):
                result = self.render(name)
                self.assertEqual(result.returncode, 0, 'Compose rendering failed')
                services = json.loads(result.stdout)['services']
                for service in services.values():
                    for port in service.get('ports', []):
                        self.assertEqual(port['host_ip'], '127.0.0.1')
                if name != 'langfuse':
                    ui = services['openwebui']['environment']
                    self.assertEqual(ui['WEBUI_AUTH'], 'true')
                    self.assertEqual(ui['ENABLE_SIGNUP'], 'false')
                    self.assertEqual(ui['OPENAI_API_KEY'], self.values['VLLM_API_KEY'])
                else:
                    self.assertEqual(services['langfuse-web']['environment']['AUTH_DISABLE_SIGNUP'], 'true')
                    self.assertNotIn('LANGFUSE_INIT_USER_PASSWORD', services['langfuse-web']['environment'])
                    for backend in ('postgres', 'redis', 'clickhouse', 'minio'):
                        self.assertFalse(services[backend].get('ports'))

    def test_missing_secrets_fail_before_deployment(self):
        empty = self.root / 'empty.env'
        empty.write_text('')
        for name in ('vllm', 'sglang', 'tensorrtllm', 'langfuse'):
            with self.subTest(engine=name):
                self.assertNotEqual(self.render(name, empty).returncode, 0)

    def test_auth_is_not_disabled_by_dotenv_or_export(self):
        result = self.render('vllm', overrides={'WEBUI_AUTH': 'false'})
        self.assertEqual(result.returncode, 0, 'Compose rendering failed')
        self.assertEqual(json.loads(result.stdout)['services']['openwebui']['environment']['WEBUI_AUTH'], 'true')

    def test_explicit_env_file_beats_compose_env_files(self):
        alternate = self.root / 'other.env'
        alternate.write_text('VLLM_API_KEY=alternate\n')
        result = self.render('vllm', overrides={'COMPOSE_ENV_FILES': str(alternate)})
        self.assertEqual(result.returncode, 0, 'Compose rendering failed')
        self.assertEqual(json.loads(result.stdout)['services']['vllm']['environment']['VLLM_API_KEY'], self.values['VLLM_API_KEY'])

    def test_controlled_signup_override(self):
        for name in ('vllm', 'sglang', 'tensorrtllm'):
            result = self.render(name, overrides={'ENABLE_SIGNUP': 'true'})
            self.assertEqual(result.returncode, 0, 'Compose rendering failed')
            ui = json.loads(result.stdout)['services']['openwebui']['environment']
            self.assertEqual(ui['ENABLE_SIGNUP'], 'true')
            self.assertEqual(ui['WEBUI_AUTH'], 'true')


if __name__ == '__main__':
    unittest.main()
