import type { ReactNode } from "react";
import {
  Box,
  Checkbox,
  LinearProgress,
  Paper,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TableSortLabel,
  Typography,
} from "@mui/material";

import EmptyState from "@/components/EmptyState";
import ErrorState from "@/components/ErrorState";
import { PAGE_SIZE_OPTIONS } from "@/utils/constants";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  width?: number | string;
  sortable?: boolean;
  hideBelow?: "sm" | "md" | "lg";
  monospace?: boolean;
}

export type SortOrder = "asc" | "desc";

export interface DataTableSelection<T> {
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  /** Rows that cannot be selected (for example unmanageable devices). */
  isRowSelectable?: (row: T) => boolean;
}

export interface DataTableProps<T> {
  columns: Array<DataTableColumn<T>>;
  rows: T[];
  getRowId: (row: T) => string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  /** 1-based page number, matching the API. */
  page?: number;
  size?: number;
  total?: number;
  onPageChange?: (page: number) => void;
  onSizeChange?: (size: number) => void;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  emptyAction?: ReactNode;
  toolbar?: ReactNode;
  sort?: string;
  order?: SortOrder;
  onSortChange?: (key: string, order: SortOrder) => void;
  dense?: boolean;
  maxHeight?: number | string;
  stickyHeader?: boolean;
  /** Enables the leading checkbox column. Omit for read-only tables. */
  selection?: DataTableSelection<T>;
}

