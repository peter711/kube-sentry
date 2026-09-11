import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter


SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "ai-agent-api")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.6.0")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() not in {"0", "false", "no"}

_INITIALIZED = False


def init_observability() -> None:
    global _INITIALIZED
    if _INITIALIZED or not OTEL_ENABLED:
        return

    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
            "deployment.environment.name": "local-k3d",
            "ai.lab.namespace": os.getenv("TARGET_NAMESPACE", "ai-lab"),
        }
    )

    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=OTLP_ENDPOINT,
                insecure=True,
            )
        )
    )
    trace.set_tracer_provider(trace_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=OTLP_ENDPOINT,
            insecure=True,
        ),
        export_interval_millis=5000,
    )
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=[metric_reader])
    )

    _INITIALIZED = True


init_observability()

tracer = trace.get_tracer("ai-k8s-lab", SERVICE_VERSION)
meter = metrics.get_meter("ai-k8s-lab", SERVICE_VERSION)

REQUESTS = meter.create_counter(
    "ai_agent_requests",
    unit="1",
    description="Agent API requests",
)
REQUEST_DURATION = meter.create_histogram(
    "ai_agent_request_duration_seconds",
    unit="s",
    description="Agent request duration",
)
TOOL_CALLS = meter.create_counter(
    "ai_agent_tool_calls",
    unit="1",
    description="Agent tool calls",
)
TOOL_DURATION = meter.create_histogram(
    "ai_agent_tool_duration_seconds",
    unit="s",
    description="Agent tool duration",
)
LLM_REQUESTS = meter.create_counter(
    "ai_agent_llm_requests",
    unit="1",
    description="OpenAI Responses API calls",
)
LLM_DURATION = meter.create_histogram(
    "ai_agent_llm_duration_seconds",
    unit="s",
    description="OpenAI Responses API latency",
)
LLM_TOKENS = meter.create_counter(
    "ai_agent_llm_tokens",
    unit="{token}",
    description="LLM tokens by direction",
)
PROPOSALS = meter.create_counter(
    "ai_agent_proposals",
    unit="1",
    description="Repair proposals created",
)
REPAIR_OPERATIONS = meter.create_counter(
    "ai_agent_repair_operations",
    unit="1",
    description="Repair operations by final status",
)
ROLLOUT_DURATION = meter.create_histogram(
    "ai_agent_rollout_duration_seconds",
    unit="s",
    description="Rollout verification duration",
)
ROLLBACKS = meter.create_counter(
    "ai_agent_rollbacks",
    unit="1",
    description="Rollback proposals created",
)


def _set_attributes(span: Any, attrs: dict[str, Any] | None) -> None:
    if not attrs:
        return
    for key, value in attrs.items():
        if value is not None:
            span.set_attribute(key, value)


@contextmanager
def observed_span(
    name: str,
    attrs: dict[str, Any] | None = None,
    context: Any | None = None,
) -> Iterator[tuple[Any, float]]:
    started = time.perf_counter()
    with tracer.start_as_current_span(name, context=context) as span:
        _set_attributes(span, attrs)
        try:
            yield span, started
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(
                Status(
                    StatusCode.ERROR,
                    f"{type(exc).__name__}: {exc}",
                )
            )
            raise


def elapsed_seconds(started: float) -> float:
    return max(0.0, time.perf_counter() - started)


def inject_current_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


def extract_context_from_env() -> Any:
    carrier: dict[str, str] = {}
    traceparent = os.getenv("TRACEPARENT")
    tracestate = os.getenv("TRACESTATE")
    if traceparent:
        carrier["traceparent"] = traceparent
    if tracestate:
        carrier["tracestate"] = tracestate
    return extract(carrier)


def current_trace_id() -> str | None:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def force_flush_observability(timeout_millis: int = 5000) -> None:
    """Best-effort flush for short-lived Kubernetes worker Jobs."""
    try:
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout_millis)
    except Exception:
        pass
    try:
        provider = metrics.get_meter_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout_millis)
    except Exception:
        pass
