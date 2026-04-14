"""
Project management handlers — ping, info, load, create, save, variables.
"""

import os

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsExpressionContextUtils,
    QgsProject,
)
from qgis.utils import active_plugins


def register(server):
    """Register project handlers."""
    s = server

    def ping(**_):
        """Basic connectivity check. Returns pong if server is alive."""
        return {"pong": True}

    def get_qgis_info(**_):
        """Return QGIS version, Qt version, profile path, and plugin count."""
        return {
            "qgis_version": Qgis.version(),
            "qt_version": "6",
            "profile_folder": QgsApplication.qgisSettingsDirPath(),
            "plugins": list(active_plugins),
            "plugins_count": len(active_plugins),
        }

    def get_project_info(**_):
        """Return project filename, title, CRS, layers summary, and variables."""
        project = QgsProject.instance()
        layers_info = []
        for layer in list(project.mapLayers().values()):
            tree_node = project.layerTreeRoot().findLayer(layer.id())
            layers_info.append({
                "id": layer.id(),
                "name": layer.name(),
                "type": s.layer_type_str(layer),
                "visible": tree_node.isVisible() if tree_node else False,
            })
        # Project variables
        scope = QgsExpressionContextUtils.projectScope(project)
        variables = {name: scope.variable(name) for name in scope.variableNames()}
        return {
            "filename": project.fileName(),
            "title": project.title(),
            "crs": project.crs().authid(),
            "layer_count": len(project.mapLayers()),
            "layers": layers_info,
            "variables": variables,
        }

    def load_project(path: str, **_):
        """Load a .qgs or .qgz project file from the given path."""
        project = QgsProject.instance()
        if not project.read(path):
            raise RuntimeError(f"Failed to load project: {path}")
        s.iface.mapCanvas().refresh()
        return {"loaded": path, "layer_count": len(project.mapLayers())}

    def create_new_project(path: str, **_):
        """Create a new empty project and save it to the given path."""
        project = QgsProject.instance()
        if project.fileName():
            project.clear()
        project.setFileName(path)
        s.iface.mapCanvas().refresh()
        if not project.write():
            raise RuntimeError(f"Failed to save new project: {path}")
        return {"created": path, "layer_count": 0}

    def save_project(path: str = None, **_):
        """Save the project to the current path or a new path."""
        project = QgsProject.instance()
        save_path = path or project.fileName()
        if not save_path:
            raise RuntimeError("No project path specified")
        if not project.write(save_path):
            raise RuntimeError(f"Failed to save: {save_path}")
        return {"saved": save_path}

    def get_project_variables(**_):
        """List all project-level variables (key/value pairs)."""
        project = QgsProject.instance()
        scope = QgsExpressionContextUtils.projectScope(project)
        variables = {}
        for name in scope.variableNames():
            val = scope.variable(name)
            if not isinstance(val, (str, int, float, bool, type(None))):
                val = str(val)
            variables[name] = val
        return {"variables": variables}

    def set_project_variable(name: str, value: str, **_):
        """Set a project-level variable."""
        project = QgsProject.instance()
        QgsExpressionContextUtils.setProjectVariable(project, name, value)
        return {"name": name, "value": value}

    s._HANDLERS.update({
        "ping": ping,
        "get_qgis_info": get_qgis_info,
        "get_project_info": get_project_info,
        "load_project": load_project,
        "create_new_project": create_new_project,
        "save_project": save_project,
        "get_project_variables": get_project_variables,
        "set_project_variable": set_project_variable,
    })
