# OTel Exporter Log Level Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OTel exporter and SDK log levels configurable via Nacos with hot reload support.

**Architecture:** Add `otel_log_level` field to `RuntimeConfig`, implement `set_otel_log_level()` helper that controls both the ROCK metrics logger and OTel SDK loggers, and integrate it into the Nacos hot reload flow via `RockConfig.update()`.

**Tech Stack:** Python 3.10+, dataclasses, Python logging, Nacos config provider, OpenTelemetry SDK

---

## File Structure

**Modified files:**
- `rock/config.py` — add `otel_log_level: str = "INFO"` to `RuntimeConfig`, update `RockConfig.update()` to read and apply it
- `rock/admin/metrics/monitor.py` — add `set_otel_log_level()` function, call it in `MetricsMonitor.__init__()` and `MetricsMonitor.create()`

**Test files:**
- `tests/unit/test_config.py` — test `RuntimeConfig.otel_log_level` default and parsing
- `tests/unit/admin/metrics/test_monitor.py` — test `set_otel_log_level()` function

---

### Task 1: Add otel_log_level field to RuntimeConfig

**Files:**
- Modify: `rock/config.py:263-298` (RuntimeConfig dataclass)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test for default value**

```python
def test_runtime_config_otel_log_level_default():
    """RuntimeConfig.otel_log_level defaults to INFO."""
    cfg = RuntimeConfig()
    assert cfg.otel_log_level == "INFO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py::test_runtime_config_otel_log_level_default -v`  
Expected: FAIL with `AttributeError: 'RuntimeConfig' object has no attribute 'otel_log_level'`

- [ ] **Step 3: Add otel_log_level field to RuntimeConfig**

In `rock/config.py`, add the field after `instance_registry_mirrors`:

```python
@dataclass
class RuntimeConfig:
    enable_auto_clear: bool = False
    project_root: str = field(default_factory=lambda: env_vars.ROCK_PROJECT_ROOT)
    python_env_path: str = field(default_factory=lambda: env_vars.ROCK_PYTHON_ENV_PATH)
    envhub_db_url: str = field(default_factory=lambda: env_vars.ROCK_ENVHUB_DB_URL)
    operator_type: str = "ray"
    standard_spec: StandardSpec = field(default_factory=StandardSpec)
    max_allowed_spec: StandardSpec = field(default_factory=lambda: StandardSpec(cpus=16, memory="64g"))
    use_standard_spec_only: bool = False
    metrics_endpoint: str = ""
    user_defined_tags: dict = field(default_factory=dict)
    sandbox_disk_limit_rootfs: str | None = None
    instance_registry_mirrors: list[str] = field(default_factory=list)
    otel_log_level: str = "INFO"
    """Log level for OTel exporter and SDK loggers.
    Supports: DEBUG, INFO, WARNING, ERROR.
    Configurable via Nacos hot reload."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py::test_runtime_config_otel_log_level_default -v`  
Expected: PASS

- [ ] **Step 5: Write test for custom value**

```python
def test_runtime_config_otel_log_level_custom():
    """RuntimeConfig.otel_log_level accepts custom values."""
    cfg = RuntimeConfig(otel_log_level="WARNING")
    assert cfg.otel_log_level == "WARNING"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py::test_runtime_config_otel_log_level_custom -v`  
Expected: PASS

- [ ] **Step 7: Write test for YAML parsing**

```python
def test_runtime_config_otel_log_level_from_yaml():
    """RuntimeConfig.otel_log_level parses from YAML dict."""
    config = {
        "standard_spec": {"memory": "8g", "cpus": 2},
        "otel_log_level": "DEBUG",
    }
    cfg = RuntimeConfig(**config)
    assert cfg.otel_log_level == "DEBUG"
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py::test_runtime_config_otel_log_level_from_yaml -v`  
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add rock/config.py tests/unit/test_config.py
git commit -m "feat: add otel_log_level field to RuntimeConfig"
```

---

### Task 2: Implement set_otel_log_level helper function

**Files:**
- Modify: `rock/admin/metrics/monitor.py`
- Test: `tests/unit/admin/metrics/test_monitor.py`

- [ ] **Step 1: Write failing test for set_otel_log_level with INFO**

```python
import logging
from rock.admin.metrics.monitor import set_otel_log_level


