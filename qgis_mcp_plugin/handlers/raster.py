"""
Raster operations handlers — raster info, renderers, brightness/contrast, statistics.
"""

from qgis.core import (
    Qgis,
    QgsBrightnessContrastFilter,
    QgsColorRampShader,
    QgsHillshadeRenderer,
    QgsMultiBandColorRenderer,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterShader,
    QgsSingleBandGrayRenderer,
    QgsSingleBandPseudoColorRenderer,
    QgsStyle,
)
from qgis.PyQt.QtGui import QColor


def register(server):
    """Register raster handlers."""
    s = server

    def get_raster_info(layer_id: str, **_):
        """Get detailed raster layer info: bands, data types, statistics, nodata, pixel size."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Raster:
            raise RuntimeError(f"Not a raster layer: {layer_id}")

        dp = layer.dataProvider()
        bands = []
        for band in range(1, layer.bandCount() + 1):
            band_info = {
                "band": band,
                "name": dp.displayBandName(band),
                "data_type": str(dp.dataType(band)),
                "nodata": dp.sourceNoDataValue(band) if dp.sourceHasNoDataValue(band) else None,
            }
            # Get basic statistics
            stats = dp.bandStatistics(band, QgsRasterBandStats.Stats.All, layer.extent(), 0)
            band_info["statistics"] = {
                "min": stats.minimumValue,
                "max": stats.maximumValue,
                "mean": stats.mean,
                "stddev": stats.stdDev,
                "range": stats.range,
            }
            bands.append(band_info)

        renderer = layer.renderer()
        return {
            "layer_id": layer_id,
            "name": layer.name(),
            "width": layer.width(),
            "height": layer.height(),
            "band_count": layer.bandCount(),
            "crs": layer.crs().authid(),
            "extent": s.extent_to_dict(layer.extent()),
            "pixel_size_x": layer.rasterUnitsPerPixelX(),
            "pixel_size_y": layer.rasterUnitsPerPixelY(),
            "renderer_type": type(renderer).__name__ if renderer else None,
            "bands": bands,
        }

    def set_raster_renderer(layer_id: str, renderer_type: str,
                            band: int = 1,
                            color_ramp: str = "Spectral",
                            min_value: float = None, max_value: float = None,
                            classification_mode: str = "continuous",
                            red_band: int = 1, green_band: int = 2, blue_band: int = 3,
                            altitude: float = 45.0, azimuth: float = 315.0,
                            z_factor: float = 1.0, **_):
        """Set the raster renderer type.

        renderer_type: singleband_gray, singleband_pseudocolor, multiband, hillshade.
        For pseudocolor: band, color_ramp, min_value, max_value, classification_mode.
        For multiband: red_band, green_band, blue_band.
        For hillshade: altitude, azimuth, z_factor.
        classification_mode: 'continuous', 'equal_interval', 'quantile'.
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Raster:
            raise RuntimeError(f"Not a raster layer: {layer_id}")

        dp = layer.dataProvider()

        if renderer_type == "singleband_gray":
            renderer = QgsSingleBandGrayRenderer(dp, band)
            layer.setRenderer(renderer)

        elif renderer_type == "singleband_pseudocolor":
            # Get min/max from statistics if not provided
            if min_value is None or max_value is None:
                stats = dp.bandStatistics(band, QgsRasterBandStats.Stats.All, layer.extent(), 0)
                if min_value is None:
                    min_value = stats.minimumValue
                if max_value is None:
                    max_value = stats.maximumValue

            shader = QgsRasterShader()
            color_ramp_shader = QgsColorRampShader()

            # Set classification mode
            mode_map = {
                "continuous": QgsColorRampShader.ClassificationMode.Continuous,
                "equal_interval": QgsColorRampShader.ClassificationMode.EqualInterval,
                "quantile": QgsColorRampShader.ClassificationMode.Quantile,
            }
            cls_mode = mode_map.get(classification_mode, QgsColorRampShader.ClassificationMode.Continuous)
            color_ramp_shader.setClassificationMode(cls_mode)

            # Set color ramp type
            color_ramp_shader.setColorRampType(QgsColorRampShader.Type.Interpolated)

            # Get the color ramp from default styles
            style = QgsStyle.defaultStyle()
            ramp = style.colorRamp(color_ramp)
            if ramp:
                color_ramp_shader.setSourceColorRamp(ramp)
                color_ramp_shader.classifyColorRamp(
                    classes=5,
                    band=band,
                    extent=layer.extent(),
                    input=dp,
                )
            else:
                # Fallback: create simple min-max items
                color_ramp_shader.setColorRampItemList([
                    QgsColorRampShader.ColorRampItem(min_value, QColor(0, 0, 255), str(min_value)),
                    QgsColorRampShader.ColorRampItem(max_value, QColor(255, 0, 0), str(max_value)),
                ])

            color_ramp_shader.setMinimumValue(min_value)
            color_ramp_shader.setMaximumValue(max_value)
            shader.setRasterShaderFunction(color_ramp_shader)

            renderer = QgsSingleBandPseudoColorRenderer(dp, band, shader)
            layer.setRenderer(renderer)

        elif renderer_type == "multiband":
            renderer = QgsMultiBandColorRenderer(dp, red_band, green_band, blue_band)
            layer.setRenderer(renderer)

        elif renderer_type == "hillshade":
            renderer = QgsHillshadeRenderer(dp, band, azimuth, altitude)
            renderer.setZFactor(z_factor)
            layer.setRenderer(renderer)

        else:
            raise RuntimeError(
                f"Unknown renderer type: {renderer_type}. "
                "Use: singleband_gray, singleband_pseudocolor, multiband, hillshade"
            )

        layer.triggerRepaint()
        return {
            "layer_id": layer_id,
            "renderer_type": renderer_type,
        }

    def set_raster_brightness_contrast(layer_id: str, brightness: int = 0,
                                       contrast: int = 0, **_):
        """Set brightness and contrast on a raster layer.

        brightness: -255 to 255 (0 = no change).
        contrast: -100 to 100 (0 = no change).
        """
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Raster:
            raise RuntimeError(f"Not a raster layer: {layer_id}")

        brightness = max(-255, min(255, brightness))
        contrast = max(-100, min(100, contrast))

        bc_filter = layer.brightnessFilter()
        if bc_filter:
            bc_filter.setBrightness(brightness)
            bc_filter.setContrast(contrast)
        else:
            # Create and set a new brightness/contrast filter
            pipe = layer.pipe()
            bc = QgsBrightnessContrastFilter()
            bc.setBrightness(brightness)
            bc.setContrast(contrast)
            pipe.set(bc)

        layer.triggerRepaint()
        return {
            "layer_id": layer_id,
            "brightness": brightness,
            "contrast": contrast,
        }

    def get_raster_statistics(layer_id: str, band: int = 1, **_):
        """Get detailed statistics for a specific raster band."""
        layer = s.get_layer_or_raise(layer_id)
        if layer.type() != Qgis.LayerType.Raster:
            raise RuntimeError(f"Not a raster layer: {layer_id}")

        if band < 1 or band > layer.bandCount():
            raise RuntimeError(
                f"Invalid band number: {band}. Layer has {layer.bandCount()} bands."
            )

        dp = layer.dataProvider()
        stats = dp.bandStatistics(band, QgsRasterBandStats.Stats.All, layer.extent(), 0)

        return {
            "layer_id": layer_id,
            "band": band,
            "band_name": dp.displayBandName(band),
            "min": stats.minimumValue,
            "max": stats.maximumValue,
            "mean": stats.mean,
            "stddev": stats.stdDev,
            "range": stats.range,
            "sum": stats.sum,
            "element_count": stats.elementCount,
        }

    s._HANDLERS.update({
        "get_raster_info": get_raster_info,
        "set_raster_renderer": set_raster_renderer,
        "set_raster_brightness_contrast": set_raster_brightness_contrast,
        "get_raster_statistics": get_raster_statistics,
    })
