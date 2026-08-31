"""
Relations & joins handlers — project relations, vector layer joins.
"""

from qgis.core import (
    Qgis,
    QgsProject,
    QgsRelation,
    QgsVectorLayerJoinInfo,
)


def register(server):
    """Register relation and join handlers."""
    s = server

    def list_relations(**_):
        """List all project relations with their properties."""
        manager = QgsProject.instance().relationManager()
        result = []
        for rel_id, rel in manager.relations().items():
            result.append({
                "id": rel.id(),
                "name": rel.name(),
                "referencing_layer": rel.referencingLayer().id() if rel.referencingLayer() else None,
                "referencing_layer_name": rel.referencingLayer().name() if rel.referencingLayer() else None,
                "referenced_layer": rel.referencedLayer().id() if rel.referencedLayer() else None,
                "referenced_layer_name": rel.referencedLayer().name() if rel.referencedLayer() else None,
                "field_pairs": [
                    {"referencing": pair.referencingColumn(),
                     "referenced": pair.referencedColumn()}
                    for pair in rel.fieldPairs()
                ] if hasattr(rel, 'fieldPairs') else [],
                "valid": rel.isValid(),
                "strength": str(rel.strength()),
            })
        return result

    def add_relation(name: str, referencing_layer_id: str, referenced_layer_id: str,
                     referencing_field: str, referenced_field: str,
                     relation_id: str = None, strength: str = "association", **_):
        """Create a project relation between two layers.

        referencing_layer_id: child layer (has the foreign key).
        referenced_layer_id: parent layer (has the primary key).
        referencing_field: foreign key field in the child layer.
        referenced_field: primary key field in the parent layer.
        strength: 'association' or 'composition'.
        """
        project = QgsProject.instance()
        ref_layer = s.get_layer_or_raise(referencing_layer_id)
        refd_layer = s.get_layer_or_raise(referenced_layer_id)

        if ref_layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Referencing layer is not a vector layer: {referencing_layer_id}")
        if refd_layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Referenced layer is not a vector layer: {referenced_layer_id}")

        rel = QgsRelation()
        rel_id = relation_id or f"{ref_layer.name()}_{refd_layer.name()}_{referencing_field}"
        rel.setId(rel_id)
        rel.setName(name)
        rel.setReferencingLayer(referencing_layer_id)
        rel.setReferencedLayer(referenced_layer_id)
        rel.addFieldPair(referencing_field, referenced_field)

        strength_map = {
            "association": QgsRelation.RelationStrength.Association,
            "composition": QgsRelation.RelationStrength.Composition,
        }
        rel_strength = strength_map.get(strength.lower(), QgsRelation.RelationStrength.Association)
        rel.setStrength(rel_strength)

        if not rel.isValid():
            raise RuntimeError(
                f"Invalid relation: check that fields '{referencing_field}' and "
                f"'{referenced_field}' exist on the respective layers"
            )

        project.relationManager().addRelation(rel)
        return {
            "id": rel.id(),
            "name": rel.name(),
            "referencing_layer": referencing_layer_id,
            "referenced_layer": referenced_layer_id,
            "valid": rel.isValid(),
        }

    def remove_relation(relation_id: str, **_):
        """Remove a project relation by its ID."""
        manager = QgsProject.instance().relationManager()
        rel = manager.relation(relation_id)
        if not rel.isValid():
            raise RuntimeError(f"Relation not found: {relation_id}")
        manager.removeRelation(relation_id)
        return {"removed": relation_id}

    def list_layer_joins(layer_id: str, **_):
        """List all joins configured on a vector layer."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        joins = []
        for join in layer.vectorJoins():
            joins.append({
                "join_layer_id": join.joinLayerId(),
                "join_layer_name": join.joinLayer().name() if join.joinLayer() else None,
                "join_field": join.joinFieldName(),
                "target_field": join.targetFieldName(),
                "prefix": join.prefix(),
                "editable": join.isEditable(),
                "upsert": join.hasUpsertOnEdit(),
                "cached": join.isUsingMemoryCache(),
            })
        return {"layer_id": layer_id, "joins": joins}

    def add_layer_join(layer_id: str, join_layer_id: str,
                       join_field: str, target_field: str,
                       prefix: str = None, editable: bool = False,
                       cached: bool = True, fields_subset: list = None, **_):
        """Join another layer to a vector layer by matching field values.

        layer_id: target layer to add the join to.
        join_layer_id: source layer providing the joined attributes.
        join_field: field name in the join layer.
        target_field: field name in the target layer.
        prefix: optional prefix for joined field names.
        fields_subset: optional list of field names to include from the join layer.
        """
        layer = s.get_layer_or_raise(layer_id)
        join_layer = s.get_layer_or_raise(join_layer_id)

        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")
        if join_layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Join layer is not a vector layer: {join_layer_id}")

        join_info = QgsVectorLayerJoinInfo()
        join_info.setJoinLayerId(join_layer_id)
        join_info.setJoinFieldName(join_field)
        join_info.setTargetFieldName(target_field)
        join_info.setUsingMemoryCache(cached)
        join_info.setEditable(editable)

        if prefix is not None:
            join_info.setPrefix(prefix)

        if fields_subset:
            join_info.setJoinFieldNamesSubset(fields_subset)

        if not layer.addJoin(join_info):
            raise RuntimeError(
                f"Failed to add join from {join_layer_id} to {layer_id}"
            )

        return {
            "layer_id": layer_id,
            "join_layer_id": join_layer_id,
            "join_field": join_field,
            "target_field": target_field,
        }

    def remove_layer_join(layer_id: str, join_layer_id: str, **_):
        """Remove a join from a vector layer by the join layer ID."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Vector:
            raise RuntimeError(f"Not a vector layer: {layer_id}")

        if not layer.removeJoin(join_layer_id):
            raise RuntimeError(
                f"Failed to remove join for join layer: {join_layer_id}"
            )
        return {"layer_id": layer_id, "removed_join_layer": join_layer_id}

    s._HANDLERS.update({
        "list_relations": list_relations,
        "add_relation": add_relation,
        "remove_relation": remove_relation,
        "list_layer_joins": list_layer_joins,
        "add_layer_join": add_layer_join,
        "remove_layer_join": remove_layer_join,
    })
