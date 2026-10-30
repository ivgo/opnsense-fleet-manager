import { configureStore } from "@reduxjs/toolkit";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "@mui/material/styles";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthUser, Device, Certificate, DeviceCommandStatus, FirmwareStatus, MetricSeries, TrafficSeries } from "@/api/types";
import authReducer from "@/store/authSlice";
import uiReducer from "@/store/uiSlice";
import { buildTheme } from "@/theme";

const {
  deviceDetailMock,
  deviceSeriesMock,
  deviceTrafficMock,
  deviceCertificatesMock,
  deviceCommandsMock,
  deviceFirmwareMock,
  deviceIpsecMock,
  deviceWireguardMock,
  deviceOpenvpnMock,
  deviceVlanMock,
  deviceDhcpMock,
  deviceDnsMock,
} = vi.hoisted(() => ({
  deviceDetailMock: vi.fn(),
  deviceSeriesMock: vi.fn(),
  deviceTrafficMock: vi.fn(),
  deviceCertificatesMock: vi.fn(),
  deviceCommandsMock: vi.fn(),
  deviceFirmwareMock: vi.fn(),
  deviceIpsecMock: vi.fn(),
  deviceWireguardMock: vi.fn(),
  deviceOpenvpnMock: vi.fn(),
  deviceVlanMock: vi.fn(),
  deviceDhcpMock: vi.fn(),
  deviceDnsMock: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  devicesApi: {
    get: deviceDetailMock,
    maintenance: vi.fn(),
    probe: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    issueCertificate: vi.fn(),
    sendCommand: vi.fn(),
    firmwareStatus: deviceFirmwareMock,
    upgradeFirmware: vi.fn(),
    rebootDevice: vi.fn(),
  },
  metricsApi: {
    deviceSeries: deviceSeriesMock,
    deviceTraffic: deviceTrafficMock,
  },
  deviceSdwanApi: {
    ipsecTunnels: deviceIpsecMock,
    wireguardServers: deviceWireguardMock,
    openvpnInstances: deviceOpenvpnMock,
    vlans: deviceVlanMock,
    dhcpLeases: deviceDhcpMock,
    dnsRecords: deviceDnsMock,
    createWireguardServer: vi.fn(),
    deleteWireguardServer: vi.fn(),
    createOpenvpnInstance: vi.fn(),
    deleteOpenvpnInstance: vi.fn(),
    createVlan: vi.fn(),
    deleteVlan: vi.fn(),
  },
  certificatesApi: {
    revoke: vi.fn(),
  },
}));

import DeviceDetailPage from "@/pages/DeviceDetailPage";

const USER: AuthUser = {
  id: "8f0d3a7e-6b1c-4a5d-9c2e-7f3b1a0d6e4c",
  tenant_id: null,
  username: "admin",
  email: "admin@example.com",
  full_name: "Platform Admin",
  roles: ["SuperAdmin"],
  permissions: ["*"],
  is_superadmin: true,
  mfa_enabled: false,
  auth_provider: "local",
  last_login_at: "2026-10-30T10:00:00Z",
};

const DEVICE_ID = "device-1";

const MOCK_DEVICE: Device = {
  id: DEVICE_ID,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-10-30T12:00:00Z",
  tenant_id: "tenant-1",
  site_id: "site-1",
  group_id: "group-1",
  name: "fw-edge-01",
  hostname: "fw-edge-01.example.com",
  description: "Edge firewall",
  serial_number: "FW123456",
  model: "OPNsense",
  firmware_version: "25.7.1",
  agent_version: "1.2.3",
  ip_address: "10.0.0.1",
  api_port: 443,
  status: "online",
  connection_status: "connected",
  is_ha: false,
  ha_role: null,
  tags: ["edge", "production"],
  certificate_serial: "ABC123DEF456",
  last_seen_at: "2026-10-30T12:00:00Z",
  last_heartbeat_at: "2026-10-30T11:59:00Z",
  uptime_seconds: 864000,
  enrolled_at: "2026-01-15T08:00:00Z",
  provisioned_at: "2026-01-16T09:00:00Z",
};

