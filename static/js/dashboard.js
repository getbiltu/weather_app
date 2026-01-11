function aqiClass(aqi) {
    if (aqi <= 50) return "badge bg-success";
    if (aqi <= 100) return "badge bg-warning text-dark";
    if (aqi <= 150) return "badge bg-orange";
    if (aqi <= 200) return "badge bg-danger";
    return "badge bg-dark";
}

function rainBadge(rainProb) {
    if (rainProb >= 70) return `<span class="badge bg-primary">High Rain</span>`;
    if (rainProb >= 40) return `<span class="badge bg-info text-dark">Medium Rain</span>`;
    return `<span class="badge bg-secondary">Low Rain</span>`;
}

async function loadTiles() {
    document.getElementById("loading").style.display = "block";

    const tiles = document.getElementById("tiles");
    tiles.style.display = "none";
    tiles.innerHTML = "";

    try {
        const res = await fetch("/api/live");
        const data = await res.json();

        if (!data || data.length === 0) {
            tiles.innerHTML = `
                <div class="col-12">
                    <div class="alert alert-warning shadow-sm">
                        ⚠️ No cities found. Please add cities from <b>Cities</b> menu.
                    </div>
                </div>`;
        } else {
            data.forEach(d => {
                tiles.innerHTML += `
                <div class="col-xl-3 col-lg-4 col-md-6">
                    <div class="card h-100">
                        <div class="card-body">

                            <div class="d-flex justify-content-between align-items-start">
                                <h5 class="card-title mb-2">📍 ${d.city}</h5>
                                <span class="${aqiClass(d.aqi)}">AQI ${d.aqi}</span>
                            </div>

                            <div class="metric-line">🌡 <b>${d.temp}</b> °C</div>
                            <div class="metric-line">💧 <b>${d.humidity}</b>% Humidity</div>
                            <div class="metric-line">
                                🌧 <b>${d.rain}</b>% | 💧 <b>${d.mm}</b> mm
                                <span class="ms-auto">${rainBadge(d.rain)}</span>
                            </div>

                        </div>

                        <div class="card-footer small text-muted d-flex justify-content-between align-items-center">
                            <span><span class="emoji-pulse">🟢</span> Live</span>
                            <span class="text-muted">Auto refresh</span>
                        </div>
                    </div>
                </div>`;
            });
        }

        document.getElementById("lastUpdated").innerText =
            "Last updated: " + new Date().toLocaleString();

    } catch (err) {
        tiles.innerHTML = `
            <div class="col-12">
                <div class="alert alert-danger shadow-sm">
                    ❌ Error loading live tiles. Please refresh.
                </div>
            </div>`;
        console.error(err);
    }

    document.getElementById("loading").style.display = "none";
    tiles.style.display = "flex";
}

loadTiles();

// background refresh (customizable)
setInterval(loadTiles, REFRESH_SECONDS * 1000);
