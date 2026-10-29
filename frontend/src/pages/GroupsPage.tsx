import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Collapse,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { groupsApi, templatesApi } from "@/api/endpoints";
import { toApiError } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { DeviceGroup, DeviceGroupPayload, GroupTreeNode } from "@/api/types";
import ConfirmDialog from "@/components/ConfirmDialog";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import { useDebounce } from "@/hooks/useDebounce";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { parseLines } from "@/utils/format";

interface GroupFormState {
  name: string;
  description: string;
  parent_id: string;
  template_id: string;
  labels: string;
}

const EMPTY_FORM: GroupFormState = {
  name: "",
  description: "",
  parent_id: "",
  template_id: "",
  labels: "",
};

interface GroupTreeRowProps {
  node: GroupTreeNode;
  level: number;
  onEdit: (groupId: string) => void;
  onDelete: (group: DeviceGroup) => void;
}

function GroupTreeRow({ node, level, onEdit, onDelete }: GroupTreeRowProps) {
  const [expanded, setExpanded] = useState(level === 0);
  const hasChildren = node.children.length > 0;
  const group: DeviceGroup = {
    id: node.id,
    created_at: "",
    updated_at: "",
    name: node.name,
    description: node.description,
    parent_id: null,
    template_id: null,
    labels: node.labels,
    device_count: node.device_count,
  };

  return (
    <>
      <ListItemButton sx={{ pl: 1.5 + level * 2.5, borderRadius: 1.5 }} onClick={() => setExpanded((v) => !v)}>
        <ListItemIcon sx={{ minWidth: 30 }}>
          {hasChildren ? (
            expanded ? (
              <ExpandLessIcon fontSize="small" />
            ) : (
              <ExpandMoreIcon fontSize="small" />
            )
          ) : (
            <FolderOutlinedIcon fontSize="small" />
          )}
        </ListItemIcon>
        <ListItemText
          primary={node.name}
          secondary={node.description ?? `${node.device_count} device(s)`}
          primaryTypographyProps={{ variant: "body2", fontWeight: 600 }}
          secondaryTypographyProps={{ variant: "caption" }}
        />
        <Chip size="small" variant="outlined" label={node.device_count} sx={{ mr: 1 }} />
        <PermissionGate permission="group:write">
          <Tooltip title="Edit group">
            <IconButton
              size="small"
              onClick={(event) => {
                event.stopPropagation();
                onEdit(node.id);
              }}
            >
              <EditOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete group">
            <IconButton
              size="small"
              color="error"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(group);
              }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </PermissionGate>
      </ListItemButton>
      {hasChildren && (
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          <List disablePadding>
            {node.children.map((child) => (
              <GroupTreeRow
                key={child.id}
                node={child}
                level={level + 1}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))}
          </List>
        </Collapse>
      )}
    </>
  );
}

