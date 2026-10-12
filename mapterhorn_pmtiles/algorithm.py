import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputMultipleLayers,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingUtils,
)

from .compat import INTEGER, NUMERIC_FIELD, POLYGON
from .mapterhorn_extract import (
    ExtractCancelled,
    ExtractError,
    PmtilesNotFound,
    extract_base,
    extract_zone,
    load_index,
    plan_zone,
    zones_from_geojson,
)


class _MapterhornAlgorithm(QgsProcessingAlgorithm):
    PMTILES_BIN = "PMTILES_BIN"
    THREADS = "THREADS"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_FILES = "OUTPUT_FILES"

    def createInstance(self):
        return type(self)()

    def _add_common_parameters(self):
        self.addParameter(
            QgsProcessingParameterFile(
                self.PMTILES_BIN,
                "pmtiles binary (empty: use PATH)",
                optional=True,
                # The default "*.*" filter rejects extensionless binaries such as pmtiles.
                fileFilter="All files (*)",
            )
        )
        self.addParameter(QgsProcessingParameterNumber(self.THREADS, "Download threads", INTEGER, 16, False, 1, 64))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, "Output folder"))
        self.addOutput(QgsProcessingOutputMultipleLayers(self.OUTPUT_FILES, "Extracted PMTiles"))

    def _options(self, parameters, context, feedback):
        return {
            "binary": self.parameterAsFile(parameters, self.PMTILES_BIN, context) or None,
            "threads": self.parameterAsInt(parameters, self.THREADS, context),
            "should_stop": feedback.isCanceled,
        }

    def _run(self, parameters, context, extract):
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))
        try:
            outputs = [str(path) for path in extract(output_dir)]
        except ExtractCancelled as error:
            raise QgsProcessingException("Cancelled.") from error
        except (PmtilesNotFound, ExtractError, ValueError, OSError) as error:
            raise QgsProcessingException(str(error)) from error
        return {self.OUTPUT_DIR: str(output_dir), self.OUTPUT_FILES: outputs}


class ExtractBaseAlgorithm(_MapterhornAlgorithm):
    EXTENT = "EXTENT"

    def name(self):
        return "extract_base"

    def displayName(self):
        return "Extract Mapterhorn base PMTiles (zooms 0-12)"

    def shortHelpString(self):
        return (
            "Produces one PMTiles with zooms 0 to 12, cut from the Mapterhorn planet archive over France, "
            "or over the extent when set. Covering France is a large download. "
            "Requires the pmtiles binary (go-pmtiles 1.31+), from the parameter or the PATH."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Extent (empty: France)", optional=True))
        self._add_common_parameters()

    def processAlgorithm(self, parameters, context, feedback):
        options = self._options(parameters, context, feedback)
        bbox = None
        if parameters.get(self.EXTENT):
            extent = self.parameterAsExtent(parameters, self.EXTENT, context, QgsCoordinateReferenceSystem("EPSG:4326"))
            bbox = (extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum())
        feedback.pushInfo("Base file: zooms 0-12 over " + ("the extent" if bbox else "France"))
        return self._run(parameters, context, lambda output_dir: [extract_base(output_dir, bbox=bbox, **options)])


class ExtractZonesAlgorithm(_MapterhornAlgorithm):
    INPUT = "INPUT"
    NAME_FIELD = "NAME_FIELD"
    MAXZOOM_FIELD = "MAXZOOM_FIELD"
    MAXZOOM = "MAXZOOM"
    SAME_ZOOM = "SAME_ZOOM"

    def name(self):
        return "extract_zones"

    def displayName(self):
        return "Extract Mapterhorn PMTiles per zone (zooms 13+)"

    def shortHelpString(self):
        return (
            "Each polygon of the input layer is a zone. Produces one PMTiles per zone from zoom 13 to the "
            "zone's max zoom, capped by what Mapterhorn provides there. The zone max zoom comes from the max "
            "zoom field, or the default max zoom when the field is empty or 'same max zoom for all zones' is "
            "checked. Zooms 0 to 12 come from the base algorithm. "
            "Requires the pmtiles binary (go-pmtiles 1.31+), from the parameter or the PATH."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT, "Zones (polygon layer)", [POLYGON]))
        self.addParameter(
            QgsProcessingParameterField(self.NAME_FIELD, "Zone name field", parentLayerParameterName=self.INPUT, optional=True)
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.MAXZOOM_FIELD,
                "Zone max zoom field",
                parentLayerParameterName=self.INPUT,
                type=NUMERIC_FIELD,
                optional=True,
            )
        )
        self.addParameter(QgsProcessingParameterNumber(self.MAXZOOM, "Default max zoom", INTEGER, 15, False, 13, 22))
        self.addParameter(QgsProcessingParameterBoolean(self.SAME_ZOOM, "Same max zoom for all zones", False))
        self._add_common_parameters()

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        name_field = self.parameterAsString(parameters, self.NAME_FIELD, context)
        zoom_field = self.parameterAsString(parameters, self.MAXZOOM_FIELD, context)
        maxzoom = self.parameterAsInt(parameters, self.MAXZOOM, context)
        same_zoom = self.parameterAsBoolean(parameters, self.SAME_ZOOM, context)
        options = self._options(parameters, context, feedback)

        work_dir = Path(QgsProcessingUtils.generateTempFilename("mapterhorn_zones"))
        work_dir.mkdir(parents=True)
        zones_path = work_dir / "input.geojson"
        _write_zones(source, context, zones_path, name_field, zoom_field)
        try:
            zones = zones_from_geojson(zones_path, maxzoom, work_dir, same_zoom=same_zoom)
            options["archives"] = load_index()
        except (ValueError, OSError) as error:
            raise QgsProcessingException(str(error)) from error

        covered = []
        for zone in zones:
            if plan_zone(zone, options["archives"]):
                covered.append(zone)
            else:
                feedback.reportError(f"Zone {zone.name}: no Mapterhorn archive above zoom 12, skipped.")
        if not covered:
            raise QgsProcessingException("No zone is covered by Mapterhorn above zoom 12.")

        def extract(output_dir):
            for done, zone in enumerate(covered):
                feedback.pushInfo(f"Zone {zone.name}: zooms 13-{zone.maxzoom}")
                yield extract_zone(zone, output_dir, **options)
                feedback.setProgress(100 * (done + 1) / len(covered))

        return self._run(parameters, context, extract)


def _write_zones(source, context, path, name_field, zoom_field):
    transform = QgsCoordinateTransform(
        source.sourceCrs(), QgsCoordinateReferenceSystem("EPSG:4326"), context.transformContext()
    )
    features = []
    for feature in source.getFeatures():
        geometry = feature.geometry()
        if geometry.isEmpty():
            continue
        geometry.transform(transform)
        properties = {
            "name": _value(feature, name_field),
            "maxzoom": _value(feature, zoom_field),
        }
        features.append({"type": "Feature", "properties": properties, "geometry": json.loads(geometry.asJson())})
    if not features:
        raise QgsProcessingException("The zones layer has no polygon to extract.")
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def _value(feature, field):
    if not field:
        return None
    value = feature[field]
    # NULL attributes come back as a null QVariant on some QGIS/PyQt builds.
    if value is None or (hasattr(value, "isNull") and value.isNull()):
        return None
    return value if isinstance(value, (int, float)) else str(value)
