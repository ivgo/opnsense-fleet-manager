import type { ReactNode } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
} from "@mui/material";

export interface FormDialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  submitLabel?: string;
  cancelLabel?: string;
  loading?: boolean;
  error?: string | null;
  maxWidth?: "xs" | "sm" | "md" | "lg";
  submitDisabled?: boolean;
  onSubmit: () => void;
  onClose: () => void;
  children: ReactNode;
}

/**
 * Dialog wrapper for create/update forms. The form element is rendered inside
 * so Enter submits consistently across every page.
 */
export function FormDialog({
  open,
  title,
  description,
  submitLabel = "Save",
  cancelLabel = "Cancel",
  loading = false,
  error,
  maxWidth = "sm",
  submitDisabled = false,
  onSubmit,
  onClose,
  children,
}: FormDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={loading ? undefined : onClose}
      maxWidth={maxWidth}
      fullWidth
      keepMounted={false}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <DialogTitle>{title}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2.25} sx={{ pt: 0.5 }}>
            {description}
            {error && <Alert severity="error">{error}</Alert>}
            {children}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={onClose} disabled={loading} color="inherit">
            {cancelLabel}
          </Button>
          <Button type="submit" variant="contained" disabled={loading || submitDisabled}>
            {submitLabel}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}

export default FormDialog;
