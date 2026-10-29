<?php

namespace OPNsense\FleetAgent;

/**
 * Persistent non-secret agent state.
 *
 * The state file contains timestamps, counters and the last observed
 * configuration hash. It is deliberately separate from config.xml so that a
 * failed cycle cannot corrupt the firewall configuration.
 */
final class State
{
    /** @var array<string, mixed>|null */
    private static ?array $cache = null;

    /**
     * @return array<string, mixed>
     */
    public static function all(): array
    {
        if (self::$cache !== null) {
            return self::$cache;
        }
        $raw = Paths::read(Paths::STATE_FILE);
        if ($raw === null || $raw === '') {
            self::$cache = [];
            return self::$cache;
        }
        $decoded = json_decode($raw, true);
        self::$cache = is_array($decoded) ? $decoded : [];
        return self::$cache;
    }

    /**
     * @param mixed $default
     * @return mixed
     */
    public static function get(string $key, $default = null)
    {
        $state = self::all();
        return array_key_exists($key, $state) ? $state[$key] : $default;
    }

    /**
     * Merge a patch into the state and persist it atomically.
     *
     * @param array<string, mixed> $patch
     * @return array<string, mixed>
     */
    public static function merge(array $patch): array
    {
        $state = array_merge(self::all(), $patch);
        self::write($state);
        return $state;
    }

    public static function set(string $key, $value): void
    {
        self::merge([$key => $value]);
    }

    /**
     * @param array<string, mixed> $state
     */
    public static function write(array $state): void
    {
        self::$cache = $state;
        $payload = json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($payload === false) {
            throw new \RuntimeException('Unable to encode agent state');
        }
        Paths::write(Paths::STATE_FILE, $payload . PHP_EOL, 0600);
    }

    public static function clear(): void
    {
        self::$cache = [];
        Paths::delete(Paths::STATE_FILE);
    }

    /**
     * Record a bounded command-result history.
     *
     * @param list<array<string, mixed>> $results
     */
    public static function appendCommandResults(array $results): void
    {
        if ($results === []) {
            return;
        }
        $history = self::get('command_results', []);
        if (!is_array($history)) {
            $history = [];
        }
        foreach ($results as $result) {
            $history[] = $result;
        }
        self::merge(['command_results' => array_slice($history, -100)]);
    }
}
