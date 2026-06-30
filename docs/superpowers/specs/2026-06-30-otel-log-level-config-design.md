# OTel Exporter Log Level Configuration Design

**Date:** 2026-06-30  
**Status:** Draft  
**Author:** ROCK Team

## Overview

Make OpenTelemetry (OTel) exporter and SDK log levels configurable via Nacos with hot reload support. This addresses the noise from frequent OTLP export logs (default every 10s) and enables operators to dynamically adjust verbosity without service restart.

## Problem Statement

Currently, `MetricsMonitor._wrap_exporter_with_logging()` hardcodes `logger.info()` for every OTLP export operation. With the default export interval of 10 seconds, this generates significant log volume. Additionally:

- OTel SDK internal loggers (e.g., `opentelemetry.exporter.otlp`, `opentelemetry.sdk.metrics`) use standard Python logging and are not routed through ROCK's file handler
- No mechanism exists to dynamically control these log levels at runtime
- Debugging export failures requires access to OTel SDK internal logs, which are currently not easily accessible

## Design Goals

1. **Configurable log level** for OTel exporter and SDK loggers
2. **Hot reload** via Nacos configuration changes (no service restart required)
3. **File output support** - OTel logs routed to the same log file as ROCK logs when `ROCK_LOGGING_PATH` is set
4. **Backward compatible** - default behavior unchanged (INFO level)

## Architecture

### Configuration Model

Add a new field to `RuntimeConfig` in `rock/config.py`:

```python
@dataclass
class RuntimeConfig:
    # ... existing fields ...
    otel_log_level: str = "INFO"
    """Log level for OTel exporter and SDK loggers.
    Supports: DEBUG, INFO, WARNING, ERROR.
    Configurable via Nacos hot reload."""
```

**Default value:** `INFO` (preserves current behavior)

**Nacos configuration example:**

```yaml
runtime:
  otel_log_level: WARNING  # Reduce OTel log noise
```

### Logger Coverage

The following loggers are controlled:

| Logger Name | Purpose |
|-------------|---------|
| `rock.admin.metrics.monitor` | `export_with_logging` wrapper logs (export duration, data points, result) |
| `opentelemetry` | All OTel SDK internal loggers (exporter, SDK metrics, etc.) |

Setting the level on `opentelemetry` (the root logger name) covers all sub-loggers via Python's logging hierarchy.

### Core Implementation

Add a helper function in `rock/admin/metrics/monitor.py`:

```python
OTEL_LOGGER_NAMES = [
    "rock.admin.metrics.monitor",
    "opentelemetry",
]

def set_otel_log_level(level: str) -> None:
    """Set log level for OTel exporter and SDK loggers.
    
    Also attaches a file handler (matching ROCK's init_logger behavior)
    so OTel internal logs are routed to the same log file.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    for name in OTEL_LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(numeric_level)
        
        # Attach file handler if ROCK_LOGGING_PATH is set.
        # init_file_handler is @cached, so calling it with the same log_name
        # returns the same handler instance (no duplicate file handles).
        if env_vars.ROCK_LOGGING_PATH and env_vars.ROCK_LOGGING_FILE_NAME:
            file_handler = init_file_handler(env_vars.ROCK_LOGGING_FILE_NAME)
            if file_handler and not any(
                isinstance(h, logging.FileHandler) for h in logger.handlers
            ):
                logger.addHandler(file_handler)
                # OTel SDK loggers propagate to root by default (propagate=True).
                # Keep propagation on so records also reach any root handlers.
                # For "opentelemetry" (not a ROCK logger), propagate is already True.
```

### Invocation Points

1. **Initialization:** `MetricsMonitor.__init__()` calls `set_otel_log_level()` after `_init_telemetry()` with the initial config value

2. **Hot reload:** `RockConfig.update()` reads `runtime.otel_log_level` from Nacos and calls `set_otel_log_level()`

### Hot Reload Flow

```
Nacos configuration change
  ↓
NacosConfigProvider._update_callback() updates config_cache
  ↓
RockConfig.update() called (periodically by sandbox_manager or on-demand)
  ↓
Read runtime.otel_log_level from Nacos config
  ↓
Call set_otel_log_level(level)
  ↓
OTel logger setLevel() takes effect immediately
```

