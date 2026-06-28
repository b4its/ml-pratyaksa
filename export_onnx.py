import xgboost as xgb
import onnxmltools
# Gunakan FloatTensorType dari onnxmltools, BUKAN dari onnxconverter_common
from onnxmltools.convert.common.data_types import FloatTensorType
import joblib

print("Memuat XGBoost model...")
model = xgb.XGBClassifier()
model.load_model("artifacts/artifact_xgb_model.json")

print("Memuat scaler...")
scaler = joblib.load("artifacts/artifact_scaler.pkl")
n_features = scaler.n_features_in_
print(f"Jumlah fitur: {n_features}")

# Konversi dengan tipe data yang sesuai
initial_type = [('float_input', FloatTensorType([None, n_features]))]
onnx_model = onnxmltools.convert_xgboost(model, initial_types=initial_type)

# Simpan
output_path = "artifacts/artifact_xgb_model.onnx"
with open(output_path, "wb") as f:
    f.write(onnx_model.SerializeToString())

print(f"✅ ONNX model berhasil disimpan di {output_path}")