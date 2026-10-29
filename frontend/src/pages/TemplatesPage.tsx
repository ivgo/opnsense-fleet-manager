import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import PlayCircleOutlineIcon from "@mui/icons-material/PlayCircleOutline";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { templatesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { Template, TemplateKind, TemplatePayload } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { formatDateTime, fromNow, prettyJson } from "@/utils/format";

const TEMPLATE_KINDS: Array<{ value: TemplateKind; label: string; description: string }> = [
  { value: "config", label: "Configuration", description: "Full OPNsense configuration fragments" },
  { value: "policy", label: "Policy", description: "Reusable rule and NAT fragments" },
  { value: "ztp", label: "Zero-touch", description: "Provisioning payloads for new appliances" },
];

interface TemplateFormState {
  name: string;
  description: string;
  kind: TemplateKind;
  parent_id: string;
  body: string;
  variables: string;
  is_active: boolean;
}

const EMPTY_FORM: TemplateFormState = {
  name: "",
  description: "",
  kind: "config",
  parent_id: "",
  body: JSON.stringify(
    {
      system: {
        hostname: "{{ hostname }}",
        domain: "{{ domain }}",
      },
      interfaces: {},
    },
    null,
    2,
  ),
  variables: JSON.stringify({ hostname: "", domain: "example.internal" }, null, 2),
  is_active: true,
};

export function TemplatesPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [activeFilter, setActiveFilter] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Template | null>(null);
  const [form, setForm] = useState<TemplateFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Template | null>(null);

  const [renderTarget, setRenderTarget] = useState<Template | null>(null);
  const [renderVariables, setRenderVariables] = useState("{}");
  const [renderResult, setRenderResult] = useState<{
    rendered: Record<string, unknown>;
    variables_used: string[];
    warnings: string[];
  } | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  const [effectiveTarget, setEffectiveTarget] = useState<Template | null>(null);

  const listParams = useMemo(
    () => ({
      page,
      size,
      sort,
      order,
      search: debouncedSearch || undefined,
      kind: kindFilter || undefined,
      is_active: activeFilter === "" ? undefined : activeFilter === "true",
    }),
    [page, size, sort, order, debouncedSearch, kindFilter, activeFilter],
  );

  const templatesQuery = useQuery({
    queryKey: qk.templates.list(listParams),
    queryFn: () => templatesApi.list(listParams),
  });

  const effectiveQuery = useQuery({
    queryKey: [...qk.templates.detail(effectiveTarget?.id ?? ""), "effective"],
    queryFn: () => templatesApi.effective(effectiveTarget?.id ?? ""),
    enabled: Boolean(effectiveTarget),
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, kindFilter, activeFilter]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.templates.all });
    void queryClient.invalidateQueries({ queryKey: qk.groups.all });
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: TemplatePayload) =>
      editing ? templatesApi.update(editing.id, payload) : templatesApi.create(payload),
    onSuccess: (template) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Template ${template.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ template, active }: { template: Template; active: boolean }) =>
      templatesApi.update(template.id, { is_active: active }),
    onSuccess: () => {
      invalidate();
      dispatch(showToast({ message: "Template state updated", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => templatesApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Template deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const renderMutation = useMutation({
    mutationFn: ({ template, variables }: { template: Template; variables: Record<string, unknown> }) =>
      templatesApi.render(template.id, variables),
    onSuccess: (result) => {
      setRenderResult(result);
      setRenderError(null);
    },
    onError: (error) => setRenderError(toApiError(error).message),
  });

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = (template: Template) => {
    setEditing(template);
    setForm({
      name: template.name,
      description: template.description ?? "",
      kind: template.kind,
      parent_id: template.parent_id ?? "",
      body: prettyJson(template.body),
      variables: prettyJson(template.variables ?? {}),
      is_active: template.is_active,
    });
    setFormError(null);
    setFormOpen(true);
  };

  const submitForm = () => {
    let body: Record<string, unknown>;
    let variables: Record<string, unknown>;
    try {
      body = JSON.parse(form.body) as Record<string, unknown>;
    } catch {
      setFormError("Template body must be valid JSON.");
      return;
    }
    try {
      variables = form.variables.trim()
        ? (JSON.parse(form.variables) as Record<string, unknown>)
        : {};
    } catch {
      setFormError("Variables must be valid JSON.");
      return;
    }
    saveMutation.mutate({
      name: form.name.trim(),
      description: form.description.trim() || null,
      kind: form.kind,
      parent_id: form.parent_id || null,
      body,
      variables,
      is_active: form.is_active,
    });
  };

  const openRender = (template: Template) => {
    setRenderTarget(template);
    setRenderVariables(prettyJson(template.variables ?? {}));
    setRenderResult(null);
    setRenderError(null);
  };

  const submitRender = () => {
    if (!renderTarget) return;
    let variables: Record<string, unknown>;
    try {
      variables = renderVariables.trim() ? (JSON.parse(renderVariables) as Record<string, unknown>) : {};
    } catch {
      setRenderError("Variables must be valid JSON.");
      return;
    }
    renderMutation.mutate({ template: renderTarget, variables });
  };

  const columns: Array<DataTableColumn<Template>> = [
    {
      key: "name",
      label: "Template",
      sortable: true,
      render: (row) => (
        <Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            {row.parent_id && <Chip size="small" label="inherits" variant="outlined" />}
          </Stack>
          <Typography variant="caption" color="text.secondary" display="block">
            {row.description ?? "No description"}
          </Typography>
        </Box>
      ),
    },
    {
      key: "kind",
      label: "Kind",
      width: 130,
      render: (row) => (
        <Chip size="small" variant="outlined" label={TEMPLATE_KINDS.find((k) => k.value === row.kind)?.label ?? row.kind} />
      ),
    },
    { key: "version", label: "Version", width: 90, align: "center", sortable: true, render: (row) => `v${row.version}` },
    {
      key: "variables",
      label: "Variables",
      width: 120,
      align: "center",
      hideBelow: "md",
      render: (row) => Object.keys(row.variables ?? {}).length,
    },
    {
      key: "is_active",
      label: "Active",
      width: 100,
      render: (row) => (
        <Tooltip title={row.is_active ? "Deactivate template" : "Activate template"}>
          <span>
            <Switch
              size="small"
              checked={row.is_active}
              onChange={(event) => toggleMutation.mutate({ template: row, active: event.target.checked })}
              disabled={toggleMutation.isPending}
              inputProps={{ "aria-label": `Activate ${row.name}` }}
            />
          </span>
        </Tooltip>
      ),
    },
    {
      key: "updated",
      label: "Updated",
      width: 160,
      hideBelow: "lg",
      sortable: true,
      render: (row) => (
        <Tooltip title={formatDateTime(row.updated_at)}>
          <span>{fromNow(row.updated_at)}</span>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 150,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <Tooltip title="Render with variables">
            <IconButton size="small" onClick={() => openRender(row)}>
              <PlayCircleOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="View effective configuration">
            <IconButton size="small" onClick={() => setEffectiveTarget(row)}>
              <AccountTreeOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <PermissionGate permission="template:write">
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row)}>
                <EditOutlinedIcon fontSize="small" />
              </IconButton>
            </Tooltip>
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

  return (
    <>
      <PageHeader
        title="Templates"
        subtitle="Reusable configuration fragments with variable substitution, inheritance and zero-touch payloads."
        actions={
          <PermissionGate permission="template:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New template
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip size="small" label={`${templatesQuery.data?.meta.total ?? 0} templates`} />
            <Chip
              size="small"
              variant="outlined"
              color="success"
              label={`${(templatesQuery.data?.items ?? []).filter((t) => t.is_active).length} active on this page`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={templatesQuery.data?.items ?? []}
        getRowId={(row) => row.id}
        loading={templatesQuery.isLoading}
        error={templatesQuery.error ? toApiError(templatesQuery.error).message : null}
        onRetry={() => templatesQuery.refetch()}
        page={page}
        size={size}
        total={templatesQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        sort={sort}
        order={order}
        onSortChange={(key, nextOrder) => {
          setSort(key);
          setOrder(nextOrder);
        }}
        onRowClick={(row) => openRender(row)}
        emptyTitle="No templates"
        emptyDescription="Templates drive group configuration and zero-touch provisioning payloads."
        emptyAction={
          <PermissionGate permission="template:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New template
            </Button>
          </PermissionGate>
        }
        toolbar={
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between">
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} flexWrap="wrap" useFlexGap>
              <TextField
                placeholder="Search templates"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 250 } }}
              />
              <TextField
                select
                label="Kind"
                value={kindFilter}
                onChange={(event) => setKindFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 160 } }}
              >
                <MenuItem value="">All</MenuItem>
                {TEMPLATE_KINDS.map((kind) => (
                  <MenuItem key={kind.value} value={kind.value}>
                    {kind.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="State"
                value={activeFilter}
                onChange={(event) => setActiveFilter(event.target.value)}
                sx={{ width: { xs: "100%", sm: 140 } }}
              >
                <MenuItem value="">All</MenuItem>
                <MenuItem value="true">Active</MenuItem>
                <MenuItem value="false">Inactive</MenuItem>
              </TextField>
            </Stack>
            <Typography variant="caption" color="text.secondary" sx={{ alignSelf: "center" }}>
              {templatesQuery.data?.meta.total ?? 0} templates
            </Typography>
          </Stack>
        }
      />

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "New template"}
        description={
          <Typography variant="body2" color="text.secondary">
            Templates are JSON documents. Use <code>{"{{ variable }}"}</code> placeholders for values supplied
            at render time. Editing a template increments its version and invalidates cached renders.
          </Typography>
        }
        submitLabel={editing ? "Save new version" : "Create template"}
        loading={saveMutation.isPending}
        error={formError}
        submitDisabled={!form.name.trim() || !form.body.trim()}
        onSubmit={submitForm}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        maxWidth="lg"
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
            select
            label="Kind"
            value={form.kind}
            onChange={(event) => setForm((value) => ({ ...value, kind: event.target.value as TemplateKind }))}
          >
            {TEMPLATE_KINDS.map((kind) => (
              <MenuItem key={kind.value} value={kind.value}>
                {kind.label}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
        />
        <TextField
          select
          label="Parent template"
          value={form.parent_id}
          onChange={(event) => setForm((value) => ({ ...value, parent_id: event.target.value }))}
          helperText="Inherited values are merged before the template body is rendered"
        >
          <MenuItem value="">None</MenuItem>
          {(templatesQuery.data?.items ?? [])
            .filter((template) => !editing || template.id !== editing.id)
            .map((template) => (
              <MenuItem key={template.id} value={template.id}>
                {template.name} (v{template.version})
              </MenuItem>
            ))}
        </TextField>
        <TextField
          label="Body (JSON)"
          value={form.body}
          onChange={(event) => setForm((value) => ({ ...value, body: event.target.value }))}
          multiline
          minRows={12}
          required
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5, lineHeight: 1.55 },
          }}
        />
        <TextField
          label="Default variables (JSON)"
          value={form.variables}
          onChange={(event) => setForm((value) => ({ ...value, variables: event.target.value }))}
          multiline
          minRows={5}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={form.is_active}
              onChange={(event) => setForm((value) => ({ ...value, is_active: event.target.checked }))}
            />
          }
          label="Active (available for group assignment and ZTP)"
        />
      </FormDialog>

      <FormDialog
        open={Boolean(renderTarget)}
        title={`Render · ${renderTarget?.name ?? ""}`}
        description={
          <Typography variant="body2" color="text.secondary">
            Variables override the template defaults for this render only. Nothing is written to devices.
          </Typography>
        }
        submitLabel="Render"
        loading={renderMutation.isPending}
        error={renderError}
        onSubmit={submitRender}
        onClose={() => {
          setRenderTarget(null);
          setRenderResult(null);
        }}
        maxWidth="lg"
      >
        <TextField
          label="Variables (JSON)"
          value={renderVariables}
          onChange={(event) => setRenderVariables(event.target.value)}
          multiline
          minRows={6}
          inputProps={{
            spellCheck: false,
            style: { fontFamily: "'JetBrains Mono', Consolas, monospace", fontSize: 12.5 },
          }}
        />
        {renderResult && (
          <Stack spacing={1.5}>
            {renderResult.warnings.length > 0 && (
              <Alert severity="warning">
                {renderResult.warnings.map((warning, index) => (
                  <Typography variant="body2" key={`${warning}-${index}`} component="div">
                    {warning}
                  </Typography>
                ))}
              </Alert>
            )}
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              <Chip size="small" color="success" label="Rendered" />
              {renderResult.variables_used.map((name) => (
                <Chip key={name} size="small" variant="outlined" label={name} />
              ))}
            </Stack>
            <CodeBlock code={prettyJson(renderResult.rendered)} language="json" maxHeight={360} />
          </Stack>
        )}
      </FormDialog>

      <FormDialog
        open={Boolean(effectiveTarget)}
        title={`Effective configuration · ${effectiveTarget?.name ?? ""}`}
        submitLabel="Close"
        onSubmit={() => setEffectiveTarget(null)}
        onClose={() => setEffectiveTarget(null)}
        maxWidth="lg"
      >
        {effectiveQuery.isLoading && <Typography variant="body2">Resolving inheritance…</Typography>}
        {effectiveQuery.isError && (
          <Alert severity="error">{toApiError(effectiveQuery.error).message}</Alert>
        )}
        {effectiveQuery.data && <CodeBlock code={prettyJson(effectiveQuery.data)} language="json" maxHeight={480} />}
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete template"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? Groups referencing it lose the assignment; rendered configurations on devices are unchanged.`
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

export default TemplatesPage;
