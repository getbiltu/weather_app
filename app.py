from flask import Flask, render_template, request, redirect, url_for, jsonify
import requests, psycopg, os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import timezone, datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")

# ---------------- DB CONFIG ----------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", 5432)
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")


def get_db():
    return psycopg.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True
    )


# ---------------- INIT DB ----------------
def init_db():
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            lat REAL,
            lon REAL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS weather_logs (
            id SERIAL PRIMARY KEY,
            city TEXT,
            temperature REAL,
            humidity INTEGER,
            aqi INTEGER,
            rain_probability INTEGER,
            rain_mm REAL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)

        # ✅ Settings table with freshness
        cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            interval_minutes INTEGER NOT NULL,
            dashboard_refresh_seconds INTEGER NOT NULL DEFAULT 60,
            data_freshness_minutes INTEGER NOT NULL DEFAULT 30,
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """)

        # ✅ If DB created earlier without freshness column, add it
        cur.execute("""
        ALTER TABLE settings
        ADD COLUMN IF NOT EXISTS data_freshness_minutes INTEGER NOT NULL DEFAULT 30;
        """)

        cur.execute("""
        INSERT INTO settings (id, interval_minutes, dashboard_refresh_seconds, data_freshness_minutes, updated_at)
        VALUES (1, 30, 60, 30, NOW())
        ON CONFLICT (id) DO NOTHING;
        """)


init_db()

# ---------------- UTILITIES ----------------
def parse_float(val):
    val = (val or "").strip()
    if val == "":
        return None
    try:
        return float(val)
    except ValueError:
        return None


# ---------------- GEO HELPERS ----------------
def geocode_city_openmeteo(name: str):
    """City Name -> lat/lon using Open-Meteo geocoding"""
    try:
        r = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": name, "count": 1},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()

        if not data.get("results"):
            return None, None

        lat = float(data["results"][0]["latitude"])
        lon = float(data["results"][0]["longitude"])
        return lat, lon

    except Exception as e:
        print("Geocode error:", e)
        return None, None


def reverse_geocode_city_nominatim(lat: float, lon: float):
    """lat/lon -> City name using OSM Nominatim reverse geocode"""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json"}
        headers = {"User-Agent": "weather-dashboard/1.0"}

        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        addr = data.get("address", {})
        city = (
            addr.get("city") or
            addr.get("town") or
            addr.get("village") or
            addr.get("municipality") or
            addr.get("county")
        )

        return city

    except Exception as e:
        print("Reverse geocode error:", e)
        return None


# ---------------- WEATHER FETCH ----------------
def fetch_weather(lat, lon):
    w = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current_weather": True,
            "hourly": "relativehumidity_2m,precipitation_probability,precipitation"
        },
        timeout=10
    ).json()

    temp = w["current_weather"]["temperature"]
    humidity = w["hourly"]["relativehumidity_2m"][0]
    rain_prob = w["hourly"]["precipitation_probability"][0]
    rain_mm = w["hourly"]["precipitation"][0]

    aqi = requests.get(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        params={"latitude": lat, "longitude": lon, "current": "us_aqi"},
        timeout=10
    ).json()["current"]["us_aqi"]

    return temp, humidity, aqi, rain_prob, rain_mm


# ---------------- DB CACHE HELPERS ----------------
def get_cached_weather(city_name: str):
    """
    Returns latest cached row:
    (temperature, humidity, aqi, rain_probability, rain_mm, created_at)
    """
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT temperature, humidity, aqi, rain_probability, rain_mm, created_at
            FROM weather_logs
            WHERE city=%s
            ORDER BY created_at DESC
            LIMIT 1
        """, (city_name,))
        return cur.fetchone()


def save_weather_log(city_name: str, t, h, aqi, rp, rm):
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO weather_logs
            (city, temperature, humidity, aqi, rain_probability, rain_mm)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (city_name, t, h, aqi, rp, rm))


# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()


def get_interval():
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT interval_minutes FROM settings WHERE id=1")
        return cur.fetchone()[0]


def collect_weather():
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, lat, lon FROM cities")
        for name, lat, lon in cur.fetchall():
            try:
                if lat is None or lon is None:
                    continue
                t, h, a, rp, rm = fetch_weather(lat, lon)
                cur.execute("""
                    INSERT INTO weather_logs
                    (city, temperature, humidity, aqi, rain_probability, rain_mm)
                    VALUES (%s,%s,%s,%s,%s,%s)
                """, (name, t, h, a, rp, rm))
            except Exception as e:
                print("Scheduler error:", e)