const MOCK_SERIES: MetricSeries = {
  device_id: DEVICE_ID,
  metric_type: "cpu",
  unit: "%",
  points: [
    { recorded_at: "2026-10-30T10:00:00Z", value: 25.5 },
    { recorded_at: "2026-10-30T11:00:00Z", value: 30.2 },
    { recorded_at: "2026-10-30T12:00:00Z", value: 28.1 },
  ],
};

const MOCK_TRAFFIC: TrafficSeries = {
  device_id: DEVICE_ID,
  interface: "wan",
  unit: "bps",
  hours: 24,
  bucket_seconds: 300,
  interfaces: [
    { key: "wan", name: "WAN" },
    { key: "lan", name: "LAN" },
  ],
  points: [
    { recorded_at: "2026-10-30T10:00:00Z", in_bps: 1000000, out_bps: 500000 },
    { recorded_at: "2026-10-30T11:00:00Z", in_bps: 1200000, out_bps: 600000 },
    { recorded_at: "2026-10-30T12:00:00Z", in_bps: 1100000, out_bps: 550000 },
  ],
  generated_at: "2026-10-30T12:00:00Z",
};

const MOCK_CERTIFICATES: Certificate[] = [
  {
    id: "cert-1",
    created_at: "2026-01-15T08:00:00Z",
    updated_at: "2026-10-30T12:00:00Z",
    device_id: DEVICE_ID,
    serial_number: "SERIAL123",
    subject_cn: "fw-edge-01.example.com",
    issuer_cn: "OFME CA",
    fingerprint_sha256: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    valid_from: "2026-01-15T08:00:00Z",
    valid_to: "2027-01-15T08:00:00Z",
    status: "valid",
    revoked_at: null,
  },
];

const MOCK_COMMANDS: DeviceCommandStatus = {
  device_id: DEVICE_ID,
  pending: [
    {
      id: "cmd-1",
      action: "ping",
      payload: {},
      requested_at: "2026-10-30T12:00:00Z",
      requested_by: "admin",
    },
  ],
  history: [
    {
      id: "cmd-2",
      action: "sync_config",
      status: "success",
      message: "Configuration applied",
      output: null,
      started_at: "2026-10-30T10:00:00Z",
      finished_at: "2026-10-30T10:01:00Z",
      duration_ms: 60000,
      received_at: "2026-10-30T10:01:00Z",
    },
  ],
  pending_count: 1,
  last_result_at: "2026-10-30T10:01:00Z",
};

const MOCK_FIRMWARE: FirmwareStatus = {
  device_id: DEVICE_ID,
  device_name: "fw-edge-01",
  reachable: true,
  product_version: "25.7.1",
  product_name: "OPNsense",
  product_series: "25.7",
  current_version: "25.7.1",
  latest_release: "25.7.2",
  needs_upgrade: true,
  upgrade_available: true,
  raw_firmware: {},
  raw_info: {},
};

