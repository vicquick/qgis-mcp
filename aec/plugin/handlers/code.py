"""
Code execution handler — execute arbitrary PyQGIS code with comprehensive namespace.
"""

import io
import sys
import traceback

# Core
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProject,
    # Layers
    QgsVectorLayer,
    QgsRasterLayer,
    QgsMapLayer,
    QgsMeshLayer,
    QgsPointCloudLayer,
    QgsAnnotationLayer,
    QgsVectorTileLayer,
    QgsGroupLayer,
    # Data
    QgsVectorDataProvider,
    QgsRasterDataProvider,
    QgsDataSourceUri,
    QgsProviderRegistry,
    # Features
    QgsFeature,
    QgsFeatureRequest,
    QgsVectorLayerEditUtils,
    QgsVectorLayerUtils,
    # Fields
    QgsField,
    QgsFields,
    QgsFieldConstraints,
    QgsDefaultValue,
    # Geometry
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsWkbTypes,
    QgsCircle,
    QgsEllipse,
    QgsTriangle,
    QgsLineString,
    QgsPolygon,
    QgsMultiPoint,
    QgsMultiLineString,
    QgsMultiPolygon,
    # CRS
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateFormatter,
    # Rendering
    QgsMapSettings,
    QgsMapRendererParallelJob,
    QgsRenderContext,
    # Symbology
    QgsSymbol,
    QgsMarkerSymbol,
    QgsLineSymbol,
    QgsFillSymbol,
    QgsSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleFillSymbolLayer,
    QgsSvgMarkerSymbolLayer,
    QgsArrowSymbolLayer,
    # Renderers
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer,
    QgsRuleBasedRenderer,
    QgsHeatmapRenderer,
    QgsPointDisplacementRenderer,
    QgsPointClusterRenderer,
    QgsInvertedPolygonRenderer,
    Qgs25DRenderer,
    QgsRendererRange,
    QgsRendererCategory,
    # Color ramps
    QgsGradientColorRamp,
    QgsColorBrewerColorRamp,
    QgsRandomColorRamp,
    QgsPresetSchemeColorRamp,
    QgsLimitedRandomColorRamp,
    # Labeling
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsRuleBasedLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsTextShadowSettings,
    QgsTextBackgroundSettings,
    # Diagrams
    QgsDiagramSettings,
    QgsDiagramLayerSettings,
    QgsLinearlyInterpolatedDiagramRenderer,
    QgsSingleCategoryDiagramRenderer,
    # Effects
    QgsEffectStack,
    QgsBlurEffect,
    QgsShadowEffect,
    QgsGlowEffect,
    QgsTransformEffect,
    QgsColorEffect,
    # Layouts
    QgsPrintLayout,
    QgsLayoutManager,
    QgsLayoutExporter,
    QgsLayoutItemMap,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemScaleBar,
    QgsLayoutItemPicture,
    QgsLayoutItemShape,
    QgsLayoutItemPage,
    QgsLayoutItemPolyline,
    QgsLayoutItemPolygon,
    QgsLayoutItemGroup,
    QgsLayoutItemHtml,
    QgsLayoutItemAttributeTable,
    QgsLayoutItemTextTable,
    QgsLayoutItemManualTable,
    QgsLayoutItemMarker,
    QgsLayoutAtlas,
    QgsLayoutSize,
    QgsLayoutPoint,
    QgsUnitTypes,
    QgsLayoutMeasurement,
    # Annotations
    QgsAnnotationItem,
    QgsAnnotationLineItem,
    QgsAnnotationMarkerItem,
    QgsAnnotationPolygonItem,
    QgsAnnotationPointTextItem,
    # Expressions
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    # Data-defined
    QgsProperty,
    QgsPropertyDefinition,
    QgsPropertyCollection,
    # Bookmarks
    QgsBookmark,
    QgsBookmarkManager,
    # Relations
    QgsRelation,
    QgsRelationManager,
    # Classification
    QgsClassificationEqualInterval,
    QgsClassificationJenks,
    QgsClassificationPrettyBreaks,
    QgsClassificationQuantile,
    QgsClassificationStandardDeviation,
    # File I/O
    QgsVectorFileWriter,
    QgsRasterFileWriter,
    # Snapping
    QgsSnappingConfig,
    QgsSnappingUtils,
    # Style
    QgsStyle,
    # Settings
    QgsSettings,
    # Auth
    QgsAuthManager,
    # Metadata
    QgsLayerMetadata,
    QgsProjectMetadata,
)

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtCore import QSize, QSizeF, QPointF, QRectF


