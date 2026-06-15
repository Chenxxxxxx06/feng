"""Demo server — runs without PostgreSQL, uses in-memory data.
Start: python demo_server.py
"""

import json, random, math, time
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8000

# ── Mock Data ──────────────────────────────────────────────────

TURBINES = []
REGIONS = {
    "陕北": {"lat_range": (37.0, 39.0), "lng_range": (107.5, 110.5)},
    "关中": {"lat_range": (34.0, 35.5), "lng_range": (108.0, 110.5)},
    "陕南": {"lat_range": (32.0, 33.5), "lng_range": (108.0, 110.0)},
}
MODELS = ["金风GW150-3MW", "远景EN-156/3.3", "Vestas V112-3.3MW", "明阳MySE3.2-156", "华能H120-2.0MW"]
NAMES_PREFIX = ["DB-A", "DB-B", "JB-C", "ZC-D", "ZC-E", "SM-F", "HS-G", "DL-H", "HY-I", "SL-J", "AK-K"]
FAULT_TYPES = [
    "轴承磨损", "齿轮箱点蚀", "发电机过热", "叶片裂纹",
    "变桨系统故障", "冷却系统故障", "主轴不对中",
]
COMPONENTS = ["叶片", "齿轮箱", "发电机", "主轴承", "变桨系统"]


def init_turbines():
    global TURBINES
    tid = 1
    for region, coords in REGIONS.items():
        count = 12 if region == "陕北" else (9 if region == "关中" else 7)
        for i in range(count):
            hi = round(random.uniform(45, 100), 1)
            status = "normal" if hi >= 80 else ("warning" if hi >= 60 else "fault")
            TURBINES.append({
                "id": tid, "name": f"{random.choice(NAMES_PREFIX)}-{i+1:03d}",
                "model": random.choice(MODELS), "power_mw": random.choice([2.0, 3.0, 3.3, 3.2]),
                "lat": round(random.uniform(*coords["lat_range"]), 4),
                "lng": round(random.uniform(*coords["lng_range"]), 4),
                "region": region, "status": status, "hi_value": hi,
                "last_maintenance": (datetime.now() - timedelta(days=random.randint(10, 400))).isoformat(),
            })
            tid += 1


def generate_scada(turbine_id, hours=24):
    records = []
    now = datetime.now(timezone.utc)
    mw = next((t["power_mw"] for t in TURBINES if t["id"] == turbine_id), 3.0)
    rated_kw = mw * 1000
    for h in range(hours):
        ts = now - timedelta(hours=h)
        ws = max(1, round(random.weibullvariate(7.5, 2.2), 1))
        power = 0 if ws < 3 else (rated_kw if ws >= 12 else round(rated_kw * (ws / 12) ** 3))
        records.append({
            "timestamp": ts.isoformat(), "power_kw": power, "wind_speed_ms": ws,
            "rotor_rpm": round(5 + ws, 1), "gen_temperature_c": round(60 + power / rated_kw * 40 + random.uniform(-3, 3), 1),
            "gearbox_temperature_c": round(50 + power / rated_kw * 30 + random.uniform(-2, 2), 1),
            "bearing_temperature_c": round(45 + power / rated_kw * 25 + random.uniform(-2, 2), 1),
            "pitch_angle_deg": round(random.uniform(0, 15), 1),
            "nacelle_direction_deg": round(random.uniform(0, 360)),
            "grid_frequency_hz": round(50 + random.uniform(-0.1, 0.1), 2),
            "ambient_temp_c": round(15 + 10 * math.sin((ts.month - 3) * math.pi / 6) + random.uniform(-3, 3), 1),
            "data_source": "demo_server",
        })
    return sorted(records, key=lambda r: r["timestamp"])


