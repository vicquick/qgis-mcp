"""
Undo/redo handlers — undo, redo, inspect undo stack.
"""

from qgis.core import Qgis


def register(server):
    """Register history handlers."""
    s = server

    def undo(layer_id: str, **_):
        """Undo the last edit operation on a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if not layer.isEditable():
            layer.startEditing()

        undo_stack = layer.undoStack()
        if undo_stack.canUndo():
            undo_stack.undo()
            layer.triggerRepaint()
            return {"layer_id": layer_id, "undone": True, "can_undo": undo_stack.canUndo()}
        else:
            return {"layer_id": layer_id, "undone": False, "message": "Nothing to undo"}

    def redo(layer_id: str, **_):
        """Redo the last undone edit operation on a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if not layer.isEditable():
            layer.startEditing()

        undo_stack = layer.undoStack()
        if undo_stack.canRedo():
            undo_stack.redo()
            layer.triggerRepaint()
            return {"layer_id": layer_id, "redone": True, "can_redo": undo_stack.canRedo()}
        else:
            return {"layer_id": layer_id, "redone": False, "message": "Nothing to redo"}

    def get_undo_stack(layer_id: str, **_):
        """List undo/redo stack items for a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        undo_stack = layer.undoStack()
        current_index = undo_stack.index()
        count = undo_stack.count()

        items = []
        for i in range(count):
            items.append({
                "index": i,
                "text": undo_stack.text(i),
                "is_current": i == current_index,
            })

        return {
            "layer_id": layer_id,
            "is_editable": layer.isEditable(),
            "can_undo": undo_stack.canUndo(),
            "can_redo": undo_stack.canRedo(),
            "current_index": current_index,
            "stack_size": count,
            "items": items,
        }

    s._HANDLERS.update({
        "undo": undo,
        "redo": redo,
        "get_undo_stack": get_undo_stack,
    })
