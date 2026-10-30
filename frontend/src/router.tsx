import { Navigate, createBrowserRouter } from "react-router-dom";

import RequireAuth from "@/components/RequireAuth";
import AppLayout from "@/layout/AppLayout";
import ApprovalsPage from "@/pages/ApprovalsPage";
import AliasesPage from "@/pages/AliasesPage";
import AuditPage from "@/pages/AuditPage";
import BackupsPage from "@/pages/BackupsPage";
import CompliancePage from "@/pages/CompliancePage";
import DashboardPage from "@/pages/DashboardPage";
import DeviceDetailPage from "@/pages/DeviceDetailPage";
import DevicesPage from "@/pages/DevicesPage";
import DhcpPage from "@/pages/DhcpPage";
import DnsPage from "@/pages/DnsPage";
import GitReposPage from "@/pages/GitReposPage";
import GroupsPage from "@/pages/GroupsPage";
import HaPage from "@/pages/HaPage";
import { InventoryPage } from "@/pages/InventoryPage";
import JobsPage from "@/pages/JobsPage";
import LoginPage from "@/pages/LoginPage";
import MaintenancePage from "@/pages/MaintenancePage";
import NatPage from "@/pages/NatPage";
import NotFoundPage from "@/pages/NotFoundPage";
import NotificationsPage from "@/pages/NotificationsPage";
import OidcCallbackPage from "@/pages/OidcCallbackPage";
import PoliciesPage from "@/pages/PoliciesPage";
import ReportsPage from "@/pages/ReportsPage";
import RulesPage from "@/pages/RulesPage";
import SamlCallbackPage from "@/pages/SamlCallbackPage";
import SdWanPage from "@/pages/SdWanPage";
import SettingsPage from "@/pages/SettingsPage";
import SitesPage from "@/pages/SitesPage";
import TemplatesPage from "@/pages/TemplatesPage";
import UsersPage from "@/pages/UsersPage";
import ZtpPage from "@/pages/ZtpPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/auth/callback", element: <OidcCallbackPage /> },
  { path: "/saml/callback", element: <SamlCallbackPage /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "devices", element: <DevicesPage /> },
      { path: "devices/:deviceId", element: <DeviceDetailPage /> },
      { path: "sites", element: <SitesPage /> },
      { path: "groups", element: <GroupsPage /> },
      { path: "dhcp", element: <DhcpPage /> },
      { path: "dns", element: <DnsPage /> },
      { path: "rules", element: <RulesPage /> },
      { path: "nat", element: <NatPage /> },
      { path: "aliases", element: <AliasesPage /> },
      { path: "ha", element: <HaPage /> },
      { path: "policies", element: <PoliciesPage /> },
      { path: "templates", element: <TemplatesPage /> },
      { path: "sdwan", element: <SdWanPage /> },
      { path: "ztp", element: <ZtpPage /> },
      { path: "git", element: <GitReposPage /> },
      { path: "approvals", element: <ApprovalsPage /> },
      { path: "notifications", element: <NotificationsPage /> },
      { path: "compliance", element: <CompliancePage /> },
      { path: "audit", element: <AuditPage /> },
      { path: "backups", element: <BackupsPage /> },
      { path: "maintenance", element: <MaintenancePage /> },
      { path: "reports", element: <ReportsPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "inventory", element: <InventoryPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export default router;
