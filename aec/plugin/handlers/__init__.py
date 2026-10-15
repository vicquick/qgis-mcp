"""
Handler registration — imports all handler modules and registers them with the server.
"""

from . import (
    analysis,
    bookmarks,
    canvas,
    code,
    database,
    export,
    features,
    geoprocessing,
    history,
    jobs,
    labeling,
    layers,
    layouts,
    processing_tools,
    project,
    quality,
    raster,
    relations,
    settings,
    sketching,
    styling,
    validation,
)

_MODULES = [
    project,
    layers,
    features,
    canvas,
    styling,
    labeling,
    layouts,
    database,
    processing_tools,
    analysis,
    bookmarks,
    sketching,
    history,
    settings,
    code,
    relations,
    raster,
    validation,
    export,
    geoprocessing,
    jobs,
    quality,
]


def register_all_handlers(server):
    """Register all handler functions from every module onto the server."""
    for module in _MODULES:
        module.register(server)
