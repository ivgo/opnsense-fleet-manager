import { useMemo, useState } from "react";
import { Box, Chip, Stack, Typography, alpha, useTheme } from "@mui/material";

import type { SiteMapPoint } from "@/api/types";
import { formatNumber } from "@/utils/format";

const MAP_WIDTH = 720;
const MAP_HEIGHT = 360;

/**
 * Coarse continent outlines in [longitude, latitude] pairs. The map is a plain
 * equirectangular projection drawn locally, so the dashboard never depends on a
 * tile provider or an internet connection.
 */
const CONTINENTS: Array<{ name: string; points: Array<[number, number]> }> = [
  {
    name: "North America",
    points: [
      [-168, 65],
      [-150, 70],
      [-125, 72],
      [-100, 74],
      [-80, 72],
      [-62, 60],
      [-55, 48],
      [-66, 44],
      [-70, 41],
      [-76, 35],
      [-81, 25],
      [-90, 22],
      [-97, 18],
      [-105, 20],
      [-114, 28],
      [-124, 40],
      [-130, 52],
      [-145, 60],
      [-168, 65],
    ],
  },
  {
    name: "Greenland",
    points: [
      [-45, 60],
      [-22, 70],
      [-20, 82],
      [-58, 82],
      [-58, 70],
      [-45, 60],
    ],
  },
  {
    name: "South America",
    points: [
      [-81, 10],
      [-70, 12],
      [-60, 8],
      [-50, 0],
      [-35, -6],
      [-38, -22],
      [-48, -28],
      [-58, -38],
      [-66, -55],
      [-72, -52],
      [-75, -40],
      [-70, -18],
      [-81, 10],
    ],
  },
  {
    name: "Africa",
    points: [
      [-17, 15],
      [-5, 36],
      [10, 37],
      [32, 31],
      [43, 12],
      [51, 12],
      [41, -2],
      [40, -15],
      [35, -25],
      [20, -35],
      [15, -22],
      [9, -2],
      [9, 4],
      [-8, 5],
      [-17, 15],
    ],
  },
  {
    name: "Europe",
    points: [
      [-10, 36],
      [-9, 44],
      [-2, 48],
      [2, 51],
      [5, 54],
      [10, 58],
      [20, 60],
      [30, 60],
      [40, 48],
      [30, 41],
      [24, 36],
      [15, 37],
      [3, 42],
      [-10, 36],
    ],
  },
  {
    name: "Asia",
    points: [
      [30, 60],
      [60, 70],
      [100, 77],
      [140, 73],
      [170, 66],
      [180, 60],
      [170, 50],
      [145, 45],
      [140, 35],
      [122, 30],
      [120, 22],
      [108, 10],
      [100, 2],
      [95, 10],
      [80, 8],
      [70, 20],
      [60, 25],
      [45, 30],
      [40, 40],
      [30, 60],
    ],
  },
  {
    name: "Australia",
    points: [
      [114, -22],
      [122, -18],
      [130, -12],
      [142, -11],
      [153, -25],
      [150, -37],
      [140, -38],
      [130, -32],
      [115, -34],
      [114, -22],
    ],
  },
];

function project(longitude: number, latitude: number): { x: number; y: number } {
  return {
    x: ((longitude + 180) / 360) * MAP_WIDTH,
    y: ((90 - latitude) / 180) * MAP_HEIGHT,
  };
}