def test_set_otel_log_level_info():
    """set_otel_log_level sets loggers to INFO level."""
    set_otel_log_level("INFO")
    assert logging.getLogger("rock.admin.metrics.monitor").level == logging.INFO
    assert logging.getLogger("opentelemetry").level == logging.INFO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_set_otel_log_level_info -v`  
Expected: FAIL with `ImportError: cannot import name 'set_otel_log_level'`

- [ ] **Step 3: Implement set_otel_log_level function**

In `rock/admin/metrics/monitor.py`, add after the imports and before `class MetricsMonitor`:

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
            from rock.logger import init_file_handler
            file_handler = init_file_handler(env_vars.ROCK_LOGGING_FILE_NAME)
            if file_handler and not any(
                isinstance(h, logging.FileHandler) for h in logger.handlers
            ):
                logger.addHandler(file_handler)
```

Note: Import `init_file_handler` inside the function to avoid circular imports (monitor.py already imports `init_logger` at the top, and `init_file_handler` is in the same module).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_set_otel_log_level_info -v`  
Expected: PASS

- [ ] **Step 5: Write test for WARNING level**

```python
def test_set_otel_log_level_warning():
    """set_otel_log_level sets loggers to WARNING level."""
    set_otel_log_level("WARNING")
    assert logging.getLogger("rock.admin.metrics.monitor").level == logging.WARNING
    assert logging.getLogger("opentelemetry").level == logging.WARNING
    
    # Reset to INFO for other tests
    set_otel_log_level("INFO")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_set_otel_log_level_warning -v`  
Expected: PASS

- [ ] **Step 7: Write test for invalid level (fallback to INFO)**

```python
def test_set_otel_log_level_invalid_falls_back_to_info():
    """set_otel_log_level falls back to INFO for invalid level strings."""
    set_otel_log_level("INVALID_LEVEL")
    assert logging.getLogger("rock.admin.metrics.monitor").level == logging.INFO
    assert logging.getLogger("opentelemetry").level == logging.INFO
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_set_otel_log_level_invalid_falls_back_to_info -v`  
Expected: PASS

- [ ] **Step 9: Write test for lowercase level**

```python
def test_set_otel_log_level_case_insensitive():
    """set_otel_log_level accepts lowercase level names."""
    set_otel_log_level("debug")
    assert logging.getLogger("rock.admin.metrics.monitor").level == logging.DEBUG
    assert logging.getLogger("opentelemetry").level == logging.DEBUG
    
    # Reset to INFO
    set_otel_log_level("INFO")
```

- [ ] **Step 10: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_set_otel_log_level_case_insensitive -v`  
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add rock/admin/metrics/monitor.py tests/unit/admin/metrics/test_monitor.py
git commit -m "feat: add set_otel_log_level helper function"
```

---

### Task 3: Call set_otel_log_level in MetricsMonitor initialization

**Files:**
- Modify: `rock/admin/metrics/monitor.py:18-68` (MetricsMonitor class)
- Test: `tests/unit/admin/metrics/test_monitor.py`

- [ ] **Step 1: Write failing test for MetricsMonitor.create() with otel_log_level**

```python
from unittest.mock import patch


@patch("rock.admin.metrics.monitor.set_otel_log_level")
@patch("rock.admin.metrics.monitor.get_uniagent_endpoint", return_value=("127.0.0.1", "4318"))
@patch("rock.admin.metrics.monitor.get_instance_id", return_value="test-pod")
@patch("rock.admin.metrics.monitor.env_vars")
def test_create_calls_set_otel_log_level(mock_env_vars, mock_instance_id, mock_uniagent, mock_set_level):
    """MetricsMonitor.create() calls set_otel_log_level with default INFO."""
    mock_env_vars.ROCK_ADMIN_ENV = "daily"
    mock_env_vars.ROCK_ADMIN_ROLE = "test"
    
    MetricsMonitor.create(export_interval_millis=10000)
    
    mock_set_level.assert_called_once_with("INFO")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_create_calls_set_otel_log_level -v`  
Expected: FAIL — `set_otel_log_level` not called

- [ ] **Step 3: Add otel_log_level parameter to MetricsMonitor.__init__()**

In `rock/admin/metrics/monitor.py`, update `__init__` signature and call `set_otel_log_level`:

```python
def __init__(
    self,
    host: str,
    port: str,
    pod: str,
    env: str = "daily",
    role: str = "test",
    export_interval_millis: int = 10000,
    endpoint: str = "",
    user_defined_tags: dict = {},
    metric_prefix: str = "",
    otel_log_level: str = "INFO",
):
    patch_view_instrument_match()
    self.metric_prefix = metric_prefix
    self.user_defined_tags = user_defined_tags
    self._init_basic_attributes(host, port, pod, env, role)
    self.endpoint = endpoint or f"http://{self.host}:{self.port}/v1/metrics"
    self._init_telemetry(export_interval_millis)
    self.counters: dict[str, Counter] = {}
    self.gauges: dict[str, _Gauge] = {}
    self._register_metrics()
    set_otel_log_level(otel_log_level)
    logger.info(
        f"Initializing MetricsCollector with host={host}, port={port}, pod={pod}, "
        f"env={env}, role={role}, endpoint={self.endpoint}"
    )
