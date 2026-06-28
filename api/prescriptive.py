# api/prescriptive.py
from typing import Dict, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

class RecommendationEngine:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def get_parts(self, component: str) -> List[Dict]:
        query = text("""
            SELECT part_number, name, cost, stock
            FROM spare_parts
            WHERE component = :comp
        """)
        async with self.engine.connect() as conn:
            result = await conn.execute(query, {"comp": component})
            rows = result.fetchall()
        return [{"part_number": r.part_number, "name": r.name,
                 "cost": float(r.cost), "stock": r.stock} for r in rows]

    async def generate(self, risk_score: float, component: str) -> Dict:
        parts = await self.get_parts(component)
        total_cost = sum(p['cost'] for p in parts)
        action = "Create Work Order" if risk_score > 0.7 else "Monitor"
        return {
            "risk_score": risk_score,
            "component": component,
            "parts": parts,
            "estimated_total_cost": total_cost,
            "action": action,
            "comparison": "vs last repair 12% lower"  # TODO: historis
        }