def schedule_job():
    interval = get_interval()
    job = scheduler.get_job("weather_job")

    if job:
        job.reschedule(trigger=IntervalTrigger(minutes=interval))
    else:
        scheduler.add_job(
            collect_weather,
            IntervalTrigger(minutes=interval),
            id="weather_job",
            replace_existing=True
        )


schedule_job()
scheduler.start()


def get_settings():
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT interval_minutes,
                   dashboard_refresh_seconds,
                   data_freshness_minutes
            FROM settings
            WHERE id=1
        """)
        interval, dash_refresh, freshness = cur.fetchone()

    return {
        "interval_minutes": interval,
        "dashboard_refresh_seconds": dash_refresh,
        "data_freshness_minutes": freshness
    }


# ✅ UPDATED to include paused
def get_scheduler_status():
    try:
        job = scheduler.get_job("weather_job")

        if not job:
            return {"status": "Stopped", "next_run": None, "paused": True}

        # APScheduler: paused job has next_run_time=None
        paused = (job.next_run_time is None)

        if job.next_run_time:
            next_run = job.next_run_time.astimezone(timezone.utc).isoformat()
            status = "Running"
        else:
            next_run = None
            status = "Paused"

        return {"status": status, "next_run": next_run, "paused": paused}

    except Exception as e:
        print("Scheduler status error:", e)
        return {"status": "Unknown", "next_run": None, "paused": True}


# ✅ NEW route for enable/disable
@app.route("/scheduler/toggle", methods=["POST"])
def scheduler_toggle():
    try:
        action = request.form.get("action")  # pause/resume
        job = scheduler.get_job("weather_job")

        # If no job exists, create it
        if not job:
            schedule_job()
            return redirect(url_for("settings", saved=1))

        if action == "pause":
            scheduler.pause_job("weather_job")
            print("⏸ Scheduler paused")

        elif action == "resume":
            scheduler.resume_job("weather_job")
            print("▶️ Scheduler resumed")

        return redirect(url_for("settings", saved=1))

    except Exception as e:
        print("Scheduler toggle error:", e)
        return redirect(url_for("settings"))


# ---------------- ROUTES ----------------
@app.route("/")
def dashboard():
    settings = get_settings()
    return render_template(
        "dashboard.html",
        title="Dashboard",
        refresh_seconds=settings["dashboard_refresh_seconds"]
    )


@app.route("/api/live")
def live_api():
    settings = get_settings()
    freshness_minutes = int(settings.get("data_freshness_minutes", 30))

    with get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, lat, lon FROM cities")
        cities = cur.fetchall()

    data = []
    now_utc = datetime.now(timezone.utc)

    for name, lat, lon in cities:
        try:
            if lat is None or lon is None:
                continue

            cached = get_cached_weather(name)

            # ✅ Use DB cache if fresh
            if cached:
                t, h, a, rp, rm, created_at = cached
                age_minutes = (now_utc - created_at).total_seconds() / 60.0

                if age_minutes <= freshness_minutes:
                    data.append({
                        "city": name,
                        "temp": t,
                        "humidity": h,
                        "aqi": a,
                        "rain": rp,
                        "mm": rm,
                        "source": "db",
                        "time": created_at.isoformat()
                    })
                    continue

            # ✅ Otherwise fetch from API
            t, h, a, rp, rm = fetch_weather(lat, lon)

            data.append({
                "city": name,
                "temp": t,
                "humidity": h,
                "aqi": a,
                "rain": rp,
                "mm": rm,
                "source": "api"
            })

            # ✅ Save fetched data into DB so next call uses cache
            save_weather_log(name, t, h, a, rp, rm)

        except Exception as e:
            print("Live API error:", e)

    return jsonify(data)


@app.route("/data")
def data():
    metric = request.args.get("metric", "temperature")
    city = request.args.get("city", "ALL")

    hours = request.args.get("hours")
    start = request.args.get("start")
    end = request.args.get("end")

    where = []
    params = []

    if city != "ALL":
        where.append("city = %s")
        params.append(city)

    if start and end:
        where.append("created_at BETWEEN %s AND %s")
        params.extend([start, end])
    else:
        hours = int(hours or 24)
        where.append(f"created_at >= NOW() - INTERVAL '{hours} hours'")

    where_sql = " AND ".join(where)
    if where_sql:
        where_sql = "WHERE " + where_sql

    query = f"""
        SELECT city, temperature, humidity, aqi, rain_mm, rain_probability, created_at
        FROM weather_logs
        {where_sql}
        ORDER BY created_at
    """

    # ✅ Summary query (high/low by metric per city)
    # Important: metric is fixed to safe list (avoid SQL injection)
    allowed_metrics = ["temperature", "humidity", "aqi", "rain_mm", "rain_probability"]
    if metric not in allowed_metrics:
        metric = "temperature"

    summary_query = f"""
        SELECT city,
               MIN({metric}) as low,
               MAX({metric}) as high
        FROM weather_logs
        {where_sql}
        GROUP BY city
        ORDER BY city
    """

    with get_db() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

        cur.execute(summary_query, params)
        summary_rows = cur.fetchall()

        cur.execute("SELECT name FROM cities ORDER BY name")
        city_list = [c[0] for c in cur.fetchall()]

    rows_js = [
        {
            "city": r[0],
            "temperature": r[1],
            "humidity": r[2],
            "aqi": r[3],
            "rain_mm": r[4],
            "rain_probability": r[5],
            "time": r[6].strftime("%Y-%m-%d %H:%M")
        }
        for r in rows
    ]

    # ✅ Summary output JS
    summary_js = [
        {"city": s[0], "low": s[1], "high": s[2]}
        for s in summary_rows
    ]

    return render_template(
        "data.html",
        title="Data",
        rows=rows_js,
        metric=metric,
        city=city,
        city_list=city_list,
        summary=summary_js
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    saved = request.args.get("saved") == "1"

    with get_db() as conn, conn.cursor() as cur:
        if request.method == "POST":
            interval = int(request.form["interval"])
            dash_refresh = int(request.form["dashboard_refresh_seconds"])
            freshness = int(request.form["data_freshness_minutes"])

            cur.execute("""
                UPDATE settings
                SET interval_minutes=%s,
                    dashboard_refresh_seconds=%s,
                    data_freshness_minutes=%s,
                    updated_at=NOW()
                WHERE id=1
            """, (interval, dash_refresh, freshness))

            conn.commit()
            schedule_job()
            return redirect(url_for("settings", saved=1))

        cur.execute("""
            SELECT interval_minutes,
                   dashboard_refresh_seconds,
                   data_freshness_minutes,
                   updated_at
            FROM settings
            WHERE id=1
        """)
        interval, dash_refresh, freshness, updated_at = cur.fetchone()

    if updated_at:
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated_at_iso = updated_at.astimezone(timezone.utc).isoformat()
    else:
        updated_at_iso = ""

    return render_template(
        "settings.html",
        title="Settings",
        interval=interval,
        dash_refresh=dash_refresh,
        data_freshness=freshness,
        scheduler=get_scheduler_status(),
        saved=saved,
        updated_at_iso=updated_at_iso
    )


@app.route("/cities", methods=["GET", "POST"])
def cities():
    with get_db() as conn, conn.cursor() as cur:

        if request.method == "POST":
            action = request.form.get("action", "")

            if action == "add":
                city_name = (request.form.get("city_name") or "").strip()
                lat_val = parse_float(request.form.get("lat"))
                lon_val = parse_float(request.form.get("lon"))

                # Case 3: all three given
                if city_name and lat_val is not None and lon_val is not None:
                    final_city = city_name
                    final_lat = lat_val
                    final_lon = lon_val

                # Case 1: city name only
                elif city_name and (lat_val is None or lon_val is None):
                    found_lat, found_lon = geocode_city_openmeteo(city_name)
                    if found_lat is None or found_lon is None:
                        print("Could not geocode:", city_name)
                        return redirect(url_for("cities"))

                    final_city = city_name
                    final_lat = found_lat
                    final_lon = found_lon

                # Case 2: lat/lon only
                elif (not city_name) and (lat_val is not None and lon_val is not None):
                    found_city = reverse_geocode_city_nominatim(lat_val, lon_val)
                    if not found_city:
                        print("Could not reverse geocode:", lat_val, lon_val)
                        return redirect(url_for("cities"))

                    final_city = found_city
                    final_lat = lat_val
                    final_lon = lon_val

                else:
                    return redirect(url_for("cities"))

                cur.execute("""
                    INSERT INTO cities (name, lat, lon)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name) DO UPDATE
                    SET lat = EXCLUDED.lat,
                        lon = EXCLUDED.lon
                """, (final_city, final_lat, final_lon))

                conn.commit()
                return redirect(url_for("cities"))

            elif action == "delete":
                city_id = request.form.get("city_id")
                cur.execute("DELETE FROM cities WHERE id=%s", (city_id,))
                conn.commit()
                return redirect(url_for("cities"))

        cur.execute("SELECT id, name, lat, lon FROM cities ORDER BY id DESC")
        cities_list = cur.fetchall()

    return render_template("cities.html", title="Cities", cities=cities_list)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