```

- [ ] **Step 4: Add otel_log_level parameter to MetricsMonitor.create()**

Update `create()` to accept and pass through `otel_log_level`:

```python
@classmethod
def create(
    cls,
    export_interval_millis: int = 20000,
    metrics_endpoint: str = "",
    user_defined_tags: dict = {},
    metric_prefix: str = "",
    otel_log_level: str = "INFO",
) -> "MetricsMonitor":
    host, port = get_uniagent_endpoint()
    pod = get_instance_id()
    env = env_vars.ROCK_ADMIN_ENV
    role = env_vars.ROCK_ADMIN_ROLE
    logger.info(f"Initializing MetricsCollector with host={host}, port={port}, env={env}, role={role}")
    return cls(
        host=host,
        port=port,
        pod=pod,
        env=env,
        role=role,
        export_interval_millis=export_interval_millis,
        endpoint=metrics_endpoint,
        user_defined_tags=user_defined_tags,
        metric_prefix=metric_prefix,
        otel_log_level=otel_log_level,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_create_calls_set_otel_log_level -v`  
Expected: PASS

- [ ] **Step 6: Write test for custom otel_log_level**

```python
@patch("rock.admin.metrics.monitor.set_otel_log_level")
@patch("rock.admin.metrics.monitor.get_uniagent_endpoint", return_value=("127.0.0.1", "4318"))
@patch("rock.admin.metrics.monitor.get_instance_id", return_value="test-pod")
@patch("rock.admin.metrics.monitor.env_vars")
def test_create_calls_set_otel_log_level_custom(mock_env_vars, mock_instance_id, mock_uniagent, mock_set_level):
    """MetricsMonitor.create() calls set_otel_log_level with custom level."""
    mock_env_vars.ROCK_ADMIN_ENV = "daily"
    mock_env_vars.ROCK_ADMIN_ROLE = "test"
    
    MetricsMonitor.create(export_interval_millis=10000, otel_log_level="WARNING")
    
    mock_set_level.assert_called_once_with("WARNING")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py::test_create_calls_set_otel_log_level_custom -v`  
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add rock/admin/metrics/monitor.py tests/unit/admin/metrics/test_monitor.py
git commit -m "feat: call set_otel_log_level in MetricsMonitor initialization"
```

---

### Task 4: Integrate otel_log_level into RockConfig.update() for Nacos hot reload

**Files:**
- Modify: `rock/config.py:495-530` (RockConfig.update method)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test for RockConfig.update() applying otel_log_level**

```python
@pytest.mark.asyncio
async def test_rock_config_update_applies_otel_log_level():
    """RockConfig.update() reads runtime.otel_log_level and calls set_otel_log_level."""
    from unittest.mock import AsyncMock, patch
    
    config = RockConfig()
    config.nacos_provider = AsyncMock()
    config.nacos_provider.get_config = AsyncMock(return_value={
        "runtime": {"otel_log_level": "WARNING"}
    })
    
    with patch("rock.config.set_otel_log_level") as mock_set_level:
        await config.update()
        mock_set_level.assert_called_once_with("WARNING")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py::test_rock_config_update_applies_otel_log_level -v`  
Expected: FAIL — `set_otel_log_level` not imported or not called

- [ ] **Step 3: Import set_otel_log_level in rock/config.py**

Add import at the top of `rock/config.py` (after the existing `yaml` import):

```python
from rock.admin.metrics.monitor import set_otel_log_level
```

This import is safe — `monitor.py` imports `rock.logger`, `rock.utils`, `rock.env_vars`, none of which import `rock.config`, so there is no circular dependency.

- [ ] **Step 4: Update RockConfig.update() to apply otel_log_level**

In `rock/config.py`, update the `update()` method. Add the `otel_log_level` handling after the existing `runtime` section:

```python
async def update(self):
    if self.nacos_provider is None:
        return

    nacos_result = await self.nacos_provider.get_config()
    if not nacos_result:
        return

    # Map config keys to their corresponding dataclass types
    config_map = {
        "sandbox_config": (SandboxConfig, "sandbox_config"),
        "proxy_service": (ProxyServiceConfig, "proxy_service"),
    }

    # Update configs that are present in nacos_result
    for key, (config_class, attr_name) in config_map.items():
        if key in nacos_result:
            setattr(self, attr_name, config_class(**nacos_result[key]))

    if "image_registry_mirrors" in nacos_result:
        raw_mirrors = nacos_result["image_registry_mirrors"] or []
        self.image_registry_mirrors = [ImageRegistryMirror(**m) for m in raw_mirrors]
    if "image_mirror_lookup_allowlist" in nacos_result:
        self.image_mirror_lookup_allowlist = list(nacos_result["image_mirror_lookup_allowlist"] or [])

    if "runtime" in nacos_result and isinstance(nacos_result["runtime"], dict):
        runtime_overrides = nacos_result["runtime"]
        if "instance_registry_mirrors" in runtime_overrides:
            self.runtime.instance_registry_mirrors = list(runtime_overrides["instance_registry_mirrors"] or [])
        if "otel_log_level" in runtime_overrides:
            self.runtime.otel_log_level = runtime_overrides["otel_log_level"]
            set_otel_log_level(self.runtime.otel_log_level)

    logger.info(
        f"Updated config from Nacos: sandbox_config={self.sandbox_config}, proxy_service={self.proxy_service}"
        f", image_registry_mirrors={self.image_registry_mirrors}"
        f", image_mirror_lookup_allowlist={self.image_mirror_lookup_allowlist}"
        f", instance_registry_mirrors={self.runtime.instance_registry_mirrors}"
        f", otel_log_level={self.runtime.otel_log_level}"
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py::test_rock_config_update_applies_otel_log_level -v`  
Expected: PASS

- [ ] **Step 6: Write test for update without otel_log_level (no-op)**

```python
@pytest.mark.asyncio
async def test_rock_config_update_without_otel_log_level():
    """RockConfig.update() doesn't call set_otel_log_level when key is missing."""
    from unittest.mock import AsyncMock, patch
    
    config = RockConfig()
    config.nacos_provider = AsyncMock()
    config.nacos_provider.get_config = AsyncMock(return_value={
        "runtime": {"other_field": "value"}
    })
    
    with patch("rock.config.set_otel_log_level") as mock_set_level:
        await config.update()
        mock_set_level.assert_not_called()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py::test_rock_config_update_without_otel_log_level -v`  
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add rock/config.py tests/unit/test_config.py
git commit -m "feat: integrate otel_log_level into RockConfig.update() for Nacos hot reload"
```

---

### Task 5: Pass otel_log_level from RuntimeConfig to MetricsMonitor.create()

**Files:**
- Modify: `rock/admin/core/sandbox_table.py:92-99`
- Modify: `rock/sandbox/base_manager.py:32-36`
- Modify: `rock/sandbox/sandbox_meta_store.py:46-50`
- Modify: `rock/sandbox/service/sandbox_proxy_service.py:57-61`
- Test: integration (covered by existing tests)

- [ ] **Step 1: Update SandboxTable to pass otel_log_level**

In `rock/admin/core/sandbox_table.py`, update the `MetricsMonitor.create()` call:

```python
def __init__(self, db_provider: DatabaseProvider, rock_config: RockConfig | None = None) -> None:
    self._db = db_provider
    self.metrics_monitor = MetricsMonitor.create(
        export_interval_millis=20_000,
        metrics_endpoint=rock_config.runtime.metrics_endpoint if rock_config else "",
        user_defined_tags=rock_config.runtime.user_defined_tags if rock_config else {},
        metric_prefix="meta_store.db",
        otel_log_level=rock_config.runtime.otel_log_level if rock_config else "INFO",
    )
```

- [ ] **Step 2: Update BaseManager to pass otel_log_level**

In `rock/sandbox/base_manager.py`, update the `MetricsMonitor.create()` call:

```python
self.metrics_monitor = MetricsMonitor.create(
    export_interval_millis=20_000,
    metrics_endpoint=rock_config.runtime.metrics_endpoint,
    user_defined_tags=rock_config.runtime.user_defined_tags,
    otel_log_level=rock_config.runtime.otel_log_level,
)
```

- [ ] **Step 3: Update SandboxMetaStore to pass otel_log_level**

In `rock/sandbox/sandbox_meta_store.py`, update the `MetricsMonitor.create()` call:

```python
self.metrics_monitor = MetricsMonitor.create(
    export_interval_millis=20_000,
    metrics_endpoint=rock_config.runtime.metrics_endpoint,
    user_defined_tags=rock_config.runtime.user_defined_tags,
    otel_log_level=rock_config.runtime.otel_log_level,
)
```

- [ ] **Step 4: Update SandboxProxyService to pass otel_log_level**

In `rock/sandbox/service/sandbox_proxy_service.py`, update the `MetricsMonitor.create()` call:

```python
self.metrics_monitor = MetricsMonitor.create(
    export_interval_millis=20_000,
    metrics_endpoint=rock_config.runtime.metrics_endpoint,
    user_defined_tags=rock_config.runtime.user_defined_tags,
    otel_log_level=rock_config.runtime.otel_log_level,
)
```

- [ ] **Step 5: Note about SDK MetricsMonitor (no change needed)**

`rock/sdk/model/server/utils.py` calls `MetricsMonitor.create()` without a `rock_config` — it uses the default `otel_log_level="INFO"` from the new parameter. No change needed there.

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `uv run pytest tests/unit/admin/metrics/test_monitor.py -v`  
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add rock/admin/core/sandbox_table.py rock/sandbox/base_manager.py rock/sandbox/sandbox_meta_store.py rock/sandbox/service/sandbox_proxy_service.py
git commit -m "feat: pass otel_log_level from RuntimeConfig to all MetricsMonitor.create() calls"
```

---

### Task 6: Run full test suite and verify implementation

**Files:**
- Test: entire test suite

- [ ] **Step 1: Run all metrics tests**

Run: `uv run pytest tests/unit/admin/metrics/ -v`  
Expected: All tests PASS

- [ ] **Step 2: Run all config tests**

Run: `uv run pytest tests/unit/test_config.py -v`  
Expected: All tests PASS

- [ ] **Step 3: Run fast test suite (no external deps)**

Run: `uv run pytest -m "not need_ray and not need_admin and not need_admin_and_network" --reruns 1`  
Expected: All tests PASS

- [ ] **Step 4: Run linter and formatter**

```bash
uv run ruff check --fix .
uv run ruff format .
```

Expected: No errors

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -A
git commit -m "style: apply ruff formatting"
```

(Skip if no changes)

- [ ] **Step 6: Create integration test example (documentation only)**

Add a comment in `docs/superpowers/plans/2026-06-30-otel-log-level-config.md` showing how to manually test:

```markdown
## Manual Integration Testing

To manually test the feature:

1. Set `ROCK_LOGGING_PATH=/tmp/rock-logs` and `ROCK_LOGGING_FILE_NAME=rock.log`
2. Start admin service with Nacos configured
3. Add to Nacos config:
   ```yaml
   runtime:
     otel_log_level: WARNING
   ```
4. Observe `/tmp/rock-logs/rock.log` — OTel logs should be suppressed
5. Change Nacos config to `otel_log_level: DEBUG`
6. Wait for next `RockConfig.update()` cycle (or trigger manually)
7. Observe `/tmp/rock-logs/rock.log` — OTel debug logs should appear
```

- [ ] **Step 7: Final commit with docs**

```bash
git add docs/superpowers/plans/2026-06-30-otel-log-level-config.md
git commit -m "docs: add manual integration testing guide"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Configurable log level (Task 2)
- ✅ Hot reload via Nacos (Task 4)
- ✅ File output support (Task 2, `set_otel_log_level` attaches file handler)
- ✅ Backward compatible default INFO (Task 1)

**No placeholders:**
- ✅ All code blocks are complete
- ✅ All test cases are written
- ✅ All file paths are exact

**Type consistency:**
- ✅ `set_otel_log_level(level: str)` signature consistent across all tasks
- ✅ `otel_log_level: str = "INFO"` field name consistent
- ✅ `OTEL_LOGGER_NAMES` constant used correctly
