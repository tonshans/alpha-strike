"""Hermes Agent plugin for Alpha-Strike market analysis.

Hermes loads this module and calls ``register(ctx)`` once. The tools appear in
the ``alpha_strike`` toolset. Registration is intentionally cheap and does no
network or subprocess I/O; the actual engine calls happen only when the model
invokes a tool.
"""

from __future__ import annotations

from functools import partial

from . import schemas, tools

PLUGIN_NAME = "alpha-strike"
TOOLSET = "alpha_strike"


def register(ctx):
    """Wire Alpha-Strike schemas to their handlers."""
    registrations = (
        (
            schemas.ANALYZE_ASSET,
            tools.analyze_asset,
            "Analisis MTFA, filter rezim, dan rencana risiko Alpha-Strike untuk satu aset.",
        ),
        (
            schemas.SCAN_MARKET,
            tools.scan_market,
            "Pindai pasar untuk kandidat BB Squeeze + Volume Spike.",
        ),
        (
            schemas.MONITOR_POSITION,
            tools.monitor_position,
            "Pantau posisi long: auto-breakeven, trailing stop, dan target TP2.",
        ),
    )

    for schema, handler, description in registrations:
        ctx.register_tool(
            name=schema["name"],
            toolset=TOOLSET,
            schema=schema,
            handler=partial(handler, ctx),
            description=description,
            emoji="📈",
        )
