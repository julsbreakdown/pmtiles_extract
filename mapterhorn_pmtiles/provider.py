from qgis.core import QgsProcessingProvider

from .algorithm import ExtractMapterhornAlgorithm


class MapterhornProvider(QgsProcessingProvider):
    def id(self):
        return "mapterhorn"

    def name(self):
        return "Mapterhorn"

    def loadAlgorithms(self):
        self.addAlgorithm(ExtractMapterhornAlgorithm())
