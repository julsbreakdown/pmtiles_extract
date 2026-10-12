from qgis.core import Qgis, QgsProcessing, QgsProcessingParameterNumber

try:
    POLYGON = Qgis.ProcessingSourceType.VectorPolygon
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
except AttributeError:  # QGIS < 3.36
    POLYGON = QgsProcessing.TypeVectorPolygon
    INTEGER = QgsProcessingParameterNumber.Integer
