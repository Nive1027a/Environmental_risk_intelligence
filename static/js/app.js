let map, gridLayerGroup, riskContributorsChart;
let currentGridData = [];
let selectedCell = null;
let lastForecastSummary = null;
let aiLoaded = false, aiPoll = null;
const aiCharts = {};

document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initCharts();
    setupTabs();
    loadTelemetry();
    runSimulation();
    loadRegionalRisk();
    loadMethodology();

    document.getElementById("btn-simulate").addEventListener("click", runSimulation);
    const btnHighRisk = document.getElementById("btn-show-high-risk");
    if (btnHighRisk) btnHighRisk.addEventListener("click", filterHighRiskZones);
    const btnAllZones = document.getElementById("btn-show-all-zones");
    if (btnAllZones) btnAllZones.addEventListener("click", () => renderGrid(currentGridData));
    const btnDownload = document.getElementById("btn-download-report");
    if (btnDownload) btnDownload.addEventListener("click", downloadReport);

    document.getElementById("slider-traffic").addEventListener("input", (e) => {
        document.getElementById("label-traffic").innerText = `${e.target.value}x`;
    });
    document.getElementById("slider-industrial").addEventListener("input", (e) => {
        document.getElementById("label-industrial").innerText = `${e.target.value}x`;
    });

    // AI tab (lazy load on first open)
    document.getElementById("tab-btn-ai").addEventListener("click", () => {
        if (!aiLoaded) { aiLoaded = true; loadAIInsights(); }
    });
    document.getElementById("btn-retrain").addEventListener("click", startTraining);
});

function initMap() {
    map = L.map('map').setView([28.6139, 77.2090], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    gridLayerGroup = L.layerGroup().addTo(map);
    setTimeout(() => map.invalidateSize(), 200);
}

function setupTabs() {
    const tabs = [
        { btn: "tab-btn-twin", view: "view-twin" },
        { btn: "tab-btn-risk", view: "view-risk" },
        { btn: "tab-btn-ai", view: "view-ai" },
        { btn: "tab-btn-method", view: "view-method" }
    ];
    tabs.forEach(tab => {
        const btnElem = document.getElementById(tab.btn);
        const viewElem = document.getElementById(tab.view);
        if (btnElem && viewElem) {
            btnElem.addEventListener("click", () => {
                tabs.forEach(t => {
                    const b = document.getElementById(t.btn);
                    const v = document.getElementById(t.view);
                    if (b) b.classList.remove("active");
                    if (v) v.classList.remove("active");
                });
                btnElem.classList.add("active");
                viewElem.classList.add("active");
                if (tab.view === "view-twin" && map) setTimeout(() => map.invalidateSize(), 100);
            });
        }
    });
}

function initCharts() {
    const riskElem = document.getElementById('riskContributorsChart');
    if (riskElem) {
        riskContributorsChart = new Chart(riskElem.getContext('2d'), {
            type: 'bar',
            data: { labels: [], datasets: [{ label: 'Contribution %', data: [], backgroundColor: '#ef4444' }] },
            options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
        });
    }
}

const $ = (id) => document.getElementById(id);

async function loadTelemetry() {
    try {
        const data = await (await fetch('/api/telemetry')).json();
        if ($('val-wind')) $('val-wind').innerText = `${data.wind_speed} m/s`;
        if ($('val-pm25')) $('val-pm25').innerText = `${data.base_pm25} µg/m³`;
        if ($('val-temp')) $('val-temp').innerText = `${data.temperature} °C`;
        if ($('val-no2')) $('val-no2').innerText = `${data.base_no2} µg/m³`;
    } catch (err) { console.error("Telemetry fetch error:", err); }
}

async function runSimulation() {
    const traffic = parseFloat($("slider-traffic").value);
    const industrial = parseFloat($("slider-industrial").value);
    try {
        const res = await fetch('/api/predict', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ traffic_modifier: traffic, industrial_modifier: industrial })
        });
        const data = await res.json();
        if (data.predictions) {
            currentGridData = data.predictions;
            renderGrid(data.predictions);
            loadRegionalRisk();
        }
    } catch (err) { console.error("Simulation error:", err); }
}

async function loadRegionalRisk() {
    try {
        const data = await (await fetch('/api/risk/area')).json();
        if (data.status === "success") {
            const s = data.summary;
            if ($('reg-avg-risk')) $('reg-avg-risk').innerText = `${s.avg_risk}/100`;
            if ($('reg-avg-no2')) $('reg-avg-no2').innerText = `${s.avg_no2} µg/m³`;
            if ($('reg-high-zones')) $('reg-high-zones').innerText = s.high_risk_zones;
            if ($('reg-low-zones')) $('reg-low-zones').innerText = s.low_risk_zones;
        }
    } catch (e) { console.error("Regional risk error:", e); }
}

