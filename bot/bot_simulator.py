# """
# PRATYAKSA Bot Simulator v2.0
# FastAPI app untuk test kirim alert ke Telegram (tanpa Redis).
# """
# import os
# import httpx
# import logging
# from fastapi import FastAPI, HTTPException, BackgroundTasks
# from pydantic import BaseModel
# 
# TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
# TELEGRAM_API       = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
# 
# logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
# logger = logging.getLogger("PRATYAKSA-BOT-SIMULATOR")
# 
# app = FastAPI(title="PRATYAKSA Bot Simulator API", version="2.0")
# 
# fleet_data: dict = {}
# 
# class AlertPayload(BaseModel):
#     asset_id: str = "EXCA-001"
#     model: str = "Komatsu PC2000"
#     lokasi: str = "Pit Roto Barat"
#     status: str = "CRITICAL"
#     rul: str = "12.4"
#     shap1: str = "Tekanan Hidrolik Turun"
#     shap2: str = "Suhu Oli Naik"
#     part_name: str = "Hydraulic Seal"
#     part_no: str = "7X-2741"
#     stok: str = "4"
# 
# async def _kirim_telegram(d: dict):
#     message = (
#         f"🚨<b>[URGENT ALARM : PRATYAKSA]</b>🚨\n\n"
#         f"🚜 <b>Unit:</b> {d.get('asset_id')} ({d.get('model')})\n"
#         f"📍 <b>Lokasi:</b> {d.get('lokasi')}\n"
#         f"⚠️ <b>Status:</b> {d.get('status')} (Estimasi Sisa Umur: {d.get('rul')} Jam)\n\n"
#         f"🔍 <b>Analisis Kerusakan AI (SHAP):</b>\n"
#         f"1. {d.get('shap1')}\n"
#         f"2. {d.get('shap2')}\n\n"
#         f"🛠️ <b>Rekomendasi Tindakan:</b>\n"
#         f"Arahkan unit ke Workshop Pit terdekat sebelum breakdown.\n\n"
#         f"📦 <b>Info Suku Cadang:</b>\n"
#         f"- Part Name: {d.get('part_name')}\n"
#         f"- Part No: {d.get('part_no')}\n"
#         f"- Stok Workshop: {d.get('stok')} Unit\n\n"
#         f"🔗 <a href=\"https://pratyaksa.kideco.co.id/wo/generate/{d.get('asset_id')}\">Buat Work Order</a>"
#     )
#     url = f"{TELEGRAM_API}/sendMessage"
#     async with httpx.AsyncClient() as client:
#         try:
#             response = await client.post(
#                 url,
#                 json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
#                 timeout=15,
#             )
#             if response.status_code == 200:
#                 logger.info(f"Berhasil! Alert {d.get('asset_id')} terkirim ke Telegram.")
#             else:
#                 logger.error(f"Telegram API Error: {response.text}")
#         except Exception as e:
#             logger.error(f"HTTP Request Error ke Telegram: {e}")
# 
# @app.post("/api/v1/send-alert")
# async def trigger_bot_alert(payload: AlertPayload, background_tasks: BackgroundTasks):
#     data_dict = payload.model_dump()
#     fleet_data[data_dict["asset_id"]] = {
#         "risk_level": data_dict["status"],
#         "last_update": data_dict["lokasi"]
#     }
#     background_tasks.add_task(_kirim_telegram, data_dict)
#     return {
#         "status": "success",
#         "message": "Payload diterima, meneruskan eksekusi ke Telegram...",
#         "asset_id": data_dict["asset_id"]
#     }
# 
# @app.get("/api/v1/fleet-status")
# async def check_fleet_status():
#     total = len(fleet_data)
#     critical = sum(1 for v in fleet_data.values() if v["risk_level"].upper() == "CRITICAL")
#     warning  = sum(1 for v in fleet_data.values() if v["risk_level"].upper() == "WARNING")
#     normal   = total - critical - warning
#     return {
#         "status": "success",
#         "summary": {
#             "total_recorded": total,
#             "critical": critical,
#             "warning": warning,
#             "normal": normal
#         },
#         "details": fleet_data
#     }
