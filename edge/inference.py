from .preprocessor import EdgePreprocessor
from .risk_resolver import RiskResolver

class EdgeInference:
    def __init__(self):
        self.preprocessor = EdgePreprocessor()
        self.resolver = RiskResolver()

    def predict(self, sensor_data: dict):
        feat = self.preprocessor.transform(sensor_data)
        risk, twin_state = self.resolver.resolve(feat)
        return risk, twin_state