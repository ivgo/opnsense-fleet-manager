import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import utc from "dayjs/plugin/utc";

dayjs.extend(relativeTime);
dayjs.extend(utc);

export const EMPTY = "—";

export function formatDateTime(value?: string | null): string {
  if (!value) return EMPTY;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD HH:mm:ss") : EMPTY;
}

export function formatDate(value?: string | null): string {
  if (!value) return EMPTY;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD") : EMPTY;
}

export function fromNow(value?: string | null): string {
  if (!value) return EMPTY;
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.fromNow() : EMPTY;
}

export function formatBytes(bytes?: number | null, precision = 1): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return EMPTY;
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  const exponent = Math.min(Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 100 || exponent === 0 ? 0 : precision)} ${units[exponent]}`;
}

/** Format a bit rate (bits per second) with SI prefixes. */
export function formatBits(bitsPerSecond?: number | null, precision = 1): string {
  if (bitsPerSecond === null || bitsPerSecond === undefined || Number.isNaN(bitsPerSecond)) return EMPTY;
  if (bitsPerSecond === 0) return "0 bps";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  const exponent = Math.min(Math.floor(Math.log(Math.abs(bitsPerSecond)) / Math.log(1000)), units.length - 1);
  const value = bitsPerSecond / 1000 ** exponent;
  return `${value.toFixed(value >= 100 || exponent === 0 ? 0 : precision)} ${units[exponent]}`;
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return EMPTY;
  const total = Math.max(0, Math.floor(seconds));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${total}s`;
}

export function formatNumber(value?: number | null, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return `${value.toFixed(digits)}%`;
}

export function titleCase(value?: string | null): string {
  if (!value) return EMPTY;
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function truncate(value: string, length = 60): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

export function initials(name?: string | null): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part.charAt(0).toUpperCase()).join("") || "?";
}

export function parseLines(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function copyToClipboard(value: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(value);
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
  return Promise.resolve();
}

export function isJsonLike(value: string): boolean {
  const trimmed = value.trim();
  return (
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  );
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Trigger a browser download for an in-memory blob. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
