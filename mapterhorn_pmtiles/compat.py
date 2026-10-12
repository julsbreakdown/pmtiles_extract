from qgis.core import Qgis, QgsProcessing, QgsProcessingParameterField, QgsProcessingParameterNumber

try:
    POLYGON = Qgis.ProcessingSourceType.VectorPolygon
    INTEGER = Qgis.ProcessingNumberParameterType.Integer
    NUMERIC_FIELD = Qgis.ProcessingFieldParameterDataType.Numeric
except AttributeError:  # QGIS < 3.36
    POLYGON = QgsProcessing.TypeVectorPolygon
    INTEGER = QgsProcessingParameterNumber.Integer
    NUMERIC_FIELD = QgsProcessingParameterField.Numeric