### File Output Support

When `ROCK_LOGGING_PATH` is set:

- ROCK's `init_logger()` creates a `FileHandler` via `init_file_handler()` (cached with `@cache`)
- `set_otel_log_level()` reuses the same `init_file_handler()` to attach it to OTel loggers
- OTel SDK logs (including export failures, connection errors) are written to the same log file
- The `@cache` decorator ensures only one file handler instance exists per log file

When `ROCK_LOGGING_PATH` is not set:

- OTel loggers use their default handlers (typically `StreamHandler` to stdout)
- Behavior is unchanged from current implementation

## Data Flow

### Initial Setup

```
MetricsMonitor.create()
  ↓
MetricsMonitor.__init__()
  ↓
_init_telemetry() creates OTLP exporter and wraps export()
  ↓
set_otel_log_level(rock_config.runtime.otel_log_level)
  ↓
OTel loggers configured with level and file handler
```

### Runtime Update

```
Nacos config changed (e.g., otel_log_level: INFO → WARNING)
  ↓
RockConfig.update() reads new config
  ↓
runtime.otel_log_level detected in nacos_result
  ↓
set_otel_log_level("WARNING")
  ↓
logging.getLogger("rock.admin.metrics.monitor").setLevel(WARNING)
logging.getLogger("opentelemetry").setLevel(WARNING)
  ↓
Subsequent OTel logs at INFO level are suppressed
```

## Error Handling

- **Invalid log level:** `getattr(logging, level.upper(), logging.INFO)` falls back to INFO
- **Missing file handler:** `init_file_handler()` returns `None` if `ROCK_LOGGING_PATH` is not set; `set_otel_log_level()` checks for this
- **Duplicate handlers:** `set_otel_log_level()` checks if a `FileHandler` already exists before adding

## Testing Strategy

### Unit Tests

1. **Config parsing:** Verify `RuntimeConfig.otel_log_level` defaults to "INFO" and parses from YAML
2. **Level mapping:** Test `set_otel_log_level()` with DEBUG/INFO/WARNING/ERROR and verify logger levels
3. **Invalid level:** Test fallback to INFO for invalid level strings (e.g., "INVALID")
4. **File handler attachment:** Mock `ROCK_LOGGING_PATH` and verify file handler is attached to OTel loggers
5. **Duplicate prevention:** Call `set_otel_log_level()` twice and verify only one file handler exists

### Integration Tests

1. **Hot reload:** Simulate Nacos config change and verify logger level updates without restart
2. **Export logging:** Trigger OTLP export and verify log output respects configured level
3. **File output:** Set `ROCK_LOGGING_PATH`, trigger OTel logs, verify they appear in log file

## Migration & Rollback

### Migration

- **No migration required** - new field has a safe default ("INFO")
- Existing deployments continue to work without Nacos config changes
- Operators can optionally add `runtime.otel_log_level` to Nacos to reduce noise

### Rollback

- Remove `otel_log_level` from Nacos config → reverts to INFO
- Code rollback: remove the field and `set_otel_log_level()` function; behavior returns to hardcoded INFO

## Future Enhancements

Potential extensions (not in current scope):

1. **Per-exporter log levels:** Separate controls for metrics/traces/logs exporters
2. **Log filtering:** Filter OTel logs by content (e.g., suppress specific error types)
3. **Metrics export interval:** Make `export_interval_millis` configurable via Nacos (currently hardcoded in `MetricsMonitor.create()`)

## References

- **Files modified:**
  - `rock/config.py` - add `otel_log_level` field to `RuntimeConfig`, update `RockConfig.update()` to read and apply it
  - `rock/admin/metrics/monitor.py` - add `set_otel_log_level()` function and call it in `__init__()`

- **Related code:**
  - `rock/logger.py` - `init_file_handler()`, `init_logger()`
  - `rock/utils/providers/nacos_provider.py` - Nacos config provider
  - `rock/sandbox/sandbox_manager.py` - calls `rock_config.update()` periodically