function polygonPath(points: Array<[number, number]>): string {
  return points
    .map(([longitude, latitude]) => {
      const { x, y } = project(longitude, latitude);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export interface SiteMapProps {
  points: SiteMapPoint[];
  selectedId?: string | null;
  onSelect?: (point: SiteMapPoint) => void;
  height?: number;
}

export function SiteMap({ points, selectedId = null, onSelect, height = 380 }: SiteMapProps) {
  const theme = useTheme();
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const located = useMemo(
    () =>
      points.filter(
        (point): point is SiteMapPoint & { latitude: number; longitude: number } =>
          point.latitude !== null && point.longitude !== null,
      ),
    [points],
  );
  const maxDevices = Math.max(1, ...located.map((point) => point.devices_total));

  const colorFor = (point: SiteMapPoint): string => {
    if (point.worst_severity === "critical") return theme.palette.error.main;
    if (point.worst_severity === "warning") return theme.palette.warning.main;
    if (point.devices_total === 0) return theme.palette.text.disabled;
    if (point.devices_online === point.devices_total) return theme.palette.success.main;
    if (point.devices_online > 0) return theme.palette.warning.main;
    return theme.palette.error.main;
  };

  const radiusFor = (point: SiteMapPoint): number =>
    4 + 10 * Math.sqrt(point.devices_total / maxDevices);

  return (
    <Box>
      <Box
        sx={{
          position: "relative",
          borderRadius: 2,
          overflow: "hidden",
          border: 1,
          borderColor: "divider",
          background: `radial-gradient(circle at 30% 20%, ${alpha(
            theme.palette.primary.main,
            0.16,
          )}, ${alpha(theme.palette.background.default, 0.2)} 55%)`,
        }}
      >
        <Box
          component="svg"
          role="img"
          aria-label={`World map with ${located.length} geolocated site${located.length === 1 ? "" : "s"}`}
          viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
          sx={{ display: "block", width: "100%", height: { xs: 260, md: height } }}
        >
          <defs>
            <linearGradient id="ofme-map-ocean" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={theme.palette.primary.main} stopOpacity={0.14} />
              <stop offset="100%" stopColor={theme.palette.primary.main} stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#ofme-map-ocean)" />

          {[-120, -60, 0, 60, 120].map((longitude) => {
            const { x } = project(longitude, 0);
            return (
              <line
                key={`lon-${longitude}`}
                x1={x}
                y1={0}
                x2={x}
                y2={MAP_HEIGHT}
                stroke={theme.palette.divider}
                strokeWidth={0.6}
                strokeDasharray="3 5"
              />
            );
          })}
          {[-60, -30, 0, 30, 60].map((latitude) => {
            const { y } = project(0, latitude);
            return (
              <line
                key={`lat-${latitude}`}
                x1={0}
                y1={y}
                x2={MAP_WIDTH}
                y2={y}
                stroke={theme.palette.divider}
                strokeWidth={latitude === 0 ? 1 : 0.6}
                strokeDasharray={latitude === 0 ? undefined : "3 5"}
              />
            );
          })}

          {CONTINENTS.map((continent) => (
            <polygon
              key={continent.name}
              points={polygonPath(continent.points)}
              fill={alpha(theme.palette.text.primary, 0.16)}
              stroke={alpha(theme.palette.text.primary, 0.32)}
              strokeWidth={0.8}
              strokeLinejoin="round"
            >
              <title>{continent.name}</title>
            </polygon>
          ))}

          {located.map((point) => {
            const { x, y } = project(point.longitude, point.latitude);
            const active = hoveredId === point.id || selectedId === point.id;
            const color = colorFor(point);
            return (
              <g
                key={point.id}
                tabIndex={onSelect ? 0 : undefined}
                role={onSelect ? "button" : undefined}
                aria-label={`${point.name}: ${point.devices_online} of ${point.devices_total} devices online`}
                onClick={() => onSelect?.(point)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect?.(point);
                  }
                }}
                onMouseEnter={() => setHoveredId(point.id)}
                onMouseLeave={() => setHoveredId(null)}
                style={{ cursor: onSelect ? "pointer" : "default", outline: "none" }}
              >
                <circle
                  cx={x}
                  cy={y}
                  r={radiusFor(point) + (active ? 5 : 2)}
                  fill={alpha(color, active ? 0.32 : 0.18)}
                />
                <circle
                  cx={x}
                  cy={y}
                  r={radiusFor(point)}
                  fill={color}
                  stroke={theme.palette.background.paper}
                  strokeWidth={1.5}
                >
                  <title>
                    {`${point.name} — ${point.devices_online}/${point.devices_total} online${
                      point.city || point.country
                        ? ` (${[point.city, point.country].filter(Boolean).join(", ")})`
                        : ""
                    }`}
                  </title>
                </circle>
                {active && (
                  <text
                    x={x}
                    y={y - radiusFor(point) - 7}
                    textAnchor="middle"
                    fontSize={10}
                    fontWeight={600}
                    fill={theme.palette.text.primary}
                  >
                    {point.name}
                  </text>
                )}
              </g>
            );
          })}
        </Box>
      </Box>

      <Stack
        direction="row"
        spacing={1}
        flexWrap="wrap"
        useFlexGap
        alignItems="center"
        justifyContent="space-between"
        sx={{ mt: 1.25 }}
      >
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" label={`${located.length} mapped sites`} />
          <Chip
            size="small"
            variant="outlined"
            color="success"
            label={`${formatNumber(located.reduce((total, point) => total + point.devices_online, 0))} online`}
          />
          <Chip
            size="small"
            variant="outlined"
            label={`${formatNumber(located.reduce((total, point) => total + point.devices_total, 0))} devices`}
          />
        </Stack>
        <Typography variant="caption" color="text.disabled">
          Marker size scales with managed devices · equirectangular projection
        </Typography>
      </Stack>

      {located.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          No sites have latitude and longitude configured yet. Add coordinates to a site to place it on
          the map.
        </Typography>
      )}
    </Box>
  );
}

export default SiteMap;
