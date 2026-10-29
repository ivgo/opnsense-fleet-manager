#!/usr/local/bin/php
<?php

/**
 * OFME Fleet Agent command line interface.
 *
 * Every sub-command prints a single JSON document on stdout so that the
 * OPNsense MVC controllers, the rc(8) service wrapper and configd can consume
 * the result without parsing human-readable text.
 */

require_once('script/load_phalcon.php');

use OPNsense\FleetAgent\Agent;
use OPNsense\FleetAgent\Logger;
use OPNsense\FleetAgent\Paths;
use OPNsense\FleetAgent\State;

const OFME_EXIT_OK = 0;
const OFME_EXIT_ERROR = 1;
const OFME_EXIT_USAGE = 2;

/**
 * @param array<string, mixed> $payload
 */
function ofme_emit(array $payload, int $exitCode = OFME_EXIT_OK): void
{
    $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    if ($encoded === false) {
        $encoded = json_encode(['status' => 'error', 'message' => 'Unable to encode the response.']);
    }
    fwrite(STDOUT, $encoded . PHP_EOL);
    exit($exitCode);
}

function ofme_fail(string $message, int $exitCode = OFME_EXIT_ERROR): void
{
    ofme_emit([
        'status' => 'error',
        'message' => $message,
        'timestamp' => gmdate('c'),
    ], $exitCode);
}

/**
 * @return array{command: string, options: array<string, mixed>, arguments: list<string>}
 */
function ofme_parse_arguments(array $argv): array
{
    $command = 'status';
    $options = [];
    $arguments = [];

    foreach (array_slice($argv, 1) as $argument) {
        if ($command === 'status' && $argument !== '' && $argument[0] !== '-') {
            $command = strtolower(trim($argument));
            continue;
        }
        if (str_starts_with($argument, '--')) {
            $option = substr($argument, 2);
            $value = true;
            if (str_contains($option, '=')) {
                [$option, $value] = explode('=', $option, 2);
            }
            $options[strtolower(trim($option))] = $value;
            continue;
        }
        if (str_starts_with($argument, '-') && strlen($argument) === 2) {
            $options[strtolower(substr($argument, 1))] = true;
            continue;
        }
        $arguments[] = $argument;
    }

    return ['command' => $command, 'options' => $options, 'arguments' => $arguments];
}

/**
 * @param array<string, mixed> $options
 * @return array<string, mixed>
 */
function ofme_parse_payload(array $options, array $arguments, int $offset): array
{
    $raw = $options['payload'] ?? ($arguments[$offset] ?? null);
    if ($raw === null || $raw === '') {
        return [];
    }
    if (is_array($raw)) {
        return $raw;
    }
    $decoded = json_decode((string)$raw, true);
    if (!is_array($decoded)) {
        throw new \InvalidArgumentException('The payload must be a JSON object.');
    }
    return $decoded;
}

function ofme_usage(): void
{
    ofme_emit([
        'status' => 'usage',
        'command' => 'agent.php <daemon|once|enroll|renew|sync|preview|status|diagnostics|reset|test|command|version> [options]',
        'commands' => [
            'daemon [--max-cycles=N]' => 'Run the blocking agent loop.',
            'once [--force]' => 'Run a single agent cycle.',
            'enroll [--token=TOKEN]' => 'Enroll the device, optionally storing a new token first.',
            'renew' => 'Renew the device certificate.',
            'sync [--force]' => 'Apply the desired configuration.',
            'preview' => 'Show the configuration plan without applying it.',
            'status' => 'Print the agent status document.',
            'diagnostics' => 'Write and print a diagnostics bundle.',
            'reset' => 'Remove enrollment material and state.',
            'test' => 'Test connectivity to the platform.',
            'command <action> [--payload=JSON]' => 'Execute a whitelisted command locally.',
            'version' => 'Print version information.',
        ],
        'options' => [
            '--force' => 'Ignore the last applied configuration hash.',
            '--max-cycles=N' => 'Stop the daemon after N cycles (testing).',
            '--token=TOKEN' => 'Enrollment token to store before enrolling.',
            '--payload=JSON' => 'JSON payload for the command sub-command.',
        ],
    ]);
}

