#!/usr/bin/env python3
"""Refresh Les Schwab winter weather signals from NWS.

This version screens both:
1) every Les Schwab market/city in data/markets.json, and
2) every corridor/choke point in data/corridors.json.

A market inherits the higher status from its city forecast or any linked corridor.
Road conditions are still linked for human verification; they are not scraped automatically.
"""
from __future__ import annotations
import json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETS_FILE = ROOT / "data" / "markets.json"
CORRIDORS_FILE = ROOT / "data" / "corridors.json"
OUTPUT_FILE = ROOT / "data" / "weather.json"

UA = "les-schwab-winter-monitor/1.1 (GitHub Pages decision-support dashboard)"
STATE_NAMES = {
    "AK":"Alaska","WA":"Washington","OR":"Oregon","CA":"California","ID":"Idaho",
    "MT":"Montana","NV":"Nevada","UT":"Utah","CO":"Colorado","WY":"Wyoming",
    "MN":"Minnesota","NE":"Nebraska","NM":"New Mexico","ND":"North Dakota","SD":"South Dakota"
}
STATUS_RANK = {"CLEAR":0, "WATCH":1, "PREPARE":2, "ACTIVATE":3}
WINTER_WORDS = ("snow","sleet","freezing rain","ice","blizzard","wintry","winter storm","snow shower","snow squall")
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
            wind = wind_mph(p.get("windSpeed") or "") or 0
            winter_hours.append((delta,pop,wind,p))

    if winter_hours:
        first_delta = min(x[0] for x in winter_hours)
        max_pop = max(x[1] for x in winter_hours)
        max_wind = max(x[2] for x in winter_hours)
        # Prepare if winter precip is near-term and reasonably likely.
        if first_delta <= 24 and (max_pop >= 40 or (max_pop >= 30 and max_wind >= 25)) and STATUS_RANK[status] < STATUS_RANK["PREPARE"]:
            status, reasons = "PREPARE", ["Winter precipitation signal within 24 hours"]
        # Watch if meaningful winter precip appears within the 72-hour planning window.
        elif first_delta <= 72 and (max_pop >= 30 or (max_pop >= 20 and max_wind >= 25)) and STATUS_RANK[status] < STATUS_RANK["WATCH"]:
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


def fetch_point(lat, lon):
    point=get_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    props=point["properties"]
    hourly=get_json(props["forecastHourly"]).get("properties",{}).get("periods",[])
    alerts=get_json(f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}").get("features",[])
    wrapped=[{"properties":p} for p in hourly]
    status,reason=classify(alerts,wrapped)
    timing,forecast,tmin,pop,wind=summarize(wrapped)
    alert_summary=[{
        "event":a.get("properties",{}).get("event"),
        "headline":a.get("properties",{}).get("headline"),
        "severity":a.get("properties",{}).get("severity"),
        "ends":a.get("properties",{}).get("ends")
    } for a in alerts if a.get("properties",{}).get("event")]
    return {
        "status":status,"reason":reason,"timing":timing,"forecast":forecast,
        "alerts":alert_summary,"temperatureMin":tmin,"maxPrecipProbability":pop,
        "maxWindMph":wind,"lat":lat,"lon":lon,
        "weatherUrl":f"https://forecast.weather.gov/MapClick.php?lat={lat:.4f}&lon={lon:.4f}"
    }


def highest_signal(signals):
    return max(signals, key=lambda x: STATUS_RANK.get(x.get("status","CLEAR"),0))


def pr_action(status, market, trigger=None):
    place = (trigger or {}).get("name") or market.get("name")
    if status == "ACTIVATE":
        return f"Confirm DOT/511 conditions for {place}; activate a local store expert and consider timely customer/media guidance."
    if status == "PREPARE":
        return f"Line up a local store spokesperson and verify road conditions for {place}; prepare an outreach angle."
    if status == "WATCH":
        return f"Monitor the next forecast cycle for {place}; no outreach yet unless road impacts strengthen."
    return "No action. Keep in the broad market screen."


def load_previous_payload():
    if OUTPUT_FILE.exists():
        try: return json.loads(OUTPUT_FILE.read_text())
        except Exception: pass
    return {"markets":[],"corridors":[]}