def generate_wind(lat, lng):
    base = 7.0 if lat >= 37 else (4.5 if lat >= 34 else 3.2)
    speed = round(base + random.uniform(-1.5, 1.5), 1)
    gust = round(speed * (1 + random.uniform(0.3, 0.8)), 1)
    direction = round(random.uniform(0, 360))
    ti = round(random.uniform(0.08, 0.22), 3)
    return {
        "wind_speed_ms": speed, "wind_gust_ms": gust, "wind_direction_deg": direction,
        "turbulence_intensity": ti, "air_temperature_c": round(20 + random.uniform(-5, 5), 1),
        "air_pressure_hpa": round(1013 + random.uniform(-10, 10), 1),
        "u_component": round(-speed * math.sin(math.radians(direction)), 1),
        "v_component": round(-speed * math.cos(math.radians(direction)), 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "era5_simulation", "note": "ERA5物理仿真",
    }


def gen_vibration(tid):
    n = 2048
    waveform = [round(math.sin(2 * math.pi * 25 * i / 10240) * 1.5 + random.gauss(0, 0.15), 4) for i in range(n)]
    rms = round(math.sqrt(sum(s**2 for s in waveform) / n), 3)
    peaks = [{"frequency_hz": 25.0, "amplitude": 1.5}, {"frequency_hz": 50.0, "amplitude": 0.7}, {"frequency_hz": 75.0, "amplitude": 0.3}]
    has_fault = random.random() < 0.2
    return {
        "turbine_id": tid, "component": "gearbox_high_speed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": 0.2, "sample_rate_hz": 10240,
        "rms": rms, "peak_amplitude": round(max(abs(x) for x in waveform), 3),
        "waveform": waveform, "spectrum": [random.uniform(0, 1) for _ in range(512)],
        "peak_frequencies": peaks, "fault_detected": has_fault,
        "fault_info": {"type": "轴承内圈故障", "characteristic_frequency_hz": 135.7, "severity": "early"} if has_fault else None,
        "data_source": "physics_simulation",
    }


# ── HTTP Handler ───────────────────────────────────────────────

class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS_preflight(self):
        self._send({"ok": True})

    def do_OPTIONS(self):
        self.do_OPTIONS_preflight()

    def do_GET(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/health":
                return self._send({"status": "ok", "app": "风调预顺 Demo"})

            elif p == "/api/auth/me":
                return self._send({"id": 1, "username": "admin", "email": "admin@fengdiao.com", "role": "admin", "api_key": None, "api_provider": None, "model_preference": "gpt-4", "is_active": True})

            elif p == "/api/turbines/":
                q = self._parse_qs()
                turbines = TURBINES
                if "region" in q: turbines = [t for t in turbines if t["region"] == q["region"]]
                if "model" in q: turbines = [t for t in turbines if t["model"] == q["model"]]
                if "status" in q: turbines = [t for t in turbines if t["status"] == q["status"]]
                return self._send({
                    "turbines": turbines, "total": len(turbines),
                    "healthy": sum(1 for t in turbines if t["status"] == "normal"),
                    "warning": sum(1 for t in turbines if t["status"] == "warning"),
                    "faulty": sum(1 for t in turbines if t["status"] == "fault"),
                })

            elif p.startswith("/api/turbines/") and p.endswith("/scada"):
                tid = int(p.split("/")[3])
                return self._send(generate_scada(tid))

            elif p.startswith("/api/turbines/") and p.endswith("/wind"):
                tid = int(p.split("/")[3])
                t = next((x for x in TURBINES if x["id"] == tid), TURBINES[0])
                return self._send(generate_wind(t["lat"], t["lng"]))

            elif p.startswith("/api/turbines/") and p.endswith("/health"):
                tid = int(p.split("/")[3])
                t = next((x for x in TURBINES if x["id"] == tid), TURBINES[0])
                return self._send({
                    "turbine_id": tid, "turbine_name": t["name"],
                    "hi_value": t["hi_value"], "status": t["status"],
                    "component_scores": {"performance": {"score": 85.0, "weight": 0.35}, "vibration": {"score": 80.0, "weight": 0.25}, "blade": {"score": 90.0, "weight": 0.15}, "maintenance": {"score": 75.0, "weight": 0.15}, "trend": {"score": 70.0, "weight": 0.10}},
                    "calculated_at": datetime.now(timezone.utc).isoformat(),
                })

            elif p.startswith("/api/turbines/"):
                tid = int(p.split("/")[3])
                t = next((x for x in TURBINES if x["id"] == tid), None)
                if not t: return self._send({"detail": "Not found"}, 404)
                return self._send(t)

            elif p == "/api/diagnosis/faults":
                faults = []
                for i, t in enumerate(TURBINES[:8]):
                    ft = random.choice(FAULT_TYPES)
                    faults.append({
                        "id": i + 1, "turbine_id": t["id"], "turbine_name": t["name"],
                        "detected_at": (datetime.now() - timedelta(hours=random.randint(1, 168))).isoformat(),
                        "fault_type": ft, "confidence": round(random.uniform(0.72, 0.96), 2),
                        "status": random.choice(["open", "open", "closed"]),
                        "details": {"recommendation": f"建议检查{ft}相关部件，安排振动复测"},
                    })
                return self._send(faults)

            elif p.startswith("/api/diagnosis/faults/"):
                fid = int(p.split("/")[4])
                return self._send({
                    "id": fid, "turbine_id": 1, "turbine_name": TURBINES[0]["name"],
                    "detected_at": datetime.now().isoformat(),
                    "fault_type": "轴承磨损", "confidence": 0.89, "status": "open",
                    "details": {"recommendation": "建议停机检查轴承温度→拆解检测磨损"},
                    "signals": [
                        {"id": 1, "sensor_name": "振动RMS值", "contribution_score": 0.85, "priority": "high"},
                        {"id": 2, "sensor_name": "轴承温度", "contribution_score": 0.72, "priority": "high"},
                        {"id": 3, "sensor_name": "发电机温度", "contribution_score": 0.58, "priority": "medium"},
                        {"id": 4, "sensor_name": "功率偏差", "contribution_score": 0.41, "priority": "low"},
                    ],
                })

            elif p == "/api/diagnosis/vibration":
                q = self._parse_qs()
                tid = int(q.get("turbine_id", 1))
                return self._send(gen_vibration(tid))

            elif p == "/api/diagnosis/blade-images":
                q = self._parse_qs()
                tid = int(q.get("turbine_id", 1))
                imgs = []
                for i in range(3):
                    has = random.random() < 0.25
                    imgs.append({
                        "id": i + 1, "turbine_id": tid,
                        "image_path": f"data/blade_images/turbine_{tid:03d}_blade_{i:04d}.png",
                        "view": random.choice(["前缘", "迎风面", "背风面"]),
                        "timestamp": datetime.now().isoformat(),
                        "has_damage": has,
                        "damage_type": random.choice(["crack", "erosion", "dirt"]) if has else None,
                        "confidence": round(random.uniform(0.82, 0.96), 3) if has else 1.0,
                        "damage_bbox": {"x": 200, "y": 100, "w": 48, "h": 24} if has else None,
                        "damage_severity": random.choice(["minor", "moderate"]) if has else None,
                        "data_source": "simulated",
                    })
                return self._send(imgs)

            elif p == "/api/prediction/rul":
                items = []
                for t in TURBINES:
                    for comp in random.sample(COMPONENTS, 3):
                        life = round(random.uniform(30, 1200), 1)
                        items.append({
                            "turbine_id": t["id"], "turbine_name": t["name"],
                            "component": comp, "remaining_life_days": life,
                            "confidence_lower": round(life * random.uniform(0.65, 0.85), 1),
                            "confidence_upper": round(life * random.uniform(1.15, 1.40), 1),
                            "predicted_at": datetime.now().isoformat(),
                        })
                return self._send({"predictions": items})

            elif p == "/api/workorders/":
                wos = []
                for i in range(6):
                    wos.append({
                        "id": i + 1, "turbine_id": random.choice(TURBINES)["id"],
                        "fault_id": None, "title": f"例行维护-风机{i+1:03d}",
                        "description": "季度例行检修", "status": random.choice(["pending", "in_progress", "completed"]),
                        "assignee": random.choice(["张工", "李工", "王工"]),
                        "cost_estimate": random.randint(3000, 50000),
                        "cost_actual": None, "created_at": datetime.now().isoformat(),
                        "completed_at": None,
                    })
                return self._send(wos)

            elif p == "/api/settings/pipeline-status":
                return self._send({
                    "sources": [
                        {"type": "scada", "name": "SCADA运行数据", "status": "connected", "last_update": datetime.now().isoformat(), "record_count": 8640, "real_data_available": False, "note": "Demo仿真数据"},
                        {"type": "vibration", "name": "振动监测数据", "status": "connected", "last_update": datetime.now().isoformat(), "record_count": 150, "real_data_available": False, "note": "物理仿真波形"},
                        {"type": "image", "name": "叶片图像数据", "status": "partial", "last_update": datetime.now().isoformat(), "record_count": 90, "real_data_available": False, "note": "模拟叶片图像"},
                        {"type": "weather", "name": "气象环境数据", "status": "connected", "last_update": datetime.now().isoformat(), "record_count": 8760, "real_data_available": False, "note": "ERA5物理仿真"},
                    ],
                    "overall_status": "healthy", "errors": [],
                })

            elif p == "/api/personnel":
                return self._send([
                    {"id": 1, "name": "张工", "skills": ["轴承维修", "齿轮箱"], "region": "陕北", "load": 2, "email": "zhang@fengdiao.com"},
                    {"id": 2, "name": "李工", "skills": ["电气系统", "变桨"], "region": "关中", "load": 1, "email": "li@fengdiao.com"},
                    {"id": 3, "name": "王工", "skills": ["叶片修复", "发电机"], "region": "陕南", "load": 3, "email": "wang@fengdiao.com"},
                    {"id": 4, "name": "赵工", "skills": ["轴承维修", "冷却系统"], "region": "陕北", "load": 0, "email": "zhao@fengdiao.com"},
                    {"id": 5, "name": "刘工", "skills": ["齿轮箱", "发电机"], "region": "关中", "load": 1, "email": "liu@fengdiao.com"},
                ])

            elif p == "/api/settings/thresholds":
                return self._send([{"id": 1, "hi_threshold": 70.0, "email_enabled": False, "email_address": None, "wechat_enabled": False}])

            elif p == "/api/settings/data-sources":
                return self._send([])

            else:
                return self._send({"detail": f"Not found: {p}"}, 404)

        except Exception as e:
            return self._send({"detail": str(e)}, 500)

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            body_len = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(body_len) if body_len else b'{}'
            # Handle encoding: try UTF-8 first, then GBK (Windows curl)
            try:
                body = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError):
                try:
                    body = json.loads(raw.decode('gbk'))
                except Exception:
                    body = json.loads(raw.decode('utf-8', errors='replace'))

            if p == "/api/auth/login":
                return self._send({
                    "access_token": "demo-token-xxxxx",
                    "token_type": "bearer",
                    "user": {"id": 1, "username": body.get("username", "admin"), "email": "admin@fengdiao.com", "role": "admin", "api_key": None, "api_provider": None, "model_preference": "gpt-4", "is_active": True},
                })

            elif p == "/api/auth/register":
                return self._send({
                    "access_token": "demo-token-xxxxx",
                    "token_type": "bearer",
                    "user": {"id": 2, "username": body.get("username", "user"), "email": body.get("email", ""), "role": "viewer", "api_key": None, "api_provider": None, "model_preference": "gpt-4", "is_active": True},
                })

            elif p == "/api/ai/summary":
                pt = body.get("page_type", "dashboard")
                page_data = body.get("page_data", {})
                # Build turbine stats for AI context
                healthy = sum(1 for t in TURBINES if t["status"] == "normal")
                warning = sum(1 for t in TURBINES if t["status"] == "warning")
                fault = sum(1 for t in TURBINES if t["status"] == "fault")
                page_data.update({
                    "total_turbines": len(TURBINES),
                    "healthy": healthy, "warning": warning, "fault": fault,
                })
                try:
                    from app.services.qwen_client import summarize_page
                    from app.config import get_settings
                    s = get_settings()
                    result = summarize_page(pt, page_data,
                        api_key=s.DASHSCOPE_API_KEY,
                        api_provider="通义千问 DashScope")
                    return self._send(result)
                except Exception:
                    from app.services.qwen_client import fallback_summary
                    return self._send(fallback_summary(pt))

            elif p == "/api/ai/copilot":
                messages = body.get("messages", [])
                page_context = body.get("page_context", {})
                healthy = sum(1 for t in TURBINES if t["status"] == "normal")
                warning = sum(1 for t in TURBINES if t["status"] == "warning")
                fault = sum(1 for t in TURBINES if t["status"] == "fault")
                page_context.update({
                    "total_turbines": len(TURBINES), "warning_count": warning, "fault_count": fault,
                })
                try:
                    from app.services.qwen_client import copilot_chat, describe_screenshot
                    from app.config import get_settings
                    s = get_settings()
                    api_key = s.DASHSCOPE_API_KEY
                    api_provider = "通义千问 DashScope"
                    # Analyze screenshot if provided
                    screenshot_desc = None
                    if body.get("screenshot"):
                        try:
                            screenshot_desc = describe_screenshot(
                                body["screenshot"],
                                page_context.get("page_type", "unknown"),
                                api_key=api_key,
                                api_provider=api_provider,
                            )
                        except Exception:
                            pass  # best-effort
                    reply = copilot_chat(messages, page_context,
                        screenshot_description=screenshot_desc,
                        api_key=api_key,
                        api_provider=api_provider)
                    return self._send({"reply": reply, "role": "assistant"})
                except Exception as e:
                    return self._send({"reply": f"AI服务暂不可用: {str(e)}", "role": "error"})

            elif p == "/api/prediction/cost-comparison":
                return self._send({
                    "immediate_repair_cost": 85000.0, "delayed_repair_cost": 135000.0,
                    "downtime_loss_per_day": 12000.0, "failure_probability": 0.35,
                    "recommendation": "建议在7天内安排检修，预期可节省维修成本约5万元",
                    "optimal_window_days": 7,
                })

            elif p == "/api/diagnosis/blade-diagnosis":
                return self._send({
                    "turbine_id": body.get("turbine_id", 1),
                    "damage_type": "crack", "confidence": 0.85,
                    "damage_bbox": {"x": 120, "y": 80, "w": 64, "h": 32},
                    "image_path": body.get("image_path", ""),
                })

            elif p == "/api/ai/analyze-fault":
                # AI analysis for work order
                turbine_id = body.get("turbine_id", 1)
                fault_type = body.get("fault_type", "未知故障")
                t = next((x for x in TURBINES if x["id"] == turbine_id), TURBINES[0])
                try:
                    from app.services.qwen_client import diagnose_fault
                    from app.config import get_settings
                    s = get_settings()
                    diagnosis = diagnose_fault(
                        {"name": t["name"], "model": t["model"], "region": t["region"], "hi_value": t["hi_value"], "status": t["status"]},
                        [{"fault_type": fault_type, "confidence": 0.87, "detected_at": datetime.now().isoformat()}],
                        api_key=s.DASHSCOPE_API_KEY,
                        api_provider="通义千问 DashScope",
                    )
                except Exception:
                    diagnosis = f"根据SCADA数据分析，{t['name']}存在{fault_type}。建议: 1.停机检查相关部件温度 2.安排振动复测 3.必要时更换受损部件。"

                # Anomaly indicators
                anomalies = [
                    {"indicator": "振动RMS", "value": "3.8 mm/s²", "normal": "<2.0 mm/s²", "deviation": "+90%", "level": "high"},
                    {"indicator": "轴承温度", "value": "68°C", "normal": "<60°C", "deviation": "+13%", "level": "high"},
                    {"indicator": "功率偏差", "value": "12%", "normal": "<10%", "deviation": "+2%", "level": "medium"},
                ]
                return self._send({
                    "diagnosis": diagnosis,
                    "anomalies": anomalies,
                    "turbine_name": t["name"],
                    "fault_type": fault_type,
                    "generated_at": datetime.now().isoformat(),
                })

            elif p == "/api/settings/data-sources/test":
                return self._send({"status": "success", "message": f"Connection test to {body.get('source_type', '')} passed", "source_type": body.get("source_type", "")})

            elif p == "/api/workorders/":
                return self._send({
                    "id": 99, "turbine_id": body.get("turbine_id", 1),
                    "fault_id": None, "title": body.get("title", "新工单"),
                    "description": body.get("description", ""), "status": "pending",
                    "assignee": body.get("assignee", None),
                    "cost_estimate": body.get("cost_estimate", 0),
                    "cost_actual": None, "created_at": datetime.now().isoformat(), "completed_at": None,
                }, 201)

            elif p.startswith("/api/workorders/") and "/" not in p[15:]:
                return self._send({"detail": "Not implemented"}, 400)

            elif p == "/api/settings/thresholds":
                return self._send({})  # PUT handled by same path

            elif p == "/api/settings/profile":
                return self._send({"id": 1, "username": "admin", "email": "admin@fengdiao.com", "role": "admin", "api_key": body.get("api_key"), "api_provider": body.get("api_provider"), "model_preference": body.get("model_preference", "gpt-4"), "is_active": True})

            else:
                return self._send({"detail": f"Not found: {p}"}, 404)

        except Exception as e:
            return self._send({"detail": str(e)}, 500)

    def do_PUT(self):
        self.do_POST()

    def _parse_qs(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        return {k: v[0] for k, v in params.items()}


if __name__ == "__main__":
    init_turbines()
    print(f" 风调预顺 Demo Server")
    print(f"  Turbines: {len(TURBINES)} ({sum(1 for t in TURBINES if t['region']=='陕北')} 陕北, {sum(1 for t in TURBINES if t['region']=='关中')} 关中, {sum(1 for t in TURBINES if t['region']=='陕南')} 陕南)")
    print(f"  Listening: http://localhost:{PORT}")
    print(f"  Frontend: http://localhost:5173")
    HTTP = HTTPServer(("0.0.0.0", PORT), DemoHandler)
    try:
        HTTP.serve_forever()
    except KeyboardInterrupt:
        HTTP.shutdown()
        print("\nShut down.")
