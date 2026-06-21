class BearingCharts {
    constructor() {
        this.powerChart = null;
        this.pressureChart = null;
        this.powerData = [];
        this.pressureData = [];
        this.maxDataPoints = 60;
    }

    initPowerChart() {
        const ctx = document.getElementById('powerChart').getContext('2d');

        const gradient = ctx.createLinearGradient(0, 0, 0, 250);
        gradient.addColorStop(0, 'rgba(79, 195, 247, 0.3)');
        gradient.addColorStop(1, 'rgba(79, 195, 247, 0)');

        this.powerChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: '摩擦功耗 (W)',
                    data: [],
                    borderColor: '#4fc3f7',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                }, {
                    label: '水温 (°C)',
                    data: [],
                    borderColor: '#ff9800',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    yAxisID: 'y1',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#b0bec5',
                            font: { size: 12 },
                            usePointStyle: true,
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#e0e6ed',
                        bodyColor: '#b0bec5',
                        borderColor: 'rgba(100, 150, 200, 0.3)',
                        borderWidth: 1,
                    }
                },
                scales: {
                    x: {
                        display: true,
                        grid: {
                            color: 'rgba(100, 150, 200, 0.1)',
                        },
                        ticks: {
                            color: '#78909c',
                            maxTicksLimit: 8,
                            maxRotation: 0,
                        }
                    },
                    y: {
                        display: true,
                        position: 'left',
                        grid: {
                            color: 'rgba(100, 150, 200, 0.1)',
                        },
                        ticks: {
                            color: '#78909c',
                        },
                        title: {
                            display: true,
                            text: '功耗 (W)',
                            color: '#90a4ae',
                        }
                    },
                    y1: {
                        display: true,
                        position: 'right',
                        grid: {
                            drawOnChartArea: false,
                        },
                        ticks: {
                            color: '#78909c',
                        },
                        title: {
                            display: true,
                            text: '温度 (°C)',
                            color: '#90a4ae',
                        }
                    }
                }
            }
        });
    }

    initPressureChart() {
        const ctx = document.getElementById('pressureChart').getContext('2d');

        const gradient = ctx.createLinearGradient(0, 0, 0, 250);
        gradient.addColorStop(0, 'rgba(100, 181, 246, 0.4)');
        gradient.addColorStop(1, 'rgba(100, 181, 246, 0)');

        this.pressureChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: '水膜压力 (kPa)',
                    data: [],
                    borderColor: '#64b5f6',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                }, {
                    label: '水膜厚度 (μm)',
                    data: [],
                    borderColor: '#81c784',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    fill: false,
                    tension: 0.1,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    yAxisID: 'y1',
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#b0bec5',
                            font: { size: 12 },
                            usePointStyle: true,
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(0, 0, 0, 0.8)',
                        titleColor: '#e0e6ed',
                        bodyColor: '#b0bec5',
                        borderColor: 'rgba(100, 150, 200, 0.3)',
                        borderWidth: 1,
                    }
                },
                scales: {
                    x: {
                        display: true,
                        grid: {
                            color: 'rgba(100, 150, 200, 0.1)',
                        },
                        ticks: {
                            color: '#78909c',
                            maxTicksLimit: 8,
                            callback: function(value) {
                                const label = this.getLabelForValue(value);
                                if (typeof label === 'number') {
                                    return (label * 180 / Math.PI).toFixed(0) + '°';
                                }
                                return label;
                            }
                        },
                        title: {
                            display: true,
                            text: '周向角度',
                            color: '#90a4ae',
                        }
                    },
                    y: {
                        display: true,
                        position: 'left',
                        grid: {
                            color: 'rgba(100, 150, 200, 0.1)',
                        },
                        ticks: {
                            color: '#78909c',
                        },
                        title: {
                            display: true,
                            text: '压力 (kPa)',
                            color: '#90a4ae',
                        }
                    },
                    y1: {
                        display: true,
                        position: 'right',
                        grid: {
                            drawOnChartArea: false,
                        },
                        ticks: {
                            color: '#78909c',
                        },
                        title: {
                            display: true,
                            text: '膜厚 (μm)',
                            color: '#90a4ae',
                        }
                    }
                }
            }
        });
    }

    addPowerDataPoint(timestamp, power, temperature) {
        if (!this.powerChart) return;

        const timeStr = new Date(timestamp).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });

        this.powerChart.data.labels.push(timeStr);
        this.powerChart.data.datasets[0].data.push(power);
        this.powerChart.data.datasets[1].data.push(temperature);

        if (this.powerChart.data.labels.length > this.maxDataPoints) {
            this.powerChart.data.labels.shift();
            this.powerChart.data.datasets[0].data.shift();
            this.powerChart.data.datasets[1].data.shift();
        }

        this.powerChart.update('none');
    }

    updatePressureDistribution(theta, pressure, filmThickness) {
        if (!this.pressureChart) return;

        this.pressureChart.data.labels = theta;
        this.pressureChart.data.datasets[0].data = pressure.map(p => p / 1000);
        this.pressureChart.data.datasets[1].data = filmThickness.map(h => h * 1e6);

        this.pressureChart.update();
    }

    updateHistoryData(historyData) {
        if (!this.powerChart || !historyData || historyData.length === 0) return;

        const labels = [];
        const powerData = [];
        const tempData = [];

        for (const point of historyData) {
            const t = new Date(point.time || point.timestamp);
            labels.push(t.toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
            }));
            powerData.push(point.power_loss || point.powerLoss || 0);
            tempData.push(point.water_temperature || point.waterTemperature || 0);
        }

        this.powerChart.data.labels = labels;
        this.powerChart.data.datasets[0].data = powerData;
        this.powerChart.data.datasets[1].data = tempData;
        this.powerChart.update();
    }

    setTimeRange(range) {
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        document.querySelector(`[data-range="${range}"]`)?.classList.add('active');
    }

    init() {
        this.initPowerChart();
        this.initPressureChart();
    }
}