function renderGrid(predictions) {
    if (!gridLayerGroup) return;
    gridLayerGroup.clearLayers();
    predictions.forEach(cell => {
        const marker = L.circleMarker([cell.lat, cell.lon], {
            radius: 12, fillColor: getColor(cell.pm25), color: '#0f172a',
            weight: 2, opacity: 1, fillOpacity: 0.85
        });
        marker.on('click', () => { selectedCell = cell; inspectCellRisk(cell); });
        marker.bindTooltip(`<b>Station:</b> ${cell.grid_id}<br><b>PM2.5:</b> ${cell.pm25} µg/m³<br><b>NO2:</b> ${cell.no2} µg/m³`);
        gridLayerGroup.addLayer(marker);
    });
    if (predictions.length > 0) {
        map.fitBounds(L.latLngBounds(predictions.map(p => [p.lat, p.lon])), { padding: [40, 40] });
    }
}

async function inspectCellRisk(cell) {
    try {
        const res = await fetch('/api/risk/calculate', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ grid_id: cell.grid_id, no2: cell.no2, pm25: cell.pm25 })
        });
        const data = await res.json();
        if (data.status === "success") {
            const r = data.risk_assessment;
            $("risk-panel-details").style.display = "block";
            $("risk-station-id").innerText = cell.grid_id;
            $("risk-score-val").innerText = r.risk_score;
            $("risk-level-badge").innerText = r.risk_level;
            $("risk-no2-val").innerText = cell.no2;
            $("risk-pm25-val").innerText = cell.pm25;
            selectedCell.risk = r;
            if (riskContributorsChart && r.contributors) {
                riskContributorsChart.data.labels = r.contributors.map(c => c.factor);
                riskContributorsChart.data.datasets[0].data = r.contributors.map(c => c.contribution);
                riskContributorsChart.update();
            }
        }
    } catch (e) { console.error("Inspect risk error:", e); }
}

async function filterHighRiskZones() {
    try {
        const data = await (await fetch('/api/risk/high-risk-zones')).json();
        if (data.status === "success") renderGrid(data.high_risk_zones);
    } catch (e) { console.error("High risk filter error:", e); }
}

