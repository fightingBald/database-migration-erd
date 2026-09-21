"""Supported D2 engines and their explicit, isolated render settings."""

from .d2_styles import COMPONENT_PADDING

LAYOUT_ENGINES = ("elk", "tala")


def validate_layout_engine(engine: str) -> None:
    if engine not in LAYOUT_ENGINES:
        raise ValueError("D2 layout engine must be elk or tala")


def engine_flags(engine: str) -> tuple[str, ...]:
    validate_layout_engine(engine)
    if engine == "tala":
        # Use the plugin's documented defaults without ambient TALA_* overrides.
        return ("--tala-seeds=1,2,3",)
    return (
        "--elk-nodeSelfLoop=100",
        "--elk-nodeNodeBetweenLayers=50",
        "--elk-edgeNodeBetweenLayers=25",
        f"--elk-padding=[top={COMPONENT_PADDING},left={COMPONENT_PADDING},"
        f"bottom={COMPONENT_PADDING},right={COMPONENT_PADDING}]",
    )
