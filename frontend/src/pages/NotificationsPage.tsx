import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import DoneAllIcon from "@mui/icons-material/DoneAll";
import MarkEmailReadOutlinedIcon from "@mui/icons-material/MarkEmailReadOutlined";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { Link as RouterLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import DOMPurify from "dompurify";
import { toApiError } from "@/api/client";
import { notificationsApi } from "@/api/endpoints";
import { qk } from "@/api/queryKeys";
import type { Notification, NotificationCreatePayload } from "@/api/types";
import CodeBlock from "@/components/CodeBlock";
import DataTable, { type DataTableColumn } from "@/components/DataTable";
import FormDialog from "@/components/FormDialog";
import PageHeader from "@/components/PageHeader";
import { PermissionGate } from "@/components/RequireAuth";
import SeverityChip from "@/components/SeverityChip";
import { useAppDispatch } from "@/store/hooks";
import { showToast } from "@/store/uiSlice";
import { DEFAULT_PAGE_SIZE } from "@/utils/constants";
import { EMPTY, formatDateTime, fromNow, parseLines, prettyJson } from "@/utils/format";

const NOTIFICATION_TYPES = ["info", "success", "warning", "error", "alert"] as const;
const SEVERITIES = ["info", "warning", "critical"] as const;

interface NotificationFormState {
  title: string;
  message: string;
  type: string;
  severity: string;
  action_url: string;
  channels: string;
}

const EMPTY_FORM: NotificationFormState = {
  title: "",
  message: "",
  type: "info",
  severity: "info",
  action_url: "",
  channels: "",
};

/**
 * Sanitize notification message content against XSS.
 *
 * Notification messages may contain user-supplied or system-supplied text.
 * Even though React auto-escapes text in JSX, notification messages are also
 * rendered through the `dangerouslySetInnerHTML`-free CodeBlock component and
 * MUI Typography.  DOMPurify is applied as defense-in-depth so that any
 * script/iframe/vector embedded in a message cannot execute.
 */
function sanitizeMessage(message: string): string {
  return DOMPurify.sanitize(message, {
    ALLOWED_TAGS: ["b", "i", "strong", "em", "u", "br", "code", "pre", "a"],
    ALLOWED_ATTR: ["href", "title", "target", "rel"],
    ADD_ATTR: ["target", "rel"],
  });
}

function deliveryColor(status: string): "success" | "error" | "default" {
  if (status === "sent") return "success";
  if (status === "failed") return "error";
  return "default";
}

export function NotificationsPage() {
  const dispatch = useAppDispatch();
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [selected, setSelected] = useState<Notification | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<NotificationFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const listParams = useMemo(
    () => ({ page, size, unread_only: unreadOnly || undefined }),
    [page, size, unreadOnly],
  );

  const notificationsQuery = useQuery({
    queryKey: qk.notifications.list(listParams),
    queryFn: () => notificationsApi.list(listParams),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    setPage(1);
  }, [unreadOnly]);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.notifications.all });
  };

  const readMutation = useMutation({
    mutationFn: (id: string) => notificationsApi.read(id),
    onSuccess: () => {
      invalidate();
      setSelected(null);
      dispatch(showToast({ message: "Notification marked as read", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const readAllMutation = useMutation({
    mutationFn: () => notificationsApi.readAll(),
    onSuccess: () => {
      invalidate();
      dispatch(showToast({ message: "All notifications marked as read", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => notificationsApi.remove(id),
    onSuccess: () => {
      invalidate();
      setSelected(null);
      dispatch(showToast({ message: "Notification deleted", severity: "success" }));
    },
    onError: (error) => dispatch(showToast({ message: toApiError(error).message, severity: "error" })),
  });

  const createMutation = useMutation({
    mutationFn: () => {
      const payload: NotificationCreatePayload = {
        title: form.title.trim(),
        message: form.message.trim(),
        type: form.type,
        severity: form.severity as NotificationCreatePayload["severity"],
        action_url: form.action_url.trim() || null,
        channels: parseLines(form.channels),
      };
      return notificationsApi.create(payload);
    },
    onSuccess: (notification) => {
      invalidate();
      setFormOpen(false);
      setForm(EMPTY_FORM);
      setFormError(null);
      const delivered = Object.values(notification.delivery ?? {}).filter(
        (entry) => entry.status === "sent",
      ).length;
      dispatch(
        showToast({
          message: delivered
            ? `Notification created · ${delivered} channel(s) delivered`
            : "Notification created",
          severity: "success",
        }),
      );
    },
    onError: (error) => setFormError(toApiError(error).message),
  });

  const rows = notificationsQuery.data?.items ?? [];
  const unreadCount = rows.filter((row) => !row.read).length;

  const columns: Array<DataTableColumn<Notification>> = [
    {
      key: "title",
      label: "Notification",
      render: (row) => (
        <Stack direction="row" spacing={1.25} alignItems="flex-start">
          <Box
            sx={{
              width: 8,
              height: 8,
              mt: 0.75,
              borderRadius: "50%",
              flexShrink: 0,
              bgcolor: row.read ? "text.disabled" : "primary.main",
            }}
          />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" fontWeight={row.read ? 500 : 700} noWrap>
              {row.title}
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap display="block">
              {sanitizeMessage(row.message)}
            </Typography>
          </Box>
        </Stack>
      ),
    },
    {
      key: "severity",
      label: "Severity",
      width: 110,
      render: (row) => <SeverityChip severity={row.severity} variant="outlined" />,
    },
    {
      key: "type",
      label: "Type",
      width: 110,
      hideBelow: "md",
      render: (row) => <Chip size="small" variant="outlined" label={row.type} />,
    },
    {
      key: "delivery",
      label: "Delivery",
      width: 220,
      hideBelow: "lg",
      render: (row) => {
        const entries = Object.entries(row.delivery ?? {});
        if (entries.length === 0) {
          return <Typography variant="caption" color="text.disabled">In-app only</Typography>;
        }
        return (
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            {entries.map(([channel, outcome]) => (
              <Tooltip
                key={channel}
                title={outcome.error ?? outcome.reason ?? outcome.at ?? channel}
              >
                <Chip
                  size="small"
                  variant="outlined"
                  color={deliveryColor(outcome.status)}
                  label={`${channel}: ${outcome.status}`}
                />
              </Tooltip>
            ))}
          </Stack>
        );
      },
    },
    {
      key: "created_at",
      label: "Received",
      width: 170,
      render: (row) => (
        <Tooltip title={formatDateTime(row.created_at)}>
          <Typography variant="body2" color="text.secondary">
            {fromNow(row.created_at)}
          </Typography>
        </Tooltip>
      ),
    },
    {
      key: "actions",
      label: "",
      align: "right",
      width: 96,
      render: (row) => (
        <Stack direction="row" spacing={0.25} justifyContent="flex-end">
          {!row.read && (
            <Tooltip title="Mark as read">
              <Button
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  readMutation.mutate(row.id);
                }}
                sx={{ minWidth: 0, px: 0.75 }}
              >
                <MarkEmailReadOutlinedIcon fontSize="small" />
              </Button>
            </Tooltip>
          )}
          <Tooltip title="Delete">
            <Button
              size="small"
              color="error"
              onClick={(event) => {
                event.stopPropagation();
                removeMutation.mutate(row.id);
              }}
              sx={{ minWidth: 0, px: 0.75 }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </Button>
          </Tooltip>
        </Stack>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Inbox for alert and workflow notifications, including per-channel delivery results."
        actions={
          <PermissionGate permission="alert:write">
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => {
                setForm(EMPTY_FORM);
                setFormError(null);
                setFormOpen(true);
              }}
            >
              New notification
            </Button>
          </PermissionGate>
        }
        meta={
          <Stack direction="row" spacing={1} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
            <Chip size="small" label={`${notificationsQuery.data?.meta.total ?? 0} notifications`} />
            <Chip
              size="small"
              variant="outlined"
              color={unreadCount > 0 ? "warning" : "default"}
              label={`${unreadCount} unread on this page`}
            />
          </Stack>
        }
      />

      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(row) => row.id}
        loading={notificationsQuery.isLoading}
        error={notificationsQuery.error ? toApiError(notificationsQuery.error).message : null}
        onRetry={() => notificationsQuery.refetch()}
        page={page}
        size={size}
        total={notificationsQuery.data?.meta.total}
        onPageChange={setPage}
        onSizeChange={setSize}
        onRowClick={(row) => setSelected(row)}
        emptyTitle={unreadOnly ? "No unread notifications" : "Inbox is empty"}
        emptyDescription={
          unreadOnly
            ? "Everything has been read. Turn off the unread filter to see the full history."
            : "Alert and workflow notifications will appear here as they are generated."
        }
        toolbar={
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            alignItems={{ xs: "stretch", sm: "center" }}
            justifyContent="space-between"
          >
            <FormControlLabel
              control={
                <Switch
                  checked={unreadOnly}
                  onChange={(event) => setUnreadOnly(event.target.checked)}
                />
              }
              label="Unread only"
            />
            <Stack direction="row" spacing={1}>
              <Button
                size="small"
                startIcon={<DoneAllIcon />}
                disabled={readAllMutation.isPending}
                onClick={() => readAllMutation.mutate()}
              >
                Mark all read
              </Button>
              <Button size="small" onClick={() => notificationsQuery.refetch()}>
                Refresh
              </Button>
            </Stack>
          </Stack>
        }
      />

      <Dialog open={Boolean(selected)} onClose={() => setSelected(null)} maxWidth="md" fullWidth>
        {selected && (
          <>
            <DialogTitle>
              <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                <SeverityChip severity={selected.severity} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="h5" component="span">
                    {selected.title}
                  </Typography>
                </Box>
                <Chip size="small" variant="outlined" label={selected.type} />
              </Stack>
            </DialogTitle>
            <DialogContent dividers>
              <Stack spacing={2}>
                <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                  {sanitizeMessage(selected.message)}
                </Typography>
                <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap>
                  <Typography variant="caption" color="text.secondary">
                    Created {formatDateTime(selected.created_at)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    Delivered {selected.delivered_at ? formatDateTime(selected.delivered_at) : EMPTY}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {selected.read ? "Read" : "Unread"}
                  </Typography>
                </Stack>
                {selected.action_url && (
                  <Box>
                    {selected.action_url.startsWith("/") ? (
                      <Button
                        component={RouterLink}
                        to={selected.action_url}
                        endIcon={<OpenInNewIcon fontSize="small" />}
                        size="small"
                      >
                        Open related page
                      </Button>
                    ) : (
                      <Button
                        href={selected.action_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        endIcon={<OpenInNewIcon fontSize="small" />}
                        size="small"
                      >
                        Open link
                      </Button>
                    )}
                  </Box>
                )}
                <Box>
                  <Typography variant="overline" color="text.secondary">
                    Delivery
                  </Typography>
                  {Object.keys(selected.delivery ?? {}).length === 0 ? (
                    <Alert severity="info" sx={{ mt: 0.5 }}>
                      This notification was delivered in-app only.
                    </Alert>
                  ) : (
                    <CodeBlock
                      code={prettyJson(selected.delivery)}
                      language="delivery.json"
                      maxHeight={240}
                    />
                  )}
                </Box>
              </Stack>
            </DialogContent>
            <DialogActions sx={{ px: 3, py: 2 }}>
              <Button color="inherit" onClick={() => setSelected(null)}>
                Close
              </Button>
              {!selected.read && (
                <Button
                  startIcon={<MarkEmailReadOutlinedIcon />}
                  disabled={readMutation.isPending}
                  onClick={() => readMutation.mutate(selected.id)}
                >
                  Mark read
                </Button>
              )}
              <Button
                color="error"
                startIcon={<DeleteOutlineIcon />}
                disabled={removeMutation.isPending}
                onClick={() => removeMutation.mutate(selected.id)}
              >
                Delete
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      <FormDialog
        open={formOpen}
        title="New notification"
        description="The notification is always stored in the inbox. External channels are best effort and each outcome is recorded."
        loading={createMutation.isPending}
        error={formError}
        submitLabel="Create notification"
        submitDisabled={!form.title.trim() || !form.message.trim()}
        onSubmit={() => createMutation.mutate()}
        onClose={() => setFormOpen(false)}
        maxWidth="md"
      >
        <TextField
          label="Title"
          value={form.title}
          onChange={(event) => setForm((value) => ({ ...value, title: event.target.value }))}
          required
          autoFocus
          inputProps={{ maxLength: 255 }}
        />
        <TextField
          label="Message"
          value={form.message}
          onChange={(event) => setForm((value) => ({ ...value, message: event.target.value }))}
          required
          multiline
          minRows={3}
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            select
            label="Type"
            value={form.type}
            onChange={(event) => setForm((value) => ({ ...value, type: event.target.value }))}
          >
            {NOTIFICATION_TYPES.map((type) => (
              <MenuItem key={type} value={type}>
                {type}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Severity"
            value={form.severity}
            onChange={(event) => setForm((value) => ({ ...value, severity: event.target.value }))}
          >
            {SEVERITIES.map((severity) => (
              <MenuItem key={severity} value={severity}>
                {severity}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        <TextField
          label="Action URL"
          value={form.action_url}
          onChange={(event) => setForm((value) => ({ ...value, action_url: event.target.value }))}
          placeholder="/policies or https://status.example.com"
          helperText="Internal paths open in the app; absolute URLs open in a new tab."
          inputProps={{ maxLength: 512 }}
        />
        <TextField
          label="Channels"
          value={form.channels}
          onChange={(event) => setForm((value) => ({ ...value, channels: event.target.value }))}
          placeholder="email, slack:https://hooks.slack.com/services/…, webhook:https://…"
          helperText="Comma or newline separated. Supported: email, slack:<webhook-url>, webhook:<url>."
        />
      </FormDialog>
    </>
  );
}

export default NotificationsPage;