async function downloadReport() {
    if (!selectedCell) { alert("Please click a station marker on the map first."); return; }
    const payload = {
        location: { name: selectedCell.grid_id, lat: selectedCell.lat, lon: selectedCell.lon },
        prediction: { no2: selectedCell.no2, pm25: selectedCell.pm25 },
        risk: selectedCell.risk || { risk_score: 0, risk_level: "UNKNOWN", contributors: [] },
        forecast: lastForecastSummary   // NEW: embeds ML outlook if the AI tab was loaded
    };
    try {
        const res = await fetch('/api/risk/report', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error("PDF report generation failed.");
        const url = window.URL.createObjectURL(await res.blob());
        const a = document.createElement('a');
        a.href = url; a.download = `Risk_Report_${selectedCell.grid_id}.pdf`;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    } catch (err) {
        console.error("PDF download error:", err);
        alert("Failed to generate PDF report.");
    }
}

async function loadMethodology() {
    try {
        const data = await (await fetch('/api/risk/methodology')).json();
        const el = $('methodology-content');
        if (el) el.innerHTML = `
            <p><strong>Assessment Type:</strong> ${data.assessment_type}</p>
            <p><strong>Model:</strong> ${data.model}</p>
            <p><strong>Data Sources:</strong> Live Open-Meteo Air Quality & Weather API Ingestion</p>
            <p><strong>Scoring Methodology:</strong> ${data.scoring_methodology}</p>
            <p><em>${data.disclaimer}</em></p>`;
    } catch (e) { console.error("Methodology load error:", e); }
}

function getColor(pm25) {
    return pm25 > 250 ? '#7f1d1d' :
           pm25 > 120 ? '#dc2626' : 
           pm25 > 90 ? '#f97316' : 
           pm25 > 60 ? '#facc15' : 
           pm25 > 30 ? '#84cc16' :
           '#10b981';
}

/* ======================= AI FORECAST & INSIGHTS ======================= */
const fmtT = (t) => t.slice(5, 16).replace("T", " ");

function setAIStatus(msg) { $("ai-status").innerText = msg; }

function makeChart(key, canvasId, config) {
    if (aiCharts[key]) aiCharts[key].destroy();
    aiCharts[key] = new Chart($(canvasId).getContext('2d'), config);
}

async function loadAIInsights() {
    loadTrend(); // works only once history exists; harmless otherwise
    setAIStatus("Checking models...");
    try {
        const m = await (await fetch('/api/ml/metrics')).json();
        if (m.status === "not_trained") {
            setAIStatus("No trained model yet — training on real Open-Meteo history (about a minute)...");
            return startTraining();
        }
        if (m.status !== "success") throw new Error(m.message);
        renderMetrics(m);
        const [f, a] = await Promise.all([
            fetch('/api/ml/forecast').then(r => r.json()),
            fetch('/api/ml/anomalies').then(r => r.json())
        ]);
        if (f.status === "success") renderForecast(f);
        if (a.status === "success") renderAnomalies(a);
        loadTrend();
        setAIStatus(`Model trained ${m.trained_at} · ${m.n_hours} real hourly records`);
    } catch (e) {
        console.error(e);
        setAIStatus("Error: " + e.message);
    }
}

async function startTraining() {
    $("btn-retrain").disabled = true;
    setAIStatus("Training models on real history...");
    await fetch('/api/ml/train', { method: 'POST' });
    clearInterval(aiPoll);
    aiPoll = setInterval(async () => {
        const s = await (await fetch('/api/ml/train/status')).json();
        if (!s.running) {
            clearInterval(aiPoll);
            $("btn-retrain").disabled = false;
            if (s.error) setAIStatus("Training failed: " + s.error);
            else loadAIInsights();
        }
    }, 3000);
}

function renderForecast(f) {
    const p = f.points, s = f.summary;
    lastForecastSummary = {
        model: f.model, mae: f.mae, peak_risk: s.peak_risk, peak_level: s.peak_level,
        peak_time: s.peak_time, hours_high: s.hours_high_or_critical, avg_pm25: s.avg_pm25_pred
    };
    $("ai-peak-risk").innerText = `${s.peak_risk}/100 (${s.peak_level})`;
    $("ai-peak-time").innerText = fmtT(s.peak_time);
    $("ai-high-hours").innerText = `${s.hours_high_or_critical} / ${p.length}`;
    $("ai-model").innerText = f.model;

    makeChart("forecast", "forecastChart", {
        type: 'line',
        data: {
            labels: p.map(x => fmtT(x.time)),
            datasets: [
                { label: 'Lower (10%)', data: p.map(x => x.pm25_low), borderWidth: 0, pointRadius: 0, fill: false },
                { label: '80% interval', data: p.map(x => x.pm25_high), borderWidth: 0, pointRadius: 0,
                  fill: '-1', backgroundColor: 'rgba(37,99,235,0.15)' },
                { label: 'ML forecast PM2.5', data: p.map(x => x.pm25_pred), borderColor: '#2563eb', borderWidth: 2.5, tension: 0.3, pointRadius: 2 },
                { label: 'CAMS forecast (reference)', data: p.map(x => x.pm25_cams), borderColor: '#f59e0b', borderDash: [6, 4], borderWidth: 2, tension: 0.3, pointRadius: 0 }
            ]
        },
        options: { responsive: true, maintainAspectRatio: false,
            scales: { y: { title: { display: true, text: 'µg/m³' }, beginAtZero: true } },
            plugins: { legend: { labels: { filter: (i) => i.text !== 'Lower (10%)' } } } }
    });
}

function renderMetrics(m) {
    const mt = m.metrics;
    const rows = [...mt.models, mt.baseline].map(r =>
        `<tr class="${r.name === mt.best ? 'best' : ''}"><td>${r.name}${r.name === mt.best ? ' ✓' : ''}</td><td>${r.mae}</td><td>${r.rmse}</td><td>${r.r2}</td></tr>`).join("");
    $("metrics-table").innerHTML = `<thead><tr><th>Model</th><th>MAE</th><th>RMSE</th><th>R²</th></tr></thead><tbody>${rows}</tbody>`;
    $("metrics-note").innerText =
        `Best model beats persistence by ${mt.skill_vs_persistence_pct}% (RMSE). Train ${m.n_train.toLocaleString()} / test ${m.n_test.toLocaleString()} samples, ` +
        `data ${m.data_from.slice(0, 10)} → ${m.data_to.slice(0, 10)}.`;

    const imp = m.importance.slice(0, 8);
    makeChart("importance", "importanceChart", {
        type: 'bar',
        data: { labels: imp.map(i => i.feature), datasets: [{ label: 'Importance %', data: imp.map(i => i.importance), backgroundColor: '#16a34a' }] },
        options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
    });
}

function renderAnomalies(a) {
    const el = $("anomaly-list");
    if (!a.anomalies.length) { el.innerText = `No anomalies in the last ${a.checked_hours} hours.`; return; }
    el.innerHTML = a.anomalies.slice(0, 8).map(x =>
        `<div class="anomaly-item"><b>${x.time}</b> — PM2.5 ${x.pm25}, NO2 ${x.no2}<br>
         Unusual <b>${x.main_driver.replace('_', ' ')}</b> (${x.direction}) · score ${x.anomaly_score}</div>`).join("");
}

async function loadTrend() {
    try {
        const d = await (await fetch('/api/history/trend?days=7')).json();
        if (d.status !== "success") return;
        makeChart("trend", "trendChart", {
            type: 'line',
            data: { labels: d.time.map(fmtT), datasets: [
                { label: 'PM2.5', data: d.pm25, borderColor: '#ef4444', borderWidth: 1.5, pointRadius: 0, tension: 0.2 },
                { label: 'NO2', data: d.no2, borderColor: '#8b5cf6', borderWidth: 1.5, pointRadius: 0, tension: 0.2 }] },
            options: { responsive: true, maintainAspectRatio: false, scales: { x: { ticks: { maxTicksLimit: 8 } } } }
        });
    } catch (e) { console.error("Trend error:", e); }
}
