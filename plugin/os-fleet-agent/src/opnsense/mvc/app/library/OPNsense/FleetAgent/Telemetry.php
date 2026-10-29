<?php

namespace OPNsense\FleetAgent;

use OPNsense\Core\Config;

/**
 * Collect the telemetry document accepted by POST /agent/heartbeat.
 *
 * Every probe degrades to null instead of failing the heartbeat. The platform
 * schema accepts nulls for all optional metrics.
 */
final class Telemetry
{
    /** @var array<string, array<string, mixed>>|null */
    private ?array $interfaceCache = null;

    public function __construct(private AgentConfig $config, private Identity $identity)
    {
    }

    /**
     * @return array<string, mixed>
     */
    public function collect(): array
    {
        $payload = [
            'serial_number' => $this->identity->serialNumber(),
            'hostname' => $this->identity->hostname(),
            'firmware_version' => $this->identity->firmwareVersion(),
            'agent_version' => Paths::VERSION,
            'uptime_seconds' => $this->identity->uptimeSeconds(),
            'cpu_pct' => $this->cpuPercent(),
            'memory_pct' => $this->memoryPercent(),
            'disk_pct' => $this->diskPercent(),
            'load_1m' => $this->loadAverage(),
            'sessions' => $this->stateCount(),
            'carp_status' => $this->carpStatus(),
        ];

        [$vpnUp, $vpnTotal] = $this->vpnCounts();
        if ($vpnTotal !== null) {
            $payload['vpn_up'] = $vpnUp;
            $payload['vpn_total'] = $vpnTotal;
        }

        [$gatewaysUp, $gatewaysTotal] = $this->gatewayCounts();
        if ($gatewaysTotal !== null) {
            $payload['gateways_up'] = $gatewaysUp;
            $payload['gateways_total'] = $gatewaysTotal;
        }

        $payload['interfaces'] = $this->interfaces();

        $traffic = $this->traffic();
        if ($traffic !== null) {
            $payload['traffic'] = $traffic;
        }

        $arp = $this->arpTable();
        if ($arp !== null) {
            $payload['arp'] = $arp;
        }

        $dhcp = $this->dhcpLeases();
        if ($dhcp !== null) {
            $payload['dhcp_leases'] = $dhcp;
        }

        $lldp = $this->lldpNeighbors();
        if ($lldp !== null) {
            $payload['lldp'] = $lldp;
        }

        return $payload;
    }

    private function cpuPercent(): ?float
    {
        $first = $this->readCpuSample();
        if ($first === null) {
            return null;
        }

        $previous = State::get('cpu_sample');
        State::set('cpu_sample', $first);
        if (!is_array($previous) || !isset($previous['total'], $previous['idle'])) {
            usleep(250000);
            $second = $this->readCpuSample();
            if ($second === null) {
                return null;
            }
            State::set('cpu_sample', $second);
            $previous = $first;
            $first = $second;
        }

        $totalDelta = (int)$first['total'] - (int)$previous['total'];
        $idleDelta = (int)$first['idle'] - (int)$previous['idle'];
        if ($totalDelta <= 0 || $idleDelta < 0) {
            return null;
        }

        $busy = 1.0 - ($idleDelta / $totalDelta);
        return round(max(0.0, min(100.0, $busy * 100.0)), 1);
    }

    /**
     * @return array{total: int, idle: int}|null
     */
    private function readCpuSample(): ?array
    {
        $result = Configd::capture('/sbin/sysctl', ['-n', 'kern.cp_time'], 5);
        if (!$result['ok']) {
            return null;
        }
        $parts = preg_split('/\s+/', trim($result['stdout'])) ?: [];
        if (count($parts) < 5) {
            return null;
        }
        $values = array_map('intval', array_slice($parts, 0, 5));
        return [
            'total' => array_sum($values),
            'idle' => $values[4],
        ];
    }

    private function memoryPercent(): ?float
    {
        $total = $this->sysctlInt('hw.physmem');
        $pageSize = $this->sysctlInt('vm.stats.vm.v_page_size');
        $free = $this->sysctlInt('vm.stats.vm.v_free_count');
        if ($total === null || $total <= 0 || $pageSize === null || $free === null) {
            return null;
        }
        $inactive = $this->sysctlInt('vm.stats.vm.v_inactive_count') ?? 0;
        $cache = $this->sysctlInt('vm.stats.vm.v_cache_count') ?? 0;
        $available = ($free + $inactive + $cache) * $pageSize;
        $used = max(0, $total - $available);
        return round(max(0.0, min(100.0, ($used / $total) * 100.0)), 1);
    }