def register(server):
    """Register code execution handler."""
    s = server

    def execute_code(code: str, **_):
        """Execute arbitrary PyQGIS code with a comprehensive namespace.

        The namespace includes all major QGIS classes, processing module,
        the live iface, and canvas references. stdout/stderr are captured.
        """
        import processing

        stdout_cap = io.StringIO()
        stderr_cap = io.StringIO()
        orig_out, orig_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = stdout_cap, stderr_cap
            ns = {
                # Core
                "Qgis": Qgis,
                "QgsProject": QgsProject,
                "QgsApplication": QgsApplication,
                # Layers
                "QgsVectorLayer": QgsVectorLayer,
                "QgsRasterLayer": QgsRasterLayer,
                "QgsMapLayer": QgsMapLayer,
                "QgsMeshLayer": QgsMeshLayer,
                "QgsPointCloudLayer": QgsPointCloudLayer,
                "QgsAnnotationLayer": QgsAnnotationLayer,
                "QgsVectorTileLayer": QgsVectorTileLayer,
                "QgsGroupLayer": QgsGroupLayer,
                # Data
                "QgsVectorDataProvider": QgsVectorDataProvider,
                "QgsRasterDataProvider": QgsRasterDataProvider,
                "QgsDataSourceUri": QgsDataSourceUri,
                "QgsProviderRegistry": QgsProviderRegistry,
                # Features
                "QgsFeature": QgsFeature,
                "QgsFeatureRequest": QgsFeatureRequest,
                "QgsVectorLayerEditUtils": QgsVectorLayerEditUtils,
                "QgsVectorLayerUtils": QgsVectorLayerUtils,
                # Fields
                "QgsField": QgsField,
                "QgsFields": QgsFields,
                "QgsFieldConstraints": QgsFieldConstraints,
                "QgsDefaultValue": QgsDefaultValue,
                # Geometry
                "QgsGeometry": QgsGeometry,
                "QgsPointXY": QgsPointXY,
                "QgsRectangle": QgsRectangle,
                "QgsWkbTypes": QgsWkbTypes,
                "QgsCircle": QgsCircle,
                "QgsEllipse": QgsEllipse,
                "QgsTriangle": QgsTriangle,
                "QgsLineString": QgsLineString,
                "QgsPolygon": QgsPolygon,
                "QgsMultiPoint": QgsMultiPoint,
                "QgsMultiLineString": QgsMultiLineString,
                "QgsMultiPolygon": QgsMultiPolygon,
                # CRS
                "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem,
                "QgsCoordinateTransform": QgsCoordinateTransform,
                "QgsCoordinateFormatter": QgsCoordinateFormatter,
                # Rendering
                "QgsMapSettings": QgsMapSettings,
                "QgsMapRendererParallelJob": QgsMapRendererParallelJob,
                "QgsRenderContext": QgsRenderContext,
                # Symbology
                "QgsSymbol": QgsSymbol,
                "QgsMarkerSymbol": QgsMarkerSymbol,
                "QgsLineSymbol": QgsLineSymbol,
                "QgsFillSymbol": QgsFillSymbol,
                "QgsSymbolLayer": QgsSymbolLayer,
                "QgsSimpleMarkerSymbolLayer": QgsSimpleMarkerSymbolLayer,
                "QgsSimpleLineSymbolLayer": QgsSimpleLineSymbolLayer,
                "QgsSimpleFillSymbolLayer": QgsSimpleFillSymbolLayer,
                "QgsSvgMarkerSymbolLayer": QgsSvgMarkerSymbolLayer,
                "QgsArrowSymbolLayer": QgsArrowSymbolLayer,
                # Renderers
                "QgsSingleSymbolRenderer": QgsSingleSymbolRenderer,
                "QgsCategorizedSymbolRenderer": QgsCategorizedSymbolRenderer,
                "QgsGraduatedSymbolRenderer": QgsGraduatedSymbolRenderer,
                "QgsRuleBasedRenderer": QgsRuleBasedRenderer,
                "QgsHeatmapRenderer": QgsHeatmapRenderer,
                "QgsPointDisplacementRenderer": QgsPointDisplacementRenderer,
                "QgsPointClusterRenderer": QgsPointClusterRenderer,
                "QgsInvertedPolygonRenderer": QgsInvertedPolygonRenderer,
                "Qgs25DRenderer": Qgs25DRenderer,
                "QgsRendererRange": QgsRendererRange,
                "QgsRendererCategory": QgsRendererCategory,
                # Color ramps
                "QgsGradientColorRamp": QgsGradientColorRamp,
                "QgsColorBrewerColorRamp": QgsColorBrewerColorRamp,
                "QgsRandomColorRamp": QgsRandomColorRamp,
                "QgsPresetSchemeColorRamp": QgsPresetSchemeColorRamp,
                "QgsLimitedRandomColorRamp": QgsLimitedRandomColorRamp,
                # Labeling
                "QgsPalLayerSettings": QgsPalLayerSettings,
                "QgsVectorLayerSimpleLabeling": QgsVectorLayerSimpleLabeling,
                "QgsRuleBasedLabeling": QgsRuleBasedLabeling,
                "QgsTextFormat": QgsTextFormat,
                "QgsTextBufferSettings": QgsTextBufferSettings,
                "QgsTextShadowSettings": QgsTextShadowSettings,
                "QgsTextBackgroundSettings": QgsTextBackgroundSettings,
                # Diagrams
                "QgsDiagramSettings": QgsDiagramSettings,
                "QgsDiagramLayerSettings": QgsDiagramLayerSettings,
                "QgsLinearlyInterpolatedDiagramRenderer": QgsLinearlyInterpolatedDiagramRenderer,
                "QgsSingleCategoryDiagramRenderer": QgsSingleCategoryDiagramRenderer,
                # Effects
                "QgsEffectStack": QgsEffectStack,
                "QgsBlurEffect": QgsBlurEffect,
                "QgsShadowEffect": QgsShadowEffect,
                "QgsGlowEffect": QgsGlowEffect,
                "QgsTransformEffect": QgsTransformEffect,
                "QgsColorEffect": QgsColorEffect,
                # Layouts
                "QgsPrintLayout": QgsPrintLayout,
                "QgsLayoutManager": QgsLayoutManager,
                "QgsLayoutExporter": QgsLayoutExporter,
                "QgsLayoutItemMap": QgsLayoutItemMap,
                "QgsLayoutItemLabel": QgsLayoutItemLabel,
                "QgsLayoutItemLegend": QgsLayoutItemLegend,
                "QgsLayoutItemScaleBar": QgsLayoutItemScaleBar,
                "QgsLayoutItemPicture": QgsLayoutItemPicture,
                "QgsLayoutItemShape": QgsLayoutItemShape,
                "QgsLayoutItemPage": QgsLayoutItemPage,
                "QgsLayoutItemPolyline": QgsLayoutItemPolyline,
                "QgsLayoutItemPolygon": QgsLayoutItemPolygon,
                "QgsLayoutItemGroup": QgsLayoutItemGroup,
                "QgsLayoutItemHtml": QgsLayoutItemHtml,
                "QgsLayoutItemAttributeTable": QgsLayoutItemAttributeTable,
                "QgsLayoutItemTextTable": QgsLayoutItemTextTable,
                "QgsLayoutItemManualTable": QgsLayoutItemManualTable,
                "QgsLayoutItemMarker": QgsLayoutItemMarker,
                "QgsLayoutAtlas": QgsLayoutAtlas,
                "QgsLayoutSize": QgsLayoutSize,
                "QgsLayoutPoint": QgsLayoutPoint,
                "QgsUnitTypes": QgsUnitTypes,
                "QgsLayoutMeasurement": QgsLayoutMeasurement,
                # Annotations
                "QgsAnnotationItem": QgsAnnotationItem,
                "QgsAnnotationLineItem": QgsAnnotationLineItem,
                "QgsAnnotationMarkerItem": QgsAnnotationMarkerItem,
                "QgsAnnotationPolygonItem": QgsAnnotationPolygonItem,
                "QgsAnnotationPointTextItem": QgsAnnotationPointTextItem,
                # Expressions
                "QgsExpression": QgsExpression,
                "QgsExpressionContext": QgsExpressionContext,
                "QgsExpressionContextScope": QgsExpressionContextScope,
                "QgsExpressionContextUtils": QgsExpressionContextUtils,
                # Data-defined
                "QgsProperty": QgsProperty,
                "QgsPropertyDefinition": QgsPropertyDefinition,
                "QgsPropertyCollection": QgsPropertyCollection,
                # Bookmarks
                "QgsBookmark": QgsBookmark,
                "QgsBookmarkManager": QgsBookmarkManager,
                # Relations
                "QgsRelation": QgsRelation,
                "QgsRelationManager": QgsRelationManager,
                # Classification
                "QgsClassificationEqualInterval": QgsClassificationEqualInterval,
                "QgsClassificationJenks": QgsClassificationJenks,
                "QgsClassificationPrettyBreaks": QgsClassificationPrettyBreaks,
                "QgsClassificationQuantile": QgsClassificationQuantile,
                "QgsClassificationStandardDeviation": QgsClassificationStandardDeviation,
                # File I/O
                "QgsVectorFileWriter": QgsVectorFileWriter,
                "QgsRasterFileWriter": QgsRasterFileWriter,
                # Snapping
                "QgsSnappingConfig": QgsSnappingConfig,
                "QgsSnappingUtils": QgsSnappingUtils,
                # Style
                "QgsStyle": QgsStyle,
                # Settings
                "QgsSettings": QgsSettings,
                # Auth
                "QgsAuthManager": QgsAuthManager,
                # Metadata
                "QgsLayerMetadata": QgsLayerMetadata,
                "QgsProjectMetadata": QgsProjectMetadata,
                # Qt types
                "QColor": QColor,
                "QSize": QSize,
                "QVariant": QVariant,
                "QFont": QFont,
                "QSizeF": QSizeF,
                "QPointF": QPointF,
                "QRectF": QRectF,
                # Processing
                "processing": processing,
                # Interface — live iface and canvas
                "iface": s.iface,
                "canvas": s.iface.mapCanvas(),
            }
            exec(code, ns)
            return {
                "executed": True,
                "stdout": stdout_cap.getvalue(),
                "stderr": stderr_cap.getvalue(),
            }
        except Exception as e:
            return {
                "executed": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "stdout": stdout_cap.getvalue(),
                "stderr": stderr_cap.getvalue(),
            }
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err

    s._HANDLERS.update({
        "execute_code": execute_code,
    })
