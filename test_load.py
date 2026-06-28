# test_load.py
from keras.saving import load_model
# 1. Import kelas dari app.py agar Keras bisa membacanya
from api.app import PRATYAKSAExpert 

model_path = "artifacts/artifact_lstm_excavator.keras" 

try:
    print(f"Mencoba memuat model: {model_path}")
    
    # 2. Load model dengan menyertakan custom_objects
    model = load_model(
        model_path, 
        custom_objects={"PRATYAKSAExpert": PRATYAKSAExpert},
        compile=False
    )
    print("✅ Berhasil! Keras 3 native loader kompatibel dengan artifact Anda.")
except Exception as e:
    print(f"❌ Gagal memuat model:\n{e}")