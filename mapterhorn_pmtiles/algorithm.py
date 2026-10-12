import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputMultipleLayers,
    QgsProcessingParameterBoolean,
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


class ExtractMapterhornAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    NAME_FIELD = "NAME_FIELD"
    MAXZOOM_FIELD = "MAXZOOM_FIELD"
    MAXZOOM = "MAXZOOM"
    SAME_ZOOM = "SAME_ZOOM"
    PMTILES_BIN = "PMTILES_BIN"
    THREADS = "THREADS"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_FILES = "OUTPUT_FILES"

    def name(self):
        return "extract"

    def displayName(self):
        return "Extract Mapterhorn PMTiles per zone"

    def shortHelpString(self):
        return (
            "Each polygon of the input layer is a zone. Produces one base PMTiles with zooms 0 to 12 "
            "over all zones, and one PMTiles per zone from zoom 13 to the zone's max zoom, capped by "
            "what Mapterhorn provides there. The zone max zoom comes from the max zoom field, or the "
            "default max zoom when the field is empty or 'same max zoom for all zones' is checked. "
            "Requires the pmtiles binary (go-pmtiles 1.31+), from the parameter or the PATH."
        )

    def createInstance(self):
        return ExtractMapterhornAlgorithm()

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

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        name_field = self.parameterAsString(parameters, self.NAME_FIELD, context)
        zoom_field = self.parameterAsString(parameters, self.MAXZOOM_FIELD, context)
        maxzoom = self.parameterAsInt(parameters, self.MAXZOOM, context)
        same_zoom = self.parameterAsBoolean(parameters, self.SAME_ZOOM, context)
        options = {
            "binary": self.parameterAsFile(parameters, self.PMTILES_BIN, context) or None,
            "threads": self.parameterAsInt(parameters, self.THREADS, context),
            "should_stop": feedback.isCanceled,
        }
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))

        work_dir = Path(QgsProcessingUtils.generateTempFilename("mapterhorn_zones"))
        work_dir.mkdir(parents=True)
        zones_path = work_dir / "input.geojson"
        _write_zones(source, context, zones_path, name_field, zoom_field)
        try:
            all_zones, zones = zones_from_geojson(zones_path, maxzoom, work_dir, same_zoom=same_zoom)
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

        outputs = []
        steps = len(covered) + 1
        try:
            feedback.pushInfo("Base file: zooms 0-12 over all zones")
            base = extract_base(all_zones, output_dir, **options)
            if base is not None:
                outputs.append(str(base))
            feedback.setProgress(100 / steps)
            for done, zone in enumerate(covered, start=2):
                feedback.pushInfo(f"Zone {zone.name}: zooms 13-{zone.maxzoom}")
                outputs.append(str(extract_zone(zone, output_dir, **options)))
                feedback.setProgress(100 * done / steps)
        except ExtractCancelled as error:
            raise QgsProcessingException("Cancelled.") from error
        except (PmtilesNotFound, ExtractError) as error:
            raise QgsProcessingException(str(error)) from error
        return {self.OUTPUT_DIR: str(output_dir), self.OUTPUT_FILES: outputs}


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
