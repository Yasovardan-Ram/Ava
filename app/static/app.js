const API_BASE = '';

function getPMVColor(pmv) {
    const abs = Math.abs(pmv);
    if (abs < 0.5) return '#22c55e';
    if (abs < 1.0) return '#eab308';
    return '#ef4444';
}

function renderPMVGauge(container, pmv, ppd, tsv) {
    const color = getPMVColor(pmv);
    container.innerHTML = `
        <div class="gauge-bar">
            <div class="gauge-fill" style="width: ${((pmv + 2) / 4) * 100}%; background: ${color};"></div>
            <div class="gauge-marker" style="left: ${((0 + 2) / 4) * 100}%;"></div>
        </div>
        <div class="gauge-labels">
            <span>Cold (-2)</span>
            <span>Neutral (0)</span>
            <span>Hot (+2)</span>
        </div>
        <div class="gauge-values">
            <span>PMV: <strong style="color:${color}">${pmv.toFixed(3)}</strong></span>
            <span>PPD: <strong>${ppd.toFixed(1)}%</strong></span>
            <span>${tsv}</span>
        </div>
    `;
}

function renderJsonDisplay(container, data) {
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(data, null, 2);
    container.innerHTML = '';
    container.appendChild(pre);
}

function animateStep(stepId, delay) {
    return new Promise(resolve => {
        setTimeout(() => {
            const el = document.getElementById(stepId);
            if (el) {
                el.style.display = 'block';
                el.style.opacity = '0';
                el.style.transform = 'translateY(10px)';
                requestAnimationFrame(() => {
                    el.style.transition = 'opacity 0.3s, transform 0.3s';
                    el.style.opacity = '1';
                    el.style.transform = 'translateY(0)';
                });
            }
            resolve();
        }, delay);
    });
}

async function loadZoneState() {
    try {
        const res = await fetch(`${API_BASE}/api/zone-state`);
        const data = await res.json();
        const s = data.state;
        const c = data.comfort;

        document.getElementById('zone-temp').textContent = s.temperature.toFixed(1);
        document.getElementById('zone-humidity').textContent = s.humidity.toFixed(1);
        document.getElementById('zone-pmv').textContent = c.pmv.toFixed(3);
        document.getElementById('zone-ppd').textContent = c.ppd.toFixed(1);
        document.getElementById('zone-tsv').textContent = c.tsv;

        document.getElementById('zone-pmv').style.color = getPMVColor(c.pmv);
    } catch (e) {
        console.error('Failed to load zone state:', e);
    }
}

async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/history`);
        const data = await res.json();

        if (!data.length) return;

        const labels = data.map((_, i) => `#${i + 1}`);
        const energyData = data.map(d => d.energy_cost || 0);
        const pmvBefore = data.map(d => d.pmv_before?.pmv || 0);
        const pmvAfter = data.map(d => d.pmv_after?.pmv || 0);

        const ctx = document.getElementById('energy-chart').getContext('2d');
        if (window.energyChart) window.energyChart.destroy();

        window.energyChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Energy Cost (W)',
                        data: energyData,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: true,
                        tension: 0.3,
                    },
                    {
                        label: 'PMV Before',
                        data: pmvBefore,
                        borderColor: '#ef4444',
                        borderDash: [5, 5],
                        tension: 0.3,
                    },
                    {
                        label: 'PMV After',
                        data: pmvAfter,
                        borderColor: '#22c55e',
                        tension: 0.3,
                    },
                ],
            },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { suggestedMin: -2, suggestedMax: 2 },
                },
            },
        });
    } catch (e) {
        console.error('Failed to load history:', e);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadZoneState();
    loadHistory();

    const form = document.getElementById('complaint-form');
    const submitBtn = document.getElementById('submit-btn');
    const resetBtn = document.getElementById('reset-btn');
    const resultsSection = document.getElementById('results-section');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const text = document.getElementById('complaint-text').value.trim();
        if (!text) return;

        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing...';
        resultsSection.style.display = 'block';

        ['step-nlp', 'step-comfort-before', 'step-optimization', 'step-comfort-after', 'step-energy']
            .forEach(id => { document.getElementById(id).style.display = 'none'; });

        try {
            const res = await fetch(`${API_BASE}/api/complaint`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ complaint: text }),
            });

            const data = await res.json();

            if (!res.ok) {
                alert(data.error || 'Failed to process complaint');
                return;
            }

            await animateStep('step-nlp', 200);
            renderJsonDisplay(document.getElementById('nlp-output'), data.nlp);

            await animateStep('step-comfort-before', 400);
            renderPMVGauge(
                document.getElementById('pmv-before-gauge'),
                data.comfort_before.pmv,
                data.comfort_before.ppd,
                data.comfort_before.tsv
            );

            await animateStep('step-optimization', 400);
            renderJsonDisplay(document.getElementById('opt-output'), data.optimization);

            await animateStep('step-comfort-after', 400);
            renderPMVGauge(
                document.getElementById('pmv-after-gauge'),
                data.comfort_after.pmv,
                data.comfort_after.ppd,
                data.comfort_after.tsv
            );

            await animateStep('step-energy', 200);
            document.getElementById('energy-cost').textContent = data.energy_cost.toFixed(2);

            loadZoneState();
            loadHistory();
            document.getElementById('complaint-text').value = '';
        } catch (err) {
            alert('Error: ' + err.message);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Analyze & Optimize';
        }
    });

    resetBtn.addEventListener('click', async () => {
        if (!confirm('Reset zone to default conditions?')) return;
        try {
            await fetch(`${API_BASE}/api/reset`, { method: 'POST' });
            loadZoneState();
            loadHistory();
        } catch (e) {
            alert('Failed to reset zone');
        }
    });
});
