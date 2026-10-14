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
        """Basic connectivity check. Returns pong if server is alive, plus
        identity for telling QGIS instances apart when several run at once:
        pid, the bound port, and the open project's path/title."""
        project = QgsProject.instance()
        path = project.fileName()
        title = project.title() or (os.path.basename(path) if path else "")
        return {
            "pong": True,
            "pid": os.getpid(),
            "port": getattr(s, "port", None),
            "project_path": path,
            "project_title": title,
            # Lets the bridge tell a plugin with the result envelope and
            # get_context apart from an older one that is still loaded.
            "features": ["envelope", "get_context"],
        }

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

    # Providers whose featureCount() is a cheap local read. Anything else
    # (postgres, wfs, ...) may run a COUNT(*) or a network request, which has
    # no place in a call made on every turn.
    _CHEAP_COUNT = {"memory", "ogr", "spatialite", "delimitedtext"}

    def get_context(since: str = None, max_fields: int = 40, **_):
        """Compact picture of the project for an agent, in layer-tree order.

        Pass the `rev` of a previous answer as `since`: if nothing an agent
        relies on changed (see QgisMCPServer.context_rev), only
        {unchanged, rev} comes back instead of the whole picture.
        """
        rev = s.context_rev()
        if since and since == rev:
            return {"unchanged": True, "rev": rev}
        project = QgsProject.instance()
        layers = project.mapLayers()
        out = []
        for node in project.layerTreeRoot().findLayers():
            layer = layers.get(node.layerId())
            if layer is None:
                continue
            item = {
                "id": layer.id(),
                "name": layer.name(),
                "type": s.layer_type_str(layer),
                "visible": node.isVisible(),
                "crs": layer.crs().authid(),
            }
            if layer.type() == Qgis.LayerType.Vector:
                provider = layer.providerType()
                item["provider"] = provider
                if provider in _CHEAP_COUNT:
                    item["features"] = layer.featureCount()
                fields = layer.fields()
                item["fields"] = [f"{f.name()}:{f.typeName()}" for f in list(fields)[:max_fields]]
                if fields.count() > max_fields:
                    item["fields_more"] = fields.count() - max_fields
                if layer.subsetString():
                    item["filter"] = layer.subsetString()
                if layer.isEditable():
                    item["editing"] = True
                if layer.selectedFeatureCount():
                    item["selected"] = layer.selectedFeatureCount()
            out.append(item)
        ctx = {
            "rev": rev,
            "project": {
                "title": project.title(),
                "path": project.fileName(),
                "crs": project.crs().authid(),
                "dirty": project.isDirty(),
                "layouts": len(project.layoutManager().layouts()),
            },
            "layers": out,
        }
        try:
            canvas = s.iface.mapCanvas()
            ctx["canvas"] = {
                "scale": round(canvas.scale()),
                "extent": s.extent_to_dict(canvas.extent()),
                "crs": canvas.mapSettings().destinationCrs().authid(),
            }
            active = s.iface.activeLayer()
            if active is not None:
                ctx["active_layer"] = active.id()
        except Exception:
            pass  # headless / no iface: the project picture still stands
        return ctx

    s._HANDLERS.update({
        "get_context": get_context,
        "ping": ping,
        "get_qgis_info": get_qgis_info,
        "get_project_info": get_project_info,
        "load_project": load_project,
        "create_new_project": create_new_project,
        "save_project": save_project,
        "get_project_variables": get_project_variables,
        "set_project_variable": set_project_variable,
    })