function responsiveDisplay(hideBelow?: "sm" | "md" | "lg") {
  if (!hideBelow) return undefined;
  if (hideBelow === "lg") return { xs: "none", lg: "table-cell" };
  if (hideBelow === "md") return { xs: "none", md: "table-cell" };
  return { xs: "none", sm: "table-cell" };
}

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  loading = false,
  error,
  onRetry,
  page = 1,
  size = 25,
  total,
  onPageChange,
  onSizeChange,
  onRowClick,
  emptyTitle = "Nothing to show yet",
  emptyDescription,
  emptyAction,
  toolbar,
  sort,
  order = "asc",
  onSortChange,
  dense = false,
  maxHeight,
  stickyHeader = false,
  selection,
}: DataTableProps<T>) {
  const paginated = typeof total === "number" && Boolean(onPageChange);
  const showTable = loading || !error || rows.length > 0;
  const columnCount = columns.length + (selection ? 1 : 0);

  const isSelectable = (row: T) => !selection?.isRowSelectable || selection.isRowSelectable(row);
  const selectableRows = selection ? rows.filter(isSelectable) : [];
  const selectedOnPage = selection
    ? selectableRows.filter((row) => selection.selectedIds.includes(getRowId(row)))
    : [];
  const allSelected = selectableRows.length > 0 && selectedOnPage.length === selectableRows.length;
  const someSelected = selectedOnPage.length > 0 && !allSelected;

  const toggleAll = () => {
    if (!selection) return;
    const pageIds = new Set(selectableRows.map(getRowId));
    const remaining = selection.selectedIds.filter((id) => !pageIds.has(id));
    selection.onChange(allSelected ? remaining : [...remaining, ...pageIds]);
  };

  const toggleRow = (row: T) => {
    if (!selection) return;
    const id = getRowId(row);
    selection.onChange(
      selection.selectedIds.includes(id)
        ? selection.selectedIds.filter((item) => item !== id)
        : [...selection.selectedIds, id],
    );
  };

  const handleSort = (key: string) => {
    if (!onSortChange) return;
    const nextOrder: SortOrder = sort === key && order === "asc" ? "desc" : "asc";
    onSortChange(key, nextOrder);
  };

  return (
    <Paper variant="outlined" sx={{ overflow: "hidden" }}>
      {toolbar && (
        <Box sx={{ px: 2, py: 1.25, borderBottom: 1, borderColor: "divider" }}>{toolbar}</Box>
      )}
      {loading && <LinearProgress sx={{ height: 2 }} />}
      {!loading && <Box sx={{ height: 2 }} />}
      <TableContainer sx={{ maxHeight }}>
        <Table stickyHeader={stickyHeader} size={dense ? "small" : "medium"} aria-label="data table">
          <TableHead>
            <TableRow>
              {selection && (
                <TableCell padding="checkbox">
                  <Checkbox
                    size="small"
                    checked={allSelected}
                    indeterminate={someSelected}
                    onChange={toggleAll}
                    disabled={selectableRows.length === 0}
                    inputProps={{ "aria-label": "Select all rows on this page" }}
                  />
                </TableCell>
              )}
              {columns.map((column) => (
                <TableCell
                  key={column.key}
                  align={column.align ?? "left"}
                  sx={{ width: column.width, display: responsiveDisplay(column.hideBelow) }}
                  sortDirection={sort === column.key ? order : false}
                >
                  {column.sortable && onSortChange ? (
                    <TableSortLabel
                      active={sort === column.key}
                      direction={sort === column.key ? order : "asc"}
                      onClick={() => handleSort(column.key)}
                    >
                      {column.label}
                    </TableSortLabel>
                  ) : (
                    column.label
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {error && rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={columnCount} sx={{ borderBottom: 0 }}>
                  <ErrorState message={error} onRetry={onRetry} compact />
                </TableCell>
              </TableRow>
            )}

            {loading &&
              rows.length === 0 &&
              Array.from({ length: 6 }).map((_, rowIndex) => (
                <TableRow key={`skeleton-${rowIndex}`}>
                  {selection && (
                    <TableCell padding="checkbox">
                      <Skeleton variant="circular" width={18} height={18} />
                    </TableCell>
                  )}
                  {columns.map((column) => (
                    <TableCell key={column.key} sx={{ display: responsiveDisplay(column.hideBelow) }}>
                      <Skeleton width="70%" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {showTable &&
              !loading &&
              rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={columnCount} sx={{ borderBottom: 0 }}>
                    <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />
                  </TableCell>
                </TableRow>
              )}

            {rows.map((row) => (
              <TableRow
                key={getRowId(row)}
                hover={Boolean(onRowClick)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                sx={{ cursor: onRowClick ? "pointer" : "default", "&:last-child td": { borderBottom: 0 } }}
              >
                {selection && (
                  <TableCell
                    padding="checkbox"
                    onClick={(event) => event.stopPropagation()}
                    sx={{ cursor: "default" }}
                  >
                    <Checkbox
                      size="small"
                      checked={selection.selectedIds.includes(getRowId(row))}
                      onChange={() => toggleRow(row)}
                      disabled={!isSelectable(row)}
                      inputProps={{ "aria-label": `Select ${getRowId(row)}` }}
                    />
                  </TableCell>
                )}
                {columns.map((column) => {
                  const content = column.render ? column.render(row) : (row as Record<string, unknown>)[column.key];
                  return (
                    <TableCell
                      key={column.key}
                      align={column.align ?? "left"}
                      sx={{
                        display: responsiveDisplay(column.hideBelow),
                        fontFamily: column.monospace ? "'JetBrains Mono', Consolas, monospace" : undefined,
                        fontSize: column.monospace ? 12.5 : undefined,
                      }}
                    >
                      {content === null || content === undefined || content === "" ? (
                        <Typography variant="body2" color="text.disabled" component="span">
                          —
                        </Typography>
                      ) : (
                        (content as ReactNode)
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {paginated && (
        <Stack direction="row" justifyContent="flex-end" sx={{ borderTop: 1, borderColor: "divider" }}>
          <TablePagination
            component="div"
            count={total ?? 0}
            page={Math.max(0, page - 1)}
            rowsPerPage={size}
            rowsPerPageOptions={PAGE_SIZE_OPTIONS}
            onPageChange={(_event, nextPage) => onPageChange?.(nextPage + 1)}
            onRowsPerPageChange={(event) => {
              onSizeChange?.(Number(event.target.value));
              onPageChange?.(1);
            }}
            showFirstButton
            showLastButton
          />
        </Stack>
      )}
    </Paper>
  );
}

export default DataTable;
