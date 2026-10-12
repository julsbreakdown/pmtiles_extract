from qgis.core import QgsProcessingProvider

from .algorithm import ExtractBaseAlgorithm, ExtractZonesAlgorithm


class MapterhornProvider(QgsProcessingProvider):
    def id(self):
        return "mapterhorn"

    def name(self):
        return "Mapterhorn"

    def loadAlgorithms(self):
        self.addAlgorithm(ExtractBaseAlgorithm())
        self.addAlgorithm(ExtractZonesAlgorithm())
