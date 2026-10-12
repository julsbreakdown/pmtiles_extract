import json
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputMultipleLayers,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingUtils,
)

from .compat import INTEGER, POLYGON
from .mapterhorn_extract import (
    ExtractCancelled,
    ExtractError,
    PmtilesNotFound,
    bbox_from_geojson,
    extract_one,
    plan,
)


class ExtractMapterhornAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    MAXZOOM = "MAXZOOM"
    PMTILES_BIN = "PMTILES_BIN"
    THREADS = "THREADS"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_FILES = "OUTPUT_FILES"

    def name(self):
        return "extract"

    def displayName(self):
        return "Extract Mapterhorn high-zoom PMTiles"

    def shortHelpString(self):
        return (
            "Extracts Mapterhorn terrain tiles from zoom 13 up to the chosen max zoom over the "
            "polygons of the input layer, one PMTiles per Mapterhorn z6 archive. Zooms 0 to 12 "
            "are not extracted. Each archive's own max zoom caps the requested one. Requires the "
            "pmtiles binary (go-pmtiles), from the parameter or the PATH."
        )

    def createInstance(self):
        return ExtractMapterhornAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(self.INPUT, "Area (polygon layer)", [POLYGON]))
        self.addParameter(QgsProcessingParameterNumber(self.MAXZOOM, "Max zoom", INTEGER, 15, False, 13, 18))
        self.addParameter(
            QgsProcessingParameterFile(self.PMTILES_BIN, "pmtiles binary (empty: use PATH)", optional=True)
        )
        self.addParameter(QgsProcessingParameterNumber(self.THREADS, "Download threads", INTEGER, 16, False, 1, 64))
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, "Output folder"))
        self.addOutput(QgsProcessingOutputMultipleLayers(self.OUTPUT_FILES, "Extracted PMTiles"))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))
        maxzoom = self.parameterAsInt(parameters, self.MAXZOOM, context)
        binary = self.parameterAsFile(parameters, self.PMTILES_BIN, context) or None
        threads = self.parameterAsInt(parameters, self.THREADS, context)
        output_dir = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))

        region = Path(QgsProcessingUtils.generateTempFilename("area.geojson"))
        _write_region(source, context, region)
        try:
            jobs = plan(bbox_from_geojson(region), maxzoom, region=region)
        except (ValueError, OSError) as error:
            raise QgsProcessingException(str(error)) from error
        if not jobs:
            raise QgsProcessingException("No Mapterhorn archive covers this area above zoom 12.")

        outputs = []
        for done, job in enumerate(jobs):
            feedback.pushInfo(f"{job.name}: z{job.minzoom}-{job.maxzoom} -> {job.output_name}")
            try:
                path = extract_one(job, output_dir, binary=binary, threads=threads, should_stop=feedback.isCanceled)
            except ExtractCancelled:
                break
            except (PmtilesNotFound, ExtractError) as error:
                raise QgsProcessingException(str(error)) from error
            outputs.append(str(path))
            feedback.setProgress(100 * (done + 1) / len(jobs))
        return {self.OUTPUT_DIR: str(output_dir), self.OUTPUT_FILES: outputs}


def _write_region(source, context, path):
    transform = QgsCoordinateTransform(
        source.sourceCrs(), QgsCoordinateReferenceSystem("EPSG:4326"), context.transformContext()
    )
    features = []
    for feature in source.getFeatures():
        geometry = feature.geometry()
        if geometry.isEmpty():
            continue
        geometry.transform(transform)
        features.append({"type": "Feature", "properties": {}, "geometry": json.loads(geometry.asJson())})
    if not features:
        raise QgsProcessingException("The area layer has no polygon to extract.")
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