def main():
    master=json.loads(MARKETS_FILE.read_text())["markets"]
    corridors=json.loads(CORRIDORS_FILE.read_text())["corridors"]
    prev_payload=load_previous_payload()
    previous={m["id"]:m for m in prev_payload.get("markets",[])}
    previous_corr={c["id"]:c for c in prev_payload.get("corridors",[])}

    # First refresh every unique corridor once. Markets can share corridor results.
    corridor_results={}
    for idx,c in enumerate(corridors,1):
        prior=previous_corr.get(c["id"],{})
        point_results=[]
        errors=[]
        prior_points={p.get("query"):p for p in prior.get("points",[]) if p.get("query")}
        for query in c.get("monitorLocations",[]):
            try:
                pp=prior_points.get(query,{})
                lat,lon=pp.get("lat"),pp.get("lon")
                if lat is None or lon is None:
                    lat,lon=geocode(query,c["state"])
                    time.sleep(.1)
                sig=fetch_point(lat,lon)
                sig["query"]=query
                point_results.append(sig)
            except Exception as exc:
                errors.append(f"{query}: {exc}")
        if point_results:
            best=highest_signal(point_results)
            result={**c,**{k:v for k,v in best.items() if k not in {"query"}},"points":point_results,
                    "triggerPoint":best.get("query"),"error":"; ".join(errors) if errors else None}
        else:
            result={**c,"status":prior.get("status","CLEAR"),"reason":prior.get("reason","Corridor weather refresh failed"),
                    "points":prior.get("points",[]),"error":"; ".join(errors) or "No corridor points refreshed"}
        corridor_results[c["id"]]=result
        print(f"[corridor {idx}/{len(corridors)}] {c['name']}, {c['state']}: {result['status']}")
        time.sleep(.08)

    output=[]
    changes=[]
    for idx,m in enumerate(master,1):
        prev=previous.get(m["id"],{})
        lat,lon=prev.get("lat"),prev.get("lon")
        try:
            if lat is None or lon is None:
                lat,lon=geocode(m["locationQuery"],m["state"])
                time.sleep(.1)
            city=fetch_point(lat,lon)
        except Exception as exc:
            city={
                "status":prev.get("cityStatus",prev.get("status","CLEAR")),
                "reason":prev.get("cityReason","Market weather refresh failed"),
                "timing":prev.get("timing"),"forecast":prev.get("forecast"),
                "temperatureMin":prev.get("temperatureMin"),"maxPrecipProbability":prev.get("maxPrecipProbability"),
                "maxWindMph":prev.get("maxWindMph"),"alerts":prev.get("alerts",[]),
                "lat":lat,"lon":lon,"weatherUrl":prev.get("weatherUrl"),"error":str(exc)
            }

        linked=[]
        for c in m.get("corridors",[]):
            cid=f"{m['state'].lower()}-{re.sub(r'[^a-z0-9]+','-',c['name'].lower()).strip('-')}"
            cr=corridor_results.get(cid)
            if cr:
                linked.append({
                    "id":cid,"name":cr["name"],"routes":cr.get("routes"),"status":cr.get("status","CLEAR"),
                    "reason":cr.get("reason"),"timing":cr.get("timing"),"forecast":cr.get("forecast"),
                    "triggerPoint":cr.get("triggerPoint"),"weatherUrl":cr.get("weatherUrl"),
                    "impactedMarkets":cr.get("impactedMarkets",[])
                })

        candidates=[{"source":"market","name":m["name"],**city}]
        candidates += [{"source":"corridor",**c} for c in linked]
        best=highest_signal(candidates)
        final_status=best.get("status","CLEAR")
        if best.get("source")=="corridor" and STATUS_RANK[final_status] > STATUS_RANK.get(city.get("status","CLEAR"),0):
            reason=f"Corridor signal — {best.get('name')}: {best.get('reason')}"
            timing=best.get("timing") or city.get("timing")
            forecast=best.get("forecast") or city.get("forecast")
            trigger={"type":"corridor","name":best.get("name"),"routes":best.get("routes"),"point":best.get("triggerPoint")}
        else:
            reason=city.get("reason")
            timing=city.get("timing")
            forecast=city.get("forecast")
            trigger={"type":"market","name":m["name"]}

        item={**m,"status":final_status,"reason":reason,"timing":timing,"forecast":forecast,
              "alerts":city.get("alerts",[]),"temperatureMin":city.get("temperatureMin"),
              "maxPrecipProbability":city.get("maxPrecipProbability"),"maxWindMph":city.get("maxWindMph"),
              "lat":city.get("lat"),"lon":city.get("lon"),"weatherUrl":city.get("weatherUrl"),
              "cityStatus":city.get("status","CLEAR"),"cityReason":city.get("reason"),
              "corridorSignals":linked,"trigger":trigger,"prAction":pr_action(final_status,m,trigger)}

        old=prev.get("status")
        if old and old != final_status:
            changes.append({"id":m["id"],"name":m["name"],"state":m["state"],"from":old,"to":final_status})
        output.append(item)
        print(f"[market {idx}/{len(master)}] {m['name']}, {m['state']}: city={city.get('status')} final={final_status}")
        time.sleep(.08)

    payload={
        "updatedAt":datetime.now(timezone.utc).isoformat(),"dataState":"live",
        "sourceNote":"National Weather Service city + corridor forecast/alert screen; DOT/511 links supplied for verification.",
        "changes":changes,"markets":output,"corridors":list(corridor_results.values())
    }
    OUTPUT_FILE.write_text(json.dumps(payload,indent=2))
    print(f"Wrote {OUTPUT_FILE}")

if __name__=="__main__":
    main()
