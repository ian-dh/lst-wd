#!/usr/bin/env python3
"""Refresh Les Schwab winter weather signals from NWS.

No API keys required.
- Geocoding is only used when a market does not already have coordinates in the prior weather.json.
- Weather and active alerts come from api.weather.gov.
"""

from __future__ import annotations
import json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETS_FILE = ROOT / "data" / "markets.json"
OUTPUT_FILE = ROOT / "data" / "weather.json"

UA = "les-schwab-winter-monitor/1.0 (GitHub Pages decision-support dashboard)"
STATE_NAMES = {
    "AK":"Alaska","WA":"Washington","OR":"Oregon","CA":"California","ID":"Idaho",
    "MT":"Montana","NV":"Nevada","UT":"Utah","CO":"Colorado","WY":"Wyoming",
    "MN":"Minnesota","NE":"Nebraska","NM":"New Mexico","ND":"North Dakota","SD":"South Dakota"
}
STATUS_RANK = {"CLEAR":0, "WATCH":1, "PREPARE":2, "ACTIVATE":3}
WINTER_WORDS = ("snow","sleet","freezing rain","ice","blizzard","wintry","winter storm","snow shower")
ACTIVATE_ALERTS = {"Blizzard Warning","Ice Storm Warning","Winter Storm Warning","Snow Squall Warning"}
PREPARE_ALERTS = {"Winter Weather Advisory","Freezing Rain Advisory"}
WATCH_ALERTS = {"Winter Storm Watch","Blizzard Watch"}

def get_json(url, attempts=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept":"application/geo+json, application/json"})
    last = None
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (i+1))
    raise last

def geocode(query, state):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({
        "name": query.split(",")[0], "count": 10, "language": "en", "format": "json", "countryCode":"US"
    })
    data = get_json(url)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"No geocode result for {query}")
    # Prefer candidates that mention the state in admin fields; otherwise first U.S. result.
    target = STATE_NAMES.get(state, state).lower()
    candidates = [r for r in results if target in ((r.get("admin1") or "")+" "+(r.get("admin2") or "")).lower()]
    r = candidates[0] if candidates else results[0]
    return float(r["latitude"]), float(r["longitude"])

def wind_mph(text):
    nums = [int(x) for x in re.findall(r"\b(\d+)\s*mph\b", text or "", re.I)]
    return max(nums) if nums else None

def winter_text(text):
    t = (text or "").lower()
    return any(w in t for w in WINTER_WORDS)

def parse_iso(v):
    if not v: return None
    return datetime.fromisoformat(v.replace("Z","+00:00"))

def classify(alerts, hours):
    status = "CLEAR"
    reasons = []
    events = [a.get("properties",{}).get("event","") for a in alerts]
    if any(e in ACTIVATE_ALERTS for e in events):
        return "ACTIVATE", next(e for e in events if e in ACTIVATE_ALERTS)
    if any(e in PREPARE_ALERTS for e in events):
        status, reasons = "PREPARE", [next(e for e in events if e in PREPARE_ALERTS)]
    elif any(e in WATCH_ALERTS for e in events):
        status, reasons = "WATCH", [next(e for e in events if e in WATCH_ALERTS)]

    now = datetime.now(timezone.utc)
    winter_hours = []
    for h in hours:
        p = h.get("properties",{})
        start = parse_iso(p.get("startTime"))
        if not start: continue
        delta = (start.astimezone(timezone.utc)-now).total_seconds()/3600
        if 0 <= delta <= 72 and winter_text((p.get("shortForecast") or "")+" "+(p.get("detailedForecast") or "")):
            pop = (p.get("probabilityOfPrecipitation") or {}).get("value") or 0
            winter_hours.append((delta,pop,p))
    if winter_hours:
        first_delta = min(x[0] for x in winter_hours)
        max_pop = max(x[1] for x in winter_hours)
        if first_delta <= 24 and max_pop >= 40 and STATUS_RANK[status] < STATUS_RANK["PREPARE"]:
            status, reasons = "PREPARE", ["Winter precipitation signal within 24 hours"]
        elif first_delta <= 72 and max_pop >= 30 and STATUS_RANK[status] < STATUS_RANK["WATCH"]:
            status, reasons = "WATCH", ["Winter precipitation signal within 72 hours"]

    if status == "CLEAR":
        reasons = ["No meaningful winter-weather signal in the next 72 hours"]
    return status, reasons[0]