    private function diskPercent(): ?float
    {
        $total = @disk_total_space('/');
        $free = @disk_free_space('/');
        if ($total === false || $free === false || $total <= 0) {
            return null;
        }
        $used = max(0.0, $total - $free);
        return round(max(0.0, min(100.0, ($used / $total) * 100.0)), 1);
    }

    private function loadAverage(): ?float
    {
        $load = @sys_getloadavg();
        if (is_array($load) && isset($load[0])) {
            return round((float)$load[0], 2);
        }
        $raw = $this->identity->productInfo();
        unset($raw);
        $result = Configd::capture('/sbin/sysctl', ['-n', 'vm.loadavg'], 5);
        if ($result['ok'] && preg_match('/\{?\s*([0-9.]+)/', $result['stdout'], $matches)) {
            return round((float)$matches[1], 2);
        }
        return null;
    }

    private function stateCount(): ?int
    {
        $result = Configd::capture('/sbin/pfctl', ['-si'], 10);
        if ($result['ok'] && preg_match('/current entries\s+(\d+)/i', $result['stdout'], $matches)) {
            return (int)$matches[1];
        }
        $diag = Configd::run('filter', 'diag.state_size', [], 10);
        if ($diag['ok'] && preg_match('/(\d+)/', $diag['stdout'], $matches)) {
            return (int)$matches[1];
        }
        return null;
    }

    private function carpStatus(): string
    {
        $config = Config::getInstance()->object();
        $configured = false;
        if (isset($config->virtualip->vip)) {
            foreach ($config->virtualip->vip as $vip) {
                if ((string)$vip->mode === 'carp') {
                    $configured = true;
                    break;
                }
            }
        }
        if (!$configured) {
            return 'disabled';
        }

        $result = Configd::shell(
            '/sbin/ifconfig | /usr/bin/grep -o "carp: [A-Za-z]*" | /usr/bin/head -n 1',
            10
        );
        if ($result['ok'] && preg_match('/carp:\s*(master|backup|init)/i', $result['stdout'], $matches)) {
            return strtolower($matches[1]);
        }
        return 'unknown';
    }

    /**
     * @return array{0: int|null, 1: int|null}
     */
    private function vpnCounts(): array
    {
        $up = 0;
        $total = 0;

        $ipsec = Configd::json('ipsec', 'list.status', [], 15);
        if (is_array($ipsec)) {
            foreach ($ipsec as $connection) {
                if (!is_array($connection)) {
                    continue;
                }
                $total++;
                if (!empty($connection['sas']) && is_array($connection['sas'])) {
                    $up++;
                }
            }
        }

        $openvpn = Configd::json('openvpn', 'connections', ['server,client'], 15);
        if (is_array($openvpn)) {
            foreach (['server', 'client'] as $role) {
                if (empty($openvpn[$role]) || !is_array($openvpn[$role])) {
                    continue;
                }
                foreach ($openvpn[$role] as $instance) {
                    if (!is_array($instance)) {
                        continue;
                    }
                    $total++;
                    if ($role === 'server') {
                        $clients = $instance['client_list'] ?? $instance['routing_table'] ?? [];
                        if (is_array($clients) && count($clients) > 0) {
                            $up++;
                        }
                    } else {
                        $status = strtolower((string)($instance['status'] ?? ''));
                        if (in_array($status, ['connected', 'ok', 'online'], true)) {
                            $up++;
                        }
                    }
                }
            }
        }

        return $total > 0 ? [$up, $total] : [null, null];
    }

    /**
     * @return array{0: int|null, 1: int|null}
     */
    private function gatewayCounts(): array
    {
        $data = Configd::json('interface', 'gateways.status', [], 15);
        if (!is_array($data)) {
            return [null, null];
        }

        $items = $data;
        if (isset($data['items']) && is_array($data['items'])) {
            $items = $data['items'];
        } elseif (!array_is_list($data)) {
            $items = [];
            foreach ($data as $name => $value) {
                if (is_array($value)) {
                    if (!isset($value['name'])) {
                        $value['name'] = $name;
                    }
                    $items[] = $value;
                }
            }
        }

        if ($items === []) {
            return [0, 0];
        }

        $up = 0;
        foreach ($items as $gateway) {
            if (!is_array($gateway)) {
                continue;
            }
            $status = strtolower((string)($gateway['status'] ?? $gateway['state'] ?? ''));
            if (in_array($status, ['none', 'online', 'up', 'ok'], true)) {
                $up++;
            }
        }
        return [$up, count($items)];
    }

