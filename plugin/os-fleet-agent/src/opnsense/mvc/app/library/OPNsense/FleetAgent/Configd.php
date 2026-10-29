<?php

namespace OPNsense\FleetAgent;

/**
 * Thin wrapper around configd and fixed system commands.
 *
 * Every caller supplies either a configd action name or a fixed executable plus
 * argument vector. User-controlled data is never interpolated into a shell
 * string; arguments are escaped through escapeshellarg().
 */
final class Configd
{
    /**
     * Run a configd action, for example Configd::run('filter', 'reload').
     *
     * @param list<string|int> $params
     * @return array{ok: bool, code: int, stdout: string, stderr: string, timed_out: bool}
     */
    public static function run(string $module, string $action, array $params = [], int $timeout = 30): array
    {
        $command = escapeshellarg(Paths::CONFIGD) . ' ' . escapeshellarg($module) . ' ' . escapeshellarg($action);
        foreach ($params as $param) {
            $command .= ' ' . escapeshellarg((string)$param);
        }
        return self::execute($command, $timeout);
    }

    /**
     * Run a configd action and decode its JSON output.
     *
     * @param list<string|int> $params
     * @return array<string, mixed>|list<mixed>|null
     */
    public static function json(string $module, string $action, array $params = [], int $timeout = 30): ?array
    {
        $result = self::run($module, $action, $params, $timeout);
        if (!$result['ok'] || trim($result['stdout']) === '') {
            return null;
        }
        $decoded = json_decode($result['stdout'], true);
        return is_array($decoded) ? $decoded : null;
    }

    /**
     * Run a fixed binary with an argument vector.
     *
     * @param list<string|int> $args
     * @return array{ok: bool, code: int, stdout: string, stderr: string, timed_out: bool}
     */
    public static function capture(string $binary, array $args = [], int $timeout = 30): array
    {
        $command = escapeshellarg($binary);
        foreach ($args as $arg) {
            $command .= ' ' . escapeshellarg((string)$arg);
        }
        return self::execute($command, $timeout);
    }

    /**
     * Run a fixed shell command without arguments.
     *
     * The command must be a constant from the agent source. This exists only
     * for pipelines that are not available as configd actions.
     *
     * @return array{ok: bool, code: int, stdout: string, stderr: string, timed_out: bool}
     */
    public static function shell(string $command, int $timeout = 30): array
    {
        return self::execute($command, $timeout);
    }

    /**
     * Run a fixed script with an argument vector.
     *
     * @param list<string|int> $args
     * @return array{ok: bool, code: int, stdout: string, stderr: string, timed_out: bool}
     */
    public static function script(string $path, array $args = [], int $timeout = 60): array
    {
        $command = escapeshellarg(Paths::PHP) . ' -f ' . escapeshellarg($path);
        foreach ($args as $arg) {
            $command .= ' ' . escapeshellarg((string)$arg);
        }
        return self::execute($command, $timeout);
    }

    /**
     * @return array{ok: bool, code: int, stdout: string, stderr: string, timed_out: bool}
     */
    private static function execute(string $command, int $timeout): array
    {
        $timeout = max(1, $timeout);
        $descriptors = [
            0 => ['pipe', 'r'],
            1 => ['pipe', 'w'],
            2 => ['pipe', 'w'],
        ];
        $pipes = [];
        $process = @proc_open($command, $descriptors, $pipes);
        if (!is_resource($process)) {
            return [
                'ok' => false,
                'code' => -1,
                'stdout' => '',
                'stderr' => 'unable to start process',
                'timed_out' => false,
            ];
        }

        fclose($pipes[0]);
        stream_set_blocking($pipes[1], false);
        stream_set_blocking($pipes[2], false);

        $stdout = '';
        $stderr = '';
        $exitCode = -1;
        $timedOut = false;
        $deadline = microtime(true) + $timeout;

        while (true) {
            $read = [];
            if (!feof($pipes[1])) {
                $read[] = $pipes[1];
            }
            if (!feof($pipes[2])) {
                $read[] = $pipes[2];
            }

            if ($read !== []) {
                $remaining = max(0.0, $deadline - microtime(true));
                $seconds = (int)floor($remaining);
                $microseconds = (int)(($remaining - $seconds) * 1000000);
                $write = null;
                $except = null;
                $ready = @stream_select($read, $write, $except, $seconds, $microseconds);
                if ($ready === false) {
                    break;
                }
                if ($ready > 0) {
                    foreach ($read as $stream) {
                        $chunk = fread($stream, 65536);
                        if ($chunk === false || $chunk === '') {
                            continue;
                        }
                        if ($stream === $pipes[1]) {
                            $stdout .= $chunk;
                        } else {
                            $stderr .= $chunk;
                        }
                    }
                }
            }

            $status = proc_get_status($process);
            if (!$status['running']) {
                $stdout .= (string)stream_get_contents($pipes[1]);
                $stderr .= (string)stream_get_contents($pipes[2]);
                $exitCode = (int)$status['exitcode'];
                break;
            }

            if (microtime(true) >= $deadline) {
                $timedOut = true;
                proc_terminate($process, 9);
                $exitCode = -1;
                break;
            }
        }

        fclose($pipes[1]);
        fclose($pipes[2]);
        $closed = proc_close($process);
        if ($exitCode < 0 && !$timedOut) {
            $exitCode = $closed;
        }

        return [
            'ok' => !$timedOut && $exitCode === 0,
            'code' => $exitCode,
            'stdout' => trim($stdout),
            'stderr' => trim($stderr),
            'timed_out' => $timedOut,
        ];
    }
}
