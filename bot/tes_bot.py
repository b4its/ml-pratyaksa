# import os
# import redis
# 
# # Koneksi ke Redis lokal
# REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
# 
# # Inisialisasi client Redis
# r = redis.from_url(REDIS_URL, decode_responses=True)
# 
# # Kirim data dummy ke Stream
# r.xadd("stream:alerts", {
#     "asset_id": "EXCA-001",
#     "model": "Komatsu PC2000",
#     "lokasi": "Pit Roto Barat",
#     "status": "CRITICAL",
#     "rul": "12.4",
#     "shap1": "Tekanan Hidrolik Turun",
#     "shap2": "Suhu Oli Naik",
#     "part_name": "Hydraulic Seal",
#     "part_no": "7X-2741",
#     "stok": "4"
# })
# 
# print("Data dikirim ke Redis!")
