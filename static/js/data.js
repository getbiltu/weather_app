function applyFilters() {
    const city = document.getElementById("city").value;
    const metric = document.getElementById("metric").value;
    const hours = document.getElementById("hours").value;
    const start = document.getElementById("start").value;
    const end = document.getElementById("end").value;

    let url = `/data?city=${encodeURIComponent(city)}&metric=${metric}`;

    if (start && end) {
        url += `&start=${start}&end=${end}`;
    } else {
        url += `&hours=${hours}`;
    }
    window.location = url;
}

function clearDates() {
    document.getElementById("start").value = "";
    document.getElementById("end").value = "";
}

/** Stable city -> color mapping */
function cityColor(city) {
    // Generate stable hash -> hue
    let hash = 0;
    for (let i = 0; i < city.length; i++) {
        hash = city.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 70%, 45%)`;
}

function labelForMetric(m) {
    if (m === "temperature") return "Temperature (°C)";
    if (m === "humidity") return "Humidity (%)";
    if (m === "aqi") return "AQI";
    if (m === "rain_mm") return "Rain (mm)";
    if (m === "rain_probability") return "Rain Probability (%)";
    return m;
}

const metric = DEFAULT_METRIC;

// Group rows by city
const grouped = {};
ROWS.forEach(r => {
    if (!grouped[r.city]) grouped[r.city] = [];
    grouped[r.city].push(r);
});

// Build datasets (one line per city)
const datasets = Object.keys(grouped).map(city => ({
    label: city,
    data: grouped[city].map(r => r[metric]),
    borderColor: cityColor(city),
    backgroundColor: cityColor(city),
    tension: 0.35,
    borderWidth: 2,
    pointRadius: 1.5
}));

// labels: use time of the longest city dataset
let labels = [];
if (Object.keys(grouped).length > 0) {
    const firstCity = Object.keys(grouped)[0];
    labels = grouped[firstCity].map(r => r.time);
}

new Chart(document.getElementById("chart"), {
    type: "line",
    data: { labels, datasets },
    options: {
        responsive: true,
        plugins: {
            legend: { position: "bottom" },
            title: {
                display: true,
                text: labelForMetric(metric)
            }
        },
        scales: {
            x: {
                ticks: { maxRotation: 45, minRotation: 0 }
            }
        }
    }
});