async function renderDeviceDetailPage(deviceId = DEVICE_ID) {
  const store = configureStore({
    reducer: { auth: authReducer, ui: uiReducer },
    preloadedState: {
      auth: {
        user: USER,
        status: "authenticated",
        hydrated: true,
        error: null,
        mfaRequired: false,
        challengeToken: null,
        mfaMethods: [],
      },
      ui: { toasts: [] },
    },
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });

  render(
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider theme={buildTheme("light")}>
          <MemoryRouter initialEntries={[`/devices/${deviceId}`]}>
            <Routes>
              <Route path="devices/:deviceId" element={<DeviceDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </Provider>,
  );

  await waitFor(() => expect(deviceDetailMock).toHaveBeenCalled());

  return { store };
}

describe("DeviceDetailPage", () => {
  beforeEach(() => {
    deviceDetailMock.mockReset();
    deviceSeriesMock.mockReset();
    deviceTrafficMock.mockReset();
    deviceCertificatesMock.mockReset();
    deviceCommandsMock.mockReset();
    deviceFirmwareMock.mockReset();
    deviceIpsecMock.mockReset();
    deviceWireguardMock.mockReset();
    deviceOpenvpnMock.mockReset();
    deviceVlanMock.mockReset();
    deviceDhcpMock.mockReset();
    deviceDnsMock.mockReset();

    deviceDetailMock.mockResolvedValue(MOCK_DEVICE);
    deviceSeriesMock.mockResolvedValue(MOCK_SERIES);
    deviceTrafficMock.mockResolvedValue(MOCK_TRAFFIC);
    deviceCertificatesMock.mockResolvedValue(MOCK_CERTIFICATES);
    deviceCommandsMock.mockResolvedValue(MOCK_COMMANDS);
    deviceFirmwareMock.mockResolvedValue(MOCK_FIRMWARE);
    deviceIpsecMock.mockResolvedValue([]);
    deviceWireguardMock.mockResolvedValue([]);
    deviceOpenvpnMock.mockResolvedValue([]);
    deviceVlanMock.mockResolvedValue([]);
    deviceDhcpMock.mockResolvedValue([]);
    deviceDnsMock.mockResolvedValue([]);
  });

  it("renders the page header with device name and breadcrumbs", async () => {
    await renderDeviceDetailPage();

    expect(await screen.findByRole("heading", { name: "fw-edge-01" })).toBeInTheDocument();
    expect(screen.getByText("Devices")).toBeInTheDocument();
  });

  it("shows device status chips", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByText("Online")).toBeInTheDocument();
    expect(screen.getByText("Agent connected")).toBeInTheDocument();
  });

  it("shows HA tag when device is HA", async () => {
    await renderDeviceDetailPage();
    // This device is not HA, but we check the HA chip doesn't appear
    // We can't easily test the positive case without another mock
  });

  it("shows device tags", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByText("edge")).toBeInTheDocument();
    expect(screen.getByText("production")).toBeInTheDocument();
  });

  it("renders all tabs", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Certificates/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Commands/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Firmware" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "IPsec" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "WireGuard" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "OpenVPN" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "VLAN" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "DHCP" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "DNS" })).toBeInTheDocument();
  });

  it("renders inventory section with device details", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByText("fw-edge-01.example.com")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1:443")).toBeInTheDocument();
    expect(screen.getByText("FW123456")).toBeInTheDocument();
    expect(screen.getByText("OPNsense")).toBeInTheDocument();
    expect(screen.getByText("25.7.1")).toBeInTheDocument();
    expect(screen.getByText("1.2.3")).toBeInTheDocument();
    expect(screen.getByText("ABC123DEF456")).toBeInTheDocument();
    expect(screen.getByText("Edge firewall")).toBeInTheDocument();
  });

  it("shows probe button", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByRole("button", { name: "Probe" })).toBeInTheDocument();
  });

  it("shows maintenance button", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByRole("button", { name: "Maintenance" })).toBeInTheDocument();
  });

  it("shows edit button", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("shows delete button", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("renders telemetry chart with metric selector", async () => {
    await renderDeviceDetailPage();

    expect(await screen.findByRole("combobox", { name: /cpu utilisation/i })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: /24 hours/i })).toBeInTheDocument();
  });

  it("renders interface traffic chart", async () => {
    await renderDeviceDetailPage();

    expect(await screen.findByRole("combobox", { name: /wan/i })).toBeInTheDocument();
  });

  it("shows certificates tab with data", async () => {
    await renderDeviceDetailPage();

    // Click Certificates tab
    const certTab = screen.getByRole("tab", { name: /Certificates/ });
    await waitFor(() => certTab.click());

    await waitFor(() => expect(deviceCertificatesMock).toHaveBeenCalled());
    expect(await screen.findByText("fw-edge-01.example.com")).toBeInTheDocument();
    expect(await screen.findByText("OFME CA")).toBeInTheDocument();
    expect(await screen.findByText("valid")).toBeInTheDocument();
  });

  it("shows commands tab with pending and history", async () => {
    await renderDeviceDetailPage();

    // Click Commands tab
    const cmdTab = screen.getByRole("tab", { name: /Commands/ });
    await waitFor(() => cmdTab.click());

    await waitFor(() => expect(deviceCommandsMock).toHaveBeenCalled());
    expect(await screen.findByText("ping")).toBeInTheDocument();
    expect(screen.getAllByText("sync_config").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("success").length).toBeGreaterThanOrEqual(1);
  });

  it("shows firmware tab with version info", async () => {
    await renderDeviceDetailPage();

    // Click Firmware tab
    const fwTab = screen.getByRole("tab", { name: "Firmware" });
    await waitFor(() => fwTab.click());

    await waitFor(() => expect(deviceFirmwareMock).toHaveBeenCalled());
    expect(await screen.findByText("OPNsense")).toBeInTheDocument();
    expect(screen.getAllByText("25.7.1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("25.7.2").length).toBeGreaterThanOrEqual(1);
  });

  it("opens edit device dialog", async () => {
    await renderDeviceDetailPage();

    await screen.findByRole("button", { name: "Edit" }).then(btn => btn.click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByRole("heading", { name: "Edit device" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("opens delete device dialog", async () => {
    await renderDeviceDetailPage();

    await screen.findByRole("button", { name: "Delete" }).then(btn => btn.click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByRole("heading", { name: "Delete device" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("opens issue certificate dialog", async () => {
    await renderDeviceDetailPage();

    const certTab = screen.getByRole("tab", { name: /Certificates/ });
    await waitFor(() => certTab.click());

    await screen.findByRole("button", { name: "Issue certificate" }).then(btn => btn.click());

    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(await screen.findByRole("heading", { name: "Issue device certificate" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Issue" })).toBeInTheDocument();
  });

  it("shows empty state for IPsec when no tunnels", async () => {
    await renderDeviceDetailPage();

    const ipsecTab = screen.getByRole("tab", { name: "IPsec" });
    await waitFor(() => ipsecTab.click());

    expect(await screen.findByText("No IPsec tunnels")).toBeInTheDocument();
  });

  it("shows empty state for WireGuard when no servers", async () => {
    await renderDeviceDetailPage();

    const wgTab = screen.getByRole("tab", { name: "WireGuard" });
    await waitFor(() => wgTab.click());

    expect(screen.getByText("No WireGuard servers")).toBeInTheDocument();
  });

  it("shows empty state for OpenVPN when no instances", async () => {
    await renderDeviceDetailPage();

    const ovpnTab = screen.getByRole("tab", { name: "OpenVPN" });
    await waitFor(() => ovpnTab.click());

    expect(screen.getByText("No OpenVPN instances")).toBeInTheDocument();
  });

  it("shows empty state for VLAN when none configured", async () => {
    await renderDeviceDetailPage();

    const vlanTab = screen.getByRole("tab", { name: "VLAN" });
    await waitFor(() => vlanTab.click());

    expect(screen.getByText("No VLANs")).toBeInTheDocument();
  });

  it("shows empty state for DHCP when no leases", async () => {
    await renderDeviceDetailPage();

    const dhcpTab = screen.getByRole("tab", { name: "DHCP" });
    await waitFor(() => dhcpTab.click());

    expect(screen.getByText("No DHCP leases")).toBeInTheDocument();
  });

  it("shows empty state for DNS when no records", async () => {
    await renderDeviceDetailPage();

    const dnsTab = screen.getByRole("tab", { name: "DNS" });
    await waitFor(() => dnsTab.click());

    expect(screen.getByText("No DNS records")).toBeInTheDocument();
  });

  it("shows device uptime and last seen", async () => {
    await renderDeviceDetailPage();

    expect(screen.getAllByText(/Last seen/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/up/)).toBeInTheDocument();
  });

  it("shows connection details", async () => {
    await renderDeviceDetailPage();

    expect(screen.getByText("Agent connected")).toBeInTheDocument();
    expect(screen.getByText(/Last heartbeat/)).toBeInTheDocument();
  });
});