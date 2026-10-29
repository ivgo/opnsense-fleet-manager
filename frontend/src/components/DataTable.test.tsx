import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import DataTable, { type DataTableColumn } from "@/components/DataTable";

interface Row {
  id: string;
  name: string;
  status: string;
}

const rows: Row[] = [
  { id: "1", name: "edge-fra-01", status: "online" },
  { id: "2", name: "edge-ber-01", status: "offline" },
];

const columns: Array<DataTableColumn<Row>> = [
  { key: "name", label: "Device" },
  {
    key: "status",
    label: "Status",
    render: (row) => <span data-testid={`status-${row.id}`}>{row.status}</span>,
  },
];

describe("DataTable", () => {
  it("renders rows and custom cells", () => {
    render(<DataTable columns={columns} rows={rows} getRowId={(row) => row.id} />);

    expect(screen.getByText("edge-fra-01")).toBeInTheDocument();
    expect(screen.getByText("edge-ber-01")).toBeInTheDocument();
    expect(screen.getByTestId("status-1")).toHaveTextContent("online");
    expect(screen.getByTestId("status-2")).toHaveTextContent("offline");
  });

  it("shows the empty state when there are no rows", () => {
    render(
      <DataTable
        columns={columns}
        rows={[]}
        getRowId={(row) => row.id}
        emptyTitle="No devices"
        emptyDescription="Add a device to get started."
      />,
    );

    expect(screen.getByText("No devices")).toBeInTheDocument();
    expect(screen.getByText("Add a device to get started.")).toBeInTheDocument();
  });

  it("renders the server-side pagination controls and emits 1-based pages", async () => {
    const onPageChange = vi.fn();
    const user = userEvent.setup();

    render(
      <DataTable
        columns={columns}
        rows={rows}
        getRowId={(row) => row.id}
        page={1}
        size={25}
        total={50}
        onPageChange={onPageChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: /go to next page/i }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("surfaces a retry action when loading fails", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    render(
      <DataTable
        columns={columns}
        rows={[]}
        getRowId={(row) => row.id}
        error="Backend unavailable"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("Backend unavailable")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
