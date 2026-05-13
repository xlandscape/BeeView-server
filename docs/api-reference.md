# API Reference

BeeView-server runs on port **32000** by default. Interactive API documentation is available at [http://localhost:32000/docs](http://localhost:32000/docs) when the server is running.

This page documents the key endpoints used by the BeeView frontend.

## Landscape data endpoints

### `GET /geojson`

Returns all landscape features as GeoJSON.

### `GET /geojson/viewport`

Returns features filtered to the current map viewport bounds.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `min_lat`, `max_lat` | float | Latitude bounds |
| `min_lon`, `max_lon` | float | Longitude bounds |
| `zoom` | float | Current zoom level (for potential simplification) |

### `GET /nectar/max/viewport`, `GET /pollen/max/viewport`

Returns maximum nectar or pollen values per feature within the viewport.

### `GET /api/timeseries/averages`

Returns daily average nectar and pollen values across features.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `feature_ids` | string | Comma-separated feature IDs (optional — omit for all features) |
| `include_nectar` | bool | Include nectar averages |
| `include_pollen` | bool | Include pollen averages |

**Response:** `{ "averages": [{ "day": 1, "nectar_avg": 0.00005, "pollen_avg": 0.03 }, ...] }`

### `GET /api/features/vegetation-mapping`

Returns vegetation class assignments per feature.

### `GET /api/beehive-location`

Returns the beehive location from the template.xrun file (legacy, used for single-run mode).

## Run management endpoints

### `GET /api/runs`

Lists all imported runs with their metadata.

**Response:** `{ "runs": [{ "id": 1, "sim_id": "hive01_MC0", "hive_group_id": "hive01", "treatment_on": false, ... }, ...] }`

### `GET /api/bee-population/timeseries`

Returns the legacy single-run bee population timeseries.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `run_id` | int | Run ID (optional — uses legacy data if omitted) |

### `GET /api/bee-population/replicates`

Returns per-replicate timeseries for a specific run, with mean and individual replicate data.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `run_id` | int | Run ID (required) |

**Response:** `{ "metrics": { "TotalIHbees + TotalForagers": { "days": [...], "mean": [...], "replicates": [...] }, ... } }`

## Exposure endpoints

### `GET /api/applications`

Returns pesticide application events for a run.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `run_id` | int | Run ID (reads from `applications` table; falls back to legacy file lookup if DB rows are missing) |
| `feature_ids` | string | Comma-separated feature IDs to filter by |

### `GET /api/exposure/timeseries`

Returns daily exposure time series computed from application events.

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `run_id` | int | Run ID |
| `feature_ids` | string | Comma-separated feature IDs |

Each application event is extended over 9 days (application day + 8 following days). Overlapping applications are summed.

Source priority for applications data:

1. `applications` table rows for the requested `run_id`
2. Legacy fallback (`source_path/.../applications.txt` or `data/applications.txt`)

## Compare endpoints

### `GET /api/compare/reduction-matrix`

Returns the percent-reduction percentile matrix (spatial × temporal).

**Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `baseline_ids` | string | Comma-separated untreated run IDs |
| `scenario_ids` | string | Comma-separated treated run IDs (same order as baselines) |
| `metric` | string | Colony metric name (e.g. `TotalIHbees + TotalForagers`) |
| `spatial_scope` | string | `pair` (each MC pair is a spatial unit) or `hive_mean` (average MC pairs per hive first) |

**Response:**

```json
{
  "matrix": [[0.6, 4.0, 6.3, ...], ...],
  "spatial_percentiles": [10, 20, 30, 40, 50, 60, 70, 80, 90],
  "temporal_percentiles": [10, 20, 30, 40, 50, 60, 70, 80, 90],
  "n_days": 366,
  "n_spatial_units": 10,
  "n_selected_pairs": 10,
  "metric": "TotalIHbees + TotalForagers",
  "spatial_scope": "pair"
}
```

Matrix values are in **percent** (e.g. `12.1` = 12.1% reduction). Positive = treated colony is smaller than untreated.

### `GET /api/compare/percentiles`

Legacy endpoint returning exceedance-fraction percentiles with a threshold parameter.

**Parameters:** Same as reduction-matrix, plus `threshold` (float) and `mode` (`decline`/`absolute`).

## Notes

- All geometries are served in **EPSG:4326** (WGS84 longitude/latitude).
- Time point queries accept either a **day-of-year integer** (1–365) or a **YYYY-MM-DD date string**.
- NaN and infinite values are cleaned to `0.0` before returning to clients.
- The server uses CORS `allow_origins=["*"]` for development. Restrict this in production.