    /**
     * @return list<array<string, mixed>>
     */
    private function interfaces(): array
    {
        $states = $this->interfaceStates();
        $config = Config::getInstance()->object();
        $rows = [];

        if (!isset($config->interfaces)) {
            return $rows;
        }

        foreach ($config->interfaces->children() as $key => $interface) {
            $device = trim((string)$interface->if);
            if ($device === '') {
                continue;
            }
            $state = $states[$device] ?? [];
            $disabled = isset($interface->enable) && (string)$interface->enable === '0';
            $rows[] = [
                'name' => (string)$key,
                'description' => (string)($interface->descr ?? strtoupper((string)$key)),
                'device' => $device,
                'ip_address' => (string)($interface->ipaddr ?? ''),
                'subnet_bits' => (string)($interface->subnet ?? ''),
                'mac' => $state['mac'] ?? null,
                'mtu' => $state['mtu'] ?? null,
                'status' => $disabled ? 'disabled' : ($state['status'] ?? 'unknown'),
            ];
        }

        return $rows;
    }

    /**
     * Cumulative byte counters per configured interface.
     *
     * The platform derives rates from two consecutive samples; the agent only
     * reports monotonic counters. `interface show traffic` already maps device
     * names to configuration keys (wan, lan, opt…) and includes the description.
     *
     * @return array<string, mixed>|null
     */
    private function traffic(): ?array
    {
        $data = Configd::json('interface', 'show.traffic', [], 15);
        if (!is_array($data) || empty($data['interfaces']) || !is_array($data['interfaces'])) {
            return null;
        }

        $interfaces = [];
        foreach ($data['interfaces'] as $key => $row) {
            if (!is_array($row)) {
                continue;
            }
            $interfaces[(string)$key] = [
                'name' => (string)($row['name'] ?? strtoupper((string)$key)),
                'inbytes' => max(0, (int)($row['inbytes'] ?? $row['bytes received'] ?? 0)),
                'outbytes' => max(0, (int)($row['outbytes'] ?? $row['bytes transmitted'] ?? 0)),
            ];
        }

        if ($interfaces === []) {
            return null;
        }

        return [
            'time' => (float)($data['time'] ?? microtime(true)),
            'interfaces' => $interfaces,
        ];
    }

    /**
     * @return array<string, array<string, mixed>>
     */
    private function interfaceStates(): array
    {
        if ($this->interfaceCache !== null) {
            return $this->interfaceCache;
        }

        $result = Configd::capture('/sbin/ifconfig', ['-a'], 15);
        $states = [];
        if (!$result['ok']) {
            $this->interfaceCache = $states;
            return $states;
        }

        $blocks = preg_split('/\n(?=[A-Za-z0-9_.]+:\s)/', $result['stdout']) ?: [];
        foreach ($blocks as $block) {
            if (!preg_match('/^([A-Za-z0-9_.]+):\s/', $block, $matches)) {
                continue;
            }
            $name = $matches[1];
            $state = ['status' => 'unknown', 'mac' => null, 'mtu' => null];
            if (preg_match('/\bmtu\s+(\d+)/', $block, $mtu)) {
                $state['mtu'] = (int)$mtu[1];
            }
            if (preg_match('/\bether\s+([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b/i', $block, $mac)) {
                $state['mac'] = strtolower($mac[1]);
            }
            if (preg_match('/\bstatus:\s+([a-z]+)/i', $block, $status)) {
                $state['status'] = strtolower($status[1]);
            } elseif (strpos($block, '<UP,') !== false || preg_match('/flags=\w+<UP[,>]/', $block)) {
                $state['status'] = 'active';
            }
            $states[$name] = $state;
        }

        $this->interfaceCache = $states;
        return $states;
    }

    private function sysctlInt(string $name): ?int
    {
        $result = Configd::capture('/sbin/sysctl', ['-n', $name], 5);
        if (!$result['ok']) {
            return null;
        }
        $value = trim($result['stdout']);
        return ctype_digit($value) ? (int)$value : null;
    }