def summarize(hours):
    now = datetime.now(timezone.utc)
    relevant=[]
    for h in hours:
        p=h.get("properties",{})
        start=parse_iso(p.get("startTime"))
        if not start: continue
        delta=(start.astimezone(timezone.utc)-now).total_seconds()/3600
        if 0 <= delta <= 72:
            relevant.append(p)
    if not relevant:
        return None, None, None, None, None
    winter=[p for p in relevant if winter_text((p.get("shortForecast") or "")+" "+(p.get("detailedForecast") or ""))]
    lows=[p.get("temperature") for p in relevant if p.get("temperatureUnit")=="F" and isinstance(p.get("temperature"),(int,float))]
    pops=[(p.get("probabilityOfPrecipitation") or {}).get("value") for p in relevant]
    pops=[p for p in pops if isinstance(p,(int,float))]
    winds=[wind_mph(p.get("windSpeed") or "") for p in relevant]
    winds=[w for w in winds if w is not None]
    if winter:
        first=winter[0]
        timing=first.get("startTime")
        texts=[]
        for p in winter[:4]:
            s=p.get("shortForecast")
            if s and s not in texts: texts.append(s)
        forecast="; ".join(texts)
    else:
        timing=None
        forecast=None
    return timing, forecast, min(lows) if lows else None, max(pops) if pops else None, max(winds) if winds else None

def pr_action(status, market):
    corridor = (market.get("corridors") or [{}])[0].get("name")
    place = corridor or market.get("name")
    if status == "ACTIVATE":
        return f"Confirm DOT/511 conditions for {place}; activate a local store expert and consider timely customer/media guidance."
    if status == "PREPARE":
        return f"Line up a local store spokesperson and verify road conditions for {place}; prepare an outreach angle."
    if status == "WATCH":
        return f"Monitor the next forecast cycle for {place}; no outreach yet unless road impacts strengthen."
    return "No action. Keep in the broad market screen."

def post_slack(changes, markets):
    import os
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if not hook:
        return
    actionable = [c for c in changes if c.get("to") in {"PREPARE","ACTIVATE"}]
    if not actionable:
        return
    by_id = {m["id"]: m for m in markets}
    lines = ["*Les Schwab Winter Weather Monitor* — status changes"]
    for c in actionable:
        m = by_id.get(c["id"], {})
        lines.append(f"• *{c['to']}* — {c['name']}, {c['state']}: {m.get('reason','Weather signal changed')}")
    body = json.dumps({"text":"\n".join(lines)}).encode()
    req = urllib.request.Request(hook, data=body, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()

def load_previous():
    if OUTPUT_FILE.exists():
        try:
            d=json.loads(OUTPUT_FILE.read_text())
            return {m["id"]:m for m in d.get("markets",[])}
        except Exception:
            return {}
    return {}

def main():
    master=json.loads(MARKETS_FILE.read_text())["markets"]
    previous=load_previous()
    output=[]
    changes=[]
    for idx,m in enumerate(master,1):
        prev=previous.get(m["id"],{})
        lat,lon=prev.get("lat"),prev.get("lon")
        try:
            if lat is None or lon is None:
                lat,lon=geocode(m["locationQuery"],m["state"])
                time.sleep(.15)

            point=get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
            props=point["properties"]
            hourly=get_json(props["forecastHourly"]).get("properties",{}).get("periods",[])
            alerts=get_json(f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}").get("features",[])
            status,reason=classify(alerts,[{"properties":p} for p in hourly])
            timing,forecast,tmin,pop,wind=summarize([{"properties":p} for p in hourly])
            alert_summary=[{
                "event":a.get("properties",{}).get("event"),
                "headline":a.get("properties",{}).get("headline"),
                "severity":a.get("properties",{}).get("severity"),
                "ends":a.get("properties",{}).get("ends")
            } for a in alerts if a.get("properties",{}).get("event")]

            item={**m,"status":status,"reason":reason,"timing":timing,"forecast":forecast,
                  "alerts":alert_summary,"temperatureMin":tmin,"maxPrecipProbability":pop,
                  "maxWindMph":wind,"lat":lat,"lon":lon,
                  "weatherUrl":f"https://forecast.weather.gov/MapClick.php?lat={lat:.4f}&lon={lon:.4f}",
                  "prAction":pr_action(status,m)}
        except Exception as exc:
            # Preserve previous usable data on a transient API failure.
            item={**m,**{k:v for k,v in prev.items() if k not in m}}
            item["error"]=str(exc)
            if not item.get("status"): item["status"]="CLEAR"
            if not item.get("reason"): item["reason"]="Weather refresh failed for this market"

        old=prev.get("status")
        if old and old != item["status"]:
            changes.append({"id":m["id"],"name":m["name"],"state":m["state"],"from":old,"to":item["status"]})
        output.append(item)
        print(f"[{idx}/{len(master)}] {m['name']}, {m['state']}: {item['status']}")
        time.sleep(.12)

    payload={"updatedAt":datetime.now(timezone.utc).isoformat(),"dataState":"live",
             "sourceNote":"National Weather Service forecast and active-alert screen; DOT/511 links supplied for verification.",
             "changes":changes,"markets":output}
    OUTPUT_FILE.write_text(json.dumps(payload,indent=2))
    try:
        post_slack(changes, output)
    except Exception as exc:
        print(f"Slack notification skipped after error: {exc}")
    print(f"Wrote {OUTPUT_FILE}")

if __name__=="__main__":
    main()