try {
    $parsed = ofme_parse_arguments($argv);
    $command = $parsed['command'];
    $options = $parsed['options'];
    $arguments = $parsed['arguments'];
    $force = isset($options['force']) || isset($options['f']);

    if (in_array($command, ['help', '-h', '--help'], true)) {
        ofme_usage();
    }

    if ($command === 'version') {
        $firmware = 'unknown';
        foreach (['/usr/local/opnsense/version/opnsense', '/usr/local/opnsense/version/core'] as $file) {
            $raw = Paths::read($file);
            if ($raw !== null && trim($raw) !== '') {
                $firmware = trim((string)strtok($raw, "\n"));
                break;
            }
        }
        ofme_emit([
            'status' => 'ok',
            'agent_version' => Paths::VERSION,
            'php_version' => PHP_VERSION,
            'openssl_version' => defined('OPENSSL_VERSION_TEXT') ? OPENSSL_VERSION_TEXT : null,
            'opnsense_version' => $firmware,
            'uname' => php_uname(),
            'config_dir' => Paths::CONFIG_DIR,
            'log_file' => Paths::LOG_FILE,
        ]);
    }

    if ($command === 'command') {
        $action = $arguments[0] ?? (isset($options['action']) ? (string)$options['action'] : '');
        if ($action === '') {
            ofme_fail('The command sub-command requires an action.', OFME_EXIT_USAGE);
        }
        $payload = ofme_parse_payload($options, $arguments, 1);
        ofme_emit((new Agent())->executeCommand($action, $payload));
    }

    if ($command === 'log') {
        $lines = isset($options['lines']) && is_numeric($options['lines'])
            ? (int)$options['lines']
            : (isset($arguments[0]) && is_numeric($arguments[0]) ? (int)$arguments[0] : 200);
        $rows = Logger::tail($lines);
        ofme_emit([
            'status' => 'ok',
            'log_file' => Paths::LOG_FILE,
            'count' => count($rows),
            'lines' => $rows,
        ]);
    }

    if ($command === 'import-ca') {
        $path = $arguments[0] ?? (isset($options['file']) ? (string)$options['file'] : '');
        if ($path === '') {
            ofme_fail('The import-ca sub-command requires a file path.', OFME_EXIT_USAGE);
        }
        $real = realpath($path);
        $temp = realpath(sys_get_temp_dir());
        if (
            $real === false
            || $temp === false
            || !str_starts_with($real, rtrim($temp, '/') . '/')
            || !str_starts_with(basename($real), 'ofme-ca-')
        ) {
            ofme_fail('Refusing to import a CA from an untrusted path.', OFME_EXIT_USAGE);
        }
        if (filesize($real) > 1048576) {
            ofme_fail('The CA bundle is larger than 1 MiB.', OFME_EXIT_USAGE);
        }
        $pem = (string)file_get_contents($real);
        if (!str_contains($pem, '-----BEGIN CERTIFICATE-----')) {
            @unlink($real);
            ofme_fail('The supplied file does not contain a PEM certificate.', OFME_EXIT_USAGE);
        }
        try {
            $fingerprint = (new Agent())->config()->importCa($pem);
        } finally {
            @unlink($real);
        }
        ofme_emit([
            'status' => 'ok',
            'ca_fingerprint' => $fingerprint,
            'timestamp' => gmdate('c'),
        ]);
    }

    $agent = new Agent();

    switch ($command) {
        case 'daemon':
            $maxCycles = 0;
            if (isset($options['max-cycles']) && is_numeric($options['max-cycles'])) {
                $maxCycles = max(0, (int)$options['max-cycles']);
            }
            $agent->runDaemon($maxCycles);
            ofme_emit([
                'status' => 'stopped',
                'timestamp' => gmdate('c'),
                'state' => State::all(),
            ]);
            break;

        case 'once':
            ofme_emit($agent->runCycle($force));
            break;

        case 'enroll':
            $token = isset($options['token']) ? trim((string)$options['token']) : '';
            if ($token === '' && isset($arguments[0])) {
                $token = trim($arguments[0]);
            }
            if ($token !== '') {
                $config = $agent->config();
                $model = $config->model();
                $model->enrollment_token = $token;
                $config->save();
            }
            ofme_emit($agent->enroll());
            break;

        case 'renew':
            ofme_emit($agent->renew());
            break;

        case 'sync':
            $report = $agent->configSync()->sync($force);
            ofme_emit($report, ($report['errors'] ?? []) === [] ? OFME_EXIT_OK : OFME_EXIT_ERROR);
            break;

        case 'preview':
            ofme_emit($agent->configSync()->preview());
            break;

        case 'status':
            ofme_emit($agent->status());
            break;

        case 'diagnostics':
            $diagnostics = $agent->diagnostics();
            if (!isset($options['full'])) {
                unset($diagnostics['payload']);
            }
            ofme_emit($diagnostics);
            break;

        case 'reset':
            ofme_emit($agent->reset());
            break;

        case 'test':
            ofme_emit($agent->testConnection());
            break;

        default:
            ofme_fail(sprintf('Unknown command: %s', $command), OFME_EXIT_USAGE);
    }
} catch (\InvalidArgumentException $exception) {
    ofme_fail($exception->getMessage(), OFME_EXIT_USAGE);
} catch (\Throwable $exception) {
    ofme_emit([
        'status' => 'error',
        'message' => $exception->getMessage(),
        'exception' => get_class($exception),
        'timestamp' => gmdate('c'),
    ], OFME_EXIT_ERROR);
}