    /**
     * ARP table: IP to MAC bindings.
     *
     * @return list<array{ip: string, mac: string, interface: string|null}>|null
     */
    private function arpTable(): ?array
    {
        $result = Configd::capture('/usr/sbin/arp', ['-an'], 10);
        if (!$result['ok']) {
            return null;
        }

        $entries = [];
        $lines = preg_split('/\r\n|\r|\n/', $result['stdout']) ?: [];

        foreach ($lines as $line) {
            // Format: ? (192.168.1.5) at aa:bb:cc:dd:ee:ff on em0 expires ...
            if (preg_match('/\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-f:]+)/i', $line, $matches)) {
                $ip = $matches[1];
                $mac = strtoupper($matches[2]);
                $interface = null;
                if (preg_match('/on\s+(\w+)/', $line, $ifMatches)) {
                    $interface = $ifMatches[1];
                }
                $entries[] = [
                    'ip' => $ip,
                    'mac' => $mac,
                    'interface' => $interface,
                ];
            }
        }

        return $entries ?: null;
    }

    /**
     * DHCP leases from dhcpd.leases file.
     *
     * @return list<array{ip: string, mac: string, hostname: string|null, expires: string|null}>|null
     */
    private function dhcpLeases(): ?array
    {
        $leaseFile = '/var/dhcpd/var/db/dhcpd.leases';
        $content = @file_get_contents($leaseFile);
        if ($content === false) {
            return null;
        }

        $entries = [];
        $currentLease = null;

        $lines = preg_split('/\r\n|\r|\n/', $content) ?: [];
        foreach ($lines as $line) {
            $line = trim($line);

            if (preg_match('/lease\s+(\d+\.\d+\.\d+\.\d+)\s*\{/', $line, $matches)) {
                if ($currentLease !== null) {
                    $entries[] = $currentLease;
                }
                $currentLease = ['ip' => $matches[1]];
            } elseif ($currentLease !== null) {
                if (preg_match('/hardware\s+ethernet\s+([0-9a-f:]+);/i', $line, $matches)) {
                    $currentLease['mac'] = strtoupper($matches[1]);
                }
                if (preg_match('/client-hostname\s+"([^"]+)";/', $line, $matches)) {
                    $currentLease['hostname'] = $matches[1];
                }
                if (preg_match('/starts\s+\d+\s+([^;]+);/', $line, $matches)) {
                    $currentLease['starts'] = trim($matches[1]);
                }
                if (preg_match('/ends\s+\d+\s+([^;]+);/', $line, $matches)) {
                    $currentLease['expires'] = trim($matches[1]);
                }
            }
        }

        if ($currentLease !== null) {
            $entries[] = $currentLease;
        }

        return $entries ?: null;
    }

    /**
     * LLDP neighbors from lldpctl.
     *
     * @return list<array{mac: string, chassis_name: string|null, port_description: string|null, management_ip: string|null}>|null
     */
    private function lldpNeighbors(): ?array
    {
        $result = Configd::shell('/usr/local/sbin/lldpctl -f keyvalue', 10);
        if (!$result['ok']) {
            return null;
        }

        $entries = [];
        $current = [];
        $lines = preg_split('/\r\n|\r|\n/', $result['stdout']) ?: [];

        foreach ($lines as $line) {
            $line = trim($line);
            if (empty($line)) {
                if (!empty($current) && isset($current['lldp.chassis.mac'])) {
                    $entries[] = [
                        'mac' => strtoupper($current['lldp.chassis.mac']),
                        'chassis_name' => $current['lldp.chassis.name'] ?? null,
                        'port_description' => $current['lldp.port.description'] ?? null,
                        'management_ip' => $current['lldp.mgmt-ip'] ?? null,
                        'vendor' => $current['lldp.chassis.description'] ?? null,
                    ];
                }
                $current = [];
                continue;
            }

            if (strpos($line, '=') !== false) {
                [$key, $value] = explode('=', $line, 2);
                $current[trim($key)] = trim($value);
            }
        }

        // Don't forget the last entry
        if (!empty($current) && isset($current['lldp.chassis.mac'])) {
            $entries[] = [
                'mac' => strtoupper($current['lldp.chassis.mac']),
                'chassis_name' => $current['lldp.chassis.name'] ?? null,
                'port_description' => $current['lldp.port.description'] ?? null,
                'management_ip' => $current['lldp.mgmt-ip'] ?? null,
                'vendor' => $current['lldp.chassis.description'] ?? null,
            ];
        }

        return $entries ?: null;
    }
}