export function GroupsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [sort, setSort] = useState("name");
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search.trim(), 350);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<DeviceGroup | null>(null);
  const [form, setForm] = useState<GroupFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeviceGroup | null>(null);

  const listParams = useMemo(
    () => ({ page, size, sort, order, search: debouncedSearch || undefined }),
    [page, size, sort, order, debouncedSearch],
  );

  const groupsQuery = useQuery({
    queryKey: qk.groups.list(listParams),
    queryFn: () => groupsApi.list(listParams),
  });

  const treeQuery = useQuery({
    queryKey: qk.groups.tree,
    queryFn: () => groupsApi.tree(),
  });

  const templatesQuery = useQuery({
    queryKey: qk.templates.list({ size: 200 }),
    queryFn: () => templatesApi.list({ size: 200 }),
    staleTime: 120_000,
  });

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.groups.all });
    void queryClient.invalidateQueries({ queryKey: qk.devices.all });
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: DeviceGroupPayload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        parent_id: form.parent_id || null,
        template_id: form.template_id || null,
        labels: parseLines(form.labels),
      };
      return editing ? groupsApi.update(editing.id, payload) : groupsApi.create(payload);
    },
    onSuccess: (group) => {
      invalidate();
      setFormOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      setFormError(null);
      dispatch(showToast({ message: `Group ${group.name} saved`, severity: "success" }));
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => groupsApi.remove(id),
    onSuccess: () => {
      invalidate();
      setDeleteTarget(null);
      dispatch(showToast({ message: "Group deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const openCreate = (parentId = "") => {
    setEditing(null);
    setForm({ ...EMPTY_FORM, parent_id: parentId });
    setFormError(null);
    setFormOpen(true);
  };

  const openEdit = async (groupId: string) => {
    try {
      const cached = groupsQuery.data?.items.find((group) => group.id === groupId);
      const group = cached ?? (await groupsApi.get(groupId));
      setEditing(group);
      setForm({
        name: group.name,
        description: group.description ?? "",
        parent_id: group.parent_id ?? "",
        template_id: group.template_id ?? "",
        labels: group.labels.join(", "),
      });
      setFormError(null);
      setFormOpen(true);
    } catch (error) {
      dispatch(showToast({ message: toApiError(error).message, severity: "error" }));
    }
  };

  const parentName = (id: string | null) =>
    id ? groupsQuery.data?.items.find((group) => group.id === id)?.name ?? "Group" : "Root";

  const columns: Array<DataTableColumn<DeviceGroup>> = [
    {
      key: "name",
      label: "Group",
      sortable: true,
      render: (row) => (
        <Stack direction="row" spacing={1} alignItems="center">
          <AccountTreeOutlinedIcon fontSize="small" color="action" />
          <Box>
            <Typography variant="body2" fontWeight={600}>
              {row.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {row.description ?? "No description"}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    { key: "parent", label: "Parent", width: 180, render: (row) => parentName(row.parent_id) },
    {
      key: "labels",
      label: "Labels",
      hideBelow: "md",
      render: (row) =>
        row.labels.length ? (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {row.labels.map((label) => (
              <Chip key={label} size="small" label={label} variant="outlined" />
            ))}
          </Stack>
        ) : (
          "—"
        ),
    },
    {
      key: "device_count",
      label: "Devices",
      width: 100,
      align: "right",
      sortable: true,
      render: (row) => <Chip size="small" variant="outlined" label={row.device_count} />,
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 150,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          <PermissionGate permission="group:write">
            <Tooltip title="Add child group">
              <IconButton size="small" onClick={() => openCreate(row.id)}>
                <AddIcon fontSize="small" />
              </IconButton>
            </Tooltip>
            <Tooltip title="Edit">
              <IconButton size="small" onClick={() => openEdit(row.id)}>
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
        title="Device groups"
        subtitle="Hierarchical groups carry template assignments, labels and policy targeting across the fleet."
        actions={
          <PermissionGate permission="group:write">
            <Button variant="contained" startIcon={<AddIcon />} onClick={() => openCreate()}>
              New group
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip size="small" label={`${groupsQuery.data?.meta.total ?? 0} groups`} />
            <Chip size="small" variant="outlined" label={`${treeQuery.data?.length ?? 0} root groups`} />
          </Stack>
        }
      />

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "360px minmax(0, 1fr)" } }}>
        <Box sx={{ border: 1, borderColor: "divider", borderRadius: 2, bgcolor: "background.paper", p: 1 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 1, py: 1 }}>
            <Box>
              <Typography variant="h5">Hierarchy</Typography>
              <Typography variant="caption" color="text.secondary">
                Parent/child inheritance
              </Typography>
            </Box>
            {treeQuery.isFetching && <Chip size="small" label="Loading" />}
          </Stack>
          {treeQuery.isError ? (
            <Typography variant="body2" color="error" sx={{ p: 2 }}>
              {toApiError(treeQuery.error).message}
            </Typography>
          ) : (treeQuery.data ?? []).length === 0 ? (
            <Box sx={{ p: 3, textAlign: "center" }}>
              <Typography variant="body2" color="text.secondary">
                No groups yet. Create a root group to start building the hierarchy.
              </Typography>
              <PermissionGate permission="group:write">
                <Button size="small" sx={{ mt: 1 }} onClick={() => openCreate()}>
                  Create group
                </Button>
              </PermissionGate>
            </Box>
          ) : (
            <List dense disablePadding>
              {(treeQuery.data ?? []).map((node) => (
                <GroupTreeRow
                  key={node.id}
                  node={node}
                  level={0}
                  onEdit={openEdit}
                  onDelete={setDeleteTarget}
                />
              ))}
            </List>
          )}
        </Box>

        <DataTable
          columns={columns}
          rows={groupsQuery.data?.items ?? []}
          getRowId={(row) => row.id}
          loading={groupsQuery.isLoading}
          error={groupsQuery.error ? toApiError(groupsQuery.error).message : null}
          onRetry={() => groupsQuery.refetch()}
          page={page}
          size={size}
          total={groupsQuery.data?.meta.total}
          onPageChange={setPage}
          onSizeChange={setSize}
          sort={sort}
          order={order}
          onSortChange={(key, nextOrder) => {
            setSort(key);
            setOrder(nextOrder);
          }}
          emptyTitle="No groups"
          emptyDescription="Groups are the unit of template assignment and policy targeting."
          emptyAction={
            <PermissionGate permission="group:write">
              <Button variant="contained" startIcon={<AddIcon />} onClick={() => openCreate()}>
                New group
              </Button>
            </PermissionGate>
          }
          toolbar={
            <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between">
              <TextField
                placeholder="Search groups"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                sx={{ width: { xs: "100%", sm: 260 } }}
              />
              <Typography variant="caption" color="text.secondary">
                {groupsQuery.data?.meta.total ?? 0} groups
              </Typography>
            </Stack>
          }
        />
      </Box>

      <FormDialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : "New group"}
        loading={saveMutation.isPending}
        error={formError}
        submitLabel={editing ? "Save changes" : "Create group"}
        submitDisabled={!form.name.trim()}
        onSubmit={() => saveMutation.mutate()}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
      >
        <TextField
          label="Name"
          value={form.name}
          onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
          required
          autoFocus
        />
        <TextField
          label="Description"
          value={form.description}
          onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))}
          multiline
          minRows={2}
        />
        <TextField
          select
          label="Parent group"
          value={form.parent_id}
          onChange={(event) => setForm((value) => ({ ...value, parent_id: event.target.value }))}
          helperText="Parent groups cascade templates and policy targets"
        >
          <MenuItem value="">Root (no parent)</MenuItem>
          {(groupsQuery.data?.items ?? [])
            .filter((group) => !editing || group.id !== editing.id)
            .map((group) => (
              <MenuItem key={group.id} value={group.id}>
                {group.name}
              </MenuItem>
            ))}
        </TextField>
        <TextField
          select
          label="Template"
          value={form.template_id}
          onChange={(event) => setForm((value) => ({ ...value, template_id: event.target.value }))}
        >
          <MenuItem value="">None</MenuItem>
          {(templatesQuery.data?.items ?? []).map((template) => (
            <MenuItem key={template.id} value={template.id}>
              {template.name} (v{template.version})
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Labels"
          value={form.labels}
          onChange={(event) => setForm((value) => ({ ...value, labels: event.target.value }))}
          helperText="Comma-separated labels used for policy selectors"
        />
      </FormDialog>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete group"
        description={
          deleteTarget
            ? `Delete ${deleteTarget.name}? Child groups are re-parented to the root and ${deleteTarget.device_count} device(s) lose this group assignment.`
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

export default GroupsPage;
