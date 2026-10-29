import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  IconButton,
  LinearProgress,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PlaceOutlinedIcon from "@mui/icons-material/PlaceOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { sitesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Site, SitePayload } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import SiteMap from "@/components/SiteMap";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatNumber } from "@/utils/format";

interface SiteFormState {
  name: string;
  code: string;
  description: string;
  address: string;
  city: string;
  country: string;
  latitude: string;
  longitude: string;
  timezone: string;
}

const EMPTY_FORM: SiteFormState = {
  name: "",
  code: "",
  description: "",
  address: "",
  city: "",
  country: "",
  latitude: "",
  longitude: "",
  timezone: "",
};

function toCoordinate(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function SitesPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Site | null>(null);
  const [form, setForm] = useState<SiteFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Site | null>(null);

  const listParams = useMemo(
    () => ({ page, size, sort, order, search: debouncedSearch || undefined }),
    [page, size, sort, order, debouncedSearch],
  );

  const sitesQuery = useQuery({
    queryKey: qk.sites.list(listParams),
    queryFn: () => sitesApi.list(listParams),
  });

  const mapQuery = useQuery({
    queryKey: qk.sites.map,
    queryFn: () => sitesApi.map(),
    staleTime: 60_000,
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.sites.all });
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
    void queryClient.invalidateQueries({ queryKey: qk.dashboard });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: SitePayload = {
        name: form.name.trim(),
        code: form.code.trim().toUpperCase(),
        description: form.description.trim() || null,
        address: form.address.trim() || null,
        city: form.city.trim() || null,
        country: form.country.trim().toUpperCase() || null,
        latitude: toCoordinate(form.latitude),
        longitude: toCoordinate(form.longitude),
        timezone: form.timezone.trim() || null,
      };
      if (editing) {
        return sitesApi.update(editing.id, {
          name: payload.name,
          description: payload.description,
          address: payload.address,
          city: payload.city,
          country: payload.country,
          latitude: payload.latitude,
          longitude: payload.longitude,
          timezone: payload.timezone,
        });
      }
      return sitesApi.create(payload);
    },
    onSuccess: (site) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Site ${site.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => sitesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Site deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (site: Site) => {
    setEditing(site);
    setForm({
      name: site.name,
      code: site.code,
      description: site.description ?? "",
      address: "",
      city: site.city ?? "",
      country: site.country ?? "",
      latitude: site.latitude !== null ? String(site.latitude) : "",
      longitude: site.longitude !== null ? String(site.longitude) : "",
      timezone: site.timezone ?? "",
    });
    setFormError(null);
    setFormOpen(true);
  };

  const columns: Array<DataTableColumn<Site>> = [
    {
      key: "name",
      label: "Site",
      sortable: true,
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <PlaceOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {row.code}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "location",
      label: "Location",
      render: (row) => [row.city, row.country].filter(Boolean).join(", ") || EMPTY,
    },
    {
      key: "coordinates",
      label: "Coordinates",
      width: 190,
      hideBelow: "md",
      monospace: true,
      render: (row) =>
        row.latitude !== null && row.longitude !== null
          ? `${row.latitude.toFixed(4)}, ${row.longitude.toFixed(4)}`
          : EMPTY,
    },
    { key: "timezone", label: "Timezone", width: 150, hideBelow: "lg", render: (row) => row.timezone ?? EMPTY },
    {
      key: "device_count",
      label: "Devices",
      width: 100,
      align: "right",
      sortable: true,
      render: (row) => <Chip size="small" variant="outlined" label={formatNumber(row.device_count)} />,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 100,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="site:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
          <PermissionGate permission="site:write">
            <Tooltip title="Delete">
              <IconButton size="small" color="error" onClick={() => setDeleteTarget(row)}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </PermissionGate>
        </Stack>
      ),
    },
  ];

  const mapPoints = mapQuery.data ?? [];
  const maxDevices = Math.max(1, ...mapPoints.map((point) => point.devices_total));

  return (
    <>
      <PageHeader
        title="Sites"
        subtitle="Physical locations used for device grouping, SD-WAN topology and compliance scoping."
        actions={
          <PermissionGate permission="site:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New site
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${sitesQuery.data?.meta.total ?? 0} sites`} />
            <Chip
              size="small"
              variant="outlined"
              label={`${formatNumber(mapPoints.reduce((total, point) => total + point.devices_total, 0))} devices`}
            />
            <Chip
              size="small"
              variant="outlined"
              color="success"
              label={`${formatNumber(mapPoints.reduce((total, point) => total + point.devices_online, 0))} online`}
            />
          </Stack>
        }
      />

      {mapPoints.length > 0 && (
        <Card sx={{ mb: 2 }}>
          <CardContent>
            <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1.5 }}>
              <Box>
                <Typography variant="h5">Geographic distribution</Typography>
                <Typography variant="caption" color="text.secondary">
                  Sites with coordinates, ranked by managed device count
                </Typography>
              </Box>
              {mapQuery.isFetching && <LinearProgress sx={{ width: 120, height: 3 }} />}
            </Stack>
            <SiteMap points={mapPoints} />
            <Typography variant="h6" sx={{ mt: 3, mb: 1.5 }}>
              Site health
            </Typography>
            <Grid container spacing={1.5}>
              {mapPoints.slice(0, 8).map((point) => (
                <Grid item xs={12} sm={6} md={4} lg={3} key={point.id}>
                  <Box sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 2 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Typography variant="body2" fontWeight={600} noWrap>
                        {point.name}
                      </Typography>
                      {point.worst_severity && (
                        <Chip
                          size="small"
                          color={point.worst_severity === "critical" ? "error" : "warning"}
                          label={point.worst_severity}
                        />
                      )}
                    </Stack>
                    <Typography variant="caption" color="text.secondary" display="block">
                      {[point.city, point.country].filter(Boolean).join(", ") || "No location data"}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 1 }}>
                      <LinearProgress
                        variant="determinate"
                        value={(point.devices_online / Math.max(1, point.devices_total)) * 100}
                        sx={{ flex: 1, height: 5, borderRadius: 3 }}
                      />
                      <Typography variant="caption" color="text.secondary">
                        {point.devices_online}/{point.devices_total}
                      </Typography>
                    </Stack>
                    <Typography variant="caption" color="text.disabled" display="block" sx={{ mt: 0.5 }}>
                      {point.latitude !== null && point.longitude !== null
                        ? `${point.latitude.toFixed(3)}, ${point.longitude.toFixed(3)} · ${Math.round(
                            (point.devices_total / maxDevices) * 100,
                          )}% of largest site`
                        : "Coordinates not configured"}
                    </Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>
          </CardContent>
        </Card>
      )}

      <DataTable
        columns={columns}
        rows={sitesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={sitesQuery.isLoading}
        error={sitesQuery.error ? toApiError(sitesQuery.error).message : null}
        onRetry={() => sitesQuery.refetch()}
        page={page}
        size={size}
        total={sitesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        sort={sort}
        order={order}
        onSortChange={(key, nextOrder) => {
          setSort(key);
          setOrder(nextOrder);
        }}
        emptyTitle="No sites configured"
        emptyDescription="Sites group devices by location and drive topology and compliance decisions."
        emptyAction={
          <PermissionGate permission="site:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New site
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
            <TextField
              placeholder="Search sites"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ width: { xs: "100%", sm: 280 } }}
            />
            <Typography variant="caption" color="text.secondary">
              {sitesQuery.data?.meta.total ?? 0} sites
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "New site"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create site"}
        submitDisabled={!form.name.trim() || !form.code.trim()}
        onSubmit={() => saveMutation.mutate()}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        maxWidth="md"
      >
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Name"
            value={form.name}
            onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
            required
            autoFocus
          />
          <TextField
            label="Code"
            value={form.code}
            onChange={(event) => setForm((value) => ({ ...value, code: event.target.value.toUpperCase() }))}
            required
            disabled={Boolean(editing)}
            helperText={editing ? "Site codes are immutable" : "Short unique code, e.g. BER-1"}
            inputProps={{ maxLength: 16 }}
          />
        </Stack>
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
        />
        <TextField
          label="Address"
          value={form.address}
          onChange={(event) => setForm((value) => ({ ...value, address: event.target.value }))}
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="City"
            value={form.city}
            onChange={(event) => setForm((value) => ({ ...value, city: event.target.value }))}
          />
          <TextField
            label="Country"
            value={form.country}
            onChange={(event) => setForm((value) => ({ ...value, country: event.target.value.toUpperCase() }))}
            helperText="ISO 3166-1 alpha-2"
            inputProps={{ maxLength: 2 }}
          />
          <TextField
            label="Timezone"
            value={form.timezone}
            onChange={(event) => setForm((value) => ({ ...value, timezone: event.target.value }))}
            placeholder="Europe/Berlin"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Latitude"
            value={form.latitude}
            onChange={(event) => setForm((value) => ({ ...value, latitude: event.target.value }))}
            placeholder="52.5200"
            inputProps={{ inputMode: "decimal" }}
          />
          <TextField
            label="Longitude"
            value={form.longitude}
            onChange={(event) => setForm((value) => ({ ...value, longitude: event.target.value }))}
            placeholder="13.4050"
            inputProps={{ inputMode: "decimal" }}
          />
        </Stack>
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete site"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? ${deleteTarget.device_count} device(s) will be unassigned from this site.`
            : undefined
        }
        confirmLabel="Delete"
        confirmColor="error"
        loading={deleteMutation.isPending}
        onConfirm={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
        onClose={() => setDeleteTarget(null)}
      />
    </>
  );
}

export default SitesPage;
