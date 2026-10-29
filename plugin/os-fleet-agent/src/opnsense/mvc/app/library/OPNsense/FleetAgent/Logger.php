<?php

namespace OPNsense\FleetAgent;

/**
 * Small append-only logger for the agent.
 *
 * OPNsense's syslog is intentionally not used for agent internals: the agent
 * can produce a large amount of diagnostics while applying policy, and a
 * dedicated file keeps /var/log/system.log readable. The file is rotated in
 * place once it exceeds MAX_LOG_BYTES.
 */
final class Logger
{
    private const LEVELS = ['debug' => 10, 'info' => 20, 'warning' => 30, 'error' => 40];

    private static string $level = 'info';

    public static function setLevel(string $level): void
    {
        $level = strtolower($level);
        self::$level = array_key_exists($level, self::LEVELS) ? $level : 'info';
    }

    public static function level(): string
    {
        return self::$level;
    }

    public static function debug(string $message, array $context = []): void
    {
        self::write('debug', $message, $context);
    }

    public static function info(string $message, array $context = []): void
    {
        self::write('info', $message, $context);
    }

    public static function warning(string $message, array $context = []): void
    {
        self::write('warning', $message, $context);
    }

    public static function error(string $message, array $context = []): void
    {
        self::write('error', $message, $context);
    }

    public static function exception(\Throwable $exception, string $message = ''): void
    {
        self::write('error', $message !== '' ? $message : $exception->getMessage(), [
            'exception' => get_class($exception),
            'message' => $exception->getMessage(),
            'file' => $exception->getFile(),
            'line' => $exception->getLine(),
        ]);
    }

    /**
     * @return list<array{ts: string, level: string, message: string, context: array}>
     */
    public static function tail(int $lines = 200): array
    {
        $lines = max(1, min($lines, 5000));
        if (!is_file(Paths::LOG_FILE) || !is_readable(Paths::LOG_FILE)) {
            return [];
        }

        $handle = @fopen(Paths::LOG_FILE, 'rb');
        if ($handle === false) {
            return [];
        }

        try {
            $buffer = '';
            $position = filesize(Paths::LOG_FILE);
            $chunk = 4096;
            while ($position > 0 && substr_count($buffer, "\n") <= $lines) {
                $read = min($chunk, $position);
                $position -= $read;
                fseek($handle, $position);
                $buffer = fread($handle, $read) . $buffer;
            }
        } finally {
            fclose($handle);
        }

        $rows = [];
        foreach (preg_split('/\r?\n/', trim($buffer)) ?: [] as $line) {
            $line = trim($line);
            if ($line === '') {
                continue;
            }
            $decoded = json_decode($line, true);
            if (is_array($decoded)) {
                $rows[] = $decoded;
            } else {
                $rows[] = ['ts' => '', 'level' => 'info', 'message' => $line, 'context' => []];
            }
        }

        return array_slice($rows, -$lines);
    }

    private static function write(string $level, string $message, array $context): void
    {
        if (self::LEVELS[$level] < self::LEVELS[self::$level]) {
            return;
        }

        Paths::ensure();
        self::rotate();

        $entry = [
            'ts' => gmdate('Y-m-d\TH:i:s\Z'),
            'level' => $level,
            'message' => $message,
            'context' => $context,
        ];
        $line = json_encode($entry, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($line === false) {
            $line = sprintf('{"ts":"%s","level":"error","message":"log encoding failed"}', gmdate('c'));
        }

        @file_put_contents(Paths::LOG_FILE, $line . PHP_EOL, FILE_APPEND | LOCK_EX);
        @chmod(Paths::LOG_FILE, 0640);
    }

    private static function rotate(): void
    {
        if (!is_file(Paths::LOG_FILE)) {
            return;
        }
        clearstatcache(true, Paths::LOG_FILE);
        if (filesize(Paths::LOG_FILE) < Paths::MAX_LOG_BYTES) {
            return;
        }
        @rename(Paths::LOG_FILE, Paths::LOG_FILE . '.1');
    }
}
